"""The whole pipeline on a real database: five sources stitched into one 360-degree view.

Sources: ScrapeBadger (LinkedIn company page, company website, Google News,
LinkedIn job search, Google Maps), LinkedIn Lead Sync, the first-party beacon
and GA4. The same person and company arrive through several of them; the test
asserts they resolve into single entities with provenance, linked signals and
explainable scores, and that row-level security scopes what an API user sees.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from scrapebadger.linkedin.models import Company, JobsSearchResponse

from leadintel.connectors.first_party import TrackEvent, event_signals, form_source_records
from leadintel.connectors.ga4 import map_visitor_activity
from leadintel.connectors.linkedin_leadsync import map_lead_form_response
from leadintel.connectors.scrapebadger import mappers
from leadintel.ontology.models import EntityHint, EntityType, FetchBatch, RawPayload, Source
from leadintel.pipeline.icp import DEFAULT_ICP
from leadintel.pipeline.service import PipelineService
from leadintel.security.authz import Principal, Role
from leadintel.security.blind_index import BlindIndexer
from leadintel.security.crypto import FieldCipher
from leadintel.storage.db import connect, principal_scope
from leadintel.storage.pipeline_repo import PipelineRepository
from leadintel.storage.raw_store import LocalRawStore

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).parents[1] / "contract" / "fixtures"
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(scope="module")
def pipeline_db(database: dict[str, str]) -> dict[str, str]:
    return database


@pytest.fixture
def service(pipeline_db: dict[str, str], cipher: FieldCipher, bidx: BlindIndexer, tmp_path: Path):  # type: ignore[no-untyped-def]
    conn = connect(pipeline_db["worker"])
    repo = PipelineRepository(conn, cipher=cipher, bidx=bidx)
    yield PipelineService(
        repo, raw_store=LocalRawStore(tmp_path), bidx=bidx, icp=DEFAULT_ICP, clock=lambda: NOW
    )
    conn.close()


def _scrapebadger_batch() -> FetchBatch:
    company = Company.model_validate(load("scrapebadger/linkedin_company.json"))
    jobs = JobsSearchResponse.model_validate(load("scrapebadger/linkedin_jobs_search.json"))
    web = load("scrapebadger/web_scrape_homepage.json")
    hint = EntityHint(entity_type=EntityType.ORGANIZATION, name="Northwind Analytics")
    batch = FetchBatch(
        records=[
            mappers.map_linkedin_company(company, now=NOW),
            mappers.map_website(
                web["content"], domain="northwindanalytics.com", url=web["url"], now=NOW
            ),
            *[
                r
                for p in load("scrapebadger/google_maps_search.json")["results"]
                if (r := mappers.map_maps_place(p, region="us", now=NOW))
            ],
        ],
        signals=[
            *mappers.map_news(
                load("scrapebadger/google_news_company.json"),
                company=hint,
                company_name="Northwind Analytics",
                now=NOW,
            ),
            *[s for c in jobs.jobs if (s := mappers.map_job_card(c, icp=DEFAULT_ICP, now=NOW))],
        ],
        raw=[
            RawPayload(
                source=Source.SB_LINKEDIN_COMPANY,
                external_id="northwind-analytics",
                fetched_at=NOW,
                body=load("scrapebadger/linkedin_company.json"),
            )
        ],
        credits_used=17,
    )
    return batch


def _first_party_event() -> TrackEvent:
    return TrackEvent.model_validate(
        {
            "visitor_id": "v_9f8e7d6c5b4a3f2e",
            "event": "form_submit",
            "url": "https://www.example-seller.com/demo",
            "ts": "2026-09-30T16:00:00Z",
            "form": {
                "email": "jordan.lee@northwindanalytics.com",
                "name": "Jordan Lee",
                "company": "Northwind Analytics",
                "form_id": "demo-request",
            },
        }
    )


def test_end_to_end_stitching(
    service: PipelineService, bidx: BlindIndexer, pipeline_db: dict[str, str]
) -> None:
    # 1. ScrapeBadger: firmographics, website, news, jobs, local businesses.
    summary = service.ingest(
        _scrapebadger_batch(),
        connector="scrapebadger",
        playbook="account_research",
        params={"company_name": "Northwind Analytics"},
    )
    assert summary["records"]["inserted"] == 4
    assert summary["signals"] == 4

    # 2. LinkedIn Lead Sync: Jordan fills a lead-gen form on LinkedIn.
    records, signals, consents = map_lead_form_response(
        load("linkedin/lead_form_response.json"), bidx=bidx
    )
    service.ingest(
        FetchBatch(records=records, signals=signals),
        connector="linkedin_leadsync",
        playbook="webhook",
        params={},
        consents=consents,
    )

    # 3. Website: Jordan requests a demo (identifies visitor v_9f8e...), GA4 saw earlier visits.
    event = _first_party_event()
    service.ingest(
        FetchBatch(
            records=form_source_records(event),
            signals=event_signals(event, icp=DEFAULT_ICP, bidx=bidx)
            + map_visitor_activity(load("ga4/visitor_report.json"), icp=DEFAULT_ICP),
        ),
        connector="first_party",
        playbook="beacon",
        params={},
    )

    result = service.resolve_pending()
    assert result["records"] >= 9
    assert service.score() >= 3

    conn = service.repo.conn
    orgs = conn.execute(
        "SELECT id, display_name, golden FROM graph.entity WHERE entity_type ="
        " 'organization' AND status = 'active'"
    ).fetchall()
    northwind = [o for o in orgs if o["display_name"] == "Northwind Analytics"]
    assert len(northwind) == 1, [o["display_name"] for o in orgs]
    org = northwind[0]
    golden = org["golden"]
    assert golden["employee_count"]["value"] == 312
    assert golden["employee_count"]["provenance"]["source"] == "scrapebadger.linkedin.company"
    assert {a["value"] for a in golden["employee_count"]["alternatives"]} == {350}
    assert "hubspot" in golden["technologies"]["value"]
    members = conn.execute(
        "SELECT sr.source FROM graph.entity_member m JOIN ingest.source_record sr ON sr.id ="
        " m.source_record_id"
        " WHERE m.entity_id = %s",
        (org["id"],),
    ).fetchall()
    assert {m["source"] for m in members} >= {
        "scrapebadger.linkedin.company",
        "scrapebadger.web",
        "linkedin.lead_sync",
        "first_party.web",
    }

    people = conn.execute(
        "SELECT id, display_name, pii_envelope, email_bidx FROM graph.entity WHERE"
        " entity_type = 'person'"
    ).fetchall()
    assert [p["display_name"] for p in people] == ["Jordan Lee"]  # form + lead form merged by email
    jordan = people[0]
    assert jordan["email_bidx"] == bidx.index("jordan.lee@northwindanalytics.com", field="email")
    assert (
        service.repo.decrypt_restricted(jordan["pii_envelope"])["email"]
        == "jordan.lee@northwindanalytics.com"
    )

    works_at = conn.execute(
        "SELECT dst_entity_id FROM graph.relationship WHERE src_entity_id = %s AND rel_type"
        " = 'works_at'",
        (jordan["id"],),
    ).fetchall()
    assert {w["dst_entity_id"] for w in works_at} == {org["id"]}

    signal_types = {
        row["signal_type"]
        for row in conn.execute(
            "SELECT signal_type FROM graph.signal WHERE entity_id = ANY(%s)",
            ([org["id"], jordan["id"]],),
        ).fetchall()
    }
    # funding + CMO news, SDR job, LinkedIn form, demo form, GA4 visits and pricing view
    assert signal_types >= {
        "funding",
        "leadership_change",
        "job_posting",
        "form_submission",
        "web_visit",
        "high_intent_page",
    }
    assert conn.execute(
        "SELECT visitor_id FROM graph.identity_link WHERE entity_id = %s", (jordan["id"],)
    ).fetchall() == [{"visitor_id": "v_9f8e7d6c5b4a3f2e"}]

    leads = conn.execute(
        "SELECT person_entity_id, tier, hot, score, score_explanation, territory_id FROM sales.lead"
        " WHERE organization_entity_id = %s",
        (org["id"],),
    ).fetchall()
    person_lead = next(lead for lead in leads if lead["person_entity_id"] == jordan["id"])
    account_lead = next(lead for lead in leads if lead["person_entity_id"] is None)
    assert person_lead["hot"]
    assert person_lead["tier"] in {"A", "B"}
    assert account_lead["tier"] in {"A", "B"}
    assert {c["component"] for c in person_lead["score_explanation"]} == {
        "fit",
        "intent",
        "engagement",
    }
    assert person_lead["territory_id"] is not None

    # Scraped Google Maps businesses become accounts but never person leads.
    assert conn.execute(
        "SELECT count(*) AS n FROM sales.lead l JOIN graph.entity e ON e.id ="
        " l.organization_entity_id"
        " WHERE e.display_name = 'Fabrikam Bakery'"
    ).fetchone() == {"n": 1}
    conn.commit()


def test_reingesting_identical_data_is_a_no_op(service: PipelineService) -> None:
    summary = service.ingest(
        _scrapebadger_batch(), connector="scrapebadger", playbook="account_research", params={}
    )
    assert summary["records"] == {"unchanged": 4}
    assert summary["signals"] == 0
    assert service.resolve_pending()["records"] == 0


def test_suppressed_identifiers_are_never_stored(
    service: PipelineService, bidx: BlindIndexer, pipeline_db: dict[str, str]
) -> None:
    # Suppressions are written by the API (compliance officer); workers may only read them.
    with connect(pipeline_db["api"]) as api:
        api.execute(
            "INSERT INTO privacy.suppression (identifier_type, identifier_bidx, reason, created_by)"
            " VALUES ('domain', %s, 'objection', 'test')",
            (bidx.index("contosorobotics.io", field="domain"),),
        )
        api.commit()
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        service.repo.conn.execute("DELETE FROM privacy.suppression")
    service.repo.conn.rollback()

    conn = service.repo.conn
    record = mappers.map_website(
        "<title>Contoso Robotics</title>",
        domain="contosorobotics.io",
        url="https://contosorobotics.io",
        now=NOW,
    )
    summary = service.ingest(
        FetchBatch(records=[record]),
        connector="scrapebadger",
        playbook="website_enrichment",
        params={},
    )
    assert summary["records"] == {"suppressed": 1}
    assert conn.execute(
        "SELECT count(*) AS n FROM ingest.source_record WHERE external_id = 'contosorobotics.io'"
    ).fetchone() == {"n": 0}


def _visible_leads(dsn: str, principal: Principal) -> list[dict[str, Any]]:
    with connect(dsn) as conn, principal_scope(conn, principal):
        return conn.execute(
            "SELECT id, organization_name, person_name FROM sales.v_lead_overview"
        ).fetchall()


def test_row_level_security_scopes_api_reads(pipeline_db: dict[str, str]) -> None:
    with psycopg.connect(pipeline_db["owner"]) as admin:
        territories = dict(admin.execute("SELECT name, id::text FROM sales.territory").fetchall())
    north_america, emea = territories["North America"], territories["EMEA"]

    analyst = Principal("00000000-0000-0000-0000-0000000000a1", frozenset({Role.ANALYST}), "t")
    rep_na = Principal(
        "00000000-0000-0000-0000-0000000000b1",
        frozenset({Role.SALES_REP}),
        "t",
        territories=frozenset({north_america}),
    )
    rep_emea = Principal(
        "00000000-0000-0000-0000-0000000000b2",
        frozenset({Role.SALES_REP}),
        "t",
        territories=frozenset({emea}),
    )
    nobody = Principal("not-a-uuid", frozenset(), "t")

    everything = _visible_leads(pipeline_db["api"], analyst)
    assert len(everything) >= 3
    na = _visible_leads(pipeline_db["api"], rep_na)
    assert {row["organization_name"] for row in na} >= {"Northwind Analytics"}
    assert any(row["person_name"] == "Jordan Lee" for row in na)
    assert _visible_leads(pipeline_db["api"], rep_emea) == []
    assert _visible_leads(pipeline_db["api"], nobody) == []

    # People are only visible through a visible lead; organizations are shared.
    with connect(pipeline_db["api"]) as conn, principal_scope(conn, rep_emea):
        types = {
            r["entity_type"]
            for r in conn.execute("SELECT entity_type FROM graph.entity").fetchall()
        }
        assert types == {"organization"}
    # Column-level grants: the API cannot rewrite scores.
    with (
        connect(pipeline_db["api"]) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
        principal_scope(conn, analyst),
    ):
        conn.execute("UPDATE sales.lead SET score = 100")


def test_merge_entities_function(pipeline_db: dict[str, str], service: PipelineService) -> None:
    conn = service.repo.conn
    rows = conn.execute(
        "SELECT id FROM graph.entity WHERE entity_type = 'organization' AND status = 'active'"
        " AND display_name IN ('Fabrikam Bakery', 'Wingtip Coffee Roasters') ORDER BY display_name"
    ).fetchall()
    fabrikam, wingtip = (UUID(str(r["id"])) for r in rows)
    with connect(pipeline_db["api"]) as api:
        api.execute("SELECT graph.merge_entities(%s, %s, %s)", (wingtip, fabrikam, "analyst-1"))
        api.commit()
    conn.rollback()
    merged = conn.execute(
        "SELECT status, merged_into FROM graph.entity WHERE id = %s", (wingtip,)
    ).fetchone()
    assert merged == {"status": "merged", "merged_into": fabrikam}
    survivor = conn.execute(
        "SELECT golden_stale FROM graph.entity WHERE id = %s", (fabrikam,)
    ).fetchone()
    assert survivor == {"golden_stale": True}
    assert service.resolve_pending()["entities_touched"] == 1  # stale golden recomputed
    conn.commit()
