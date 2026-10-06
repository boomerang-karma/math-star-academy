"""Privacy operations: suppression list and data-subject requests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from leadintel.api import queries
from leadintel.api.deps import AppServices, audit_event, require, services
from leadintel.compliance.dsar import due_date
from leadintel.core.errors import NotFoundError, ValidationFailedError
from leadintel.pipeline.normalize import (
    company_domain,
    normalize_email,
    normalize_phone,
    parse_linkedin_url,
)
from leadintel.security.authz import Permission, Principal

router = APIRouter(prefix="/v1/privacy", tags=["privacy"])


class SuppressionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identifier_type: Literal["email", "phone", "domain", "linkedin_slug"]
    value: str = Field(min_length=3, max_length=320)
    reason: Literal["objection", "unsubscribe", "do_not_contact"]


def _normalize_identifier(kind: str, value: str) -> str:
    normalized: str | None
    if kind == "email":
        normalized = normalize_email(value)
    elif kind == "phone":
        normalized = normalize_phone(value)
    elif kind == "domain":
        normalized = company_domain(value)
    else:
        parsed = parse_linkedin_url(value)
        normalized = parsed[1] if parsed else value.strip().lower()
    if not normalized:
        raise ValidationFailedError(f"not a valid {kind}")
    return normalized


@router.post("/suppressions", status_code=201)
def add_suppression(
    body: SuppressionRequest,
    request: Request,
    principal: Principal = Depends(require(Permission.COMPLIANCE_SUPPRESS)),
    svc: AppServices = Depends(services),
) -> dict[str, Any]:
    normalized = _normalize_identifier(body.identifier_type, body.value)
    bidx = svc.bidx.index(normalized, field=body.identifier_type)
    with svc.db.scoped(principal) as conn:
        created = queries.add_suppression(
            conn,
            identifier_type=body.identifier_type,
            bidx=bidx,
            reason=body.reason,
            actor=principal.subject,
        )
        # The audit trail records the fingerprint, never the identifier itself.
        queries.append_audit(
            conn,
            audit_event(
                request,
                principal,
                action="privacy.suppress",
                resource_type="suppression",
                resource_id=bidx[:16],
                details={"type": body.identifier_type, "reason": body.reason},
            ),
        )
    return {"created": created}


class DsarRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_type: Literal[
        "access", "erasure", "rectification", "restriction", "objection", "portability"
    ]
    jurisdiction: Literal["gdpr", "uk_gdpr", "ccpa", "other"]
    email: str = Field(max_length=320)


@router.post("/dsar", status_code=201)
def create_dsar(
    body: DsarRequest,
    request: Request,
    principal: Principal = Depends(require(Permission.COMPLIANCE_DSAR)),
    svc: AppServices = Depends(services),
) -> dict[str, Any]:
    email = normalize_email(body.email)
    if email is None:
        raise ValidationFailedError("not a valid email")
    received = datetime.now(UTC)
    with svc.db.scoped(principal) as conn:
        row = queries.create_dsar(
            conn,
            request_type=body.request_type,
            jurisdiction=body.jurisdiction,
            subject_bidx=svc.bidx.index(email, field="email"),
            due_at=due_date(body.jurisdiction, received),
            actor=principal.subject,
        )
        queries.append_audit(
            conn,
            audit_event(
                request,
                principal,
                action="privacy.dsar.create",
                resource_type="dsar",
                resource_id=str(row["id"]),
                details={"type": body.request_type},
            ),
        )
    return {
        **row,
        "id": str(row["id"]),
        "received_at": row["received_at"].isoformat(),
        "due_at": row["due_at"].isoformat(),
    }


@router.get("/dsar")
def list_dsars(
    open_only: bool = True,
    principal: Principal = Depends(require(Permission.COMPLIANCE_DSAR)),
    svc: AppServices = Depends(services),
) -> dict[str, Any]:
    with svc.db.scoped(principal) as conn:
        rows = queries.list_dsars(conn, open_only=open_only)
    return {"items": [{**r, "id": str(r["id"])} for r in rows]}


@router.post("/dsar/{dsar_id}/approve")
def approve_dsar(
    dsar_id: UUID,
    request: Request,
    principal: Principal = Depends(require(Permission.COMPLIANCE_DSAR)),
    svc: AppServices = Depends(services),
) -> dict[str, Any]:
    """Identity verified out of band: hand the request to the DSAR worker."""
    with svc.db.scoped(principal) as conn:
        if not queries.approve_dsar(conn, dsar_id, principal.subject):
            raise NotFoundError("no open request with that id")
        queries.append_audit(
            conn,
            audit_event(
                request,
                principal,
                action="privacy.dsar.approve",
                resource_type="dsar",
                resource_id=str(dsar_id),
            ),
        )
    return {"id": str(dsar_id), "status": "in_progress"}
