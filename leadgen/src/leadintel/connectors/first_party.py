"""First-party tracking beacon (``POST /api/collect``).

The website's small snippet sends page views and form submissions with a
random first-party ``visitor_id`` cookie. The beacon is the bridge between
anonymous behaviour and known people: a form submission carries both the
visitor id and an email, which links every earlier anonymous visit (ours and
GA4's) to that person.

Privacy by design: events are validated against a strict schema, IP addresses
are never stored, the email is blind-indexed and envelope-encrypted before it
reaches storage, and the snippet only loads after analytics consent where the
visitor's jurisdiction requires it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from leadintel.ontology.models import (
    EntityHint,
    EntityType,
    LawfulBasis,
    RelationshipAssertion,
    RelationType,
    Signal,
    SignalType,
    Source,
    SourceRecord,
)
from leadintel.pipeline.icp import IcpProfile
from leadintel.pipeline.normalize import (
    clean_text,
    company_domain,
    email_domain,
    normalize_email,
    normalize_url,
    split_person_name,
)
from leadintel.security.blind_index import BlindIndexer

_ID = r"^[A-Za-z0-9_-]{16,64}$"


class FormFields(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    email: str = Field(max_length=254)
    name: str | None = Field(default=None, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    title: str | None = Field(default=None, max_length=200)
    form_id: str = Field(max_length=100)
    marketing_consent: bool = False


class TrackEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    visitor_id: str = Field(pattern=_ID)
    session_id: str | None = Field(default=None, pattern=_ID)
    event: Literal["page_view", "form_submit", "download"]
    url: str = Field(max_length=2048)
    referrer: str | None = Field(default=None, max_length=2048)
    ts: datetime
    ga_client_id: str | None = Field(default=None, pattern=r"^\d{1,12}\.\d{1,12}$")
    utm: dict[str, str] = Field(default_factory=dict)
    form: FormFields | None = None

    @field_validator("utm")
    @classmethod
    def _utm(cls, value: dict[str, str]) -> dict[str, str]:
        allowed = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"}
        return {k: v[:200] for k, v in value.items() if k in allowed}

    @field_validator("url")
    @classmethod
    def _url(cls, value: str) -> str:
        normalized = normalize_url(value)
        if normalized is None:
            raise ValueError("url must be http(s)")
        return normalized


def _path(url: str) -> str:
    return urlsplit(url).path or "/"


def event_signals(event: TrackEvent, *, icp: IcpProfile, bidx: BlindIndexer) -> list[Signal]:
    path = _path(event.url)
    subject = EntityHint(entity_type=EntityType.PERSON, visitor_id=event.visitor_id)
    ext = f"{event.visitor_id}:{int(event.ts.timestamp() * 1000)}:{event.event}"
    if event.event == "form_submit" and event.form is not None:
        email = normalize_email(event.form.email)
        subject = EntityHint(
            entity_type=EntityType.PERSON,
            visitor_id=event.visitor_id,
            email_bidx=bidx.maybe_index(email, field="email"),
        )
        return [
            Signal(
                signal_type=SignalType.FORM_SUBMISSION,
                source=Source.FIRST_PARTY_WEB,
                external_id=ext,
                occurred_at=event.ts,
                subject=subject,
                title=f"Submitted form {event.form.form_id}",
                strength=0.9,
                url=event.url,
                attributes={"form_id": event.form.form_id, **event.utm},
            )
        ]
    if event.event == "download":
        return [
            Signal(
                signal_type=SignalType.CONTENT_DOWNLOAD,
                source=Source.FIRST_PARTY_WEB,
                external_id=ext,
                occurred_at=event.ts,
                subject=subject,
                title=f"Downloaded {path}",
                strength=0.6,
                url=event.url,
                attributes=dict(event.utm),
            )
        ]
    if icp.is_high_intent_path(path):
        return [
            Signal(
                signal_type=SignalType.HIGH_INTENT_PAGE,
                source=Source.FIRST_PARTY_WEB,
                external_id=ext,
                occurred_at=event.ts,
                subject=subject,
                title=f"Viewed {path}",
                strength=0.8,
                url=event.url,
                attributes={"path": path, **event.utm},
            )
        ]
    return [
        Signal(
            signal_type=SignalType.WEB_VISIT,
            source=Source.FIRST_PARTY_WEB,
            external_id=ext,
            occurred_at=event.ts,
            subject=subject,
            title=f"Viewed {path}",
            strength=0.2,
            url=event.url,
            attributes={"path": path, **event.utm},
        )
    ]


def form_source_records(event: TrackEvent) -> list[SourceRecord]:
    """The person (and their company) who identified themselves through a form."""
    if event.event != "form_submit" or event.form is None:
        return []
    email = normalize_email(event.form.email)
    if email is None:
        return []
    first, last, full = split_person_name(event.form.name)
    org_domain = company_domain(email_domain(email))
    company = clean_text(event.form.company)
    basis = LawfulBasis.CONSENT if event.form.marketing_consent else LawfulBasis.LEGITIMATE_INTEREST
    external_id = f"{event.form.form_id}:{event.visitor_id}:{int(event.ts.timestamp())}"
    org_hint = EntityHint(entity_type=EntityType.ORGANIZATION, domain=org_domain, name=company)
    records = [
        SourceRecord(
            source=Source.FIRST_PARTY_WEB,
            external_id=external_id,
            entity_type=EntityType.PERSON,
            observed_at=event.ts,
            attributes={
                k: v
                for k, v in {
                    "full_name": full,
                    "first_name": first,
                    "last_name": last,
                    "title": clean_text(event.form.title),
                    "company_name": company,
                    "company_domain": org_domain,
                }.items()
                if v
            },
            restricted={"email": email},
            relationships=[RelationshipAssertion(rel_type=RelationType.WORKS_AT, target=org_hint)]
            if not org_hint.is_empty()
            else [],
            lawful_basis=basis,
        )
    ]
    if org_domain or company:
        records.append(
            SourceRecord(
                source=Source.FIRST_PARTY_WEB,
                external_id=f"{external_id}#organization",
                entity_type=EntityType.ORGANIZATION,
                observed_at=event.ts,
                attributes={k: v for k, v in {"name": company, "domain": org_domain}.items() if v},
                lawful_basis=basis,
            )
        )
    return records
