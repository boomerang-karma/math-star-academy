"""Canonical attribute names and their data classification.

Classification drives storage:

* ``RESTRICTED`` - direct personal identifiers. Envelope-encrypted with KMS data
  keys in the application *and* blind-indexed for equality lookups. Shown only to
  principals holding ``pii:read``.
* ``CONFIDENTIAL`` - personal but non-contact data (names, titles). Encrypted at
  rest by Aurora/S3, row-level-secured by territory, masked in analyst views.
* ``INTERNAL`` - business firmographics, mostly public.
"""

from __future__ import annotations

from enum import StrEnum

from leadintel.ontology.models import EntityType


class DataClass(StrEnum):
    RESTRICTED = "restricted"
    CONFIDENTIAL = "confidential"
    INTERNAL = "internal"


ORGANIZATION_ATTRIBUTES: dict[str, DataClass] = {
    "name": DataClass.INTERNAL,
    "domain": DataClass.INTERNAL,
    "website": DataClass.INTERNAL,
    "linkedin_slug": DataClass.INTERNAL,
    "linkedin_url": DataClass.INTERNAL,
    "google_place_id": DataClass.INTERNAL,
    "industry": DataClass.INTERNAL,
    "description": DataClass.INTERNAL,
    "specialties": DataClass.INTERNAL,
    "categories": DataClass.INTERNAL,
    "employee_count": DataClass.INTERNAL,
    "employee_range": DataClass.INTERNAL,
    "founded_year": DataClass.INTERNAL,
    "follower_count": DataClass.INTERNAL,
    "hq_city": DataClass.INTERNAL,
    "hq_region": DataClass.INTERNAL,
    "hq_country": DataClass.INTERNAL,
    "address": DataClass.INTERNAL,
    "phone": DataClass.INTERNAL,  # switchboard number of a business
    "rating": DataClass.INTERNAL,
    "review_count": DataClass.INTERNAL,
    "technologies": DataClass.INTERNAL,
}

PERSON_ATTRIBUTES: dict[str, DataClass] = {
    "full_name": DataClass.CONFIDENTIAL,
    "first_name": DataClass.CONFIDENTIAL,
    "last_name": DataClass.CONFIDENTIAL,
    "title": DataClass.CONFIDENTIAL,
    "seniority": DataClass.CONFIDENTIAL,
    "headline": DataClass.CONFIDENTIAL,
    "linkedin_slug": DataClass.CONFIDENTIAL,
    "linkedin_url": DataClass.CONFIDENTIAL,
    "city": DataClass.CONFIDENTIAL,
    "region": DataClass.CONFIDENTIAL,
    "country": DataClass.CONFIDENTIAL,
    "company_name": DataClass.CONFIDENTIAL,
    "company_domain": DataClass.CONFIDENTIAL,
    "email": DataClass.RESTRICTED,
    "phone": DataClass.RESTRICTED,
}

# Restricted attributes travel in SourceRecord.restricted, never in .attributes.
RESTRICTED_PERSON_ATTRIBUTES = frozenset(
    name for name, cls in PERSON_ATTRIBUTES.items() if cls is DataClass.RESTRICTED
)


def schema_for(entity_type: EntityType) -> dict[str, DataClass]:
    if entity_type is EntityType.ORGANIZATION:
        return ORGANIZATION_ATTRIBUTES
    return PERSON_ATTRIBUTES


def unknown_attributes(entity_type: EntityType, names: set[str]) -> set[str]:
    return names - set(schema_for(entity_type))
