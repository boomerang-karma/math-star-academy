"""Connector contract, run context and credit budgeting."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from leadintel.core.errors import BudgetExceededError, ValidationFailedError
from leadintel.ontology.models import FetchBatch
from leadintel.pipeline.icp import DEFAULT_ICP, IcpProfile


class CreditBudget:
    """Per-run spending cap for paid sources.

    ``ensure_available`` runs *before* a call with the estimated cost, ``charge``
    after it with the actual cost. The upstream account balance is the second,
    hard limit (a 402 from the vendor surfaces as BudgetExceededError too).
    """

    def __init__(self, limit: int) -> None:
        if limit < 0:
            raise ValueError("budget limit must be >= 0")
        self.limit = limit
        self.used = 0
        self._lock = threading.Lock()

    @property
    def remaining(self) -> int:
        return max(self.limit - self.used, 0)

    def ensure_available(self, estimate: int) -> None:
        if self.used + estimate > self.limit:
            raise BudgetExceededError(
                "run credit budget exhausted",
                details={"limit": self.limit, "used": self.used, "next_call_estimate": estimate},
            )

    def charge(self, credits: int) -> None:
        with self._lock:
            self.used += max(credits, 0)


@dataclass
class RunContext:
    budget: CreditBudget
    run_id: UUID = field(default_factory=uuid4)
    icp: IcpProfile = DEFAULT_ICP
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))

    def now(self) -> datetime:
        return self.clock()


class Connector(Protocol):
    name: str

    def playbooks(self) -> frozenset[str]: ...

    async def run(
        self, playbook: str, params: Mapping[str, Any], ctx: RunContext
    ) -> FetchBatch: ...


def require_param(params: Mapping[str, Any], name: str) -> Any:
    value = params.get(name)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValidationFailedError(f"missing required parameter {name!r}")
    return value
