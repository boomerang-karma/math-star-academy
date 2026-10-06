"""Pipeline-side persistence. Runs as ``leadintel_pipeline`` (cross-territory writes).

Restricted attributes are encrypted (envelope) and blind-indexed here, at the
last moment before they touch the database. Suppressed identifiers are dropped
before anything is written.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from leadintel.compliance.consent import ConsentRecord
from leadintel.ontology.models import EntityType, GoldenRecord, Signal, SignalType, SourceRecord
from leadintel.pipeline.normalize import company_domain
from leadintel.pipeline.resolution.model import EntitySnapshot
from leadintel.pipeline.scoring import LeadScore, SignalView
from leadintel.security.blind_index import BlindIndexer
from leadintel.security.crypto import FieldCipher
from leadintel.storage.db import Connection

NIL = "00000000-0000-0000-0000-000000000000"


class PipelineRepository:
    def __init__(self, conn: Connection, *, cipher: FieldCipher, bidx: BlindIndexer) -> None:
        self.conn = conn
        self._cipher = cipher
        self._bidx = bidx

    # ------------------------------------------------------------------ runs

    def start_run(self, connector: str, playbook: str, params: dict[str, Any]) -> UUID:
        row = self.conn.execute(
            "INSERT INTO ingest.connector_run (connector, playbook, params) VALUES (%s, %s,"
            " %s) RETURNING id",
            (connector, playbook, Jsonb(params)),
        ).fetchone()
        assert row is not None
        return UUID(str(row["id"]))

    def finish_run(
        self,
        run_id: UUID,
        *,
        status: str,
        records_in: int,
        signals_in: int,
        credits_used: int,
        error: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            UPDATE ingest.connector_run
               SET status = %s, finished_at = now(), records_in = %s, signals_in = %s,
                   credits_used = %s, error = %s
             WHERE id = %s
            """,
            (status, records_in, signals_in, credits_used, error, run_id),
        )

    # ------------------------------------------------------------------ privacy

    def _identifiers(self, record: SourceRecord) -> list[tuple[str, str]]:
        ids: list[tuple[str, str]] = []
        for kind in ("email", "phone"):
            if value := record.restricted.get(kind):
                ids.append((kind, self._bidx.index(value, field=kind)))
        domain = company_domain(
            record.attributes.get("domain") or record.attributes.get("company_domain")
        )
        if domain:
            ids.append(("domain", self._bidx.index(domain, field="domain")))
        if slug := record.attributes.get("linkedin_slug"):
            ids.append(("linkedin_slug", self._bidx.index(slug, field="linkedin_slug")))
        return ids

    def is_suppressed(self, record: SourceRecord) -> bool:
        ids = self._identifiers(record)
        if not ids:
            return False
        row = self.conn.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM privacy.suppression s
                JOIN unnest(%s::text[], %s::text[]) AS i(kind, bidx)
                  ON s.identifier_type = i.kind AND s.identifier_bidx = i.bidx)
            """,
            ([k for k, _ in ids], [b for _, b in ids]),
        ).fetchone()
        return bool(row and row["exists"])

    # ------------------------------------------------------------------ ingest

    def upsert_source_record(
        self, record: SourceRecord, *, run_id: UUID | None, raw_uri: str | None
    ) -> str:
        if self.is_suppressed(record):
            return "suppressed"
        envelope = self._cipher.encrypt_json(record.restricted) if record.restricted else None
        row = self.conn.execute(
            """
            INSERT INTO ingest.source_record AS sr
                (id, source, external_id, entity_type, run_id, observed_at, attributes,
                    relationships,
                 pii_envelope, email_bidx, phone_bidx, content_hash, lawful_basis, source_url,
                     raw_uri)
            VALUES (%(id)s, %(source)s, %(external_id)s, %(entity_type)s, %(run_id)s,
                %(observed_at)s,
                    %(attributes)s, %(relationships)s, %(envelope)s, %(email_bidx)s, %(phone_bidx)s,
                    %(hash)s, %(basis)s, %(url)s, %(raw)s)
            ON CONFLICT (source, external_id) DO UPDATE SET
                run_id = EXCLUDED.run_id,
                observed_at = EXCLUDED.observed_at,
                fetched_at = now(),
                attributes = EXCLUDED.attributes,
                relationships = EXCLUDED.relationships,
                pii_envelope = EXCLUDED.pii_envelope,
                email_bidx = EXCLUDED.email_bidx,
                phone_bidx = EXCLUDED.phone_bidx,
                content_hash = EXCLUDED.content_hash,
                lawful_basis = EXCLUDED.lawful_basis,
                source_url = coalesce(EXCLUDED.source_url, sr.source_url),
                raw_uri = coalesce(EXCLUDED.raw_uri, sr.raw_uri),
                resolution_state = CASE WHEN sr.content_hash IS DISTINCT FROM EXCLUDED.content_hash
                                        THEN 'pending' ELSE sr.resolution_state END
            RETURNING (xmax = 0) AS inserted,
                      (resolution_state = 'pending') AS pending
            """,
            {
                "id": record.id,
                "source": record.source.value,
                "external_id": record.external_id,
                "entity_type": record.entity_type.value,
                "run_id": run_id,
                "observed_at": record.observed_at,
                "attributes": Jsonb(record.attributes),
                "relationships": Jsonb([r.model_dump(mode="json") for r in record.relationships]),
                "envelope": envelope,
                "email_bidx": self._bidx.maybe_index(record.restricted.get("email"), field="email"),
                "phone_bidx": self._bidx.maybe_index(record.restricted.get("phone"), field="phone"),
                "hash": record.content_hash(),
                "basis": record.lawful_basis.value,
                "url": record.source_url,
                "raw": raw_uri,
            },
        ).fetchone()
        assert row is not None
        with self.conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO graph.attribute_assertion (source_record_id, attribute, value,
                    observed_at)
                VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING
                """,
                [
                    (record.id, k, Jsonb(v), record.observed_at)
                    for k, v in record.attributes.items()
                ],
            )
        if row["inserted"]:
            return "inserted"
        return "updated" if row["pending"] else "unchanged"

    def insert_signals(self, signals: Iterable[Signal]) -> int:
        inserted = 0
        for signal in signals:
            cur = self.conn.execute(
                """
                INSERT INTO graph.signal
                    (id, signal_type, source, occurred_at, title, url, strength, subject_hint,
                        attributes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    signal.id,
                    signal.signal_type.value,
                    signal.source.value,
                    signal.occurred_at,
                    signal.title,
                    signal.url,
                    signal.strength,
                    Jsonb(signal.subject.model_dump(mode="json", exclude_none=True)),
                    Jsonb(signal.attributes),
                ),
            )
            inserted += cur.rowcount
        return inserted

    def insert_consents(self, consents: Iterable[ConsentRecord]) -> int:
        count = 0
        for consent in consents:
            self.conn.execute(
                """
                INSERT INTO privacy.consent
                    (subject_bidx, purpose, status, lawful_basis, source, evidence, captured_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    consent.subject_bidx,
                    consent.purpose.value,
                    consent.status.value,
                    consent.lawful_basis.value,
                    consent.source,
                    Jsonb(consent.evidence),
                    consent.captured_at,
                ),
            )
            count += 1
        return count

    # ------------------------------------------------------------------ resolution

    def claim_pending(self, limit: int) -> list[dict[str, Any]]:
        """Lock a batch of pending records; concurrent workers skip each other's rows."""
        return self.conn.execute(
            """
            SELECT id, source, external_id, entity_type, observed_at, attributes, relationships,
                   email_bidx, phone_bidx, lawful_basis
              FROM ingest.source_record
             WHERE resolution_state = 'pending'
             ORDER BY fetched_at
             LIMIT %s
             FOR UPDATE SKIP LOCKED
            """,
            (limit,),
        ).fetchall()

    def entities_for_keys(self, keys: Iterable[str]) -> list[EntitySnapshot]:
        keys = list(keys)
        if not keys:
            return []
        rows = self.conn.execute(
            """
            SELECT DISTINCT e.id, e.entity_type, e.golden, e.email_bidx, e.phone_bidx
              FROM graph.entity_key k JOIN graph.entity e ON e.id = k.entity_id
             WHERE k.key = ANY(%s) AND e.status = 'active'
            """,
            (keys,),
        ).fetchall()
        return [
            EntitySnapshot(
                entity_id=row["id"],
                entity_type=EntityType(row["entity_type"]),
                attributes={k: v.get("value") for k, v in (row["golden"] or {}).items()},
                email_bidx=row["email_bidx"],
                phone_bidx=row["phone_bidx"],
            )
            for row in rows
        ]

    def entity_ids_for_key(self, key: str) -> list[UUID]:
        rows = self.conn.execute(
            """
            SELECT k.entity_id FROM graph.entity_key k JOIN graph.entity e ON e.id = k.entity_id
             WHERE k.key = %s AND e.status = 'active'
            """,
            (key,),
        ).fetchall()
        return [row["entity_id"] for row in rows]

    def create_entity(self, entity_id: UUID, entity_type: EntityType) -> None:
        self.conn.execute(
            "INSERT INTO graph.entity (id, entity_type) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (entity_id, entity_type.value),
        )

    def assign_member(
        self,
        record_id: UUID,
        entity_id: UUID,
        *,
        probability: float,
        method: str,
        evidence: list[dict[str, Any]],
    ) -> UUID | None:
        """Attach a record; returns the entity it previously belonged to, if it moved."""
        previous = self.conn.execute(
            "SELECT entity_id FROM graph.entity_member WHERE source_record_id = %s", (record_id,)
        ).fetchone()
        self.conn.execute(
            """
            INSERT INTO graph.entity_member
                (source_record_id, entity_id, match_probability, method, evidence)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (source_record_id) DO UPDATE SET
                entity_id = EXCLUDED.entity_id, match_probability = EXCLUDED.match_probability,
                method = EXCLUDED.method, evidence = EXCLUDED.evidence, decided_at = now()
            """,
            (record_id, entity_id, probability, method, Jsonb(evidence)),
        )
        if previous and previous["entity_id"] != entity_id:
            return UUID(str(previous["entity_id"]))
        return None

    def add_keys(self, entity_id: UUID, keys: Iterable[str]) -> None:
        with self.conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO graph.entity_key (key, entity_id) VALUES (%s, %s)"
                " ON CONFLICT DO NOTHING",
                [(key, entity_id) for key in keys],
            )

    def mark_resolved(self, record_ids: Sequence[UUID]) -> None:
        self.conn.execute(
            "UPDATE ingest.source_record SET resolution_state = 'resolved' WHERE id = ANY(%s)",
            (list(record_ids),),
        )

    def add_review(
        self,
        *,
        record_id: UUID,
        record_entity_id: UUID,
        candidate_entity_id: UUID,
        probability: float,
        evidence: list[dict[str, Any]],
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO graph.match_candidate
                (source_record_id, record_entity_id, candidate_entity_id, probability, evidence)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (source_record_id, candidate_entity_id) DO NOTHING
            """,
            (record_id, record_entity_id, candidate_entity_id, probability, Jsonb(evidence)),
        )

    def members_of(self, entity_id: UUID) -> list[dict[str, Any]]:
        return self.conn.execute(
            """
            SELECT sr.id, sr.source, sr.observed_at, sr.attributes, sr.pii_envelope, sr.entity_type
              FROM graph.entity_member m JOIN ingest.source_record sr ON sr.id = m.source_record_id
             WHERE m.entity_id = %s
            """,
            (entity_id,),
        ).fetchall()

    def decrypt_restricted(self, envelope: bytes) -> dict[str, Any]:
        return self._cipher.decrypt_json(envelope)

    def save_golden(self, golden: GoldenRecord, *, restricted: dict[str, Any] | None) -> None:
        email = (restricted or {}).get("email")
        phone = (restricted or {}).get("phone")
        self.conn.execute(
            """
            UPDATE graph.entity
               SET golden = %s, display_name = %s, primary_domain = %s, linkedin_slug = %s,
                   pii_envelope = %s, email_bidx = %s, phone_bidx = %s, golden_stale = false
             WHERE id = %s
            """,
            (
                Jsonb(golden.model_dump(mode="json")["attributes"]),
                golden.display_name,
                golden.value("domain") if golden.entity_type is EntityType.ORGANIZATION else None,
                golden.value("linkedin_slug"),
                self._cipher.encrypt_json(restricted) if restricted else None,
                self._bidx.maybe_index(email, field="email"),
                self._bidx.maybe_index(phone, field="phone"),
                golden.entity_id,
            ),
        )

    def stale_entities(self, limit: int = 500) -> list[UUID]:
        rows = self.conn.execute(
            "SELECT id FROM graph.entity WHERE golden_stale AND status = 'active' LIMIT %s",
            (limit,),
        ).fetchall()
        return [row["id"] for row in rows]

    def retire_if_empty(self, entity_id: UUID) -> None:
        """Drop an entity whose last member moved away during re-resolution."""
        self.conn.execute(
            """
            DELETE FROM graph.entity e
             WHERE e.id = %s
               AND NOT EXISTS (SELECT 1 FROM graph.entity_member m WHERE m.entity_id = e.id)
               AND NOT EXISTS (SELECT 1 FROM sales.lead l
                                WHERE l.organization_entity_id = e.id OR l.person_entity_id = e.id)
            """,
            (entity_id,),
        )

    def entity_for_record(self, record_id: UUID) -> UUID | None:
        row = self.conn.execute(
            "SELECT entity_id FROM graph.entity_member WHERE source_record_id = %s", (record_id,)
        ).fetchone()
        return row["entity_id"] if row else None

    def upsert_relationship(
        self,
        *,
        src: UUID,
        dst: UUID,
        rel_type: str,
        properties: dict[str, Any],
        source: str,
        source_record_id: UUID,
        valid_from: datetime | None,
        valid_to: datetime | None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO graph.relationship
                (src_entity_id, dst_entity_id, rel_type, properties, source, source_record_id,
                 valid_from, valid_to)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (src_entity_id, dst_entity_id, rel_type, source) DO UPDATE
                SET properties = EXCLUDED.properties, valid_from = EXCLUDED.valid_from,
                    valid_to = EXCLUDED.valid_to
            """,
            (src, dst, rel_type, Jsonb(properties), source, source_record_id, valid_from, valid_to),
        )

    def unresolved_signals(self, limit: int = 5_000) -> list[dict[str, Any]]:
        return self.conn.execute(
            """
            SELECT id, subject_hint FROM graph.signal
             WHERE entity_id IS NULL
             ORDER BY (subject_hint ? 'email_bidx') DESC, occurred_at
             LIMIT %s
            """,
            (limit,),
        ).fetchall()

    def set_signal_entity(self, signal_id: UUID, entity_id: UUID) -> None:
        self.conn.execute(
            "UPDATE graph.signal SET entity_id = %s WHERE id = %s", (entity_id, signal_id)
        )

    def link_visitor(self, visitor_id: str, entity_id: UUID, method: str) -> None:
        self.conn.execute(
            """
            INSERT INTO graph.identity_link (visitor_id, entity_id, method) VALUES (%s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (visitor_id, entity_id, method),
        )

    def entity_for_visitor(self, visitor_id: str) -> UUID | None:
        rows = self.conn.execute(
            "SELECT entity_id FROM graph.identity_link WHERE visitor_id = %s", (visitor_id,)
        ).fetchall()
        return rows[0]["entity_id"] if len(rows) == 1 else None

    def entity_types(self, entity_ids: Iterable[UUID]) -> dict[UUID, EntityType]:
        rows = self.conn.execute(
            "SELECT id, entity_type FROM graph.entity WHERE id = ANY(%s) AND status = 'active'",
            (list(entity_ids),),
        ).fetchall()
        return {row["id"]: EntityType(row["entity_type"]) for row in rows}

    def employer_of(self, person_id: UUID) -> UUID | None:
        row = self.conn.execute(
            """
            SELECT dst_entity_id FROM graph.relationship
             WHERE src_entity_id = %s AND rel_type = 'works_at'
             ORDER BY confidence DESC, created_at DESC LIMIT 1
            """,
            (person_id,),
        ).fetchone()
        return row["dst_entity_id"] if row else None

    def people_at(self, org_id: UUID) -> list[UUID]:
        rows = self.conn.execute(
            "SELECT src_entity_id FROM graph.relationship"
            " WHERE dst_entity_id = %s AND rel_type = 'works_at'",
            (org_id,),
        ).fetchall()
        return [row["src_entity_id"] for row in rows]

    def has_engaged_member(self, person_id: UUID, sources: Sequence[str]) -> bool:
        row = self.conn.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM graph.entity_member m
                  JOIN ingest.source_record sr ON sr.id = m.source_record_id
                 WHERE m.entity_id = %s AND sr.source = ANY(%s))
            """,
            (person_id, list(sources)),
        ).fetchone()
        return bool(row and row["exists"])

    # ------------------------------------------------------------------ leads

    def ensure_lead(self, org_id: UUID | None, person_id: UUID | None) -> None:
        self.conn.execute(
            f"""
            INSERT INTO sales.lead (organization_entity_id, person_entity_id) VALUES (%s, %s)
            ON CONFLICT ((coalesce(organization_entity_id, '{NIL}'::uuid)),
                         (coalesce(person_entity_id, '{NIL}'::uuid))) DO NOTHING
            """,  # noqa: S608 - NIL is a module constant, not input
            (org_id, person_id),
        )

    def leads_for_scoring(self, lead_ids: Sequence[UUID] | None = None) -> list[dict[str, Any]]:
        if lead_ids is None:
            return self.conn.execute(
                "SELECT id, organization_entity_id, person_entity_id FROM sales.lead"
                " WHERE status NOT IN ('converted', 'disqualified')"
            ).fetchall()
        return self.conn.execute(
            "SELECT id, organization_entity_id, person_entity_id FROM sales.lead"
            " WHERE id = ANY(%s)",
            (list(lead_ids),),
        ).fetchall()

    def golden_values(self, entity_id: UUID | None) -> dict[str, Any] | None:
        if entity_id is None:
            return None
        row = self.conn.execute(
            "SELECT golden FROM graph.entity WHERE id = %s", (entity_id,)
        ).fetchone()
        if row is None:
            return None
        return {k: v.get("value") for k, v in (row["golden"] or {}).items()}

    def signals_for(self, entity_ids: Iterable[UUID], *, since: datetime) -> list[SignalView]:
        rows = self.conn.execute(
            """
            SELECT signal_type, occurred_at, strength, title FROM graph.signal
             WHERE entity_id = ANY(%s) AND occurred_at >= %s
            """,
            (list(entity_ids), since),
        ).fetchall()
        return [
            SignalView(
                SignalType(r["signal_type"]), r["occurred_at"], float(r["strength"]), r["title"]
            )
            for r in rows
        ]

    def territory_for_country(self, country: str | None) -> UUID | None:
        if not country:
            return None
        row = self.conn.execute(
            "SELECT id FROM sales.territory WHERE %s = ANY(countries) ORDER BY name LIMIT 1",
            (country.upper(),),
        ).fetchone()
        return row["id"] if row else None

    def save_score(
        self, lead_id: UUID, score: LeadScore, *, territory_id: UUID | None, now: datetime
    ) -> None:
        explanation = Jsonb([c.as_dict() for c in score.contributions])
        self.conn.execute(
            """
            UPDATE sales.lead
               SET score = %s, tier = %s, fit_score = %s, intent_score = %s, engagement_score = %s,
                   hot = %s, score_explanation = %s, scored_at = %s,
                   territory_id = coalesce(territory_id, %s)
             WHERE id = %s
            """,
            (
                score.total,
                score.tier,
                score.fit,
                score.intent,
                score.engagement,
                score.hot,
                explanation,
                now,
                territory_id,
                lead_id,
            ),
        )
        self.conn.execute(
            """
            INSERT INTO sales.lead_score_history (lead_id, scored_at, score, tier, components)
            VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
            """,
            (
                lead_id,
                now,
                score.total,
                score.tier,
                Jsonb({"fit": score.fit, "intent": score.intent, "engagement": score.engagement}),
            ),
        )
