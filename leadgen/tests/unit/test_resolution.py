from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import count
from typing import Any
from uuid import UUID

import pytest

from leadintel.ontology.models import EntityType, Source
from leadintel.pipeline.resolution.blocking import blocking_keys
from leadintel.pipeline.resolution.clustering import MAX_WEAK_BLOCK, resolve
from leadintel.pipeline.resolution.matching import Decision, compare
from leadintel.pipeline.resolution.model import EntitySnapshot, ResolvableRecord
from leadintel.pipeline.resolution.survivorship import MemberRecord, survive
from leadintel.security.blind_index import BlindIndexer

NOW = datetime(2026, 10, 1, tzinfo=UTC)
_ids = count(1)


def rid() -> UUID:
    return UUID(int=next(_ids))


def org(source: Source = Source.SB_LINKEDIN_COMPANY, **attrs: Any) -> ResolvableRecord:
    return ResolvableRecord(rid(), EntityType.ORGANIZATION, source, NOW, attrs)


def person(bidx: BlindIndexer, *, email: str | None = None, **attrs: Any) -> ResolvableRecord:
    return ResolvableRecord(
        rid(),
        EntityType.PERSON,
        Source.SB_LINKEDIN_PROFILE,
        NOW,
        attrs,
        email_bidx=bidx.maybe_index(email, field="email"),
    )


# ---------------------------------------------------------------- matching


def test_org_same_domain_is_deterministic_match() -> None:
    a = org(
        name="Northwind Analytics",
        domain="northwindanalytics.com",
        linkedin_slug="northwind-analytics",
    )
    b = org(Source.SB_WEB, name="Northwind Analytics | Revenue", domain="northwindanalytics.com")
    result = compare(a, b)
    assert result.decision is Decision.MATCH
    assert result.deterministic
    assert result.evidence[0].feature == "domain"


@pytest.mark.parametrize(
    ("a", "b", "decision"),
    [
        (
            {"name": "Acme", "domain": "acme.com"},
            {"name": "Acme", "domain": "acme.io"},
            Decision.NO_MATCH,
        ),
        ({"name": "Acme Bakery"}, {"name": "Acme Bakery"}, Decision.NO_MATCH),
        (
            {"name": "Acme Bakery", "phone": "+12175550142"},
            {"name": "ACME Bakery LLC", "phone": "+12175550142"},
            Decision.MATCH,
        ),
        (
            {"name": "Acme", "linkedin_slug": "acme"},
            {"name": "Acme", "linkedin_slug": "acme-corp"},
            Decision.NO_MATCH,
        ),
    ],
)
def test_org_matching_cases(a: dict[str, Any], b: dict[str, Any], decision: Decision) -> None:
    assert compare(org(**a), org(**b)).decision is decision


def test_person_matching_cases(bidx: BlindIndexer) -> None:
    by_email = compare(
        person(bidx, email="a@x.com", full_name="Avery Quinn"),
        person(bidx, email="a@x.com", full_name="A. Quinn"),
    )
    assert by_email.decision is Decision.MATCH
    assert by_email.deterministic

    # Same LinkedIn profile, work vs personal email: still the same person.
    by_slug = compare(
        person(bidx, email="avery@northwind.com", linkedin_slug="avery-q", full_name="Avery Quinn"),
        person(bidx, email="avery.q@gmail.com", linkedin_slug="avery-q", full_name="Avery Quinn"),
    )
    assert by_slug.decision is Decision.MATCH

    # Name + employer only: plausible, needs a human.
    soft = compare(
        person(bidx, full_name="Avery Quinn", company_name="Northwind Analytics"),
        person(bidx, full_name="Avery Quinn", company_name="Northwind Analytics Inc."),
    )
    assert soft.decision is Decision.REVIEW

    # A shared email next to two different LinkedIn profiles is suspicious, never automatic.
    conflict = compare(
        person(bidx, email="team@x.com", linkedin_slug="a", full_name="Avery Quinn"),
        person(bidx, email="team@x.com", linkedin_slug="b", full_name="Avery Quinn"),
    )
    assert conflict.decision is Decision.REVIEW

    different = compare(
        person(bidx, full_name="Avery Quinn", company_domain="x.com"),
        person(bidx, full_name="Jordan Lee", company_domain="x.com"),
    )
    assert different.decision is Decision.NO_MATCH


def test_compare_rejects_mixed_types(bidx: BlindIndexer) -> None:
    with pytest.raises(ValueError, match="person"):
        compare(org(name="x"), person(bidx, full_name="x"))


def test_person_blocking_keys_are_blind(bidx: BlindIndexer) -> None:
    keys = blocking_keys(
        person(
            bidx,
            email="a@x.com",
            full_name="Avery Quinn",
            linkedin_slug="avery-q",
            company_domain="x.com",
        ),
        bidx,
    )
    assert {k.split(":", 1)[0] for k in keys} == {"email", "li", "name_domain"}
    assert not any("avery" in k for k in keys)


# ---------------------------------------------------------------- clustering


def test_three_sources_collapse_into_one_new_entity(bidx: BlindIndexer) -> None:
    linkedin = org(
        name="Northwind Analytics",
        domain="northwindanalytics.com",
        linkedin_slug="northwind-analytics",
    )
    website = org(Source.SB_WEB, name="Northwind Analytics", domain="northwindanalytics.com")
    maps = org(
        Source.SB_GOOGLE_MAPS,
        name="Northwind Analytics HQ",
        domain="northwindanalytics.com",
        google_place_id="p1",
    )
    other = org(name="Contoso Robotics", domain="contosorobotics.io")
    outcome = resolve([linkedin, website, maps, other], [], bidx=bidx)
    assert len({outcome.assignments[r.record_id] for r in (linkedin, website, maps)}) == 1
    assert outcome.assignments[other.record_id] != outcome.assignments[linkedin.record_id]
    assert len(outcome.created) == 2
    assert outcome.evidence[website.record_id] is not None
    assert outcome.evidence[other.record_id] is None  # singleton, nothing matched
    assert outcome.reviews == []


def test_record_attaches_to_existing_entity(bidx: BlindIndexer) -> None:
    existing = EntitySnapshot(
        UUID(int=999),
        EntityType.ORGANIZATION,
        {"name": "Northwind Analytics", "domain": "northwindanalytics.com"},
    )
    record = org(Source.SB_WEB, name="Northwind", domain="northwindanalytics.com")
    outcome = resolve([record], [existing], bidx=bidx)
    assert outcome.assignments[record.record_id] == UUID(int=999)
    assert outcome.created == {}


def test_transitive_chain_through_conflicting_profiles_is_blocked(bidx: BlindIndexer) -> None:
    # A and C are different LinkedIn pages; B (no slug) matches both by domain.
    a = org(name="Globex", domain="globex.com", linkedin_slug="globex")
    b = org(Source.SB_WEB, name="Globex", domain="globex.com")
    c = org(name="Globex", domain="globex.com", linkedin_slug="globex-labs")
    outcome = resolve([a, b, c], [], bidx=bidx)
    assert outcome.assignments[a.record_id] != outcome.assignments[c.record_id]
    assert len(outcome.reviews) >= 1


def test_record_bridging_two_existing_entities_creates_review(bidx: BlindIndexer) -> None:
    e1 = EntitySnapshot(
        UUID(int=1001), EntityType.ORGANIZATION, {"name": "Initech", "domain": "initech.com"}
    )
    e2 = EntitySnapshot(
        UUID(int=1002), EntityType.ORGANIZATION, {"name": "Initech", "linkedin_slug": "initech"}
    )
    record = org(name="Initech", domain="initech.com", linkedin_slug="initech")
    outcome = resolve([record], [e1, e2], bidx=bidx)
    assigned = outcome.assignments[record.record_id]
    assert assigned in {UUID(int=1001), UUID(int=1002)}
    (review,) = outcome.reviews
    assert review.candidate_entity_id == ({UUID(int=1001), UUID(int=1002)} - {assigned}).pop()


def test_oversized_weak_blocks_are_skipped(bidx: BlindIndexer) -> None:
    records = [
        org(Source.SB_GOOGLE_MAPS, name="Main Street Pizza", google_place_id=f"p{i}")
        for i in range(MAX_WEAK_BLOCK + 1)
    ]
    outcome = resolve(records, [], bidx=bidx)
    assert "orgname:main street pizza" in outcome.skipped_blocks
    assert len(set(outcome.assignments.values())) == len(records)


# ---------------------------------------------------------------- survivorship


def member(source: Source, days_ago: int = 0, **attrs: Any) -> MemberRecord:
    return MemberRecord(rid(), source, NOW - timedelta(days=days_ago), attrs)


def test_survivorship_prefers_authoritative_sources_and_keeps_alternatives() -> None:
    linkedin = member(
        Source.SB_LINKEDIN_COMPANY,
        employee_count=312,
        name="Northwind Analytics",
        phone="+15125550100",
    )
    form = member(Source.LINKEDIN_LEAD_SYNC, employee_count=350, name="Northwind Analytics")
    maps = member(
        Source.SB_GOOGLE_MAPS, name="Northwind", phone="+15125550111", technologies=["wordpress"]
    )
    web = member(Source.SB_WEB, technologies=["hubspot", "segment"])
    golden = survive(UUID(int=7), EntityType.ORGANIZATION, [linkedin, form, maps, web], now=NOW)

    headcount = golden.attributes["employee_count"]
    assert headcount.value == 312  # LinkedIn is authoritative for headcount
    assert headcount.provenance.source is Source.SB_LINKEDIN_COMPANY
    assert [a.value for a in headcount.alternatives] == [350]

    name = golden.attributes["name"]
    assert name.value == "Northwind Analytics"
    assert name.agreeing_sources == 2
    assert golden.attributes["phone"].value == "+15125550111"  # Maps is authoritative for phones
    assert golden.attributes["technologies"].value == ["hubspot", "segment", "wordpress"]
    assert golden.display_name == "Northwind Analytics"
    assert len(golden.member_record_ids) == 4


def test_survivorship_recency_breaks_trust_ties() -> None:
    old = member(Source.SB_LINKEDIN_PROFILE, days_ago=400, title="Director of Sales")
    new = member(Source.SB_LINKEDIN_PROFILE, days_ago=10, title="VP Sales")
    golden = survive(UUID(int=8), EntityType.PERSON, [old, new], now=NOW)
    assert golden.attributes["title"].value == "VP Sales"
    assert golden.attributes["title"].alternatives[0].value == "Director of Sales"
