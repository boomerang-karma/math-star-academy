"""Tamper-evident audit trail.

Rows in ``audit.audit_log`` form a hash chain: each row's ``hash`` is
``sha256(prev_hash || canonical_line(row))``. The chain is computed by a
database trigger under an advisory lock, so concurrent writers cannot fork it,
and update/delete/truncate are rejected by triggers. A scheduled job copies the
chain head to an S3 Object Lock bucket, so even someone able to rewrite the
table cannot do it without the anchored head disagreeing.

:func:`canonical_line` here and ``audit.canonical_line`` in SQL must stay
byte-for-byte identical; ``tests/integration/test_audit_chain.py`` checks that.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

GENESIS_HASH = b"\x00" * 32
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class ActorType(StrEnum):
    USER = "user"
    SERVICE = "service"
    SYSTEM = "system"


class Outcome(StrEnum):
    SUCCESS = "success"
    DENIED = "denied"
    ERROR = "error"


@dataclass(frozen=True)
class AuditEvent:
    actor_id: str
    actor_type: ActorType
    action: str
    resource_type: str
    resource_id: str | None = None
    outcome: Outcome = Outcome.SUCCESS
    request_id: str | None = None
    ip: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AuditRow:
    """A persisted audit row as read back for verification.

    ``details_text`` must be the database's own ``details::text`` rendering.
    """

    seq: int
    occurred_at: datetime
    actor_id: str
    actor_type: str
    action: str
    resource_type: str
    resource_id: str | None
    outcome: str
    request_id: str | None
    ip: str | None
    details_text: str
    prev_hash: bytes | None
    hash: bytes


def _epoch_micros(ts: datetime) -> int:
    return (ts - _EPOCH) // timedelta(microseconds=1)


def canonical_line(row: AuditRow) -> str:
    return "|".join(
        [
            str(row.seq),
            str(_epoch_micros(row.occurred_at)),
            row.actor_id,
            row.actor_type,
            row.action,
            row.resource_type,
            row.resource_id or "",
            row.outcome,
            row.request_id or "",
            row.ip or "",
            row.details_text,
        ]
    )


def chain_hash(prev_hash: bytes | None, line: str) -> bytes:
    return hashlib.sha256((prev_hash or GENESIS_HASH) + line.encode()).digest()


def verify_chain(rows: Iterable[AuditRow]) -> int | None:
    """Walk rows in ``seq`` order; return the first seq whose link is broken, else None."""
    previous: bytes | None = None
    first = True
    for row in rows:
        if not first and row.prev_hash != previous:
            return row.seq
        if row.hash != chain_hash(row.prev_hash, canonical_line(row)):
            return row.seq
        previous = row.hash
        first = False
    return None
