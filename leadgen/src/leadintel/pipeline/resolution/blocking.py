"""Blocking: cheap keys that put plausible duplicates in the same bucket.

Only records sharing at least one key are compared, which turns an O(n^2)
problem into many tiny ones. Person keys are blind-indexed (HMAC) so the
``graph.entity_key`` table never holds names or LinkedIn handles in clear text;
organization keys are business identifiers and stay readable.
"""

from __future__ import annotations

from typing import Any, Protocol

from leadintel.ontology.models import EntityType
from leadintel.pipeline.normalize import company_name_key, normalize_domain, person_name_key
from leadintel.security.blind_index import BlindIndexer

# Keys that identify an entity on their own; their blocks are always compared.
STRONG_KEY_PREFIXES = ("email:", "phone:", "li:", "li_org:", "domain:", "gplace:")


class Blockable(Protocol):
    @property
    def entity_type(self) -> EntityType: ...
    @property
    def attributes(self) -> Any: ...
    @property
    def email_bidx(self) -> str | None: ...
    @property
    def phone_bidx(self) -> str | None: ...


def blocking_keys(item: Blockable, bidx: BlindIndexer) -> set[str]:
    attrs = item.attributes
    keys: set[str] = set()
    if item.entity_type is EntityType.PERSON:
        if item.email_bidx:
            keys.add(f"email:{item.email_bidx}")
        if item.phone_bidx:
            keys.add(f"phone:{item.phone_bidx}")
        if slug := attrs.get("linkedin_slug"):
            keys.add(f"li:{bidx.index(slug, field='key.li')}")
        name = person_name_key(attrs.get("full_name"))
        if name:
            if domain := normalize_domain(attrs.get("company_domain")):
                keys.add(f"name_domain:{bidx.index(f'{name}|{domain}', field='key.name_domain')}")
            if company := company_name_key(attrs.get("company_name")):
                keys.add(
                    f"name_company:{bidx.index(f'{name}|{company}', field='key.name_company')}"
                )
        return keys

    if domain := attrs.get("domain"):
        keys.add(f"domain:{domain}")
    if slug := attrs.get("linkedin_slug"):
        keys.add(f"li_org:{slug}")
    if place := attrs.get("google_place_id"):
        keys.add(f"gplace:{place}")
    if phone := attrs.get("phone"):
        keys.add(f"orgphone:{phone}")
    if name := company_name_key(attrs.get("name")):
        keys.add(f"orgname:{name}")
    return keys


def is_strong(key: str) -> bool:
    return key.startswith(STRONG_KEY_PREFIXES)
