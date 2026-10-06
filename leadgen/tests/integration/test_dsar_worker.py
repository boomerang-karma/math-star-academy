"""The DSAR worker on a real database.

An access request is completed only after its export is delivered; erasure
leaves no personal data behind and suppresses the subject so the next
collection run cannot bring them back.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from psycopg.rows import dict_row

from leadintel.connectors.first_party import TrackEvent, event_signals, form_source_records
from leadintel.core.config import Settings
from leadintel.ontology.models import FetchBatch
from leadintel.pipeline import handlers
from leadintel.pipeline.icp import DEFAULT_ICP
from leadintel.pipeline.runtime import Runtime
from leadintel.pipeline.service import PipelineService
from leadintel.storage.db import connect
from leadintel.storage.pipeline_repo import PipelineRepository
from tests.conftest import TEST_BLIND_INDEX_KEY, TEST_MASTER_KEY

pytestmark = pytest.mark.integration

EMAIL = "jordan.lee@northwindanalytics.com"


@pytest.fixture
def rt(
    database: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Runtime]:
    settings = Settings(
        env="local",
        tenant_id="test",
        local_master_key_b64=base64.b64encode(TEST_MASTER_KEY).decode(),
        local_blind_index_key_b64=base64.b64encode(TEST_BLIND_INDEX_KEY).decode(),
        local_data_dir=str(tmp_path),
    )
    runtime = Runtime(settings)
    runtime._conn = connect(database["worker"])
    monkeypatch.setattr(handlers, "runtime", lambda: runtime)
    yield runtime
    runtime._conn.close()


def _ingest_person(rt: Runtime) -> dict[str, Any]:
    event = TrackEvent.model_validate(
        {
            "visitor_id": "v_9f8e7d6c5b4a3f2e",
            "event": "form_submit",
            "url": "https://www.example-seller.com/demo",
            "ts": "2026-09-30T16:00:00Z",
            "form": {
                "email": EMAIL,
                "name": "Jordan Lee",
                "company": "Northwind Analytics",
                "form_id": "demo-request",
            },
        }
    )
    repo = PipelineRepository(rt.connection(), cipher=rt.cipher, bidx=rt.bidx)
    service = PipelineService(repo, raw_store=rt.raw_store, bidx=rt.bidx, icp=DEFAULT_ICP)
    summary = service.ingest(
        FetchBatch(
            records=form_source_records(event),
            signals=event_signals(event, icp=DEFAULT_ICP, bidx=rt.bidx),
        ),
        connector="first_party",
        playbook="beacon",
        params={},
    )
    service.resolve_pending()
    return summary


def _request(database: dict[str, str], rt: Runtime, kind: str) -> UUID:
    with psycopg.connect(database["owner"]) as conn:
        row = conn.execute(
            "INSERT INTO privacy.dsar_request"
            " (request_type, jurisdiction, subject_email_bidx, status, due_at, created_by)"
            " VALUES (%s, 'gdpr', %s, 'in_progress', now() + interval '30 days', 'test')"
            " RETURNING id",
            (kind, rt.bidx.index(EMAIL, field="email")),
        ).fetchone()
    assert row is not None
    request_id: UUID = row[0]
    return request_id


def _owner_query(database: dict[str, str], sql: str, *params: Any) -> list[dict[str, Any]]:
    with psycopg.connect(database["owner"], row_factory=dict_row) as conn:
        return conn.execute(sql, params).fetchall()


def test_access_request_is_completed_only_with_its_export(
    rt: Runtime, database: dict[str, str], tmp_path: Path
) -> None:
    _ingest_person(rt)
    request_id = _request(database, rt, "access")

    assert handlers.dsar_worker({}) == {"processed": 1}

    path = tmp_path / "dsar-exports" / "dsar" / f"{request_id}.json"
    export = json.loads(path.read_text())
    assert any(r["restricted"].get("email") == EMAIL for r in export["records"])
    assert export["signals"], "the form submission belongs to the subject"
    [request] = _owner_query(
        database, "SELECT status, result FROM privacy.dsar_request WHERE id = %s", request_id
    )
    assert request["status"] == "completed"
    assert request["result"]["export_uri"] == path.resolve().as_uri()
    assert EMAIL not in json.dumps(request["result"])  # the database keeps only counts


def test_failed_delivery_leaves_the_request_open(rt: Runtime, database: dict[str, str]) -> None:
    class Unreachable:
        def put(self, key: str, body: bytes) -> str:
            raise OSError("export bucket unreachable")

    rt.__dict__["export_store"] = Unreachable()  # replaces the cached store
    request_id = _request(database, rt, "access")

    with pytest.raises(OSError, match="unreachable"):
        handlers.dsar_worker({})

    [request] = _owner_query(
        database, "SELECT status FROM privacy.dsar_request WHERE id = %s", request_id
    )
    assert request["status"] == "in_progress"  # retried on the next run
    _owner_query(
        database,
        "UPDATE privacy.dsar_request SET status = 'rejected' WHERE id = %s RETURNING id",
        request_id,
    )


def test_erasure_leaves_no_personal_data_and_blocks_recollection(
    rt: Runtime, database: dict[str, str]
) -> None:
    _ingest_person(rt)
    email_bidx = rt.bidx.index(EMAIL, field="email")
    _request(database, rt, "erasure")

    assert handlers.dsar_worker({}) == {"processed": 1}

    assert _owner_query(
        database,
        "SELECT count(*) AS n FROM ingest.source_record WHERE email_bidx = %s",
        email_bidx,
    ) == [{"n": 0}]
    assert _owner_query(
        database, "SELECT count(*) AS n FROM graph.entity WHERE email_bidx = %s", email_bidx
    ) == [{"n": 0}]
    erased = _owner_query(
        database,
        "SELECT golden, display_name, pii_envelope FROM graph.entity WHERE status = 'erased'",
    )
    assert erased
    assert all(e == {"golden": {}, "display_name": None, "pii_envelope": None} for e in erased)
    assert _owner_query(
        database,
        "SELECT count(*) AS n FROM privacy.suppression"
        " WHERE identifier_type = 'email' AND identifier_bidx = %s",
        email_bidx,
    ) == [{"n": 1}]

    # The same form arriving again is refused at the door.
    assert _ingest_person(rt)["records"].get("suppressed") == 1
