"""Tracked companies: the admin's watch list of accounts to research and follow."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from leadintel.api import queries
from leadintel.api.deps import AppServices, audit_event, require, services
from leadintel.core.errors import ConflictError, NotFoundError, ValidationFailedError
from leadintel.pipeline.normalize import company_domain, parse_linkedin_url
from leadintel.pipeline.tracking import start_research
from leadintel.security.authz import Permission, Principal

router = APIRouter(prefix="/v1/tracked-companies", tags=["tracked companies"])

MANAGE = require(Permission.CONNECTORS_CONFIGURE)


def _view(row: dict[str, Any]) -> dict[str, Any]:
    def iso(value: Any) -> str | None:
        return value.isoformat() if value else None

    return {
        "id": str(row["id"]),
        "name": row["name"],
        "domain": row["domain"],
        "linkedin_slug": row["linkedin_slug"],
        "notes": row["notes"],
        "status": row["status"],
        "added_by": row["added_by"],
        "created_at": iso(row["created_at"]),
        "last_research_at": iso(row["last_research_at"]),
        "last_run_status": row["last_run_status"],
        "entity": {"id": str(row["entity_id"]), "name": row["entity_name"]}
        if row.get("entity_id")
        else None,
        "lead": {
            "id": str(row["lead_id"]),
            "tier": row["tier"],
            "score": float(row["score"]) if row["score"] is not None else None,
        }
        if row.get("lead_id")
        else None,
    }


def _normalize_domain(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    domain = company_domain(value)
    if domain is None:
        raise ValidationFailedError(
            "not a company domain (free-mail and platform domains are refused)"
        )
    return domain


def _normalize_slug(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    parsed = parse_linkedin_url(value) if "/" in value else ("company", value.strip().lower())
    if parsed is None or parsed[0] != "company":
        raise ValidationFailedError("not a LinkedIn company page (linkedin.com/company/<name>)")
    return parsed[1]


class TrackedCompanyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    domain: str | None = Field(default=None, max_length=253)
    linkedin: str | None = Field(default=None, max_length=300)
    notes: str | None = Field(default=None, max_length=1000)


class TrackedCompanyPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["active", "paused"] | None = None
    notes: str | None = Field(default=None, max_length=1000)


@router.get("")
def list_tracked(
    principal: Principal = Depends(MANAGE), svc: AppServices = Depends(services)
) -> dict[str, Any]:
    with svc.db.scoped(principal) as conn:
        rows = queries.list_tracked_companies(conn)
    return {"items": [_view(r) for r in rows]}


@router.post("", status_code=201)
def add_tracked(
    body: TrackedCompanyCreate,
    request: Request,
    principal: Principal = Depends(MANAGE),
    svc: AppServices = Depends(services),
) -> dict[str, Any]:
    name = " ".join(body.name.split())
    domain = _normalize_domain(body.domain)
    slug = _normalize_slug(body.linkedin)
    try:
        with svc.db.scoped(principal) as conn:
            company_id = queries.add_tracked_company(
                conn,
                name=name,
                domain=domain,
                linkedin_slug=slug,
                notes=(body.notes or "").strip() or None,
                actor=principal.subject,
            )
            queries.append_audit(
                conn,
                audit_event(
                    request,
                    principal,
                    action="tracked_company.add",
                    resource_type="tracked_company",
                    resource_id=str(company_id),
                    details={"name": name, "domain": domain},
                ),
            )
            row = queries.get_tracked_company(conn, company_id)
    except psycopg.errors.UniqueViolation as exc:
        raise ConflictError(f"{domain or name} is already tracked") from exc
    assert row is not None
    return _view(row)


@router.patch("/{company_id}")
def update_tracked(
    company_id: UUID,
    patch: TrackedCompanyPatch,
    request: Request,
    principal: Principal = Depends(MANAGE),
    svc: AppServices = Depends(services),
) -> dict[str, Any]:
    changes = patch.model_dump(exclude_none=True)
    if "notes" in changes:
        changes["notes"] = changes["notes"].strip() or None
        if changes["notes"] is None:
            changes["clear_notes"] = True
    with svc.db.scoped(principal) as conn:
        if not queries.update_tracked_company(conn, company_id, **changes):
            raise NotFoundError("tracked company not found")
        queries.append_audit(
            conn,
            audit_event(
                request,
                principal,
                action="tracked_company.update",
                resource_type="tracked_company",
                resource_id=str(company_id),
                details=patch.model_dump(exclude_none=True),
            ),
        )
        row = queries.get_tracked_company(conn, company_id)
    assert row is not None
    return _view(row)


@router.delete("/{company_id}", status_code=204)
def remove_tracked(
    company_id: UUID,
    request: Request,
    principal: Principal = Depends(MANAGE),
    svc: AppServices = Depends(services),
) -> Response:
    """Stops tracking. Data already collected about the company stays in the graph."""
    with svc.db.scoped(principal) as conn:
        if not queries.delete_tracked_company(conn, company_id):
            raise NotFoundError("tracked company not found")
        queries.append_audit(
            conn,
            audit_event(
                request,
                principal,
                action="tracked_company.remove",
                resource_type="tracked_company",
                resource_id=str(company_id),
            ),
        )
    return Response(status_code=204)


@router.post("/{company_id}/research", status_code=202)
def research_now(
    company_id: UUID,
    request: Request,
    principal: Principal = Depends(
        require(Permission.CONNECTORS_CONFIGURE, Permission.CONNECTORS_RUN)
    ),
    svc: AppServices = Depends(services),
) -> dict[str, Any]:
    with svc.db.scoped(principal) as conn:
        row = queries.get_tracked_company(conn, company_id)
    if row is None:
        raise NotFoundError("tracked company not found")
    arns = start_research(
        svc.stepfunctions,
        svc.settings.enrichment_state_machine_arn,
        [row],
        credit_budget=svc.settings.tracked_research_credit_budget,
        name_prefix="tracked-manual",
    )
    with svc.db.scoped(principal) as conn:
        queries.mark_tracked_research(conn, [company_id], status="queued")
        queries.append_audit(
            conn,
            audit_event(
                request,
                principal,
                action="tracked_company.research",
                resource_type="tracked_company",
                resource_id=str(company_id),
            ),
        )
    return {"execution_arn": arns[0]}
