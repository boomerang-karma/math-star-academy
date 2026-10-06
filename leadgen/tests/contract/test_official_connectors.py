"""LinkedIn Lead Sync, GA4 and first-party beacon mapping."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import ValidationError

from leadintel.compliance.consent import ConsentStatus
from leadintel.connectors.first_party import TrackEvent, event_signals, form_source_records
from leadintel.connectors.ga4 import (
    Ga4Client,
    GoogleServiceAccountTokenProvider,
    map_visitor_activity,
    visitor_activity_request,
)
from leadintel.connectors.linkedin_leadsync import LinkedInLeadSyncClient, map_lead_form_response
from leadintel.core.errors import RateLimitedError, SourceNotFoundError
from leadintel.ontology.models import EntityType, LawfulBasis, SignalType
from leadintel.pipeline.icp import DEFAULT_ICP
from leadintel.security.blind_index import BlindIndexer

FIXTURES = Path(__file__).parent / "fixtures"


def load(path: str) -> dict:  # type: ignore[type-arg]
    return json.loads((FIXTURES / path).read_text())


# ---------------------------------------------------------------- LinkedIn Lead Sync


def test_lead_form_response_mapping(bidx: BlindIndexer) -> None:
    records, signals, consents = map_lead_form_response(
        load("linkedin/lead_form_response.json"), bidx=bidx
    )
    person, org = records
    assert person.entity_type is EntityType.PERSON
    assert person.attributes["full_name"] == "Jordan Lee"
    assert person.attributes["title"] == "Head of Revenue Operations"
    assert person.attributes["company_domain"] == "northwindanalytics.com"
    assert person.restricted == {
        "email": "jordan.lee@northwindanalytics.com",
        "phone": "+15125550199",
    }
    assert "email" not in person.attributes  # restricted data never travels in attributes
    assert person.lawful_basis is LawfulBasis.CONSENT
    assert person.relationships[0].target.domain == "northwindanalytics.com"
    assert org.attributes == {
        "name": "Northwind Analytics",
        "domain": "northwindanalytics.com",
        "employee_range": "201-500",
        "employee_count": 350,
    }
    (signal,) = signals
    assert signal.signal_type is SignalType.FORM_SUBMISSION
    assert signal.subject.email_bidx == bidx.index(
        "jordan.lee@northwindanalytics.com", field="email"
    )
    assert signal.occurred_at == datetime.fromtimestamp(1727700000, tz=UTC)
    assert [c.status for c in consents] == [ConsentStatus.GRANTED]


def test_test_leads_are_skipped(bidx: BlindIndexer) -> None:
    payload = load("linkedin/lead_form_response.json") | {"testLead": True}
    assert map_lead_form_response(payload, bidx=bidx) == ([], [], [])


async def _token() -> str:
    return "li-access-token"


@respx.mock
async def test_lead_sync_client_headers_and_errors() -> None:
    route = respx.get(url__regex=r"https://api\.linkedin\.com/rest/leadFormResponses/abc.*").mock(
        return_value=httpx.Response(200, json={"id": "abc"})
    )
    async with httpx.AsyncClient() as http:
        client = LinkedInLeadSyncClient(http, token=_token, api_version="202608")
        assert await client.get_response("abc") == {"id": "abc"}
        headers = route.calls.last.request.headers
        assert headers["Authorization"] == "Bearer li-access-token"
        assert headers["Linkedin-Version"] == "202608"
        assert headers["X-Restli-Protocol-Version"] == "2.0.0"

        route.mock(return_value=httpx.Response(404))
        with pytest.raises(SourceNotFoundError):
            await client.get_response("abc")
        route.mock(return_value=httpx.Response(429, headers={"Retry-After": "30"}))
        with pytest.raises(RateLimitedError) as info:
            await client.get_response("abc")
        assert info.value.retry_after_s == 30


# ---------------------------------------------------------------- GA4


def test_visitor_activity_request_shape() -> None:
    body = visitor_activity_request(
        start=date(2026, 9, 1),
        end=date(2026, 9, 30),
        visitor_dimension="customUser:lead_visitor_id",
    )
    assert body["dimensions"][0] == {"name": "customUser:lead_visitor_id"}
    assert body["dateRanges"] == [{"startDate": "2026-09-01", "endDate": "2026-09-30"}]


def test_visitor_activity_mapping() -> None:
    signals = map_visitor_activity(load("ga4/visitor_report.json"), icp=DEFAULT_ICP)
    visits = [s for s in signals if s.signal_type is SignalType.WEB_VISIT]
    intents = [s for s in signals if s.signal_type is SignalType.HIGH_INTENT_PAGE]
    assert {s.subject.visitor_id for s in visits} == {"v_9f8e7d6c5b4a3f2e", "v_1a2b3c4d5e6f7a8b"}
    first = next(s for s in visits if s.subject.visitor_id == "v_9f8e7d6c5b4a3f2e")
    assert first.attributes["page_views"] == 5
    assert first.attributes["top_pages"] == ["/pricing", "/"]
    assert first.occurred_at == datetime(2026, 9, 29, tzinfo=UTC)
    assert [s.attributes["path"] for s in intents] == ["/pricing"]


@respx.mock
async def test_ga4_token_exchange_and_report() -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    token_route = respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(200, json={"access_token": "ya29.token", "expires_in": 3600})
    )
    report_route = respx.post(
        "https://analyticsdata.googleapis.com/v1beta/properties/123:runReport"
    ).mock(return_value=httpx.Response(200, json={"rows": []}))
    async with httpx.AsyncClient() as http:
        tokens = GoogleServiceAccountTokenProvider(
            http,
            {
                "client_email": "sa@proj.iam.gserviceaccount.com",
                "private_key": pem,
                "private_key_id": "k1",
            },
        )
        client = Ga4Client(http, property_id="123", token=tokens)
        await client.run_report({"limit": 1})
        await client.run_report({"limit": 1})
    assert token_route.call_count == 1  # cached
    assert report_route.calls.last.request.headers["Authorization"] == "Bearer ya29.token"
    form = dict(x.split("=", 1) for x in token_route.calls.last.request.content.decode().split("&"))
    assert form["grant_type"] == "urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Ajwt-bearer"


# ---------------------------------------------------------------- first-party beacon


def _event(**overrides: object) -> TrackEvent:
    base: dict[str, object] = {
        "visitor_id": "v_9f8e7d6c5b4a3f2e",
        "event": "page_view",
        "url": "https://www.example-seller.com/pricing?utm_source=li",
        "ts": "2026-09-30T10:00:00Z",
        "utm": {"utm_source": "linkedin", "evil": "x"},
    }
    base.update(overrides)
    return TrackEvent.model_validate(base)


def test_beacon_validation() -> None:
    event = _event()
    assert event.utm == {"utm_source": "linkedin"}  # unknown keys dropped
    assert event.url == "https://www.example-seller.com/pricing"
    with pytest.raises(ValidationError):
        _event(visitor_id="short")
    with pytest.raises(ValidationError):
        _event(url="javascript:alert(1)")
    with pytest.raises(ValidationError):
        _event(extra_field="x")


def test_beacon_signals(bidx: BlindIndexer) -> None:
    (pricing,) = event_signals(_event(), icp=DEFAULT_ICP, bidx=bidx)
    assert pricing.signal_type is SignalType.HIGH_INTENT_PAGE
    (visit,) = event_signals(
        _event(url="https://www.example-seller.com/blog"), icp=DEFAULT_ICP, bidx=bidx
    )
    assert visit.signal_type is SignalType.WEB_VISIT
    assert visit.attributes["path"] == "/blog"


def test_form_submission_links_visitor_to_email(bidx: BlindIndexer) -> None:
    event = _event(
        event="form_submit",
        form={
            "email": "Avery@NorthwindAnalytics.com",
            "name": "Avery Quinn",
            "company": "Northwind",
            "form_id": "demo-request",
            "marketing_consent": False,
        },
    )
    (signal,) = event_signals(event, icp=DEFAULT_ICP, bidx=bidx)
    assert signal.signal_type is SignalType.FORM_SUBMISSION
    assert signal.subject.visitor_id == "v_9f8e7d6c5b4a3f2e"
    assert signal.subject.email_bidx == bidx.index("avery@northwindanalytics.com", field="email")
    person, org = form_source_records(event)
    assert person.restricted == {"email": "avery@northwindanalytics.com"}
    assert person.lawful_basis is LawfulBasis.LEGITIMATE_INTEREST
    assert org.attributes["domain"] == "northwindanalytics.com"
