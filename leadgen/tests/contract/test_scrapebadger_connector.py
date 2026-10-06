"""Contract tests: the real ScrapeBadger SDK against recorded-shape HTTP fixtures.

These pin the request paths, auth header and response shapes our mappers rely on.
When upgrading the ``scrapebadger`` pin, refresh fixtures from live responses
(``make refresh-fixtures`` with a key) and re-run: a failure here is the early
warning that upstream changed.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from leadintel.connectors.base import CreditBudget, RunContext
from leadintel.connectors.scrapebadger.connector import ScrapeBadgerConnector
from leadintel.connectors.scrapebadger.gateway import ScrapeBadgerGateway
from leadintel.core.errors import (
    BudgetExceededError,
    ComplianceBlockedError,
    ConnectorError,
    RateLimitedError,
    SourceNotFoundError,
)
from leadintel.ontology.models import EntityType, RelationType, SignalType, Source

BASE = "https://scrapebadger.com"
FIXTURES = Path(__file__).parent / "fixtures" / "scrapebadger"
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def ctx() -> RunContext:
    return RunContext(budget=CreditBudget(1_000), clock=lambda: NOW)


@pytest.fixture
async def connector():  # type: ignore[no-untyped-def]
    gateway = ScrapeBadgerGateway.from_api_key("sb_test_key123456", max_retries=0, timeout_s=5)
    yield ScrapeBadgerConnector(gateway, allow_person_profiles=True, url_validator=lambda url: url)
    await gateway.close()


@respx.mock
async def test_company_profile_by_slug(connector: ScrapeBadgerConnector, ctx: RunContext) -> None:
    route = respx.get(f"{BASE}/v1/linkedin/companies/northwind-analytics").mock(
        return_value=httpx.Response(200, json=fixture("linkedin_company.json"))
    )
    batch = await connector.run("company_profile", {"linkedin_slug": "northwind-analytics"}, ctx)

    request = route.calls.last.request
    assert request.headers["x-api-key"] == "sb_test_key123456"
    assert request.url.params["country"] == "us"
    (record,) = batch.records
    assert record.source is Source.SB_LINKEDIN_COMPANY
    assert record.entity_type is EntityType.ORGANIZATION
    assert record.attributes["domain"] == "northwindanalytics.com"
    assert record.attributes["website"] == "https://www.northwindanalytics.com"
    assert record.attributes["employee_count"] == 312
    assert record.attributes["hq_country"] == "US"
    assert batch.raw[0].body["universal_name"] == "northwind-analytics"
    assert ctx.budget.used == 5


@respx.mock
async def test_company_profile_discovers_slug_via_google(
    connector: ScrapeBadgerConnector, ctx: RunContext
) -> None:
    serp = respx.get(f"{BASE}/v1/google/search").mock(
        return_value=httpx.Response(200, json=fixture("google_search_company.json"))
    )
    respx.get(f"{BASE}/v1/linkedin/companies/northwind-analytics").mock(
        return_value=httpx.Response(200, json=fixture("linkedin_company.json"))
    )
    batch = await connector.run("company_profile", {"company_name": "Northwind Analytics"}, ctx)
    assert serp.calls.last.request.url.params["mode"] == "fast"
    assert batch.records[0].attributes["linkedin_slug"] == "northwind-analytics"


@respx.mock
async def test_market_hiring_scan_maps_job_cards(
    connector: ScrapeBadgerConnector, ctx: RunContext
) -> None:
    route = respx.get(f"{BASE}/v1/linkedin/jobs/search").mock(
        return_value=httpx.Response(200, json=fixture("linkedin_jobs_search.json"))
    )
    batch = await connector.run(
        "market_hiring_scan", {"keywords": ["sales development"], "location": "United States"}, ctx
    )
    assert route.calls.last.request.url.params["date_posted"] == "past_week"
    signals = {s.external_id: s for s in batch.signals}
    assert set(signals) == {"4012345678", "4012345679"}  # card without a company is dropped
    sdr = signals["4012345678"]
    assert sdr.signal_type is SignalType.JOB_POSTING
    assert sdr.subject.linkedin_slug == "northwind-analytics"
    assert sdr.strength == 1.0  # an ICP role
    assert sdr.occurred_at == datetime(2026, 9, 28, tzinfo=UTC)
    assert signals["4012345679"].strength == 0.3  # hiring, but not for a role we sell into
    assert signals["4012345679"].subject.linkedin_slug == "contoso-robotics"


@respx.mock
async def test_local_discovery_maps_places(
    connector: ScrapeBadgerConnector, ctx: RunContext
) -> None:
    respx.get(f"{BASE}/v1/google/maps/search").mock(
        return_value=httpx.Response(200, json=fixture("google_maps_search.json"))
    )
    batch = await connector.run("local_discovery", {"query": "bakery springfield il"}, ctx)
    by_id = {r.external_id: r for r in batch.records}
    assert set(by_id) == {"ChIJfabrikam0001", "ChIJwingtip0002"}
    bakery = by_id["ChIJfabrikam0001"].attributes
    assert bakery["domain"] == "fabrikambakery.com"
    assert bakery["phone"] == "+12175550142"
    assert bakery["review_count"] == 312
    assert bakery["categories"] == ["Bakery"]
    coffee = by_id["ChIJwingtip0002"].attributes
    assert "domain" not in coffee  # a Facebook page is not a company domain
    assert coffee["categories"] == ["Coffee shop", "Cafe"]


@respx.mock
async def test_news_triggers_classifies_and_drops_namesakes(
    connector: ScrapeBadgerConnector, ctx: RunContext
) -> None:
    respx.get(f"{BASE}/v1/google/news/search").mock(
        return_value=httpx.Response(200, json=fixture("google_news_company.json"))
    )
    batch = await connector.run("news_triggers", {"company_name": "Northwind Analytics"}, ctx)
    kinds = sorted(s.signal_type.value for s in batch.signals)
    assert kinds == ["funding", "leadership_change"]
    funding = next(s for s in batch.signals if s.signal_type is SignalType.FUNDING)
    assert funding.url == "https://news.example.com/northwind-series-b"
    assert funding.attributes["publisher"] == "TechWire"
    assert funding.occurred_at == datetime(2026, 9, 22, 14, 0, tzinfo=UTC)


@respx.mock
async def test_website_enrichment_detects_technologies(
    connector: ScrapeBadgerConnector, ctx: RunContext
) -> None:
    route = respx.post(f"{BASE}/v1/web/scrape").mock(
        return_value=httpx.Response(200, json=fixture("web_scrape_homepage.json"))
    )
    batch = await connector.run("website_enrichment", {"domain": "www.northwindanalytics.com"}, ctx)
    body = json.loads(route.calls.last.request.content)
    assert body["url"] == "https://northwindanalytics.com"
    (record,) = batch.records
    assert record.attributes["name"] == "Northwind Analytics"
    assert record.attributes["description"] == "Forecast revenue with confidence."
    assert record.attributes["technologies"] == ["google_analytics", "hubspot", "nextjs", "segment"]
    assert ctx.budget.used == 1  # reported credits_used wins over the estimate


@respx.mock
async def test_person_profile_maps_employment_graph(
    connector: ScrapeBadgerConnector, ctx: RunContext
) -> None:
    respx.get(f"{BASE}/v1/linkedin/profiles/avery-quinn-4a1b2c").mock(
        return_value=httpx.Response(200, json=fixture("linkedin_profile.json"))
    )
    batch = await connector.run("person_profile", {"public_id": "avery-quinn-4a1b2c"}, ctx)
    (person,) = batch.records
    assert person.entity_type is EntityType.PERSON
    assert person.attributes["full_name"] == "Avery Quinn"
    assert person.attributes["title"] == "VP Sales"
    assert person.attributes["city"] == "Austin"
    assert person.attributes["country"] == "US"
    rels = {(r.rel_type, r.target.linkedin_slug) for r in person.relationships}
    assert rels == {
        (RelationType.WORKS_AT, "northwind-analytics"),
        (RelationType.WORKED_AT, "contoso-robotics"),
    }


async def test_person_profiles_are_gated(ctx: RunContext) -> None:
    gateway = ScrapeBadgerGateway.from_api_key("sb_test_key123456", max_retries=0)
    try:
        gated = ScrapeBadgerConnector(gateway)
        with pytest.raises(ComplianceBlockedError):
            await gated.run("person_profile", {"public_id": "x"}, ctx)
    finally:
        await gateway.close()


@respx.mock
@pytest.mark.parametrize(
    ("status", "payload", "error", "retryable"),
    [
        (429, {"detail": "slow down", "limit": 60, "remaining": 0}, RateLimitedError, True),
        (402, {"detail": "no credits"}, BudgetExceededError, False),
        (404, {"detail": "no such company"}, SourceNotFoundError, False),
        (401, {"detail": "bad key"}, ConnectorError, False),
        (500, {"detail": "boom"}, ConnectorError, True),
    ],
)
async def test_gateway_maps_upstream_errors(
    connector: ScrapeBadgerConnector,
    ctx: RunContext,
    status: int,
    payload: dict[str, Any],
    error: type[Exception],
    retryable: bool,
) -> None:
    respx.get(f"{BASE}/v1/linkedin/companies/acme").mock(
        return_value=httpx.Response(status, json=payload, headers={"Retry-After": "7"})
    )
    with pytest.raises(error) as info:
        await connector.run("company_profile", {"linkedin_slug": "acme"}, ctx)
    assert info.value.retryable is retryable  # type: ignore[attr-defined]
    if status == 429:
        assert info.value.retry_after_s == 7  # type: ignore[attr-defined]


@respx.mock
async def test_gateway_maps_network_errors(
    connector: ScrapeBadgerConnector, ctx: RunContext
) -> None:
    respx.get(f"{BASE}/v1/linkedin/companies/acme").mock(side_effect=httpx.ConnectTimeout("t/o"))
    with pytest.raises(ConnectorError) as info:
        await connector.run("company_profile", {"linkedin_slug": "acme"}, ctx)
    assert info.value.retryable


async def test_budget_is_checked_before_calling(connector: ScrapeBadgerConnector) -> None:
    tight = RunContext(budget=CreditBudget(3), clock=lambda: NOW)
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(f"{BASE}/v1/linkedin/companies/acme")
        with pytest.raises(BudgetExceededError):
            await connector.run("company_profile", {"linkedin_slug": "acme"}, tight)
        assert not route.called


@respx.mock
async def test_account_research_tolerates_partial_failure(
    connector: ScrapeBadgerConnector, ctx: RunContext
) -> None:
    respx.get(f"{BASE}/v1/google/search").mock(
        return_value=httpx.Response(200, json=fixture("google_search_company.json"))
    )
    respx.get(f"{BASE}/v1/linkedin/companies/northwind-analytics").mock(
        return_value=httpx.Response(200, json=fixture("linkedin_company.json"))
    )
    respx.post(f"{BASE}/v1/web/scrape").mock(
        return_value=httpx.Response(404, json={"detail": "gone"})
    )
    respx.get(f"{BASE}/v1/google/news/search").mock(
        return_value=httpx.Response(200, json=fixture("google_news_company.json"))
    )
    batch = await connector.run("account_research", {"company_name": "Northwind Analytics"}, ctx)
    assert [r.source for r in batch.records] == [Source.SB_LINKEDIN_COMPANY]
    assert len(batch.signals) == 2
    assert any("website_enrichment" in w for w in batch.warnings)
