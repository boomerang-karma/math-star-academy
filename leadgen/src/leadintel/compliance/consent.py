"""Consent evidence captured from forms (LinkedIn Lead Gen Forms, our own website)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from leadintel.ontology.models import LawfulBasis


class Purpose(StrEnum):
    MARKETING_EMAIL = "marketing_email"
    SALES_OUTREACH = "sales_outreach"
    ANALYTICS = "analytics"
    PROFILING = "profiling"


class ConsentStatus(StrEnum):
    GRANTED = "granted"
    DENIED = "denied"
    WITHDRAWN = "withdrawn"


class ConsentRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    subject_bidx: str
    purpose: Purpose
    status: ConsentStatus
    lawful_basis: LawfulBasis
    source: str
    captured_at: datetime
    evidence: dict[str, Any] = Field(default_factory=dict)
