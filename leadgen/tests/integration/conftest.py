"""PostgreSQL fixtures.

Uses ``LEADINTEL_TEST_DATABASE_URL`` when set (CI provides a postgres:16 service);
otherwise starts a private server from local PostgreSQL binaries in a temp dir.
Each test module gets a freshly created database with all migrations applied.
Tests are skipped, not failed, when no PostgreSQL is available.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

from leadintel.storage.migrate import MigrationRunner, discover

APP_PASSWORD = "app-test-password"  # local throwaway server only
WORKER_PASSWORD = "worker-test-password"


def _pg_bin() -> Path | None:
    candidates = sorted(Path("/usr/lib/postgresql").glob("*/bin"))
    for directory in reversed(candidates):
        if (directory / "initdb").exists():
            return directory
    found = shutil.which("initdb")
    return Path(found).parent if found else None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _run_as_db_user(args: list[str]) -> None:
    if os.geteuid() == 0:
        args = ["runuser", "-u", "postgres", "--", *args]
    subprocess.run(args, check=True, capture_output=True)


@pytest.fixture(scope="session")
def pg_server() -> Iterator[str]:
    """Yield a superuser DSN template (without database name)."""
    env_url = os.environ.get("LEADINTEL_TEST_DATABASE_URL")
    if env_url:
        yield env_url.rsplit("/", 1)[0]
        return
    pg_bin = _pg_bin()
    if pg_bin is None:
        pytest.skip("no PostgreSQL binaries and no LEADINTEL_TEST_DATABASE_URL")
    tmp = Path(tempfile.mkdtemp(prefix="leadintel-pg-"))
    data = tmp / "data"
    if os.geteuid() == 0:
        shutil.chown(tmp, "postgres", "postgres")
    port = _free_port()
    _run_as_db_user([str(pg_bin / "initdb"), "-D", str(data), "-U", "postgres", "--auth=trust"])
    _run_as_db_user(
        [
            str(pg_bin / "pg_ctl"),
            "-D",
            str(data),
            "-w",
            "-l",
            str(tmp / "log"),
            "-o",
            f"-p {port} -c listen_addresses=127.0.0.1 -k {tmp} -c fsync=off",
            "start",
        ]
    )
    try:
        yield f"postgresql://postgres@127.0.0.1:{port}"
    finally:
        _run_as_db_user([str(pg_bin / "pg_ctl"), "-D", str(data), "-m", "immediate", "stop"])
        shutil.rmtree(tmp, ignore_errors=True)


def _ensure_login_users(admin: psycopg.Connection) -> None:
    """Login users mirroring production: leadintel_api -> app role, leadintel_worker -> pipeline."""
    for user, role, password in (
        ("leadintel_api", "leadintel_app", APP_PASSWORD),
        ("leadintel_worker", "leadintel_pipeline", WORKER_PASSWORD),
    ):
        exists = admin.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (user,)).fetchone()
        if not exists:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(user), sql.Literal(password)
                )
            )
        admin.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier(role), sql.Identifier(user)))


@pytest.fixture(scope="module")
def database(pg_server: str) -> Iterator[dict[str, str]]:
    """A migrated, seeded database. Yields DSNs for the superuser, API and worker users."""
    name = f"leadintel_test_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(f"{pg_server}/postgres", autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    owner_dsn = f"{pg_server}/{name}"
    with psycopg.connect(owner_dsn) as conn:
        runner = MigrationRunner(conn)
        runner.migrate(discover())
        runner.seed()
    with psycopg.connect(owner_dsn, autocommit=True) as admin:
        _ensure_login_users(admin)
    host = pg_server.split("@", 1)[1]
    try:
        yield {
            "owner": owner_dsn,
            "api": f"postgresql://leadintel_api:{APP_PASSWORD}@{host}/{name}",
            "worker": f"postgresql://leadintel_worker:{WORKER_PASSWORD}@{host}/{name}",
        }
    finally:
        with psycopg.connect(f"{pg_server}/postgres", autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )
