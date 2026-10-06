"""API against a real database, through the full middleware stack (local-dev identities)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

import psycopg
import pytest
from fastapi.testclient import TestClient

from leadintel.ai.brief import AccountBrief
from leadintel.api.app import create_app
from leadintel.api.deps import AppServices, Database
from leadintel.core.config import Settings
from leadintel.security.blind_index import BlindIndexer
from leadintel.security.crypto import FieldCipher, LocalKeyProvider
from tests.conftest import TEST_BLIND_INDEX_KEY, TEST_MASTER_KEY
from tests.integration.test_pipeline_end_to_end import (
    _first_party_event,
    _scrapebadger_batch,
    load,
)

pytestmark = pytest.mark.integration

ANALYST = {"x-dev-user": "00000000-0000-0000-0000-0000000000a1", "x-dev-roles": "analyst"}
COMPLIANCE = {
    "x-dev-user": "00000000-0000-0000-0000-0000000000c1",
    "x-dev-roles": "compliance_officer",
}
VIEWER = {"x-dev-user": "00000000-0000-0000-0000-0000000000d1", "x-dev-roles": "viewer"}


@pytest.fixture(scope="module")
def seeded(database: dict[str, str], tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """Run the pipeline once so the API has a realistic graph to serve."""
    from datetime import UTC, datetime

    from leadintel.connectors.first_party import event_signals, form_source_records
    from leadintel.connectors.ga4 import map_visitor_activity
    from leadintel.connectors.linkedin_leadsync import map_lead_form_response
    from leadintel.ontology.models import FetchBatch
    from leadintel.pipeline.icp import DEFAULT_ICP
    from leadintel.pipeline.service import PipelineService
    from leadintel.storage.db import connect
    from leadintel.storage.pipeline_repo import PipelineRepository
    from leadintel.storage.raw_store import LocalRawStore

    cipher = FieldCipher(LocalKeyProvider(TEST_MASTER_KEY), tenant_id="test")
    bidx = BlindIndexer(TEST_BLIND_INDEX_KEY)
    with connect(database["worker"]) as conn:
        service = PipelineService(
            PipelineRepository(conn, cipher=cipher, bidx=bidx),
            raw_store=LocalRawStore(tmp_path_factory.mktemp("raw")),
            bidx=bidx,
            icp=DEFAULT_ICP,
            clock=lambda: datetime(2026, 10, 1, 12, tzinfo=UTC),
        )
        service.ingest(_scrapebadger_batch(), connector="scrapebadger", playbook="t", params={})
        records, signals, consents = map_lead_form_response(
            load("linkedin/lead_form_response.json"), bidx=bidx
        )
        service.ingest(
            FetchBatch(records=records, signals=signals),
            connector="li",
            playbook="t",
            params={},
            consents=consents,
        )
        event = _first_party_event()
        service.ingest(
            FetchBatch(
                records=form_source_records(event),
                signals=event_signals(event, icp=DEFAULT_ICP, bidx=bidx)
                + map_visitor_activity(load("ga4/visitor_report.json"), icp=DEFAULT_ICP),
            ),
            connector="fp",
            playbook="t",
            params={},
        )
        service.resolve_pending()
        service.score()
    return database


@pytest.fixture(scope="module")
def client(seeded: dict[str, str]) -> Iterator[TestClient]:
    settings = Settings(
        env="local",
        auth_mode="local-dev",
        local_master_key_b64=base64.b64encode(TEST_MASTER_KEY).decode(),
        local_blind_index_key_b64=base64.b64encode(TEST_BLIND_INDEX_KEY).decode(),
        database_url=seeded["api"],
        beacon_allowed_origins=["https://www.example-seller.com"],
        web_events_queue_url="https://sqs.us-east-1.amazonaws.com/123456789012/web-events",
        linkedin_queue_url="https://sqs.us-east-1.amazonaws.com/123456789012/linkedin",
    )  # type: ignore[arg-type]
    brief_generator = MagicMock()
    brief_generator.model_id = "anthropic.claude-opus-5-5"
    brief_generator.generate.return_value = AccountBrief(
        summary="Northwind is scaling sales after a Series B.",
        why_now=["funding"],
        talking_points=["SDR ramp"],
        risks=["in-house tooling"],
        recommended_next_step="Email RevOps",
        confidence="medium",
    )
    services = AppServices(
        settings=settings,
        db=Database(lambda: seeded["api"]),
        cipher=FieldCipher(LocalKeyProvider(TEST_MASTER_KEY), tenant_id="test"),
        bidx=BlindIndexer(TEST_BLIND_INDEX_KEY),
        brief_generator=brief_generator,
        sqs=MagicMock(),
    )
    with TestClient(create_app(settings, services=services)) as test_client:
        test_client.services = services  # type: ignore[attr-defined]
        yield test_client


def _territory_header(seeded: dict[str, str], name: str) -> str:
    with psycopg.connect(seeded["owner"]) as conn:
        row = conn.execute(
            "SELECT id::text FROM sales.territory WHERE name = %s", (name,)
        ).fetchone()
    assert row
    return str(row[0])


def test_security_headers_and_health(client: TestClient) -> None:
    response = client.get("/api/healthz")
    assert response.status_code == 200
    for header in (
        "strict-transport-security",
        "x-content-type-options",
        "content-security-policy",
        "x-request-id",
        "cache-control",
    ):
        assert header in response.headers
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/api/readyz").json() == {"status": "ok"}


def test_lead_list_and_360(client: TestClient) -> None:
    listing = client.get("/api/v1/leads", headers=ANALYST, params={"q": "northwind"}).json()
    names = {(i["organization"]["name"], (i["person"] or {}).get("name")) for i in listing["items"]}
    assert ("Northwind Analytics", "Jordan Lee") in names
    person_lead = next(i for i in listing["items"] if i["person"])

    view = client.get(f"/api/v1/leads/{person_lead['id']}", headers=ANALYST).json()
    org = view["organization"]
    assert org["attributes"]["employee_count"]["value"] == 312
    assert org["attributes"]["employee_count"]["source"] == "scrapebadger.linkedin.company"
    assert org["attributes"]["employee_count"]["alternatives"][0]["value"] == 350
    # Analysts lack pii:read: contact details come back masked.
    assert view["person"]["contact"] == {
        "email": "j***@northwindanalytics.com",
        "phone": "+*******0199",
        "masked": True,
    }
    assert {s["type"] for s in view["signals"]} >= {
        "funding",
        "form_submission",
        "high_intent_page",
    }
    assert {e["type"] for e in view["graph"]["edges"]} >= {"works_at"}
    assert {c["purpose"] for c in view["consent"]} == {"marketing_email"}
    assert view["lead"]["explanation"]


def test_compliance_officer_sees_pii_and_it_is_audited(client: TestClient) -> None:
    lead = next(
        i for i in client.get("/api/v1/leads", headers=ANALYST).json()["items"] if i["person"]
    )
    view = client.get(f"/api/v1/leads/{lead['id']}", headers=COMPLIANCE).json()
    assert view["person"]["contact"]["email"] == "jordan.lee@northwindanalytics.com"
    trail = client.get(
        "/api/v1/audit",
        headers=COMPLIANCE,
        params={"resource_type": "lead", "resource_id": lead["id"]},
    ).json()["items"]
    assert any(e["action"] == "pii.read" for e in trail)
    assert client.get("/api/v1/audit/verify", headers=COMPLIANCE).json() == {
        "intact": True,
        "broken_at": None,
    }


def test_permissions_are_enforced_and_denials_audited(client: TestClient) -> None:
    denied = client.get("/api/v1/audit", headers=VIEWER)
    assert denied.status_code == 403
    assert denied.headers["content-type"].startswith("application/problem+json")
    assert denied.json()["details"] == {"missing": ["audit:read"]}
    trail = client.get(
        "/api/v1/audit", headers=COMPLIANCE, params={"resource_type": "endpoint"}
    ).json()["items"]
    assert any(
        e["action"] == "authz.denied" and e["actor_id"] == VIEWER["x-dev-user"] for e in trail
    )


def test_territory_scoping_through_the_api(client: TestClient, seeded: dict[str, str]) -> None:
    emea_rep = {
        "x-dev-user": "00000000-0000-0000-0000-0000000000b2",
        "x-dev-roles": "sales_rep",
        "x-dev-territories": _territory_header(seeded, "EMEA"),
    }
    assert client.get("/api/v1/leads", headers=emea_rep).json()["items"] == []
    lead = client.get("/api/v1/leads", headers=ANALYST).json()["items"][0]
    assert client.get(f"/api/v1/leads/{lead['id']}", headers=emea_rep).status_code == 404


def test_lead_update_requires_assign_for_owner_changes(client: TestClient) -> None:
    lead = client.get("/api/v1/leads", headers=ANALYST).json()["items"][0]
    ok = client.patch(f"/api/v1/leads/{lead['id']}", headers=ANALYST, json={"status": "working"})
    assert ok.status_code == 200
    forbidden = client.patch(
        f"/api/v1/leads/{lead['id']}",
        headers=ANALYST,
        json={"owner_user_id": "00000000-0000-0000-0000-0000000000a1"},
    )
    assert forbidden.status_code == 403
    invalid = client.patch(f"/api/v1/leads/{lead['id']}", headers=ANALYST, json={"status": "won"})
    assert invalid.status_code == 422


def test_search_and_entity_lineage(client: TestClient) -> None:
    hits = client.get("/api/v1/search", headers=ANALYST, params={"q": "northwind"}).json()["items"]
    org = next(
        h for h in hits if h["type"] == "organization" and h["name"] == "Northwind Analytics"
    )
    entity = client.get(f"/api/v1/entities/{org['id']}", headers=ANALYST).json()
    sources = {r["source"] for r in entity["lineage"]}
    assert {"scrapebadger.linkedin.company", "scrapebadger.web", "linkedin.lead_sync"} <= sources
    assert all("method" in r["match"] for r in entity["lineage"])
    graph = client.get(
        f"/api/v1/entities/{org['id']}/graph", headers=ANALYST, params={"depth": 2}
    ).json()
    assert any(n["label"] == "Jordan Lee" for n in graph["nodes"])


def test_ai_brief_is_generated_cached_and_audited(client: TestClient) -> None:
    lead = next(
        i for i in client.get("/api/v1/leads", headers=ANALYST).json()["items"] if i["person"]
    )
    first = client.post(f"/api/v1/leads/{lead['id']}/brief", headers=ANALYST).json()
    second = client.post(f"/api/v1/leads/{lead['id']}/brief", headers=ANALYST).json()
    assert first["cached"] is False
    assert second["cached"] is True
    generator = client.services.brief_generator  # type: ignore[attr-defined]
    assert generator.generate.call_count == 1
    brief_input = generator.generate.call_args.args[0]
    assert "full_name" in brief_input.person  # the generator itself drops identity fields
    assert "jordan" not in json.dumps(brief_input.as_payload()).lower()


def test_privacy_endpoints(client: TestClient) -> None:
    created = client.post(
        "/api/v1/privacy/dsar",
        headers=COMPLIANCE,
        json={"request_type": "erasure", "jurisdiction": "gdpr", "email": "Someone@Example.org"},
    )
    assert created.status_code == 201
    dsar_id = created.json()["id"]
    assert (
        client.post(f"/api/v1/privacy/dsar/{dsar_id}/approve", headers=COMPLIANCE).status_code
        == 200
    )
    assert (
        client.post(f"/api/v1/privacy/dsar/{dsar_id}/approve", headers=COMPLIANCE).status_code
        == 404
    )
    suppressed = client.post(
        "/api/v1/privacy/suppressions",
        headers=COMPLIANCE,
        json={
            "identifier_type": "domain",
            "value": "https://www.globex.com",
            "reason": "do_not_contact",
        },
    )
    assert suppressed.status_code == 201
    assert (
        client.post(
            "/api/v1/privacy/dsar",
            headers=ANALYST,
            json={"request_type": "access", "jurisdiction": "gdpr", "email": "a@b.co"},
        ).status_code
        == 403
    )


def test_beacon_cors_and_validation(client: TestClient) -> None:
    sqs = client.services.sqs  # type: ignore[attr-defined]
    event = {
        "visitor_id": "v_9f8e7d6c5b4a3f2e",
        "event": "page_view",
        "url": "https://www.example-seller.com/pricing",
        "ts": "2026-10-01T10:00:00Z",
    }
    ok = client.post(
        "/api/collect",
        content=json.dumps(event),
        headers={"origin": "https://www.example-seller.com", "content-type": "text/plain"},
    )
    assert ok.status_code == 204
    assert ok.headers["access-control-allow-origin"] == "https://www.example-seller.com"
    assert sqs.send_message.called
    evil = client.post(
        "/api/collect", content=json.dumps(event), headers={"origin": "https://evil.example"}
    )
    assert evil.status_code == 403
    bad = client.post(
        "/api/collect",
        content=json.dumps({**event, "visitor_id": "x"}),
        headers={"origin": "https://www.example-seller.com"},
    )
    assert bad.status_code == 422


def test_oversized_bodies_are_rejected(client: TestClient) -> None:
    response = client.post("/api/collect", content=b"x" * 2_000_000)
    assert response.status_code == 413


def test_linkedin_webhook_signature(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from leadintel.api.routers import ingest

    monkeypatch.setattr(ingest, "_linkedin_secret", lambda svc: "client-secret")
    challenge = client.get("/api/webhooks/linkedin", params={"challengeCode": "abc"}).json()
    assert (
        challenge["challengeResponse"]
        == hmac.new(b"client-secret", b"abc", hashlib.sha256).hexdigest()
    )
    body = json.dumps(
        {"leadGenFormResponse": "urn:li:leadGenFormResponse:resp-1", "leadAction": "CREATED"}
    ).encode()
    signature = hmac.new(b"client-secret", b"hmacsha256=" + body, hashlib.sha256).hexdigest()
    accepted = client.post(
        "/api/webhooks/linkedin", content=body, headers={"x-li-signature": signature}
    )
    assert accepted.status_code == 200
    forged = client.post(
        "/api/webhooks/linkedin", content=body, headers={"x-li-signature": "0" * 64}
    )
    assert forged.status_code == 401


def test_review_queue_accept_flow(client: TestClient, seeded: dict[str, str]) -> None:
    # Create two near-duplicate organizations and a pending review between them.
    with psycopg.connect(seeded["owner"]) as conn:
        a, b = (
            conn.execute(
                "INSERT INTO graph.entity (entity_type, display_name) VALUES ('organization', %s)"
                " RETURNING id",
                (name,),
            ).fetchone()[0]
            for name in ("Initech", "Initech Inc")
        )
        record_id = conn.execute(
            "INSERT INTO ingest.source_record (id, source, external_id, entity_type,"
            " observed_at, content_hash,"
            " lawful_basis) VALUES (gen_random_uuid(), 'manual', 'initech-1',"
            " 'organization', now(), 'h',"
            " 'legitimate_interest') RETURNING id"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO graph.entity_member (source_record_id, entity_id,"
            " match_probability, method)"
            " VALUES (%s, %s, 1, 'seed')",
            (record_id, a),
        )
        review_id = conn.execute(
            "INSERT INTO graph.match_candidate (source_record_id, record_entity_id,"
            " candidate_entity_id,"
            " probability, evidence) VALUES (%s, %s, %s, 0.82, '[]') RETURNING id",
            (record_id, a, b),
        ).fetchone()[0]
    queue = client.get("/api/v1/review", headers=ANALYST).json()["items"]
    assert any(item["id"] == str(review_id) for item in queue)
    decided = client.post(
        f"/api/v1/review/{review_id}", headers=ANALYST, json={"decision": "accept"}
    )
    assert decided.status_code == 200
    again = client.post(f"/api/v1/review/{review_id}", headers=ANALYST, json={"decision": "reject"})
    assert again.status_code == 409
    with psycopg.connect(seeded["owner"]) as conn:
        status: Any = conn.execute("SELECT status FROM graph.entity WHERE id = %s", (a,)).fetchone()
    assert status == ("merged",)
