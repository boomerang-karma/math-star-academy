"""Data-subject requests: access (export) and erasure.

Subjects are located by the blind index of their email, so a request can be
served without ever searching plaintext. Erasure removes the person from every
table, deletes their bronze-zone payloads, tombstones the entity (no personal
data remains in the row) and adds a suppression so the next scrape does not
re-collect them. Audit rows keep only ids, never personal data, so they stay.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from leadintel.security.crypto import FieldCipher
from leadintel.storage.db import Connection
from leadintel.storage.raw_store import RawStore

RESPONSE_WINDOW = {
    "gdpr": timedelta(days=30),
    "uk_gdpr": timedelta(days=30),
    "ccpa": timedelta(days=45),
    "other": timedelta(days=30),
}


def due_date(jurisdiction: str, received_at: datetime) -> datetime:
    return received_at + RESPONSE_WINDOW.get(jurisdiction, timedelta(days=30))


def _subject_entities(conn: Connection, email_bidx: str) -> list[UUID]:
    rows = conn.execute(
        """
        SELECT id FROM graph.entity WHERE entity_type = 'person' AND email_bidx = %s
        UNION
        SELECT m.entity_id FROM ingest.source_record sr
          JOIN graph.entity_member m ON m.source_record_id = sr.id
         WHERE sr.email_bidx = %s AND sr.entity_type = 'person'
        """,
        (email_bidx, email_bidx),
    ).fetchall()
    return [row["id"] for row in rows]


def _subject_records(
    conn: Connection, email_bidx: str, entities: list[UUID]
) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT sr.id, sr.source, sr.attributes, sr.pii_envelope, sr.raw_uri, sr.observed_at
          FROM ingest.source_record sr
         WHERE (sr.email_bidx = %s AND sr.entity_type = 'person')
            OR sr.id IN (SELECT source_record_id FROM graph.entity_member WHERE entity_id = ANY(%s))
        """,
        (email_bidx, entities),
    ).fetchall()


def export_subject(conn: Connection, *, email_bidx: str, cipher: FieldCipher) -> dict[str, Any]:
    """Everything we hold about one person, decrypted, for an access/portability request."""
    entities = _subject_entities(conn, email_bidx)
    records = _subject_records(conn, email_bidx, entities)
    signals = conn.execute(
        "SELECT signal_type, source, occurred_at, title, url FROM graph.signal"
        " WHERE entity_id = ANY(%s) OR subject_hint ->> 'email_bidx' = %s ORDER BY occurred_at",
        (entities, email_bidx),
    ).fetchall()
    consents = conn.execute(
        "SELECT purpose, status, lawful_basis, source, captured_at FROM privacy.consent"
        " WHERE subject_bidx = %s",
        (email_bidx,),
    ).fetchall()
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "records": [
            {
                "source": r["source"],
                "observed_at": r["observed_at"].isoformat(),
                "attributes": r["attributes"],
                "restricted": cipher.decrypt_json(r["pii_envelope"]) if r["pii_envelope"] else {},
            }
            for r in records
        ],
        "signals": [{**s, "occurred_at": s["occurred_at"].isoformat()} for s in signals],
        "consents": [{**c, "captured_at": c["captured_at"].isoformat()} for c in consents],
    }


def erase_subject(
    conn: Connection, *, email_bidx: str, actor: str, raw_store: RawStore | None = None
) -> dict[str, int]:
    """Erase one person. Run inside a transaction (the DSAR worker does)."""
    entities = _subject_entities(conn, email_bidx)
    records = _subject_records(conn, email_bidx, entities)
    record_ids = [r["id"] for r in records]
    counts: dict[str, int] = {}

    def run(name: str, sql: str, params: tuple[Any, ...]) -> None:
        counts[name] = conn.execute(sql, params).rowcount

    run(
        "signals",
        "DELETE FROM graph.signal WHERE entity_id = ANY(%s) OR subject_hint ->> 'email_bidx' = %s",
        (entities, email_bidx),
    )
    run("identity_links", "DELETE FROM graph.identity_link WHERE entity_id = ANY(%s)", (entities,))
    run(
        "relationships",
        "DELETE FROM graph.relationship WHERE src_entity_id = ANY(%s) OR dst_entity_id = ANY(%s)",
        (entities, entities),
    )
    run("leads", "DELETE FROM sales.lead WHERE person_entity_id = ANY(%s)", (entities,))
    run(
        "review_items",
        "DELETE FROM graph.match_candidate WHERE record_entity_id = ANY(%s)"
        " OR candidate_entity_id = ANY(%s) OR source_record_id = ANY(%s)",
        (entities, entities, record_ids),
    )
    run("entity_keys", "DELETE FROM graph.entity_key WHERE entity_id = ANY(%s)", (entities,))
    run("source_records", "DELETE FROM ingest.source_record WHERE id = ANY(%s)", (record_ids,))
    run(
        "entities",
        """
        UPDATE graph.entity
           SET status = 'erased', golden = '{}', display_name = NULL, pii_envelope = NULL,
               email_bidx = NULL, phone_bidx = NULL, linkedin_slug = NULL, golden_stale = false
         WHERE id = ANY(%s) AND status = 'active'
        """,
        (entities,),
    )
    run("consents", "DELETE FROM privacy.consent WHERE subject_bidx = %s", (email_bidx,))
    conn.execute(
        """
        INSERT INTO privacy.suppression (identifier_type, identifier_bidx, reason, created_by)
        VALUES ('email', %s, 'erasure', %s) ON CONFLICT DO NOTHING
        """,
        (email_bidx, actor),
    )
    deleted_objects = 0
    if raw_store is not None:
        for record in records:
            if record["raw_uri"]:
                raw_store.delete(record["raw_uri"])
                deleted_objects += 1
    counts["raw_objects"] = deleted_objects
    return counts


def complete_request(
    conn: Connection, request_id: UUID, *, handled_by: str, result: dict[str, Any]
) -> None:
    conn.execute(
        """
        UPDATE privacy.dsar_request
           SET status = 'completed', completed_at = now(), handled_by = %s, result = %s
         WHERE id = %s
        """,
        (handled_by, Jsonb(result), request_id),
    )
