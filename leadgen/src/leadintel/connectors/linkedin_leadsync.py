"""LinkedIn Lead Sync: Lead Gen Form responses through LinkedIn's official API.

This is the compliant way to get LinkedIn *people* into the platform: the member
submitted a form on LinkedIn and chose to share their details with us. Access
is a separate LinkedIn program (apply for Lead Sync API access; Advertising API
access does not include it).

Flow::

    LinkedIn --(leadNotifications webhook, X-LI-Signature)--> API /webhooks/linkedin
        -> SQS -> worker: GET /rest/leadFormResponses/{id} -> map -> ingest

A ``DELETED`` notification means the member withdrew the lead; the worker
erases the corresponding source record (LinkedIn's terms require it).

The response shape below follows the versioned ``/rest`` API (``Linkedin-Version``
header). Field paths are isolated in this module and covered by
``tests/contract/test_linkedin_leadsync.py``; re-record that fixture when access
is granted and whenever the API version is bumped.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx

from leadintel.compliance.consent import ConsentRecord, ConsentStatus, Purpose
from leadintel.core.errors import ConnectorError, RateLimitedError, SourceNotFoundError
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
from leadintel.pipeline.normalize import (
    clean_text,
    company_domain,
    country_code,
    email_domain,
    employee_range_to_count,
    linkedin_url,
    normalize_email,
    normalize_phone,
    parse_linkedin_url,
    split_person_name,
)
from leadintel.security.blind_index import BlindIndexer

API_BASE = "https://api.linkedin.com/rest"
RESPONSE_FIELDS = (
    "id,submittedAt,testLead,leadType,owner,versionedLeadGenFormUrn,"
    "formResponse,form:(id,name,hiddenFields,content)"
)

TokenSource = Callable[[], Awaitable[str]]


class LinkedInLeadSyncClient:
    def __init__(self, http: httpx.AsyncClient, *, token: TokenSource, api_version: str) -> None:
        self._http = http
        self._token = token
        self._version = api_version

    async def _get(self, url: str) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {await self._token()}",
            "Linkedin-Version": self._version,
            "X-Restli-Protocol-Version": "2.0.0",
        }
        try:
            response = await self._http.get(url, headers=headers, timeout=20)
        except httpx.HTTPError as exc:
            raise ConnectorError("LinkedIn API unreachable", retryable=True) from exc
        if response.status_code == 404:
            raise SourceNotFoundError("lead form response not found")
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            raise RateLimitedError(
                "LinkedIn API throttled",
                retry_after_s=int(retry_after) if retry_after and retry_after.isdigit() else None,
            )
        if response.status_code >= 500:
            raise ConnectorError(f"LinkedIn API {response.status_code}", retryable=True)
        if response.status_code >= 400:
            raise ConnectorError(f"LinkedIn API rejected the request ({response.status_code})")
        body: dict[str, Any] = response.json()
        return body

    async def get_response(self, response_id: str) -> dict[str, Any]:
        return await self._get(
            f"{API_BASE}/leadFormResponses/{quote(response_id, safe='')}?fields={RESPONSE_FIELDS}"
        )

    async def responses_by_owner(
        self, sponsored_account_id: str, *, since: datetime, until: datetime, page_size: int = 50
    ) -> AsyncIterator[dict[str, Any]]:
        """Backfill/reconciliation path when webhooks were missed."""
        owner = quote(f"urn:li:sponsoredAccount:{sponsored_account_id}", safe="")
        since_ms, until_ms = int(since.timestamp() * 1000), int(until.timestamp() * 1000)
        start = 0
        while True:
            # Rest.li query syntax: parentheses/colons stay literal, URNs are percent-encoded.
            url = (
                f"{API_BASE}/leadFormResponses?q=owner&owner=(sponsoredAccount:{owner})"
                "&leadType=(leadType:SPONSORED)&limitedToTestLeads=false"
                f"&submittedAtTimeRange=(start:{since_ms},end:{until_ms})"
                f"&fields={RESPONSE_FIELDS}&start={start}&count={page_size}"
            )
            page = await self._get(url)
            elements = page.get("elements") or []
            for element in elements:
                yield element
            if len(elements) < page_size:
                return
            start += page_size


def _answer_text(answer: dict[str, Any]) -> str | None:
    details = answer.get("answerDetails") or {}
    text = (details.get("textQuestionAnswer") or {}).get("answer")
    if text is not None:
        return str(text)
    options = (details.get("multipleChoiceAnswer") or {}).get("options")
    if options:
        return ",".join(str(o) for o in options)
    return None


def _answers_by_field(response: dict[str, Any]) -> dict[str, str]:
    questions = ((response.get("form") or {}).get("content") or {}).get("questions") or []
    field_by_question = {
        q.get("questionId"): q.get("predefinedField") or q.get("name") for q in questions
    }
    answers: dict[str, str] = {}
    for answer in (response.get("formResponse") or {}).get("answers") or []:
        field = field_by_question.get(answer.get("questionId"))
        text = _answer_text(answer)
        if field and text:
            answers[str(field).upper()] = text
    return answers


def map_lead_form_response(
    response: dict[str, Any], *, bidx: BlindIndexer, include_test_leads: bool = False
) -> tuple[list[SourceRecord], list[Signal], list[ConsentRecord]]:
    if response.get("testLead") and not include_test_leads:
        return [], [], []
    response_id = str(response["id"])
    submitted_at = datetime.fromtimestamp(int(response["submittedAt"]) / 1000, tz=UTC)
    answers = _answers_by_field(response)

    email = normalize_email(answers.get("WORK_EMAIL") or answers.get("EMAIL"))
    phone = normalize_phone(answers.get("WORK_PHONE_NUMBER") or answers.get("PHONE_NUMBER"))
    first, last, full = split_person_name(
        " ".join(p for p in (answers.get("FIRST_NAME"), answers.get("LAST_NAME")) if p)
    )
    linkedin = parse_linkedin_url(answers.get("LINKEDIN_PROFILE_LINK"))
    person_slug = linkedin[1] if linkedin and linkedin[0] == "person" else None
    company_name = clean_text(answers.get("COMPANY_NAME"))
    org_domain = company_domain(email_domain(email))

    consents = (response.get("formResponse") or {}).get("consentResponses") or []
    accepted = any(c.get("accepted") for c in consents)
    # Submitting the form is a request to be contacted about it; marketing needs consent.
    basis = LawfulBasis.CONSENT if accepted else LawfulBasis.LEGITIMATE_INTEREST

    restricted = {k: v for k, v in {"email": email, "phone": phone}.items() if v}
    org_hint = EntityHint(entity_type=EntityType.ORGANIZATION, domain=org_domain, name=company_name)
    person = SourceRecord(
        source=Source.LINKEDIN_LEAD_SYNC,
        external_id=response_id,
        entity_type=EntityType.PERSON,
        observed_at=submitted_at,
        attributes={
            k: v
            for k, v in {
                "full_name": full,
                "first_name": first,
                "last_name": last,
                "title": clean_text(answers.get("JOB_TITLE")),
                "seniority": clean_text(answers.get("SENIORITY")),
                "city": clean_text(answers.get("CITY")),
                "region": clean_text(answers.get("STATE")),
                "country": country_code(answers.get("COUNTRY")),
                "company_name": company_name,
                "company_domain": org_domain,
                "linkedin_slug": person_slug,
                "linkedin_url": linkedin_url("person", person_slug) if person_slug else None,
            }.items()
            if v
        },
        restricted=restricted,
        relationships=[RelationshipAssertion(rel_type=RelationType.WORKS_AT, target=org_hint)]
        if not org_hint.is_empty()
        else [],
        lawful_basis=basis,
    )
    records = [person]
    if company_name or org_domain:
        records.append(
            SourceRecord(
                source=Source.LINKEDIN_LEAD_SYNC,
                external_id=f"{response_id}#organization",
                entity_type=EntityType.ORGANIZATION,
                observed_at=submitted_at,
                attributes={
                    k: v
                    for k, v in {
                        "name": company_name,
                        "domain": org_domain,
                        "industry": clean_text(answers.get("INDUSTRY")),
                        "employee_range": clean_text(answers.get("COMPANY_SIZE")),
                        "employee_count": employee_range_to_count(answers.get("COMPANY_SIZE")),
                    }.items()
                    if v
                },
                lawful_basis=basis,
            )
        )

    email_bidx = bidx.maybe_index(email, field="email")
    form_name = (response.get("form") or {}).get("name")
    signals = [
        Signal(
            signal_type=SignalType.FORM_SUBMISSION,
            source=Source.LINKEDIN_LEAD_SYNC,
            external_id=response_id,
            occurred_at=submitted_at,
            subject=EntityHint(
                entity_type=EntityType.PERSON, email_bidx=email_bidx, linkedin_slug=person_slug
            ),
            title=f"Submitted LinkedIn lead form{f': {form_name}' if form_name else ''}",
            strength=0.9,
            attributes={"form_urn": response.get("versionedLeadGenFormUrn")},
        )
    ]
    consent_records = [
        ConsentRecord(
            subject_bidx=email_bidx,
            purpose=Purpose.MARKETING_EMAIL,
            status=ConsentStatus.GRANTED if c.get("accepted") else ConsentStatus.DENIED,
            lawful_basis=LawfulBasis.CONSENT,
            source=Source.LINKEDIN_LEAD_SYNC.value,
            captured_at=submitted_at,
            evidence={"response_id": response_id, "consent_id": c.get("consentId")},
        )
        for c in consents
        if email_bidx
    ]
    return records, signals, consent_records
