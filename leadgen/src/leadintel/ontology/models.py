"""Ontology objects.

Three kinds of facts flow through the platform:

* :class:`SourceRecord` - what one source said about one person or organization
  at one point in time. Immutable; the unit of provenance.
* :class:`Signal` - a time-stamped event that hints at intent or engagement
  (a job posting, a funding round, a pricing-page visit, a form fill).
* :class:`GoldenRecord` - the resolved view of an entity, where every attribute
  value remembers which source asserted it, when, and what the alternatives were.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from leadintel.core.ids import stable_uuid


class EntityType(StrEnum):
    PERSON = "person"
    ORGANIZATION = "organization"


class Source(StrEnum):
    SB_LINKEDIN_COMPANY = "scrapebadger.linkedin.company"
    SB_LINKEDIN_PROFILE = "scrapebadger.linkedin.profile"
    SB_LINKEDIN_JOBS = "scrapebadger.linkedin.jobs"
    SB_GOOGLE_MAPS = "scrapebadger.google.maps"
    SB_GOOGLE_SERP = "scrapebadger.google.serp"
    SB_GOOGLE_NEWS = "scrapebadger.google.news"
    SB_WEB = "scrapebadger.web"
    LINKEDIN_LEAD_SYNC = "linkedin.lead_sync"
    GA4 = "google.ga4"
    FIRST_PARTY_WEB = "first_party.web"
    CRM = "crm"
    MANUAL = "manual"


class SignalType(StrEnum):
    JOB_POSTING = "job_posting"
    FUNDING = "funding"
    ACQUISITION = "acquisition"
    EXPANSION = "expansion"
    LEADERSHIP_CHANGE = "leadership_change"
    NEWS_MENTION = "news_mention"
    TECH_DETECTED = "tech_detected"
    WEB_VISIT = "web_visit"
    HIGH_INTENT_PAGE = "high_intent_page"
    CONTENT_DOWNLOAD = "content_download"
    FORM_SUBMISSION = "form_submission"
    EMAIL_CLICK = "email_click"
    MEETING_BOOKED = "meeting_booked"


class LawfulBasis(StrEnum):
    """GDPR Art. 6 basis recorded with every personal-data record."""

    CONSENT = "consent"
    LEGITIMATE_INTEREST = "legitimate_interest"
    CONTRACT = "contract"


class RelationType(StrEnum):
    WORKS_AT = "works_at"
    WORKED_AT = "worked_at"
    ALUMNI_OF = "alumni_of"
    USES_TECHNOLOGY = "uses_technology"
    MENTIONED_IN = "mentioned_in"
    SUBSIDIARY_OF = "subsidiary_of"
    COMPETITOR_OF = "competitor_of"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EntityHint(_Frozen):
    """How a signal or relationship points at an entity *before* resolution.

    The resolver turns hints into entity ids by looking up the same blocking
    keys it uses for matching (domain, LinkedIn slug, blind-indexed email...).
    """

    entity_type: EntityType
    domain: str | None = None
    linkedin_slug: str | None = None
    google_place_id: str | None = None
    email_bidx: str | None = None
    visitor_id: str | None = None
    name: str | None = None

    def is_empty(self) -> bool:
        return not any(
            (
                self.domain,
                self.linkedin_slug,
                self.google_place_id,
                self.email_bidx,
                self.visitor_id,
                self.name,
            )
        )


class RelationshipAssertion(_Frozen):
    rel_type: RelationType
    target: EntityHint
    properties: dict[str, Any] = Field(default_factory=dict)
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class SourceRecord(_Frozen):
    """One source's statement about one entity.

    ``attributes`` uses the canonical names in :mod:`leadintel.ontology.attributes`.
    ``restricted`` holds identifiers that must be encrypted at rest (email, personal
    phone); it exists only in memory and is envelope-encrypted before persistence.
    """

    source: Source
    external_id: str
    entity_type: EntityType
    observed_at: datetime
    attributes: dict[str, Any] = Field(default_factory=dict)
    restricted: dict[str, str] = Field(default_factory=dict, repr=False)
    relationships: list[RelationshipAssertion] = Field(default_factory=list)
    lawful_basis: LawfulBasis = LawfulBasis.LEGITIMATE_INTEREST
    source_url: str | None = None

    @field_validator("external_id")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("external_id must not be blank")
        return value

    @property
    def id(self) -> UUID:
        return stable_uuid("source_record", self.source.value, self.external_id)

    def content_hash(self) -> str:
        """Hash of everything the record asserts; unchanged hash means nothing to re-resolve."""
        body = {
            "attributes": self.attributes,
            "restricted": self.restricted,
            "relationships": [r.model_dump(mode="json") for r in self.relationships],
        }
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()


class Signal(_Frozen):
    signal_type: SignalType
    source: Source
    external_id: str
    occurred_at: datetime
    subject: EntityHint
    title: str
    strength: float = Field(default=0.5, ge=0.0, le=1.0)
    url: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)

    @property
    def id(self) -> UUID:
        return stable_uuid("signal", self.source.value, self.signal_type.value, self.external_id)


class RawPayload(_Frozen):
    """An upstream response kept verbatim in the bronze zone so mappers can be re-run."""

    source: Source
    external_id: str
    fetched_at: datetime
    body: Any
    content_type: str = "application/json"


class FetchBatch(BaseModel):
    """Everything one connector call produced."""

    records: list[SourceRecord] = Field(default_factory=list)
    signals: list[Signal] = Field(default_factory=list)
    raw: list[RawPayload] = Field(default_factory=list)
    credits_used: int = 0
    warnings: list[str] = Field(default_factory=list)

    def extend(self, other: FetchBatch) -> None:
        self.records.extend(other.records)
        self.signals.extend(other.signals)
        self.raw.extend(other.raw)
        self.credits_used += other.credits_used
        self.warnings.extend(other.warnings)


class Provenance(_Frozen):
    source: Source
    source_record_id: UUID
    observed_at: datetime
    trust: float = Field(ge=0.0, le=1.0)


class AttributeValue(_Frozen):
    """A survived attribute value plus the evidence for it and the values it beat."""

    value: Any
    provenance: Provenance
    confidence: float = Field(ge=0.0, le=1.0)
    agreeing_sources: int = 1
    alternatives: list[AlternativeValue] = Field(default_factory=list)


class AlternativeValue(_Frozen):
    value: Any
    provenance: Provenance


class GoldenRecord(BaseModel):
    entity_id: UUID
    entity_type: EntityType
    attributes: dict[str, AttributeValue] = Field(default_factory=dict)
    member_record_ids: list[UUID] = Field(default_factory=list)

    def value(self, name: str) -> Any:
        attr = self.attributes.get(name)
        return attr.value if attr else None

    @property
    def display_name(self) -> str | None:
        keys = ("name", "domain") if self.entity_type is EntityType.ORGANIZATION else ("full_name",)
        for key in keys:
            if value := self.value(key):
                return str(value)
        return None


AttributeValue.model_rebuild()
