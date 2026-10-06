"""Domain error hierarchy.

Every error carries an HTTP status and a stable machine-readable ``code`` so the
API layer can render RFC 7807 problem documents without leaking internals, and
pipeline code can decide whether a failure is worth retrying.
"""

from __future__ import annotations

from typing import Any


class LeadIntelError(Exception):
    status_code: int = 500
    code: str = "internal_error"
    retryable: bool = False

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class AuthenticationError(LeadIntelError):
    status_code = 401
    code = "unauthenticated"


class ForbiddenError(LeadIntelError):
    status_code = 403
    code = "forbidden"


class NotFoundError(LeadIntelError):
    status_code = 404
    code = "not_found"


class ConflictError(LeadIntelError):
    status_code = 409
    code = "conflict"


class ValidationFailedError(LeadIntelError):
    status_code = 422
    code = "validation_failed"


class ComplianceBlockedError(LeadIntelError):
    """The action is blocked by a privacy rule (suppression, disabled source, missing basis)."""

    status_code = 451
    code = "compliance_blocked"


class ConfigurationError(LeadIntelError):
    status_code = 500
    code = "configuration_error"


class ConnectorError(LeadIntelError):
    """A data source failed. ``retryable`` tells the orchestrator whether to back off and retry."""

    status_code = 502
    code = "connector_error"

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.retryable = retryable


class SourceNotFoundError(ConnectorError):
    """The upstream entity does not exist (deleted profile, wrong slug). Never retried."""

    code = "source_not_found"


class RateLimitedError(ConnectorError):
    code = "rate_limited"

    def __init__(self, message: str, *, retry_after_s: int | None = None) -> None:
        super().__init__(message, retryable=True, details={"retry_after_s": retry_after_s})
        self.retry_after_s = retry_after_s


class BudgetExceededError(ConnectorError):
    """A run (or the upstream account) has no credits left. Stops the run; never retried."""

    code = "budget_exceeded"
