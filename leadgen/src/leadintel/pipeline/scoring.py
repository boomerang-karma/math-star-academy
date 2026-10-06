"""Explainable lead scoring.

Three components, each 0-100:

* **Fit** - how closely the account (and person) matches the ICP: industry,
  size, geography, technology stack, buyer persona.
* **Intent** - market signals that the account is in motion: hiring for roles we
  sell into, funding, expansion, leadership changes, news.
* **Engagement** - interactions with us: site visits, pricing-page views,
  downloads, form fills, meetings.

Signals decay exponentially (each type has its own half-life), repeated signals
of one type have diminishing returns (the k-th strongest counts ``0.5^k``), and
components saturate (``100 * (1 - e^(-x/50))``), so a pile of weak signals
cannot outrank a few strong ones.
``total = 0.45 fit + 0.35 intent + 0.20 engagement``; tiers are
A >= 70, B >= 50, C >= 30, else D. Every point is attributed to a factor, and
the API returns the list as the lead's "why this score".
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from leadintel.ontology.models import SignalType
from leadintel.pipeline.icp import IcpProfile

WEIGHTS: Mapping[str, float] = {"fit": 0.45, "intent": 0.35, "engagement": 0.20}
TIERS: tuple[tuple[float, str], ...] = ((70.0, "A"), (50.0, "B"), (30.0, "C"), (0.0, "D"))
SATURATION = 50.0
HOT_WINDOW = timedelta(hours=72)

# signal type -> (component, base points, half-life in days)
SIGNAL_POLICY: Mapping[SignalType, tuple[str, float, float]] = {
    SignalType.JOB_POSTING: ("intent", 18.0, 30.0),
    SignalType.FUNDING: ("intent", 30.0, 90.0),
    SignalType.ACQUISITION: ("intent", 15.0, 90.0),
    SignalType.EXPANSION: ("intent", 18.0, 60.0),
    SignalType.LEADERSHIP_CHANGE: ("intent", 20.0, 90.0),
    SignalType.NEWS_MENTION: ("intent", 5.0, 30.0),
    SignalType.TECH_DETECTED: ("intent", 8.0, 180.0),
    SignalType.WEB_VISIT: ("engagement", 10.0, 14.0),
    SignalType.HIGH_INTENT_PAGE: ("engagement", 25.0, 14.0),
    SignalType.CONTENT_DOWNLOAD: ("engagement", 20.0, 30.0),
    SignalType.FORM_SUBMISSION: ("engagement", 45.0, 45.0),
    SignalType.EMAIL_CLICK: ("engagement", 12.0, 14.0),
    SignalType.MEETING_BOOKED: ("engagement", 60.0, 60.0),
}
HOT_SIGNALS = frozenset(
    {SignalType.FORM_SUBMISSION, SignalType.HIGH_INTENT_PAGE, SignalType.MEETING_BOOKED}
)

# Fit factor maxima (points before normalization).
FIT_MAX = {"industry": 30.0, "size": 25.0, "geography": 15.0, "technology": 15.0, "persona": 15.0}


@dataclass(frozen=True)
class SignalView:
    signal_type: SignalType
    occurred_at: datetime
    strength: float
    title: str


@dataclass(frozen=True)
class Contribution:
    component: str
    factor: str
    points: float
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "factor": self.factor,
            "points": self.points,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class LeadScore:
    total: float
    tier: str
    fit: float
    intent: float
    engagement: float
    hot: bool
    contributions: tuple[Contribution, ...]


def _saturate(raw: float) -> float:
    return 100.0 * (1.0 - math.exp(-max(raw, 0.0) / SATURATION))


def fit_score(
    org: Mapping[str, Any], person: Mapping[str, Any] | None, icp: IcpProfile
) -> tuple[float, list[Contribution]]:
    contributions: list[Contribution] = []
    excluded = icp.is_excluded(
        org.get("name"),
        org.get("description"),
        (person or {}).get("title"),
        (person or {}).get("headline"),
    )
    if excluded:
        return 0.0, [
            Contribution("fit", "excluded", 0.0, f"matches exclusion keyword '{excluded}'")
        ]

    earned = 0.0
    available = 0.0

    def add(factor: str, weight: float | None, detail: str) -> None:
        """``weight=None`` means the attribute is unknown: it counts half against the lead."""
        nonlocal earned, available
        if weight is None:
            available += FIT_MAX[factor] * 0.5
            return
        points = FIT_MAX[factor] * weight
        earned += points
        available += FIT_MAX[factor]
        if points > 0:
            contributions.append(Contribution("fit", factor, round(points, 2), detail))

    industry = org.get("industry")
    industry_weight, keyword = icp.industry_weight(industry)
    add(
        "industry",
        industry_weight if industry else None,
        f"industry '{industry}' matches '{keyword}'",
    )
    count = org.get("employee_count")
    add(
        "size", icp.employee_weight(int(count)) if count is not None else None, f"{count} employees"
    )
    country = org.get("hq_country")
    add(
        "geography", icp.country_weight(country) if country else None, f"headquartered in {country}"
    )
    technologies = org.get("technologies") or []
    matched = [t for t in technologies if t in icp.technologies]
    tech_weight = min(1.0, sum(icp.technologies[t] for t in matched))
    add("technology", tech_weight if technologies else None, f"uses {', '.join(matched)}")
    if person is not None:
        title = person.get("title") or person.get("headline")
        persona = icp.title_match(title)
        add(
            "persona",
            (1.0 if persona else 0.0) if title else None,
            f"title '{title}' is a buyer persona",
        )

    if available == 0:
        return 0.0, contributions
    return round(100.0 * earned / available, 2), contributions


def signal_component(
    signals: Iterable[SignalView], component: str, now: datetime
) -> tuple[float, list[Contribution]]:
    by_type: dict[SignalType, list[tuple[float, SignalView, float]]] = {}
    for signal in signals:
        policy = SIGNAL_POLICY.get(signal.signal_type)
        if policy is None or policy[0] != component:
            continue
        _, base, half_life = policy
        age_days = max((now - signal.occurred_at).total_seconds() / 86_400, 0.0)
        decayed = base * signal.strength * 0.5 ** (age_days / half_life)
        by_type.setdefault(signal.signal_type, []).append((decayed, signal, age_days))

    raw = 0.0
    contributions: list[Contribution] = []
    for signal_type, items in by_type.items():
        items.sort(key=lambda item: -item[0])
        for rank, (decayed, signal, age_days) in enumerate(items):
            points = decayed * 0.5**rank  # diminishing returns within a signal type
            if points < 0.05:
                break
            raw += points
            contributions.append(
                Contribution(
                    component,
                    signal_type.value,
                    round(points, 2),
                    f"{signal.title} ({age_days:.0f}d ago)",
                )
            )
    return round(_saturate(raw), 2), contributions


def score_lead(
    *,
    org: Mapping[str, Any],
    person: Mapping[str, Any] | None,
    signals: Iterable[SignalView],
    icp: IcpProfile,
    now: datetime,
) -> LeadScore:
    signals = list(signals)
    fit, fit_parts = fit_score(org, person, icp)
    intent, intent_parts = signal_component(signals, "intent", now)
    engagement, engagement_parts = signal_component(signals, "engagement", now)
    total = round(
        WEIGHTS["fit"] * fit + WEIGHTS["intent"] * intent + WEIGHTS["engagement"] * engagement, 2
    )
    tier = next(label for threshold, label in TIERS if total >= threshold)
    hot = any(s.signal_type in HOT_SIGNALS and now - s.occurred_at <= HOT_WINDOW for s in signals)
    contributions = sorted(fit_parts + intent_parts + engagement_parts, key=lambda c: -c.points)
    return LeadScore(total, tier, fit, intent, engagement, hot, tuple(contributions))
