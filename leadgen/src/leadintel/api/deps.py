"""Request-scoped dependencies: database sessions, authentication, authorization, audit."""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import psycopg
from fastapi import Depends, Request

from leadintel.api import queries
from leadintel.core.config import AuthMode, Settings
from leadintel.core.errors import AuthenticationError, ForbiddenError
from leadintel.core.logging import request_id_var
from leadintel.security.audit import ActorType, AuditEvent, Outcome
from leadintel.security.authz import Permission, Principal, Role, principal_from_claims
from leadintel.security.blind_index import BlindIndexer
from leadintel.security.crypto import FieldCipher
from leadintel.security.jwt_verifier import CognitoJwtVerifier
from leadintel.storage.db import STALE_AFTER_S, Connection, connect, is_usable, principal_scope


class Database:
    """One connection per worker thread (Lambda: per container), replaced when it goes stale."""

    def __init__(
        self, dsn_factory: Callable[[], str], *, stale_after_s: float = STALE_AFTER_S
    ) -> None:
        self._dsn_factory = dsn_factory
        self._stale_after_s = stale_after_s
        self._local = threading.local()

    def _connection(self) -> Connection:
        conn: Connection | None = getattr(self._local, "conn", None)
        now = time.monotonic()
        idle_for = now - getattr(self._local, "used_at", now)
        if conn is None or not is_usable(
            conn, idle_for_s=idle_for, stale_after_s=self._stale_after_s
        ):
            conn = connect(self._dsn_factory(), application_name="leadintel-api")
            self._local.conn = conn
        self._local.used_at = now
        return conn

    @contextmanager
    def scoped(self, principal: Principal) -> Iterator[Connection]:
        conn = self._connection()
        try:
            with principal_scope(conn, principal):
                yield conn
        except psycopg.OperationalError:
            self._local.conn = None
            raise

    @contextmanager
    def unscoped(self) -> Iterator[Connection]:
        conn = self._connection()
        try:
            with conn.transaction():
                yield conn
        except psycopg.OperationalError:
            self._local.conn = None
            raise

    def ping(self) -> bool:
        """Readiness: never raises, so the probe reports "degraded" instead of erroring."""
        try:
            with self.unscoped() as conn:
                return conn.execute("SELECT 1 AS ok").fetchone() == {"ok": 1}
        except psycopg.Error:
            return False


@dataclass
class AppServices:
    settings: Settings
    db: Database
    cipher: FieldCipher
    bidx: BlindIndexer
    verifier: CognitoJwtVerifier | None = None
    brief_generator: Any = None
    sqs: Any = None
    stepfunctions: Any = None


def services(request: Request) -> AppServices:
    svc: AppServices = request.app.state.services
    return svc


_TERRITORY_CACHE: dict[str, tuple[frozenset[str], float]] = {}
_TERRITORY_TTL_S = 60.0


def _territories(svc: AppServices, subject: str) -> frozenset[str]:
    hit = _TERRITORY_CACHE.get(subject)
    if hit and time.monotonic() - hit[1] < _TERRITORY_TTL_S:
        return hit[0]
    with svc.db.unscoped() as conn:
        territories = frozenset(queries.user_territories(conn, subject))
    _TERRITORY_CACHE[subject] = (territories, time.monotonic())
    return territories


def _dev_principal(request: Request, svc: AppServices) -> Principal:
    subject = request.headers.get("x-dev-user") or "00000000-0000-0000-0000-00000000dev1"
    roles = frozenset(
        Role(r.strip())
        for r in (request.headers.get("x-dev-roles") or "admin").split(",")
        if r.strip()
    )
    territories = frozenset(
        t.strip() for t in (request.headers.get("x-dev-territories") or "").split(",") if t.strip()
    )
    return Principal(
        subject=subject,
        roles=roles,
        tenant_id=svc.settings.tenant_id,
        territories=territories,
        display_name="local developer",
    )


def current_principal(request: Request, svc: AppServices = Depends(services)) -> Principal:
    if svc.settings.auth_mode is AuthMode.LOCAL_DEV:
        principal = _dev_principal(request, svc)
    else:
        header = request.headers.get("authorization") or ""
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise AuthenticationError("missing bearer token")
        if svc.verifier is None:
            raise AuthenticationError("authentication is not configured")
        claims = svc.verifier.verify(token)
        principal = principal_from_claims(
            claims,
            tenant_id=svc.settings.tenant_id,
            territories=_territories(svc, str(claims["sub"])),
        )
    request.state.principal = principal
    return principal


def client_ip(request: Request) -> str | None:
    # CloudFront -> API Gateway: the viewer address is the first X-Forwarded-For hop.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        candidate = forwarded.split(",")[0].strip()
    else:
        candidate = request.client.host if request.client else ""
    try:
        import ipaddress

        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def audit_event(
    request: Request,
    principal: Principal,
    *,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    outcome: Outcome = Outcome.SUCCESS,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    return AuditEvent(
        actor_id=principal.subject,
        actor_type=ActorType.SERVICE if Role.SERVICE in principal.roles else ActorType.USER,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=outcome,
        request_id=request_id_var.get(),
        ip=client_ip(request),
        details=details or {},
    )


def require(*permissions: Permission) -> Callable[..., Principal]:
    """Dependency factory: authorize, and audit every denial."""

    def dependency(
        request: Request,
        principal: Principal = Depends(current_principal),
        svc: AppServices = Depends(services),
    ) -> Principal:
        missing = [p for p in permissions if not principal.has(p)]
        if missing:
            event = audit_event(
                request,
                principal,
                action="authz.denied",
                resource_type="endpoint",
                resource_id=f"{request.method} {request.url.path}",
                outcome=Outcome.DENIED,
                details={"missing": [p.value for p in missing]},
            )
            try:
                with svc.db.scoped(principal) as conn:
                    queries.append_audit(conn, event)
            except psycopg.Error:
                pass  # never turn a 403 into a 500 because auditing failed
            raise ForbiddenError(
                "missing permission", details={"missing": [p.value for p in missing]}
            )
        return principal

    return dependency


def new_request_id(header_value: str | None) -> str:
    if header_value:
        try:
            return str(uuid.UUID(header_value))
        except ValueError:
            pass
    return str(uuid.uuid4())
