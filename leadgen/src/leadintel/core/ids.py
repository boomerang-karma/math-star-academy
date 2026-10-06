"""Deterministic identifiers.

Source records and signals get UUIDv5 ids derived from their natural keys, so
re-running a connector upserts instead of duplicating, and the same upstream
object always maps to the same row no matter which worker ingested it.
"""

from __future__ import annotations

import uuid

# Fixed namespace for every LeadIntel UUIDv5. Changing it re-keys all data.
LEADINTEL_NAMESPACE = uuid.UUID("6f1c2b0e-5f7a-4f43-9a35-3c1d1e0b7a21")


def stable_uuid(*parts: str) -> uuid.UUID:
    """Return a UUIDv5 over ``parts`` joined with a separator that cannot appear in them."""
    if not parts:
        raise ValueError("stable_uuid needs at least one part")
    return uuid.uuid5(LEADINTEL_NAMESPACE, "\x1f".join(parts))
