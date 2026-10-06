"""Entities, lineage, the relationship graph, search and the entity-resolution review queue."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict

from leadintel.api import queries, views
from leadintel.api.deps import AppServices, audit_event, require, services
from leadintel.core.errors import ConflictError, NotFoundError
from leadintel.security.authz import Permission, Principal

router = APIRouter(prefix="/v1", tags=["graph"])


@router.get("/entities/{entity_id}")
def get_entity(
    entity_id: UUID,
    request: Request,
    principal: Principal = Depends(require(Permission.ENTITIES_READ)),
    svc: AppServices = Depends(services),
) -> dict[str, Any]:
    with svc.db.scoped(principal) as conn:
        row = queries.get_entity(conn, entity_id)
        if row is None:
            raise NotFoundError("entity not found")
        contact = (
            views.contact_view(row, principal, svc.cipher)
            if row["entity_type"] == "person"
            else None
        )
        lineage = queries.entity_lineage(conn, entity_id)
        signals = queries.entity_signals(conn, [entity_id])
        if contact and not contact["masked"]:
            queries.append_audit(
                conn,
                audit_event(
                    request,
                    principal,
                    action="pii.read",
                    resource_type="entity",
                    resource_id=str(entity_id),
                ),
            )
    return {
        **views.entity_view(row, contact=contact),
        "lineage": views.lineage_view(lineage),
        "signals": [views.signal_view(s) for s in signals],
    }


@router.get("/entities/{entity_id}/graph")
def entity_graph(
    entity_id: UUID,
    depth: int = Query(default=1, ge=1, le=2),
    principal: Principal = Depends(require(Permission.ENTITIES_READ)),
    svc: AppServices = Depends(services),
) -> dict[str, Any]:
    with svc.db.scoped(principal) as conn:
        if queries.get_entity(conn, entity_id) is None:
            raise NotFoundError("entity not found")
        return views.graph_view(queries.neighborhood(conn, [entity_id], depth=depth))


@router.get("/search")
def search(
    q: str = Query(min_length=2, max_length=100),
    limit: int = Query(default=20, ge=1, le=50),
    principal: Principal = Depends(require(Permission.ENTITIES_READ)),
    svc: AppServices = Depends(services),
) -> dict[str, Any]:
    with svc.db.scoped(principal) as conn:
        rows = queries.search_entities(conn, q, limit=limit)
    return {
        "items": [
            {
                "id": str(r["id"]),
                "type": r["entity_type"],
                "name": r["display_name"],
                "domain": r["primary_domain"],
            }
            for r in rows
        ]
    }


@router.get("/review")
def review_queue(
    limit: int = Query(default=50, ge=1, le=200),
    principal: Principal = Depends(require(Permission.ENTITIES_MERGE)),
    svc: AppServices = Depends(services),
) -> dict[str, Any]:
    with svc.db.scoped(principal) as conn:
        rows = queries.pending_reviews(conn, limit=limit)
    return {
        "items": [
            {
                "id": str(r["id"]),
                "probability": float(r["probability"]),
                "evidence": r["evidence"],
                "entity_type": r["entity_type"],
                "record_source": r["record_source"],
                "record_entity": {
                    "id": str(r["record_entity_id"]),
                    "name": r["record_entity_name"],
                },
                "candidate_entity": {
                    "id": str(r["candidate_entity_id"]),
                    "name": r["candidate_entity_name"],
                },
            }
            for r in rows
        ]
    }


class ReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["accept", "reject"]


@router.post("/review/{review_id}")
def decide_review(
    review_id: UUID,
    body: ReviewDecision,
    request: Request,
    principal: Principal = Depends(require(Permission.ENTITIES_MERGE)),
    svc: AppServices = Depends(services),
) -> dict[str, Any]:
    with svc.db.scoped(principal) as conn:
        review = queries.get_review(conn, review_id)
        if review is None:
            raise NotFoundError("review item not found")
        if review["status"] != "pending":
            raise ConflictError("review item already decided")
        if body.decision == "accept":
            try:
                queries.merge_entities(
                    conn,
                    review["record_entity_id"],
                    review["candidate_entity_id"],
                    principal.subject,
                )
            except psycopg.errors.RaiseException as exc:
                raise ConflictError(str(exc.diag.message_primary or "merge rejected")) from exc
        else:
            queries.reject_review(conn, review_id, principal.subject)
        queries.append_audit(
            conn,
            audit_event(
                request,
                principal,
                action=f"entity.review.{body.decision}",
                resource_type="match_candidate",
                resource_id=str(review_id),
                details={
                    "record_entity": str(review["record_entity_id"]),
                    "candidate_entity": str(review["candidate_entity_id"]),
                },
            ),
        )
    return {"id": str(review_id), "decision": body.decision}
