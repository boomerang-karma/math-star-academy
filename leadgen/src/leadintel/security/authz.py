"""Authorization: role-based permissions plus territory-based row scoping.

Two layers enforce access:

1. **Permissions** (this module) gate *actions*: can this principal read leads,
   see unmasked PII, run connectors, process a DSAR?
2. **Row-level security** in PostgreSQL gates *rows*: a sales rep only ever
   receives leads in their territories or assigned to them. The API sets the
   principal's scope per transaction (``app.scope``, ``app.territories``) and the
   policies in ``database/migrations/V0007__row_level_security.sql`` do the rest,
   so a bug in a query cannot leak another territory's leads.

Roles come from Cognito groups (``leadintel-<role>``).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from leadintel.core.errors import ForbiddenError


class Role(StrEnum):
    ADMIN = "admin"
    ANALYST = "analyst"
    SALES_REP = "sales_rep"
    COMPLIANCE_OFFICER = "compliance_officer"
    VIEWER = "viewer"
    SERVICE = "service"


class Permission(StrEnum):
    LEADS_READ = "leads:read"
    LEADS_WRITE = "leads:write"
    LEADS_ASSIGN = "leads:assign"
    ENTITIES_READ = "entities:read"
    ENTITIES_MERGE = "entities:merge"
    PII_READ = "pii:read"
    CONNECTORS_RUN = "connectors:run"
    CONNECTORS_CONFIGURE = "connectors:configure"
    COMPLIANCE_DSAR = "compliance:dsar"
    COMPLIANCE_SUPPRESS = "compliance:suppress"
    AUDIT_READ = "audit:read"
    USERS_ADMIN = "users:admin"
    AI_BRIEF = "ai:brief"


ROLE_PERMISSIONS: Mapping[Role, frozenset[Permission]] = {
    Role.ADMIN: frozenset(Permission),
    # Analysts work the data (resolution, enrichment) but see contact details masked.
    Role.ANALYST: frozenset(
        {
            Permission.LEADS_READ,
            Permission.LEADS_WRITE,
            Permission.ENTITIES_READ,
            Permission.ENTITIES_MERGE,
            Permission.CONNECTORS_RUN,
            Permission.AI_BRIEF,
        }
    ),
    # Reps need contact details for outreach, but only within their territory (RLS).
    Role.SALES_REP: frozenset(
        {
            Permission.LEADS_READ,
            Permission.LEADS_WRITE,
            Permission.ENTITIES_READ,
            Permission.PII_READ,
            Permission.AI_BRIEF,
        }
    ),
    Role.COMPLIANCE_OFFICER: frozenset(
        {
            Permission.LEADS_READ,
            Permission.ENTITIES_READ,
            Permission.PII_READ,
            Permission.COMPLIANCE_DSAR,
            Permission.COMPLIANCE_SUPPRESS,
            Permission.AUDIT_READ,
        }
    ),
    Role.VIEWER: frozenset({Permission.LEADS_READ, Permission.ENTITIES_READ}),
    Role.SERVICE: frozenset(
        {
            Permission.LEADS_READ,
            Permission.LEADS_WRITE,
            Permission.ENTITIES_READ,
            Permission.ENTITIES_MERGE,
            Permission.CONNECTORS_RUN,
        }
    ),
}

# Roles whose row scope is global. Everyone else is limited to territories/ownership.
_GLOBAL_SCOPE_ROLES = frozenset({Role.ADMIN, Role.ANALYST, Role.COMPLIANCE_OFFICER, Role.SERVICE})

COGNITO_GROUP_PREFIX = "leadintel-"


@dataclass(frozen=True)
class Principal:
    subject: str
    roles: frozenset[Role]
    tenant_id: str
    territories: frozenset[str] = field(default_factory=frozenset)
    display_name: str | None = None

    @property
    def permissions(self) -> frozenset[Permission]:
        granted: set[Permission] = set()
        for role in self.roles:
            granted |= ROLE_PERMISSIONS[role]
        return frozenset(granted)

    def has(self, permission: Permission) -> bool:
        return permission in self.permissions

    @property
    def row_scope(self) -> str:
        """``global`` or ``territory``; mirrored into ``app.scope`` for RLS."""
        return "global" if self.roles & _GLOBAL_SCOPE_ROLES else "territory"


def require(principal: Principal, *permissions: Permission) -> None:
    missing = [p for p in permissions if not principal.has(p)]
    if missing:
        raise ForbiddenError("missing permission", details={"missing": [p.value for p in missing]})


def roles_from_groups(groups: Iterable[str]) -> frozenset[Role]:
    roles: set[Role] = set()
    for group in groups:
        if not group.startswith(COGNITO_GROUP_PREFIX):
            continue
        try:
            roles.add(Role(group.removeprefix(COGNITO_GROUP_PREFIX)))
        except ValueError:
            continue
    return frozenset(roles)


def principal_from_claims(
    claims: Mapping[str, Any], *, tenant_id: str, territories: Iterable[str] = ()
) -> Principal:
    """Build a principal from verified Cognito access-token claims.

    Territories are not trusted from the token; they come from ``sales.app_user``.
    A token with no recognised group gets no roles and therefore no permissions.
    """
    groups = claims.get("cognito:groups") or []
    return Principal(
        subject=str(claims["sub"]),
        roles=roles_from_groups(groups),
        tenant_id=tenant_id,
        territories=frozenset(territories),
        display_name=claims.get("username"),
    )


def mask_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return email
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


def mask_phone(phone: str | None) -> str | None:
    if not phone:
        return phone
    digits = [c for c in phone if c.isdigit()]
    if len(digits) <= 4:
        return "***"
    prefix = "+" if phone.startswith("+") else ""
    return f"{prefix}{'*' * (len(digits) - 4)}{''.join(digits[-4:])}"
