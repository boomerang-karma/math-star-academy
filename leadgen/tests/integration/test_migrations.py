from __future__ import annotations

import uuid

import psycopg
import pytest

from leadintel.security.audit import AuditRow, verify_chain
from leadintel.storage.migrate import MigrationError, MigrationRunner, discover

pytestmark = pytest.mark.integration


def test_all_migrations_applied_and_owned_by_owner_role(database: dict[str, str]) -> None:
    with psycopg.connect(database["owner"]) as conn:
        statuses = MigrationRunner(conn).status(discover())
        assert {state for _, state in statuses} == {"applied"}
        owners = conn.execute(
            """
            SELECT DISTINCT tableowner FROM pg_tables
            WHERE schemaname IN ('ingest', 'graph', 'sales', 'privacy', 'audit')
            """
        ).fetchall()
        assert owners == [("leadintel_owner",)]


def test_migrations_are_idempotent(database: dict[str, str]) -> None:
    with psycopg.connect(database["owner"]) as conn:
        assert MigrationRunner(conn).migrate(discover()) == []


def test_drift_is_detected(database: dict[str, str], tmp_path) -> None:  # type: ignore[no-untyped-def]
    for migration in discover():
        target = tmp_path / migration.path.name
        target.write_text(migration.sql + ("\n-- edited\n" if migration.version == "0002" else ""))
    with psycopg.connect(database["owner"]) as conn, pytest.raises(MigrationError, match="V0002"):
        MigrationRunner(conn).verify(discover(tmp_path))


def test_seed_is_idempotent(database: dict[str, str]) -> None:
    with psycopg.connect(database["owner"]) as conn:
        MigrationRunner(conn).seed()
        count = conn.execute("SELECT count(*) FROM sales.territory").fetchone()
        assert count == (4,)


def test_audit_log_is_append_only_and_chained(database: dict[str, str]) -> None:
    with psycopg.connect(database["api"]) as conn:
        for i in range(3):
            conn.execute(
                """
                INSERT INTO audit.audit_log
                    (actor_id, actor_type, action, resource_type, resource_id, outcome, ip, details)
                VALUES ('u1', 'user', 'lead.view', 'lead', %s, 'success', '10.1.2.3', %s)
                """,
                (str(i), psycopg.types.json.Jsonb({"i": i, "note": "ünïcode"})),
            )
        conn.commit()
        assert conn.execute("SELECT audit.verify_chain()").fetchone() == (None,)
        # Layer 1: the API role has no UPDATE/DELETE privilege at all.
        for statement in ("UPDATE audit.audit_log SET action = 'x'", "DELETE FROM audit.audit_log"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(statement)
            conn.rollback()

    # Layer 2: even the owning role is stopped by the append-only triggers.
    with psycopg.connect(database["owner"]) as conn:
        for statement in (
            "UPDATE audit.audit_log SET action = 'tampered'",
            "DELETE FROM audit.audit_log",
            "TRUNCATE audit.audit_log",
        ):
            with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
                conn.execute(statement)
            conn.rollback()

    # The Python verifier must agree with the SQL one byte for byte.
    with psycopg.connect(database["owner"]) as conn:
        rows = conn.execute(
            """
            SELECT seq, occurred_at, actor_id, actor_type, action, resource_type, resource_id,
                   outcome, request_id, host(ip), details::text, prev_hash, hash
            FROM audit.audit_log ORDER BY seq
            """
        ).fetchall()
    audit_rows = [AuditRow(*row) for row in rows]
    assert len(audit_rows) >= 3
    assert verify_chain(audit_rows) is None


def test_merge_function_rejects_type_mismatch(database: dict[str, str]) -> None:
    with psycopg.connect(database["worker"]) as conn:
        org = conn.execute(
            "INSERT INTO graph.entity (entity_type, display_name) VALUES"
            " ('organization','A') RETURNING id"
        ).fetchone()
        person = conn.execute(
            "INSERT INTO graph.entity (entity_type, display_name) VALUES ('person','B')"
            " RETURNING id"
        ).fetchone()
        assert org is not None
        assert person is not None
        with pytest.raises(psycopg.errors.RaiseException, match="cannot merge"):
            conn.execute("SELECT graph.merge_entities(%s, %s, 'u1')", (person[0], org[0]))
        conn.rollback()
        with pytest.raises(psycopg.errors.RaiseException, match="not found"):
            conn.execute("SELECT graph.merge_entities(%s, %s, 'u1')", (uuid.uuid4(), org[0]))


def test_runner_works_with_dict_row_connections(database: dict[str, str]) -> None:
    # The migrator Lambda reuses the worker runtime's connection, which yields dict rows.
    from leadintel.storage.db import connect

    with connect(database["owner"]) as conn:
        runner = MigrationRunner(conn)
        assert {state for _, state in runner.status(discover())} == {"applied"}
        assert runner.migrate(discover()) == []
