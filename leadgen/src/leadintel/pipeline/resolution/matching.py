"""Pairwise match scoring (Fellegi-Sunter style, hand-tuned weights).

Each comparable feature adds or subtracts log-odds evidence; the sum plus a
prior is squashed into a match probability. Weights are deliberately simple
and documented so analysts can reason about decisions; replace them with
weights learned from review-queue labels once enough decisions accumulate
(roadmap phase 3).

Thresholds: p >= 0.95 auto-match, 0.70 <= p < 0.95 human review, else distinct.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from rapidfuzz import fuzz
from rapidfuzz.distance import JaroWinkler

from leadintel.ontology.models import EntityType
from leadintel.pipeline.normalize import (
    company_name_key,
    normalize_domain,
    person_name_key,
)
from leadintel.pipeline.resolution.blocking import Blockable

PRIOR_LOG_ODDS = -4.0  # ~1.8%: two random records in a block are rarely the same entity
STRONG_CONFLICT = -6.0


class Decision(StrEnum):
    MATCH = "match"
    REVIEW = "review"
    NO_MATCH = "no_match"


@dataclass(frozen=True)
class Evidence:
    feature: str
    weight: float
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {"feature": self.feature, "weight": self.weight, "detail": self.detail}


@dataclass(frozen=True)
class Thresholds:
    match: float = 0.95
    review: float = 0.70


@dataclass(frozen=True)
class MatchResult:
    probability: float
    decision: Decision
    evidence: tuple[Evidence, ...]
    deterministic: bool

    @property
    def method(self) -> str:
        return "deterministic" if self.deterministic else "probabilistic"


def _both(a: Any, b: Any) -> bool:
    return a not in (None, "") and b not in (None, "")


class _Scorer:
    def __init__(self) -> None:
        self.evidence: list[Evidence] = []
        self.deterministic = False

    def add(self, feature: str, weight: float, detail: str, *, deterministic: bool = False) -> None:
        self.evidence.append(Evidence(feature, weight, detail))
        self.deterministic = self.deterministic or deterministic

    def result(self, thresholds: Thresholds) -> MatchResult:
        total = PRIOR_LOG_ODDS + sum(e.weight for e in self.evidence)
        probability = round(1.0 / (1.0 + math.exp(-total)), 4)
        if probability >= thresholds.match:
            decision = Decision.MATCH
        elif probability >= thresholds.review:
            decision = Decision.REVIEW
        else:
            decision = Decision.NO_MATCH
        # A shared hard identifier next to a hard conflict needs a human, whatever the sum.
        if self.deterministic and any(e.weight <= STRONG_CONFLICT for e in self.evidence):
            decision = Decision.REVIEW
        ordered = tuple(sorted(self.evidence, key=lambda e: -abs(e.weight)))
        return MatchResult(probability, decision, ordered, self.deterministic)


def _name_similarity(a: str, b: str) -> float:
    return float(JaroWinkler.normalized_similarity(a, b))


def _compare_people(a: Blockable, b: Blockable, s: _Scorer) -> None:
    aa, ba = a.attributes, b.attributes
    if _both(a.email_bidx, b.email_bidx):
        if a.email_bidx == b.email_bidx:
            s.add("email", 9.0, "same email address", deterministic=True)
        else:
            s.add("email", -1.0, "different email addresses")
    if _both(aa.get("linkedin_slug"), ba.get("linkedin_slug")):
        if aa["linkedin_slug"] == ba["linkedin_slug"]:
            s.add("linkedin", 9.0, "same LinkedIn profile", deterministic=True)
        else:
            s.add("linkedin", -8.0, "different LinkedIn profiles")
    if _both(a.phone_bidx, b.phone_bidx) and a.phone_bidx == b.phone_bidx:
        s.add("phone", 5.0, "same phone number")

    na, nb = person_name_key(aa.get("full_name")), person_name_key(ba.get("full_name"))
    if na and nb:
        sim = _name_similarity(na, nb)
        if sim >= 0.97:
            s.add("name", 4.0, f"names match ({sim:.2f})")
        elif sim >= 0.92:
            s.add("name", 2.5, f"names very similar ({sim:.2f})")
        elif sim >= 0.85:
            s.add("name", 1.0, f"names similar ({sim:.2f})")
        elif sim < 0.75:
            s.add("name", -4.0, f"names differ ({sim:.2f})")

    da, db = normalize_domain(aa.get("company_domain")), normalize_domain(ba.get("company_domain"))
    if da and db:
        if da == db:
            s.add("company", 2.5, f"same company domain {da}")
        else:
            s.add("company", -1.5, "different company domains")
    else:
        ca, cb = company_name_key(aa.get("company_name")), company_name_key(ba.get("company_name"))
        if ca and cb and fuzz.token_set_ratio(ca, cb) >= 90:
            s.add("company", 1.5, "same company name")

    if _both(aa.get("country"), ba.get("country")) and aa["country"] != ba["country"]:
        s.add("country", -1.5, "different countries")
    elif (
        _both(aa.get("city"), ba.get("city")) and str(aa["city"]).lower() == str(ba["city"]).lower()
    ):
        s.add("city", 0.5, "same city")
    titles = (str(aa.get("title") or "").lower(), str(ba.get("title") or "").lower())
    if all(titles) and fuzz.token_set_ratio(*titles) >= 85:
        s.add("title", 0.5, "similar job titles")


def _compare_orgs(a: Blockable, b: Blockable, s: _Scorer) -> None:
    aa, ba = a.attributes, b.attributes
    if _both(aa.get("linkedin_slug"), ba.get("linkedin_slug")):
        if aa["linkedin_slug"] == ba["linkedin_slug"]:
            s.add("linkedin", 9.0, "same LinkedIn company page", deterministic=True)
        else:
            s.add("linkedin", -7.0, "different LinkedIn company pages")
    if _both(aa.get("domain"), ba.get("domain")):
        if aa["domain"] == ba["domain"]:
            s.add("domain", 7.0, f"same website domain {aa['domain']}", deterministic=True)
        else:
            s.add("domain", -4.0, "different website domains")
    if _both(aa.get("google_place_id"), ba.get("google_place_id")):
        if aa["google_place_id"] == ba["google_place_id"]:
            s.add("google_place", 9.0, "same Google Maps place", deterministic=True)
        else:
            # One organization can have several locations, so this is weak evidence.
            s.add("google_place", -1.0, "different Google Maps places")
    if _both(aa.get("phone"), ba.get("phone")) and aa["phone"] == ba["phone"]:
        s.add("phone", 4.0, "same business phone")

    na, nb = company_name_key(aa.get("name")), company_name_key(ba.get("name"))
    if na and nb:
        sim = fuzz.token_set_ratio(na, nb) / 100
        if sim >= 0.97:
            s.add("name", 3.5, f"names match ({sim:.2f})")
        elif sim >= 0.90:
            s.add("name", 2.0, f"names very similar ({sim:.2f})")
        elif sim >= 0.80:
            s.add("name", 0.5, f"names similar ({sim:.2f})")
        elif sim < 0.60:
            s.add("name", -4.0, f"names differ ({sim:.2f})")

    if _both(aa.get("hq_country"), ba.get("hq_country")) and aa["hq_country"] != ba["hq_country"]:
        s.add("country", -2.0, "different HQ countries")
    elif (
        _both(aa.get("hq_city"), ba.get("hq_city"))
        and str(aa["hq_city"]).lower() == str(ba["hq_city"]).lower()
    ):
        s.add("city", 0.5, "same HQ city")


def compare(a: Blockable, b: Blockable, thresholds: Thresholds = Thresholds()) -> MatchResult:
    if a.entity_type is not b.entity_type:
        raise ValueError("cannot compare a person with an organization")
    scorer = _Scorer()
    if a.entity_type is EntityType.PERSON:
        _compare_people(a, b, scorer)
    else:
        _compare_orgs(a, b, scorer)
    return scorer.result(thresholds)
