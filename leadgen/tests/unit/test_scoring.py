from __future__ import annotations

from datetime import UTC, datetime, timedelta

from leadintel.ontology.models import SignalType
from leadintel.pipeline.icp import DEFAULT_ICP, IcpProfile
from leadintel.pipeline.scoring import SignalView, fit_score, score_lead, signal_component

NOW = datetime(2026, 10, 1, tzinfo=UTC)
ORG = {
    "name": "Northwind Analytics",
    "industry": "Computer Software",
    "employee_count": 312,
    "hq_country": "US",
    "technologies": ["hubspot", "segment"],
}


def sig(kind: SignalType, days_ago: float, strength: float = 1.0) -> SignalView:
    return SignalView(kind, NOW - timedelta(days=days_ago), strength, kind.value)


def test_ideal_account_fit() -> None:
    fit, parts = fit_score(ORG, {"title": "VP Sales"}, DEFAULT_ICP)
    assert fit == 100.0
    assert {p.factor for p in parts} == {"industry", "size", "geography", "technology", "persona"}


def test_unknown_attributes_count_half() -> None:
    fit, _ = fit_score({"industry": "Computer Software"}, None, DEFAULT_ICP)
    # industry 30/30 earned; size/geo/tech unknown -> 27.5 more available
    assert fit == round(100 * 30 / (30 + 12.5 + 7.5 + 7.5), 2)


def test_exclusions_zero_the_fit() -> None:
    fit, parts = fit_score(ORG, {"title": "Student at UT Austin"}, DEFAULT_ICP)
    assert fit == 0.0
    assert parts[0].factor == "excluded"


def test_signals_decay_and_saturate() -> None:
    fresh, _ = signal_component([sig(SignalType.FUNDING, 0)], "intent", NOW)
    stale, _ = signal_component([sig(SignalType.FUNDING, 180)], "intent", NOW)
    assert fresh > stale > 0
    many_weak, parts = signal_component([sig(SignalType.NEWS_MENTION, 0)] * 200, "intent", NOW)
    assert many_weak < fresh  # 200 trivial mentions never beat one funding round
    assert len(parts) < 10  # diminishing returns stop counting long before 200


def test_hot_tier_a_lead_with_explanations() -> None:
    signals = [
        sig(SignalType.FUNDING, 9),
        sig(SignalType.JOB_POSTING, 3),
        sig(SignalType.LEADERSHIP_CHANGE, 16),
        sig(SignalType.HIGH_INTENT_PAGE, 1),
        sig(SignalType.FORM_SUBMISSION, 1),
    ]
    score = score_lead(
        org=ORG, person={"title": "VP Sales"}, signals=signals, icp=DEFAULT_ICP, now=NOW
    )
    assert score.tier == "A"
    assert score.hot
    assert score.contributions[0].points >= score.contributions[-1].points
    assert {c.component for c in score.contributions} == {"fit", "intent", "engagement"}


def test_cold_poor_fit_is_tier_d() -> None:
    icp = IcpProfile(name="narrow", industries={"biotech": 1.0}, countries={"DE": 1.0})
    score = score_lead(
        org={"industry": "Restaurants", "hq_country": "US"},
        person=None,
        signals=[],
        icp=icp,
        now=NOW,
    )
    assert score.tier == "D"
    assert not score.hot
