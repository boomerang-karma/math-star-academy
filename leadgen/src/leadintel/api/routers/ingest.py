"""Unauthenticated ingress: the first-party tracking beacon and the LinkedIn webhook.

Both are reachable without a user token, so each has its own control: the
beacon accepts only a strict schema from allow-listed origins (and the WAF
rate-limits it); the webhook only accepts requests signed with the LinkedIn
app's client secret. Both hand work to SQS and return immediately.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import ValidationError

from leadintel.api.deps import AppServices, services
from leadintel.connectors.first_party import TrackEvent
from leadintel.core.errors import ConfigurationError, ForbiddenError, ValidationFailedError
from leadintel.security.webhooks import linkedin_challenge_response, verify_linkedin_signature

router = APIRouter(tags=["ingest"])


def _cors_headers(origin: str | None, svc: AppServices) -> dict[str, str]:
    if origin and origin in svc.settings.beacon_allowed_origins:
        return {
            "Access-Control-Allow-Origin": origin,
            "Vary": "Origin",
            "Access-Control-Allow-Methods": "POST",
            "Access-Control-Allow-Headers": "content-type",
            "Access-Control-Max-Age": "600",
        }
    return {}


@router.options("/collect")
def collect_preflight(request: Request, svc: AppServices = Depends(services)) -> Response:
    headers = _cors_headers(request.headers.get("origin"), svc)
    return Response(status_code=204 if headers else 403, headers=headers)


@router.post("/collect", status_code=204)
async def collect(request: Request, svc: AppServices = Depends(services)) -> Response:
    origin = request.headers.get("origin")
    headers = _cors_headers(origin, svc)
    if origin is not None and not headers:
        raise ForbiddenError("origin not allowed")
    body = await request.body()  # sendBeacon posts text/plain to avoid a preflight
    try:
        event = TrackEvent.model_validate_json(body)
    except ValidationError as exc:
        raise ValidationFailedError("invalid tracking event") from exc
    if svc.sqs is None or not svc.settings.web_events_queue_url:
        raise ConfigurationError("tracking queue is not configured")
    svc.sqs.send_message(
        QueueUrl=svc.settings.web_events_queue_url, MessageBody=event.model_dump_json()
    )
    return Response(status_code=204, headers=headers)


def _linkedin_secret(svc: AppServices) -> str:
    if not svc.settings.linkedin_client_secret_arn:
        raise ConfigurationError("LinkedIn webhook is not configured")
    from leadintel.security.keyring import build_secrets_provider

    return build_secrets_provider(svc.settings).get(svc.settings.linkedin_client_secret_arn)


@router.get("/webhooks/linkedin")
def linkedin_challenge(
    challenge_code: str = Query(alias="challengeCode", min_length=1, max_length=256),
    svc: AppServices = Depends(services),
) -> dict[str, str]:
    return linkedin_challenge_response(challenge_code, _linkedin_secret(svc))


@router.post("/webhooks/linkedin")
async def linkedin_notification(
    request: Request, svc: AppServices = Depends(services)
) -> dict[str, Any]:
    raw = await request.body()
    verify_linkedin_signature(raw, request.headers.get("x-li-signature"), _linkedin_secret(svc))
    payload = json.loads(raw)
    response_urn = str(payload.get("leadGenFormResponse") or payload.get("leadFormResponse") or "")
    response_id = response_urn.rsplit(":", 1)[-1]
    if not response_id:
        raise ValidationFailedError("notification has no lead form response")
    if svc.sqs is None or not svc.settings.linkedin_queue_url:
        raise ConfigurationError("LinkedIn queue is not configured")
    svc.sqs.send_message(
        QueueUrl=svc.settings.linkedin_queue_url,
        MessageBody=json.dumps(
            {"response_id": response_id, "action": payload.get("leadAction", "CREATED")}
        ),
    )
    return {"accepted": True}
