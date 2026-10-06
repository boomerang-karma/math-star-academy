"""Application factory.

All routes live under ``/api`` so CloudFront can serve the SPA and the API from
one origin (no CORS for the app itself); the tracking beacon is the only
cross-origin route.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, FastAPI

from leadintel import __version__
from leadintel.api import middleware
from leadintel.api.deps import AppServices, Database
from leadintel.api.routers import graph, ingest, leads, ops, privacy, tracked
from leadintel.core.config import AuthMode, Settings, get_settings
from leadintel.core.logging import configure_logging
from leadintel.security.jwt_verifier import CognitoJwtVerifier
from leadintel.security.keyring import build_blind_indexer, build_field_cipher
from leadintel.storage.db import dsn_from_settings


def _origin_secret_provider(settings: Settings) -> Callable[[], str | None]:
    if not settings.origin_verify_secret_arn:
        return lambda: None
    from leadintel.security.keyring import build_secrets_provider

    provider = build_secrets_provider(settings)  # cached for 5 minutes: rotation-friendly
    arn = settings.origin_verify_secret_arn
    return lambda: provider.get(arn)


def build_services(settings: Settings) -> AppServices:
    verifier = None
    if (
        settings.auth_mode is AuthMode.COGNITO
        and settings.cognito_user_pool_id
        and settings.cognito_app_client_id
    ):
        verifier = CognitoJwtVerifier(
            region=settings.aws_region,
            user_pool_id=settings.cognito_user_pool_id,
            app_client_id=settings.cognito_app_client_id,
        )
    sqs: Any = None
    stepfunctions: Any = None
    if not settings.is_local:
        import boto3

        sqs = boto3.client("sqs", region_name=settings.aws_region)
        stepfunctions = boto3.client("stepfunctions", region_name=settings.aws_region)
    brief_generator = None
    if settings.ai_enabled:
        from leadintel.ai.brief import build_bedrock_generator

        brief_generator = build_bedrock_generator(settings)
    return AppServices(
        settings=settings,
        db=Database(lambda: dsn_from_settings(settings)),
        cipher=build_field_cipher(settings),
        bidx=build_blind_indexer(settings),
        verifier=verifier,
        brief_generator=brief_generator,
        sqs=sqs,
        stepfunctions=stepfunctions,
    )


def create_app(settings: Settings | None = None, *, services: AppServices | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="LeadIntel API",
        version=__version__,
        docs_url="/api/docs" if settings.is_local else None,  # no public schema outside local
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.is_local else None,
    )
    app.state.services = services or build_services(settings)
    app.state.started_at = time.time()
    middleware.install(
        app,
        origin_secret=_origin_secret_provider(settings),
        max_body_bytes=settings.max_request_body_bytes,
    )
    api = APIRouter(prefix="/api")
    for module in (ops, leads, graph, privacy, ingest, tracked):
        api.include_router(module.router)
    app.include_router(api)
    return app
