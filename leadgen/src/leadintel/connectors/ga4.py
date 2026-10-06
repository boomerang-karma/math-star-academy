"""Google Analytics 4: per-visitor web engagement via the GA4 Data API.

GA4 reports are aggregated, so the website tags every event with our own
pseudonymous first-party visitor id (a random UUID cookie, never an email or
other PII, which Google's policies forbid) registered as a user-scoped custom
dimension ``lead_visitor_id``. Grouping a report by that dimension yields
per-visitor activity; when the visitor later submits a form, the identity graph
links the visitor id to a person, and every earlier visit lands on their
timeline.

Authentication uses a Google service account (JSON key in Secrets Manager).
Workload Identity Federation from AWS is the key-less hardening step; see
docs/SECURITY.md.
"""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import UTC, date, datetime
from typing import Any

import httpx
import jwt

from leadintel.core.errors import AuthenticationError, ConnectorError, RateLimitedError
from leadintel.ontology.models import EntityHint, EntityType, Signal, SignalType, Source
from leadintel.pipeline.icp import IcpProfile

DATA_API = "https://analyticsdata.googleapis.com/v1beta"
SCOPE = "https://www.googleapis.com/auth/analytics.readonly"


class GoogleServiceAccountTokenProvider:
    """OAuth 2.0 JWT-bearer grant for a service account, cached until shortly before expiry."""

    def __init__(
        self, http: httpx.AsyncClient, service_account: dict[str, Any], *, scope: str = SCOPE
    ) -> None:
        self._http = http
        self._sa = service_account
        self._scope = scope
        self._token: str | None = None
        self._expires_at = 0.0

    async def __call__(self) -> str:
        now = time.time()
        if self._token and now < self._expires_at - 60:
            return self._token
        token_uri = self._sa.get("token_uri", "https://oauth2.googleapis.com/token")
        assertion = jwt.encode(
            {
                "iss": self._sa["client_email"],
                "scope": self._scope,
                "aud": token_uri,
                "iat": int(now),
                "exp": int(now) + 3600,
            },
            self._sa["private_key"],
            algorithm="RS256",
            headers={"kid": self._sa.get("private_key_id")},
        )
        response = await self._http.post(
            token_uri,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
            timeout=10,
        )
        if response.status_code != 200:
            raise AuthenticationError("Google token exchange failed")
        body = response.json()
        self._token = str(body["access_token"])
        self._expires_at = now + float(body.get("expires_in", 3600))
        return self._token


class Ga4Client:
    def __init__(self, http: httpx.AsyncClient, *, property_id: str, token: Any) -> None:
        self._http = http
        self._property = property_id
        self._token = token

    async def run_report(self, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{DATA_API}/properties/{self._property}:runReport"
        try:
            response = await self._http.post(
                url,
                json=body,
                headers={"Authorization": f"Bearer {await self._token()}"},
                timeout=30,
            )
        except httpx.HTTPError as exc:
            raise ConnectorError("GA4 Data API unreachable", retryable=True) from exc
        if response.status_code == 429:
            raise RateLimitedError("GA4 quota exhausted")
        if response.status_code >= 500:
            raise ConnectorError(f"GA4 Data API {response.status_code}", retryable=True)
        if response.status_code >= 400:
            raise ConnectorError(f"GA4 Data API rejected the report ({response.status_code})")
        report: dict[str, Any] = response.json()
        return report


def visitor_activity_request(
    *, start: date, end: date, visitor_dimension: str, limit: int = 10_000, offset: int = 0
) -> dict[str, Any]:
    return {
        "dateRanges": [{"startDate": start.isoformat(), "endDate": end.isoformat()}],
        "dimensions": [
            {"name": visitor_dimension},
            {"name": "date"},
            {"name": "pagePath"},
            {"name": "sessionSourceMedium"},
        ],
        "metrics": [{"name": "screenPageViews"}, {"name": "userEngagementDuration"}],
        "dimensionFilter": {
            "notExpression": {
                "filter": {"fieldName": visitor_dimension, "stringFilter": {"value": "(not set)"}}
            }
        },
        "limit": limit,
        "offset": offset,
    }


def map_visitor_activity(report: dict[str, Any], *, icp: IcpProfile) -> list[Signal]:
    """One WEB_VISIT signal per visitor-day, plus HIGH_INTENT_PAGE per pricing/demo page."""
    dims = [h["name"] for h in report.get("dimensionHeaders", [])]
    mets = [h["name"] for h in report.get("metricHeaders", [])]
    days: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"views": 0, "engagement_s": 0.0, "pages": defaultdict(int), "channels": set()}
    )
    for row in report.get("rows", []):
        d = dict(zip(dims, (v.get("value") for v in row.get("dimensionValues", [])), strict=False))
        m = dict(zip(mets, (v.get("value") for v in row.get("metricValues", [])), strict=False))
        visitor, day = d.get(dims[0]) if dims else None, d.get("date")
        if not visitor or not day or visitor == "(not set)":
            continue
        bucket = days[(visitor, day)]
        views = int(float(m.get("screenPageViews") or 0))
        bucket["views"] += views
        bucket["engagement_s"] += float(m.get("userEngagementDuration") or 0)
        bucket["pages"][d.get("pagePath") or "/"] += views
        if d.get("sessionSourceMedium"):
            bucket["channels"].add(d["sessionSourceMedium"])

    signals: list[Signal] = []
    for (visitor, day), bucket in sorted(days.items()):
        occurred = datetime.strptime(day, "%Y%m%d").replace(tzinfo=UTC)
        subject = EntityHint(entity_type=EntityType.PERSON, visitor_id=visitor)
        top_pages = sorted(bucket["pages"].items(), key=lambda kv: -kv[1])[:5]
        signals.append(
            Signal(
                signal_type=SignalType.WEB_VISIT,
                source=Source.GA4,
                external_id=f"{visitor}:{day}",
                occurred_at=occurred,
                subject=subject,
                title=f"{bucket['views']} page views on the website",
                strength=round(
                    min(1.0, 0.2 + bucket["views"] / 20 + bucket["engagement_s"] / 900), 3
                ),
                attributes={
                    "page_views": bucket["views"],
                    "engagement_s": round(bucket["engagement_s"]),
                    "top_pages": [p for p, _ in top_pages],
                    "channels": sorted(bucket["channels"]),
                },
            )
        )
        for path in bucket["pages"]:
            if icp.is_high_intent_path(path):
                signals.append(
                    Signal(
                        signal_type=SignalType.HIGH_INTENT_PAGE,
                        source=Source.GA4,
                        external_id=f"{visitor}:{day}:{path}",
                        occurred_at=occurred,
                        subject=subject,
                        title=f"Viewed {path}",
                        strength=0.8,
                        attributes={"path": path},
                    )
                )
    return signals
