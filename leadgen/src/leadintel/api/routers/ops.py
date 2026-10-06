"""Health, identity, audit trail and connector runs."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from leadintel.api import queries
from leadintel.api.deps import AppServices, audit_event, current_principal, require, services
from leadintel.connectors import registry
from leadintel.core.errors import ConfigurationError, ValidationFailedError
from leadintel.security.authz import Permission, Principal

router = APIRouter(tags=["ops"])


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
def readyz(response: Response, svc: AppServices = Depends(services)) -> dict[str, str]:
    if svc.db.ping():
        return {"status": "ok"}
    response.status_code = 503
    return {"status": "degraded"}


@router.get("/v1/me")
def me(principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    return {
        "subject": principal.subject,
        "roles": sorted(r.value for r in principal.roles),
        "permissions": sorted(p.value for p in principal.permissions),
        "territories": sorted(principal.territories),
        "row_scope": principal.row_scope,
    }


@router.get("/v1/audit")
def audit_log(
    resource_type: str | None = None,
    resource_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    principal: Principal = Depends(require(Permission.AUDIT_READ)),
    svc: AppServices = Depends(services),
) -> dict[str, Any]:
    with svc.db.scoped(principal) as conn:
        rows = queries.list_audit(
            conn, resource_type=resource_type, resource_id=resource_id, limit=limit
        )
    return {"items": [{**r, "occurred_at": r["occurred_at"].isoformat()} for r in rows]}


@router.get("/v1/audit/verify")
def verify_audit(
    principal: Principal = Depends(require(Permission.AUDIT_READ)),
    svc: AppServices = Depends(services),
) -> dict[str, Any]:
    with svc.db.scoped(principal) as conn:
        row = conn.execute("SELECT audit.verify_chain() AS broken_at").fetchone()
    broken_at = row["broken_at"] if row else None
    return {"intact": broken_at is None, "broken_at": broken_at}


class ConnectorRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    playbook: str = Field(max_length=64)
    params: dict[str, Any] = Field(default_factory=dict)
    credit_budget: int | None = Field(default=None, ge=1, le=50_000)


@router.post("/v1/connectors/{name}/runs", status_code=202)
def start_connector_run(
    name: str,
    body: ConnectorRunRequest,
    request: Request,
    principal: Principal = Depends(require(Permission.CONNECTORS_RUN)),
    svc: AppServices = Depends(services),
) -> dict[str, Any]:
    if name not in registry.names():
        raise ValidationFailedError(f"unknown connector {name!r}")
    if len(json.dumps(body.params)) > 4_000:
        raise ValidationFailedError("params too large")
    if svc.stepfunctions is None or not svc.settings.enrichment_state_machine_arn:
        raise ConfigurationError(
            "connector runs are orchestrated by Step Functions; not configured here"
        )
    execution = svc.stepfunctions.start_execution(
        stateMachineArn=svc.settings.enrichment_state_machine_arn,
        name=f"api-{name}-{uuid4().hex[:12]}",
        input=json.dumps(
            {
                "tasks": [
                    {
                        "connector": name,
                        "playbook": body.playbook,
                        "params": body.params,
                        "credit_budget": body.credit_budget,
                    }
                ]
            }
        ),
    )
    with svc.db.scoped(principal) as conn:
        queries.append_audit(
            conn,
            audit_event(
                request,
                principal,
                action="connector.run",
                resource_type="connector",
                resource_id=name,
                details={"playbook": body.playbook},
            ),
        )
    return {"execution_arn": execution["executionArn"]}
