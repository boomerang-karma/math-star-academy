"""Survivorship: build an entity's golden record from its member source records.

For every attribute, each distinct value is scored by the best supporting
source (trust x recency) plus a bonus for each additional source that agrees.
The winner keeps full provenance, and the losing values are kept as
alternatives, so the UI can answer "who says this, since when, and who
disagrees?" for any field. Attribute-specific source preferences encode what
each source is actually good at (Maps for phone numbers, LinkedIn for headcount,
the company's own website for its technology stack).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from leadintel.ontology.models import (
    AlternativeValue,
    AttributeValue,
    EntityType,
    GoldenRecord,
    Provenance,
    Source,
)

SOURCE_TRUST: Mapping[Source, float] = {
    Source.MANUAL: 1.0,
    Source.LINKEDIN_LEAD_SYNC: 0.95,  # self-reported by the person
    Source.FIRST_PARTY_WEB: 0.9,  # self-reported on our website
    Source.CRM: 0.9,
    Source.SB_LINKEDIN_COMPANY: 0.85,
    Source.SB_LINKEDIN_PROFILE: 0.8,
    Source.SB_WEB: 0.75,
    Source.SB_GOOGLE_MAPS: 0.7,
    Source.SB_LINKEDIN_JOBS: 0.6,
    Source.SB_GOOGLE_NEWS: 0.5,
    Source.SB_GOOGLE_SERP: 0.5,
    Source.GA4: 0.5,
}

# Per-attribute boosts for the source that is authoritative for that field.
ATTRIBUTE_PREFERENCE: Mapping[str, Mapping[Source, float]] = {
    "employee_count": {Source.SB_LINKEDIN_COMPANY: 0.15},
    "employee_range": {Source.SB_LINKEDIN_COMPANY: 0.15},
    "industry": {Source.SB_LINKEDIN_COMPANY: 0.1},
    "phone": {Source.SB_GOOGLE_MAPS: 0.25},
    "address": {Source.SB_GOOGLE_MAPS: 0.2},
    "rating": {Source.SB_GOOGLE_MAPS: 0.3},
    "review_count": {Source.SB_GOOGLE_MAPS: 0.3},
    "technologies": {Source.SB_WEB: 0.3},
    "description": {Source.SB_WEB: 0.1},
    "title": {Source.SB_LINKEDIN_PROFILE: 0.1},
}

MULTI_VALUED = frozenset({"technologies", "specialties", "categories"})
RECENCY_HALF_LIFE_DAYS = 365.0
AGREEMENT_BONUS = 0.1


@dataclass(frozen=True)
class MemberRecord:
    record_id: UUID
    source: Source
    observed_at: datetime
    attributes: Mapping[str, Any]


def _trust(source: Source, attribute: str) -> float:
    base = SOURCE_TRUST.get(source, 0.5)
    return min(1.0, base + ATTRIBUTE_PREFERENCE.get(attribute, {}).get(source, 0.0))


def _recency(observed_at: datetime, now: datetime) -> float:
    age_days = max((now - observed_at).total_seconds() / 86_400, 0.0)
    return float(0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS))


def _comparable(value: Any) -> str:
    if isinstance(value, str):
        return value.strip().casefold()
    return json.dumps(value, sort_keys=True, default=str)


def _provenance(member: MemberRecord, attribute: str) -> Provenance:
    return Provenance(
        source=member.source,
        source_record_id=member.record_id,
        observed_at=member.observed_at,
        trust=round(_trust(member.source, attribute), 3),
    )


def _survive_single(
    attribute: str, claims: list[tuple[Any, MemberRecord]], now: datetime
) -> AttributeValue:
    groups: dict[str, list[tuple[Any, MemberRecord]]] = {}
    for value, member in claims:
        groups.setdefault(_comparable(value), []).append((value, member))

    def group_score(group: list[tuple[Any, MemberRecord]]) -> tuple[float, datetime]:
        best = max(_trust(m.source, attribute) * _recency(m.observed_at, now) for _, m in group)
        distinct_sources = len({m.source for _, m in group})
        newest = max(m.observed_at for _, m in group)
        return best + AGREEMENT_BONUS * (distinct_sources - 1), newest

    ranked = sorted(groups.values(), key=group_score, reverse=True)
    winner = ranked[0]
    # Within the winning group, cite the most trusted, then most recent, claim.
    value, member = max(winner, key=lambda c: (_trust(c[1].source, attribute), c[1].observed_at))
    agreeing = len({m.source for _, m in winner})
    total_sources = len({m.source for _, m in claims})
    confidence = _trust(member.source, attribute) * (0.6 + 0.4 * agreeing / total_sources)
    alternatives = []
    for group in ranked[1:]:
        alt_value, alt_member = max(
            group, key=lambda c: (_trust(c[1].source, attribute), c[1].observed_at)
        )
        alternatives.append(
            AlternativeValue(value=alt_value, provenance=_provenance(alt_member, attribute))
        )
    return AttributeValue(
        value=value,
        provenance=_provenance(member, attribute),
        confidence=round(min(confidence, 1.0), 3),
        agreeing_sources=agreeing,
        alternatives=alternatives,
    )


def _survive_multi(attribute: str, claims: list[tuple[Any, MemberRecord]]) -> AttributeValue:
    """Union of list values; provenance points at the most trusted contributor."""
    merged: list[Any] = []
    seen: set[str] = set()
    for values, _ in sorted(claims, key=lambda c: -_trust(c[1].source, attribute)):
        for item in values if isinstance(values, list) else [values]:
            key = _comparable(item)
            if key not in seen:
                seen.add(key)
                merged.append(item)
    member = max((m for _, m in claims), key=lambda m: (_trust(m.source, attribute), m.observed_at))
    return AttributeValue(
        value=merged,
        provenance=_provenance(member, attribute),
        confidence=round(_trust(member.source, attribute), 3),
        agreeing_sources=len({m.source for _, m in claims}),
    )


def survive(
    entity_id: UUID,
    entity_type: EntityType,
    members: Iterable[MemberRecord],
    *,
    now: datetime,
) -> GoldenRecord:
    members = list(members)
    claims: dict[str, list[tuple[Any, MemberRecord]]] = {}
    for member in members:
        for attribute, value in member.attributes.items():
            if value in (None, "", [], {}):
                continue
            claims.setdefault(attribute, []).append((value, member))

    attributes: dict[str, AttributeValue] = {}
    for attribute, attribute_claims in sorted(claims.items()):
        if attribute in MULTI_VALUED:
            attributes[attribute] = _survive_multi(attribute, attribute_claims)
        else:
            attributes[attribute] = _survive_single(attribute, attribute_claims, now)
    return GoldenRecord(
        entity_id=entity_id,
        entity_type=entity_type,
        attributes=attributes,
        member_record_ids=sorted((m.record_id for m in members), key=str),
    )
