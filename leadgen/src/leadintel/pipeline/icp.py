"""Ideal Customer Profile: the business definition of a good lead.

Scoring, hiring-signal relevance and discovery playbooks all read the same
profile, so changing who you sell to is a config change, not a code change.
Load a custom profile with ``LEADINTEL_ICP_PATH=/path/icp.json``; the default
below describes a B2B software seller and is meant to be edited.
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class EmployeeBand(BaseModel):
    model_config = ConfigDict(frozen=True)

    min: int
    max: int | None = None
    weight: float = Field(ge=0, le=1)

    def contains(self, count: int) -> bool:
        return count >= self.min and (self.max is None or count <= self.max)


def _contains_phrase(haystack: str, phrase: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", haystack) is not None


class IcpProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    industries: dict[str, float] = Field(default_factory=dict)
    employee_bands: list[EmployeeBand] = Field(default_factory=list)
    countries: dict[str, float] = Field(default_factory=dict)
    buyer_titles: list[str] = Field(default_factory=list)
    buyer_seniorities: list[str] = Field(default_factory=list)
    hiring_keywords: list[str] = Field(default_factory=list)
    technologies: dict[str, float] = Field(default_factory=dict)
    exclude_keywords: list[str] = Field(default_factory=list)
    high_intent_paths: list[str] = Field(default_factory=lambda: ["/pricing", "/demo", "/contact"])

    def industry_weight(self, industry: str | None) -> tuple[float, str | None]:
        if not industry:
            return 0.0, None
        text = industry.lower()
        best = max(
            ((w, k) for k, w in self.industries.items() if _contains_phrase(text, k)),
            default=(0.0, None),
        )
        return best

    def employee_weight(self, count: int | None) -> float:
        if count is None:
            return 0.0
        return max((b.weight for b in self.employee_bands if b.contains(count)), default=0.0)

    def country_weight(self, country: str | None) -> float:
        return self.countries.get((country or "").upper(), 0.0)

    def title_match(self, title: str | None) -> str | None:
        text = (title or "").lower()
        return next((t for t in self.buyer_titles if _contains_phrase(text, t)), None)

    def hiring_relevance(self, job_title: str | None) -> float:
        """1.0 when a job title names a role that signals need for what we sell."""
        text = (job_title or "").lower()
        return 1.0 if any(_contains_phrase(text, k) for k in self.hiring_keywords) else 0.0

    def is_excluded(self, *texts: str | None) -> str | None:
        joined = " ".join(t.lower() for t in texts if t)
        return next((k for k in self.exclude_keywords if _contains_phrase(joined, k)), None)

    def is_high_intent_path(self, path: str | None) -> bool:
        if not path:
            return False
        return any(path.startswith(p) for p in self.high_intent_paths)


DEFAULT_ICP = IcpProfile(
    name="B2B software, mid-market",
    industries={
        "software": 1.0,
        "saas": 1.0,
        "information technology": 0.9,
        "internet": 0.8,
        "computer software": 1.0,
        "financial services": 0.7,
        "marketing": 0.7,
        "advertising": 0.6,
        "staffing": 0.5,
        "consulting": 0.5,
    },
    employee_bands=[
        EmployeeBand(min=1, max=10, weight=0.2),
        EmployeeBand(min=11, max=50, weight=0.6),
        EmployeeBand(min=51, max=1000, weight=1.0),
        EmployeeBand(min=1001, max=5000, weight=0.7),
        EmployeeBand(min=5001, weight=0.4),
    ],
    countries={"US": 1.0, "CA": 0.9, "GB": 0.9, "IE": 0.8, "DE": 0.8, "NL": 0.8, "AU": 0.7},
    buyer_titles=[
        "chief revenue officer",
        "cro",
        "vp sales",
        "vice president of sales",
        "head of sales",
        "head of growth",
        "vp marketing",
        "cmo",
        "chief marketing officer",
        "revenue operations",
        "sales operations",
        "demand generation",
        "founder",
        "ceo",
    ],
    buyer_seniorities=["c-level", "vp", "director", "head", "founder", "owner"],
    hiring_keywords=[
        "sales development",
        "sdr",
        "bdr",
        "business development representative",
        "account executive",
        "revenue operations",
        "sales operations",
        "growth marketing",
        "demand generation",
        "marketing operations",
    ],
    technologies={
        "hubspot": 0.6,
        "salesforce": 0.8,
        "marketo": 0.6,
        "segment": 0.4,
        "intercom": 0.3,
        "google_analytics": 0.1,
    },
    exclude_keywords=["student", "intern", "recruiter", "job seeker"],
)


@lru_cache(maxsize=4)
def _load(path: str) -> IcpProfile:
    return IcpProfile.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


def load_icp(path: str | None = None) -> IcpProfile:
    path = path or os.environ.get("LEADINTEL_ICP_PATH")
    return _load(path) if path else DEFAULT_ICP
