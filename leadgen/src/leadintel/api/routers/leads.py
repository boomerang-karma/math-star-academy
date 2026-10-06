"""Leads: the ranked worklist and the 360-degree lead view."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict

from leadintel.ai.brief import BriefInput
from leadintel.api import queries, views
from leadintel.api.deps import AppServices, audit_event, require, services
from leadintel.core.errors import ForbiddenError, NotFoundError, ValidationFailedError
from leadintel.security.authz import Permission, Principal

router = APIRouter(prefix="/v1/leads", tags=["leads"])

LeadStatus = Literal["new", "working", "nurture", "qualified", "disqualified", "converted"]


def _parse_cursor(cursor: str | None) -> tuple[float, UUID] | None:
    if not cursor:
        return None
    try:
        score, _, lead_id = cursor.partition(":")
        return float(score), UUID(lead_id)
    except ValueError as exc:
        raise ValidationFailedError("invalid cursor") from exc


@router.get("")
def list_leads(
    tier: Literal["A", "B", "C", "D"] | None = None,
    status: LeadStatus | None = None,
    hot: bool | None = None,
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    principal: Principal = Depends(require(Permission.LEADS_READ)),
    svc: AppServices = Depends(services),
) -> dict[str, Any]:
    with svc.db.scoped(principal) as conn:
        rows = queries.list_leads(
            conn,
            tier=tier,
            status=status,
            hot=hot,
            query=q,
            limit=limit,
            cursor=_parse_cursor(cursor),
        )
    items = [views.lead_summary(row) for row in rows]
    next_cursor = None
    if len(rows) == limit:
        last = rows[-1]
        next_cursor = f"{float(last['score']) if last['score'] is not None else -1}:{last['id']}"
    return {"items": items, "next_cursor": next_cursor}


@router.get("/{lead_id}")
def lead_360(
    lead_id: UUID,
    request: Request,
    principal: Principal = Depends(require(Permission.LEADS_READ, Permission.ENTITIES_READ)),
    svc: AppServices = Depends(services),
) -> dict[str, Any]:
    with svc.db.scoped(principal) as conn:
        lead = queries.get_lead(conn, lead_id)
        if lead is None:
            raise NotFoundError("lead not found")  # also what RLS-hidden leads look like
        org_row = (
            queries.get_entity(conn, lead["organization_entity_id"])
            if lead["organization_entity_id"]
            else None
        )
        person_row = (
            queries.get_entity(conn, lead["person_entity_id"]) if lead["person_entity_id"] else None
        )
        contact = views.contact_view(person_row, principal, svc.cipher) if person_row else None
        entity_ids = [e["id"] for e in (org_row, person_row) if e]
        signals = queries.entity_signals(conn, entity_ids)
        graph = queries.neighborhood(conn, entity_ids, depth=1)
        consent = (
            queries.consent_status(conn, person_row["email_bidx"])
            if person_row and person_row["email_bidx"]
            else []
        )
        suppressed = bool(
            person_row
            and person_row["email_bidx"]
            and queries.is_suppressed(conn, "email", person_row["email_bidx"])
        )
        brief = queries.cached_brief(conn, lead_id)
        history = queries.score_history(conn, lead_id)
        if contact and not contact["masked"]:
            queries.append_audit(
                conn,
                audit_event(
                    request,
                    principal,
                    action="pii.read",
                    resource_type="lead",
                    resource_id=str(lead_id),
                ),
            )
    return {
        "lead": {
            "id": str(lead["id"]),
            "status": lead["status"],
            "tier": lead["tier"],
            "score": float(lead["score"]) if lead["score"] is not None else None,
            "components": {
                "fit": float(lead["fit_score"] or 0),
                "intent": float(lead["intent_score"] or 0),
                "engagement": float(lead["engagement_score"] or 0),
            },
            "hot": lead["hot"],
            "explanation": lead["score_explanation"],
            "scored_at": lead["scored_at"].isoformat() if lead["scored_at"] else None,
            "territory": lead["territory"],
            "owner": {"id": str(lead["owner_user_id"]), "name": lead["owner_name"]}
            if lead["owner_user_id"]
            else None,
            "history": [
                {"at": h["scored_at"].isoformat(), "score": float(h["score"]), "tier": h["tier"]}
                for h in history
            ],
        },
        "organization": views.entity_view(org_row) if org_row else None,
        "person": views.entity_view(person_row, contact=contact) if person_row else None,
        "signals": [views.signal_view(s) for s in signals],
        "graph": views.graph_view(graph),
        "consent": [
            {
                "purpose": c["purpose"],
                "status": c["status"],
                "source": c["source"],
                "captured_at": c["captured_at"].isoformat(),
            }
            for c in consent
        ],
        "suppressed": suppressed,
        "brief": {
            "model": brief["model_id"],
            "generated_at": brief["generated_at"].isoformat(),
            **brief["brief"],
        }
        if brief
        else None,
    }


class LeadPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: LeadStatus | None = None
    owner_user_id: UUID | None = None
    clear_owner: bool = False


@router.patch("/{lead_id}")
def update_lead(
    lead_id: UUID,
    patch: LeadPatch,
    request: Request,
    principal: Principal = Depends(require(Permission.LEADS_WRITE)),
    svc: AppServices = Depends(services),
) -> dict[str, Any]:
    set_owner = patch.owner_user_id is not None or patch.clear_owner
    if set_owner and not principal.has(Permission.LEADS_ASSIGN):
        raise ForbiddenError("reassigning leads requires leads:assign")
    with svc.db.scoped(principal) as conn:
        if not queries.update_lead(
            conn,
            lead_id,
            status=patch.status,
            owner_user_id=patch.owner_user_id,
            set_owner=set_owner,
        ):
            raise NotFoundError("lead not found")
        queries.append_audit(
            conn,
            audit_event(
                request,
                principal,
                action="lead.update",
                resource_type="lead",
                resource_id=str(lead_id),
                details=patch.model_dump(mode="json", exclude_defaults=True),
            ),
        )
    return {"id": str(lead_id), "updated": True}


@router.post("/{lead_id}/brief")
def generate_brief(
    lead_id: UUID,
    request: Request,
    principal: Principal = Depends(require(Permission.LEADS_READ, Permission.AI_BRIEF)),
    svc: AppServices = Depends(services),
) -> dict[str, Any]:
    if svc.brief_generator is None:
        from leadintel.ai.brief import BriefUnavailableError

        raise BriefUnavailableError("AI briefs are disabled in this environment")
    with svc.db.scoped(principal) as conn:
        lead = queries.get_lead(conn, lead_id)
        if lead is None:
            raise NotFoundError("lead not found")
        org = (
            queries.get_entity(conn, lead["organization_entity_id"])
            if lead["organization_entity_id"]
            else None
        )
        person = (
            queries.get_entity(conn, lead["person_entity_id"]) if lead["person_entity_id"] else None
        )
        signals = queries.entity_signals(conn, [e["id"] for e in (org, person) if e], limit=40)
        cached = queries.cached_brief(conn, lead_id)
    values = {k: v.get("value") for k, v in ((org or {}).get("golden") or {}).items()}
    brief_input = BriefInput(
        company={
            k: values.get(k)
            for k in (
                "name",
                "domain",
                "industry",
                "description",
                "employee_count",
                "hq_city",
                "hq_country",
                "technologies",
                "specialties",
            )
            if values.get(k)
        },
        person={k: v.get("value") for k, v in ((person or {}).get("golden") or {}).items()}
        if person
        else None,
        signals=[
            {
                "id": str(s["id"]),
                "type": s["signal_type"],
                "title": s["title"],
                "date": s["occurred_at"].date().isoformat(),
                "source": s["source"],
            }
            for s in signals
        ],
        score={
            "tier": lead["tier"],
            "total": float(lead["score"] or 0),
            "top_factors": [c["detail"] for c in (lead["score_explanation"] or [])[:5]],
        },
        icp_name="configured ICP",
    )
    fingerprint = brief_input.fingerprint()
    if cached and cached["input_hash"] == fingerprint:
        return {"cached": True, "model": cached["model_id"], **cached["brief"]}
    brief = svc.brief_generator.generate(brief_input).model_dump()
    with svc.db.scoped(principal) as conn:
        queries.store_brief(
            conn,
            lead_id,
            model_id=svc.brief_generator.model_id,
            input_hash=fingerprint,
            brief=brief,
            actor=principal.subject,
        )
        queries.append_audit(
            conn,
            audit_event(
                request,
                principal,
                action="ai.brief",
                resource_type="lead",
                resource_id=str(lead_id),
                details={"signals": len(signals)},
            ),
        )
    return {"cached": False, "model": svc.brief_generator.model_id, **brief}
