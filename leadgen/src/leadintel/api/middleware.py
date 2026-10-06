"""HTTP hardening applied to every response, plus error rendering (RFC 7807)."""

from __future__ import annotations

import hmac
import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

from leadintel.api.deps import new_request_id
from leadintel.core.errors import LeadIntelError
from leadintel.core.logging import request_id_var

logger = logging.getLogger("leadintel.api")

SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Resource-Policy": "same-origin",
    # API responses carry personal data: never cache them anywhere.
    "Cache-Control": "no-store",
}


def problem(
    status: int, code: str, detail: str, *, details: dict[str, object] | None = None
) -> JSONResponse:
    body: dict[str, object] = {
        "type": f"https://leadintel.dev/problems/{code}",
        "title": code.replace("_", " "),
        "status": status,
        "detail": detail,
        "request_id": request_id_var.get(),
    }
    if details:
        body["details"] = details
    return JSONResponse(body, status_code=status, media_type="application/problem+json")


def install(app: FastAPI, *, origin_secret: Callable[[], str | None], max_body_bytes: int) -> None:
    @app.middleware("http")
    async def harden(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = new_request_id(request.headers.get("x-request-id"))
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            expected = origin_secret()
            if expected is not None:
                supplied = request.headers.get("x-origin-verify", "")
                if not hmac.compare_digest(supplied.encode(), expected.encode()):
                    response: Response = problem(
                        403, "forbidden", "requests must come through the CDN"
                    )
                    return _finish(response, request_id)
            length = request.headers.get("content-length")
            if length is not None and (not length.isdigit() or int(length) > max_body_bytes):
                return _finish(
                    problem(413, "payload_too_large", "request body too large"), request_id
                )
            try:
                response = await call_next(request)
            except Exception:
                logger.exception("unhandled error")
                response = problem(500, "internal_error", "an unexpected error occurred")
            return _finish(response, request_id)
        finally:
            logger.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
            request_id_var.reset(token)

    @app.exception_handler(LeadIntelError)
    async def domain_error(request: Request, exc: LeadIntelError) -> Response:
        if exc.status_code >= 500:
            logger.error("request failed: %s", exc.code)
        return problem(exc.status_code, exc.code, exc.message, details=exc.details or None)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> Response:
        fields = [{"loc": list(e.get("loc", [])), "msg": e.get("msg")} for e in exc.errors()]
        return problem(
            422, "validation_failed", "request validation failed", details={"errors": fields}
        )


def _finish(response: Response, request_id: str) -> Response:
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    response.headers["X-Request-Id"] = request_id
    return response
