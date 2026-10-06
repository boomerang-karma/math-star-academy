"""Inputs to the resolver: records being resolved and snapshots of existing entities."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from leadintel.ontology.models import EntityType, Source, SourceRecord
from leadintel.security.blind_index import BlindIndexer


@dataclass(frozen=True)
class ResolvableRecord:
    """A source record as the resolver sees it: restricted identifiers only as blind indexes."""

    record_id: UUID
    entity_type: EntityType
    source: Source
    observed_at: datetime
    attributes: Mapping[str, Any]
    email_bidx: str | None = None
    phone_bidx: str | None = None

    @classmethod
    def from_source_record(cls, record: SourceRecord, bidx: BlindIndexer) -> ResolvableRecord:
        return cls(
            record_id=record.id,
            entity_type=record.entity_type,
            source=record.source,
            observed_at=record.observed_at,
            attributes=dict(record.attributes),
            email_bidx=bidx.maybe_index(record.restricted.get("email"), field="email"),
            phone_bidx=bidx.maybe_index(record.restricted.get("phone"), field="phone"),
        )


@dataclass(frozen=True)
class EntitySnapshot:
    """An existing entity, flattened to its golden values for comparison."""

    entity_id: UUID
    entity_type: EntityType
    attributes: Mapping[str, Any]
    email_bidx: str | None = None
    phone_bidx: str | None = None
    member_sources: frozenset[Source] = field(default_factory=frozenset)
