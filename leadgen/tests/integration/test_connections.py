"""Cached connections outlive their server side.

RDS Proxy closes clients idle for 15 minutes; failovers and restarts drop every
connection. Lambda containers keep theirs across invocations, so without a
check the first request (or scheduled run) after an idle spell would fail.
``pg_terminate_backend`` stands in for the proxy here.
"""

from __future__ import annotations

import base64

import psycopg
import pytest
from fastapi.testclient import TestClient

from leadintel.api.app import create_app
from leadintel.api.deps import AppServices, Database
from leadintel.core.config import Settings
from leadintel.pipeline.runtime import Runtime
from leadintel.security.authz import Principal, Role
from leadintel.security.blind_index import BlindIndexer
from leadintel.security.crypto import FieldCipher, LocalKeyProvider
from leadintel.storage.db import Connection
from tests.conftest import TEST_BLIND_INDEX_KEY, TEST_MASTER_KEY

pytestmark = pytest.mark.integration

ADMIN = Principal(
    subject="00000000-0000-4000-8000-000000000001",
    roles=frozenset({Role.ADMIN}),
    tenant_id="test",
    territories=frozenset(),
)


def _backend_pid(conn: Connection) -> int:
    row = conn.execute("SELECT pg_backend_pid() AS pid").fetchone()
    assert row is not None
    pid: int = row["pid"]
    return pid


def _drop_server_side(database: dict[str, str], pid: int) -> None:
    with psycopg.connect(database["owner"], autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(%s)", (pid,))


def test_api_replaces_a_dropped_connection(database: dict[str, str]) -> None:
    unchecked = Database(lambda: database["api"], stale_after_s=3600)
    checked = Database(lambda: database["api"], stale_after_s=0)
    old_pids = {}
    for db in (unchecked, checked):
        with db.unscoped() as conn:
            old_pids[id(db)] = _backend_pid(conn)
        _drop_server_side(database, old_pids[id(db)])

    # Without the idle check, the next request fails on its first statement...
    with pytest.raises(psycopg.OperationalError), unchecked.scoped(ADMIN):
        pass
    # ...with it, the dead connection is replaced before use.
    with checked.scoped(ADMIN) as conn:
        assert _backend_pid(conn) != old_pids[id(checked)]


def test_worker_runtime_replaces_a_dropped_connection(database: dict[str, str]) -> None:
    rt = Runtime(Settings(env="local", database_url=database["worker"]), stale_after_s=0)
    conn = rt.connection()
    pid = _backend_pid(conn)
    conn.rollback()
    _drop_server_side(database, pid)

    fresh = rt.connection()
    assert fresh is not conn
    assert _backend_pid(fresh) != pid


def test_open_transactions_are_never_pinged(database: dict[str, str]) -> None:
    rt = Runtime(Settings(env="local", database_url=database["worker"]), stale_after_s=0)
    conn = rt.connection()
    conn.execute("CREATE TEMP TABLE work_in_flight (x int)")
    conn.execute("INSERT INTO work_in_flight VALUES (1)")

    assert rt.connection() is conn  # no ping, no rollback mid-transaction
    assert conn.execute("SELECT count(*) AS n FROM work_in_flight").fetchone() == {"n": 1}
    conn.rollback()


def test_readiness_reports_degraded_instead_of_failing() -> None:
    settings = Settings(
        env="local",
        auth_mode="local-dev",
        local_master_key_b64=base64.b64encode(TEST_MASTER_KEY).decode(),
        local_blind_index_key_b64=base64.b64encode(TEST_BLIND_INDEX_KEY).decode(),
    )
    services = AppServices(
        settings=settings,
        db=Database(lambda: "postgresql://nobody@127.0.0.1:1/none?connect_timeout=1"),
        cipher=FieldCipher(LocalKeyProvider(TEST_MASTER_KEY), tenant_id="test"),
        bidx=BlindIndexer(TEST_BLIND_INDEX_KEY),
    )
    with TestClient(create_app(settings, services=services)) as client:
        response = client.get("/api/readyz")
    assert response.status_code == 503
    assert response.json() == {"status": "degraded"}
