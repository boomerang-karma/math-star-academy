"""Versioned SQL migration runner.

Migrations are plain SQL files named ``V<4 digits>__<description>.sql`` in
``database/migrations``. Each runs in its own transaction as the
``leadintel_owner`` role, so every object ends up owned by the NOLOGIN owner
rather than by whoever happened to run the deploy. Applied versions are
recorded with a SHA-256 checksum; editing an applied migration is detected as
drift and stops the run (write a new migration instead).

Directives (comment lines anywhere in the file):

* ``-- leadintel:as-login-user`` - do not ``SET ROLE``; needed for CREATE EXTENSION
  and cluster-level grants.
* ``-- leadintel:no-transaction`` - run outside a transaction (CREATE INDEX CONCURRENTLY).

CLI::

    python -m leadintel.storage.migrate status   --dsn postgresql://...
    python -m leadintel.storage.migrate up       --dsn ...        # apply pending
    python -m leadintel.storage.migrate verify   --dsn ...        # checksum drift only
    python -m leadintel.storage.migrate seed     --dsn ...        # idempotent reference data
    python -m leadintel.storage.migrate up --secret-arn arn:...   # RDS secret (in-VPC runs)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import tuple_row

OWNER_ROLE = "leadintel_owner"
META_SCHEMA = "leadintel_meta"
_FILENAME_RE = re.compile(r"^V(\d{4})__([a-z0-9_]+)\.sql$")
_LOCK_KEY = 74_211_903  # arbitrary, fixed: serializes concurrent runners


def _database_dir() -> Path:
    """``database/`` in the repository (src layout) or next to the package (Lambda bundle)."""
    here = Path(__file__).resolve()
    for candidate in (here.parents[3] / "database", here.parents[2] / "database"):
        if (candidate / "migrations").is_dir():
            return candidate
    return here.parents[3] / "database"


DEFAULT_MIGRATIONS_DIR = _database_dir() / "migrations"
DEFAULT_SEEDS_DIR = _database_dir() / "seeds"


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: str
    description: str
    path: Path
    sql: str
    checksum: str
    as_login_user: bool
    transactional: bool


def discover(directory: Path = DEFAULT_MIGRATIONS_DIR) -> list[Migration]:
    migrations: list[Migration] = []
    seen: set[str] = set()
    for path in sorted(directory.glob("*.sql")):
        match = _FILENAME_RE.match(path.name)
        if not match:
            raise MigrationError(f"unexpected file in migrations directory: {path.name}")
        version, description = match.groups()
        if version in seen:
            raise MigrationError(f"duplicate migration version {version}")
        seen.add(version)
        text = path.read_text(encoding="utf-8")
        migrations.append(
            Migration(
                version=version,
                description=description,
                path=path,
                sql=text,
                checksum=hashlib.sha256(text.encode()).hexdigest(),
                as_login_user="leadintel:as-login-user" in text,
                transactional="leadintel:no-transaction" not in text,
            )
        )
    return migrations


class MigrationRunner:
    def __init__(self, conn: psycopg.Connection[Any], *, owner_role: str = OWNER_ROLE) -> None:
        if conn.autocommit is False and conn.info.transaction_status != 0:
            raise MigrationError("pass a connection that is not inside a transaction")
        self._conn = conn
        self._owner = owner_role

    def ensure_meta(self) -> None:
        with self._conn.transaction():
            self._conn.execute(
                sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(META_SCHEMA))
            )
            self._conn.execute(
                sql.SQL(
                    "CREATE TABLE IF NOT EXISTS {}.schema_migrations ("
                    " version text PRIMARY KEY,"
                    " description text NOT NULL,"
                    " checksum text NOT NULL,"
                    " applied_at timestamptz NOT NULL DEFAULT now(),"
                    " applied_by text NOT NULL DEFAULT current_user,"
                    " execution_ms integer NOT NULL)"
                ).format(sql.Identifier(META_SCHEMA))
            )

    def _fetchone(self, query: Any, params: Any = None) -> tuple[Any, ...] | None:
        # Explicit tuple rows: callers may hand us a connection with a dict row factory.
        with self._conn.cursor(row_factory=tuple_row) as cur:
            return cur.execute(query, params).fetchone()

    def applied(self) -> dict[str, str]:
        with self._conn.cursor(row_factory=tuple_row) as cur:
            query = sql.SQL("SELECT version, checksum FROM {}.schema_migrations ORDER BY version")
            rows = cur.execute(query.format(sql.Identifier(META_SCHEMA))).fetchall()
        self._conn.commit()
        return {row[0]: row[1] for row in rows}

    def status(self, migrations: Sequence[Migration]) -> list[tuple[Migration, str]]:
        self.ensure_meta()
        applied = self.applied()
        result = []
        for migration in migrations:
            if migration.version not in applied:
                state = "pending"
            elif applied[migration.version] != migration.checksum:
                state = "drifted"
            else:
                state = "applied"
            result.append((migration, state))
        return result

    def verify(self, migrations: Sequence[Migration]) -> None:
        drifted = [m.path.name for m, state in self.status(migrations) if state == "drifted"]
        if drifted:
            raise MigrationError(
                "applied migrations were modified: "
                + ", ".join(drifted)
                + " (add a new migration instead of editing applied ones)"
            )

    def _owner_exists(self) -> bool:
        row = self._fetchone(
            "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s)", (self._owner,)
        )
        return bool(row and row[0])

    def _apply(self, migration: Migration) -> None:
        started = time.monotonic()
        record = sql.SQL(
            "INSERT INTO {}.schema_migrations (version, description, checksum, execution_ms)"
            " VALUES (%s, %s, %s, %s)"
        ).format(sql.Identifier(META_SCHEMA))

        def run_body(cur: psycopg.Cursor) -> None:
            if not migration.as_login_user:
                if not self._owner_exists():
                    raise MigrationError(
                        f"{migration.path.name}: role {self._owner} does not exist yet"
                    )
                cur.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(self._owner)))
            cur.execute(migration.sql.encode())
            cur.execute("RESET ROLE")

        if migration.transactional:
            with self._conn.transaction(), self._conn.cursor() as cur:
                run_body(cur)
                elapsed = int((time.monotonic() - started) * 1000)
                cur.execute(
                    record,
                    (migration.version, migration.description, migration.checksum, elapsed),
                )
        else:
            previous = self._conn.autocommit
            self._conn.autocommit = True
            try:
                with self._conn.cursor() as cur:
                    if not migration.as_login_user:
                        cur.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(self._owner)))
                    cur.execute(migration.sql.encode())
                    cur.execute("RESET ROLE")
                    elapsed = int((time.monotonic() - started) * 1000)
                    cur.execute(
                        record,
                        (migration.version, migration.description, migration.checksum, elapsed),
                    )
            finally:
                self._conn.autocommit = previous

    def migrate(self, migrations: Sequence[Migration], *, target: str | None = None) -> list[str]:
        self.ensure_meta()
        self._conn.execute("SELECT pg_advisory_lock(%s)", (_LOCK_KEY,))
        self._conn.commit()
        try:
            self.verify(migrations)
            applied = self.applied()
            done: list[str] = []
            for migration in migrations:
                if target is not None and migration.version > target:
                    break
                if migration.version in applied:
                    continue
                try:
                    self._apply(migration)
                except psycopg.Error as exc:
                    raise MigrationError(f"{migration.path.name} failed: {exc}") from exc
                done.append(migration.version)
            return done
        finally:
            self._conn.execute("SELECT pg_advisory_unlock(%s)", (_LOCK_KEY,))
            self._conn.commit()

    def ensure_login_user(self, username: str, password: str, group_role: str) -> None:
        """Create or update a LOGIN user and grant it a group role (used by RDS Proxy).

        CREATE/ALTER ROLE cannot take bind parameters, so the password is sent as a
        quoted literal; keep statement logging (log_statement, pgaudit) off for DDL
        on the migrator connection.
        """
        if group_role not in {"leadintel_app", "leadintel_pipeline", "leadintel_readonly"}:
            raise MigrationError(f"refusing to grant unexpected role {group_role!r}")
        with self._conn.transaction():
            exists = self._conn.execute(
                "SELECT 1 FROM pg_roles WHERE rolname = %s", (username,)
            ).fetchone()
            verb = "ALTER" if exists else "CREATE"
            self._conn.execute(
                sql.SQL(verb + " ROLE {} WITH LOGIN PASSWORD {}").format(
                    sql.Identifier(username), sql.Literal(password)
                )
            )
            self._conn.execute(
                sql.SQL("GRANT {} TO {}").format(
                    sql.Identifier(group_role), sql.Identifier(username)
                )
            )
            # IAM authentication through RDS Proxy (role exists only on RDS/Aurora).
            has_rds_iam = self._conn.execute(
                "SELECT 1 FROM pg_roles WHERE rolname = 'rds_iam'"
            ).fetchone()
            if has_rds_iam:
                self._conn.execute(sql.SQL("GRANT rds_iam TO {}").format(sql.Identifier(username)))

    def seed(self, directory: Path = DEFAULT_SEEDS_DIR) -> list[str]:
        """Apply every seed file. Seeds must be idempotent (upserts); they are not tracked."""
        applied: list[str] = []
        for path in sorted(directory.glob("*.sql")):
            with self._conn.transaction(), self._conn.cursor() as cur:
                cur.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(self._owner)))
                cur.execute(path.read_text(encoding="utf-8").encode())
                cur.execute("RESET ROLE")
            applied.append(path.name)
        return applied


def dsn_from_rds_secret(
    secret_json: str, *, host_override: str | None = None, sslrootcert: str | None = None
) -> str:
    """Build a libpq conninfo from an RDS-managed secret (username/password/host/port/dbname)."""
    secret = json.loads(secret_json)
    params = {
        "host": host_override or secret["host"],
        "port": str(secret.get("port", 5432)),
        "dbname": secret.get("dbname", "leadintel"),
        "user": secret["username"],
        "password": secret["password"],
        "sslmode": "verify-full" if sslrootcert else "require",
        "connect_timeout": "10",
    }
    if sslrootcert:
        params["sslrootcert"] = sslrootcert
    return psycopg.conninfo.make_conninfo(**params)


def _connect(args: argparse.Namespace) -> psycopg.Connection:
    if args.dsn:
        return psycopg.connect(args.dsn)
    if args.secret_arn:
        import boto3

        client = boto3.client("secretsmanager")
        secret = client.get_secret_value(SecretId=args.secret_arn)["SecretString"]
        return psycopg.connect(
            dsn_from_rds_secret(secret, host_override=args.host, sslrootcert=args.sslrootcert)
        )
    raise SystemExit("either --dsn or --secret-arn is required")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="leadintel.storage.migrate")
    parser.add_argument("command", choices=["status", "up", "verify", "seed"])
    parser.add_argument("--dsn", help="libpq connection string")
    parser.add_argument("--secret-arn", help="RDS-format Secrets Manager secret")
    parser.add_argument("--host", help="override the secret's host (e.g. RDS Proxy endpoint)")
    parser.add_argument("--sslrootcert", help="CA bundle for sslmode=verify-full")
    parser.add_argument("--target", help="stop after this version (e.g. 0004)")
    parser.add_argument("--migrations-dir", type=Path, default=DEFAULT_MIGRATIONS_DIR)
    parser.add_argument("--seeds-dir", type=Path, default=DEFAULT_SEEDS_DIR)
    args = parser.parse_args(argv)

    migrations = discover(args.migrations_dir)
    with _connect(args) as conn:
        runner = MigrationRunner(conn)
        if args.command == "status":
            for migration, state in runner.status(migrations):
                print(f"{migration.version}  {state:8}  {migration.description}")
        elif args.command == "verify":
            runner.verify(migrations)
            print("ok: no drift")
        elif args.command == "up":
            done = runner.migrate(migrations, target=args.target)
            print(f"applied {len(done)} migration(s): {', '.join(done) or '-'}")
        else:
            print("seeded: " + ", ".join(runner.seed(args.seeds_dir)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
