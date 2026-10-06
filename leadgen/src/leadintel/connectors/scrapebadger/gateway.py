"""Anti-corruption layer around the official ScrapeBadger SDK.

* Retries and timeouts tuned to fit inside a Lambda invocation (the SDK defaults
  are 10 retries / 300 s, sized for long-running scripts).
* A semaphore caps concurrent calls per run so one playbook cannot exhaust the
  account's rate limit for everyone else.
* SDK exceptions become platform errors with an explicit ``retryable`` flag, which
  Step Functions uses to decide between back-off and failing the branch.
* Every call is charged to the run's :class:`CreditBudget`, using the credits the
  API reports when it reports them and a conservative estimate otherwise.

Key hygiene: ScrapeBadger keys can be restricted to API scopes and to source IPs.
Production restricts the key to the scopes the playbooks use and to the NAT
gateway Elastic IPs that ``infra`` exports (see docs/SECURITY.md).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, TypeVar

import httpx
import scrapebadger as sb

from leadintel.connectors.base import CreditBudget
from leadintel.core.errors import (
    BudgetExceededError,
    ConnectorError,
    RateLimitedError,
    SourceNotFoundError,
)

T = TypeVar("T")

# Conservative per-call estimates used for budget checks before a call. Real costs
# come from ScrapeBadger's public pricing API and the credits_used field when present.
DEFAULT_CREDIT_ESTIMATES: Mapping[str, int] = {
    "linkedin.company": 5,
    "linkedin.profile": 5,
    "linkedin.jobs_search": 5,
    "google.search": 2,
    "google.maps.search": 3,
    "google.news.search": 2,
    "web.scrape": 5,
}


class ScrapeBadgerGateway:
    def __init__(
        self,
        client: Any,
        *,
        max_concurrency: int = 4,
        credit_estimates: Mapping[str, int] = DEFAULT_CREDIT_ESTIMATES,
    ) -> None:
        self.client = client
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._estimates = dict(credit_estimates)

    @classmethod
    def from_api_key(
        cls,
        api_key: str,
        *,
        timeout_s: float = 60.0,
        max_retries: int = 3,
        max_concurrency: int = 4,
        base_url: str | None = None,
    ) -> ScrapeBadgerGateway:
        client = sb.ScrapeBadger(
            api_key=api_key, timeout=timeout_s, max_retries=max_retries, base_url=base_url
        )
        return cls(client, max_concurrency=max_concurrency)

    async def close(self) -> None:
        await self.client.close()

    async def call(
        self,
        operation: str,
        fn: Callable[[], Awaitable[T]],
        *,
        budget: CreditBudget,
    ) -> T:
        estimate = self._estimates.get(operation, 5)
        budget.ensure_available(estimate)
        async with self._semaphore:
            try:
                result = await fn()
            except sb.RateLimitError as exc:
                raise RateLimitedError(
                    f"ScrapeBadger rate limit on {operation}", retry_after_s=exc.retry_after
                ) from exc
            except sb.InsufficientCreditsError as exc:
                raise BudgetExceededError("ScrapeBadger account is out of credits") from exc
            except sb.IPNotAllowedError as exc:
                raise ConnectorError(
                    "ScrapeBadger key is IP-restricted and this egress IP is not allowed",
                    details={"operation": operation},
                ) from exc
            except (sb.AuthenticationError, sb.PermissionDeniedError) as exc:
                raise ConnectorError(
                    f"ScrapeBadger rejected the API key for {operation}",
                    details={"operation": operation},
                ) from exc
            except sb.NotFoundError as exc:
                raise SourceNotFoundError(f"{operation}: not found upstream") from exc
            except sb.ValidationError as exc:
                raise ConnectorError(f"{operation}: invalid request ({exc.message})") from exc
            except sb.ScrapeBadgerError as exc:
                # ServerError and anything unclassified: transient by assumption.
                raise ConnectorError(f"{operation}: upstream error", retryable=True) from exc
            except httpx.HTTPError as exc:
                # The SDK re-raises transport errors (timeouts, resets) once its retries run out.
                raise ConnectorError(f"{operation}: network error", retryable=True) from exc
        reported = getattr(result, "credits_used", None)
        if reported is None and isinstance(result, dict):
            reported = result.get("credits_used")
        budget.charge(int(reported) if isinstance(reported, int) and reported > 0 else estimate)
        return result
