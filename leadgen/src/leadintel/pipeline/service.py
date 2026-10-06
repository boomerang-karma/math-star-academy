"""Pipeline orchestration over the repository: ingest -> resolve -> link -> score.

Each public method is one unit of work (one transaction) and maps to one Lambda
handler / Step Functions state, so a failure retries only that step.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from leadintel.compliance.consent import ConsentRecord
from leadintel.core.ids import stable_uuid
from leadintel.ontology.models import EntityType, FetchBatch, Source, SourceRecord
from leadintel.pipeline.icp import IcpProfile
from leadintel.pipeline.normalize import company_name_key, linkedin_url
from leadintel.pipeline.resolution.blocking import blocking_keys
from leadintel.pipeline.resolution.clustering import resolve
from leadintel.pipeline.resolution.model import ResolvableRecord
from leadintel.pipeline.resolution.survivorship import MemberRecord, survive
from leadintel.pipeline.scoring import score_lead
from leadintel.security.blind_index import BlindIndexer
from leadintel.storage.pipeline_repo import PipelineRepository
from leadintel.storage.raw_store import RawStore

# Sources where the person identified themselves; only these create person-level leads.
SELF_IDENTIFYING_SOURCES = (
    Source.LINKEDIN_LEAD_SYNC.value,
    Source.FIRST_PARTY_WEB.value,
    Source.CRM.value,
    Source.MANUAL.value,
)
SIGNAL_LOOKBACK = timedelta(days=365)


def relationship_stub_id(record_external_id: str, rel_type: str, index: int) -> str:
    return f"{record_external_id}#{rel_type}#{index}"


def expand_relationship_targets(record: SourceRecord) -> list[SourceRecord]:
    """Stub records for relationship targets that carry a strong identifier.

    A LinkedIn profile saying "works at linkedin.com/company/acme" yields a stub
    organization record; resolution then folds it into the real Acme entity (or
    creates it). Name-only targets get no stub - a bare name would spawn
    duplicates - and are linked later only if the name is unambiguous.
    """
    stubs: list[SourceRecord] = []
    for index, rel in enumerate(record.relationships):
        target = rel.target
        if not (target.domain or target.linkedin_slug or target.google_place_id):
            continue
        attributes = {
            "name": target.name,
            "domain": target.domain,
            "linkedin_slug": target.linkedin_slug,
            "linkedin_url": linkedin_url("company", target.linkedin_slug)
            if target.linkedin_slug
            else None,
            "google_place_id": target.google_place_id,
        }
        stubs.append(
            SourceRecord(
                source=record.source,
                external_id=relationship_stub_id(record.external_id, rel.rel_type.value, index),
                entity_type=target.entity_type,
                observed_at=record.observed_at,
                attributes={k: v for k, v in attributes.items() if v},
                lawful_basis=record.lawful_basis,
            )
        )
    return stubs


class PipelineService:
    def __init__(
        self,
        repo: PipelineRepository,
        *,
        raw_store: RawStore,
        bidx: BlindIndexer,
        icp: IcpProfile,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.repo = repo
        self._raw = raw_store
        self._bidx = bidx
        self._icp = icp
        self._clock = clock

    # ------------------------------------------------------------------ ingest

    def ingest(
        self,
        batch: FetchBatch,
        *,
        connector: str,
        playbook: str,
        params: Mapping[str, Any],
        consents: Iterable[ConsentRecord] = (),
    ) -> dict[str, Any]:
        conn = self.repo.conn
        with conn.transaction():
            run_id = self.repo.start_run(connector, playbook, dict(params))
            raw_uris = {
                (payload.source, payload.external_id): self._raw.put(payload, run_id=run_id)
                for payload in batch.raw
            }
            outcomes: Counter[str] = Counter()
            for record in batch.records:
                for item in (record, *expand_relationship_targets(record)):
                    uri = raw_uris.get((item.source, item.external_id))
                    outcomes[self.repo.upsert_source_record(item, run_id=run_id, raw_uri=uri)] += 1
            signals_in = self.repo.insert_signals(batch.signals)
            self.repo.insert_consents(consents)
            status = "partial" if batch.warnings else "succeeded"
            self.repo.finish_run(
                run_id,
                status=status,
                records_in=sum(outcomes.values()),
                signals_in=signals_in,
                credits_used=batch.credits_used,
                error="; ".join(batch.warnings)[:2000] or None,
            )
        return {
            "run_id": str(run_id),
            "records": dict(outcomes),
            "signals": signals_in,
            "warnings": batch.warnings,
        }

    # ------------------------------------------------------------------ resolve

    def resolve_pending(self, *, limit: int = 500) -> dict[str, Any]:
        conn = self.repo.conn
        with conn.transaction():
            rows = self.repo.claim_pending(limit)
            records = [
                ResolvableRecord(
                    record_id=row["id"],
                    entity_type=EntityType(row["entity_type"]),
                    source=Source(row["source"]),
                    observed_at=row["observed_at"],
                    attributes=row["attributes"],
                    email_bidx=row["email_bidx"],
                    phone_bidx=row["phone_bidx"],
                )
                for row in rows
            ]
            keys = {r.record_id: blocking_keys(r, self._bidx) for r in records}
            existing = self.repo.entities_for_keys(set().union(*keys.values()) if keys else set())
            outcome = resolve(records, existing, bidx=self._bidx)

            by_id = {r.record_id: r for r in records}
            for entity_id, members in outcome.created.items():
                self.repo.create_entity(entity_id, by_id[members[0]].entity_type)
            affected: set[UUID] = set()
            vacated: set[UUID] = set()
            for record_id, entity_id in outcome.assignments.items():
                why = outcome.evidence.get(record_id)
                previous = self.repo.assign_member(
                    record_id,
                    entity_id,
                    probability=why.probability if why else 1.0,
                    method=why.method if why else "seed",
                    evidence=[e.as_dict() for e in why.evidence] if why else [],
                )
                self.repo.add_keys(entity_id, keys[record_id])
                affected.add(entity_id)
                if previous is not None:
                    vacated.add(previous)
            for review in outcome.reviews:
                self.repo.add_review(
                    record_id=review.record_id,
                    record_entity_id=outcome.assignments[review.record_id],
                    candidate_entity_id=review.candidate_entity_id,
                    probability=review.result.probability,
                    evidence=[e.as_dict() for e in review.result.evidence],
                )
            self.repo.mark_resolved(list(outcome.assignments))

            affected |= set(self.repo.stale_entities())
            for entity_id in affected | vacated:
                self._recompute_golden(entity_id)
            for entity_id in vacated - affected:
                self.repo.retire_if_empty(entity_id)
            self._link_relationships(rows)
            linked_signals = self._resolve_signals()
            self._ensure_leads(affected)
        return {
            "records": len(records),
            "entities_created": len(outcome.created),
            "entities_touched": len(affected),
            "reviews": len(outcome.reviews),
            "signals_linked": linked_signals,
        }

    def _recompute_golden(self, entity_id: UUID) -> None:
        members = self.repo.members_of(entity_id)
        if not members:
            return
        now = self._clock()
        entity_type = EntityType(members[0]["entity_type"])
        golden = survive(
            entity_id,
            entity_type,
            [
                MemberRecord(m["id"], Source(m["source"]), m["observed_at"], m["attributes"])
                for m in members
            ],
            now=now,
        )
        restricted_members = [
            MemberRecord(
                m["id"],
                Source(m["source"]),
                m["observed_at"],
                self.repo.decrypt_restricted(m["pii_envelope"]),
            )
            for m in members
            if m["pii_envelope"]
        ]
        restricted = None
        if restricted_members:
            survived = survive(entity_id, entity_type, restricted_members, now=now)
            restricted = {name: attr.value for name, attr in survived.attributes.items()}
        self.repo.save_golden(golden, restricted=restricted)

    def _unique_org_by_name(self, name: str | None) -> UUID | None:
        key = company_name_key(name)
        if not key:
            return None
        matches = self.repo.entity_ids_for_key(f"orgname:{key}")
        return matches[0] if len(matches) == 1 else None

    def _link_relationships(self, rows: Iterable[Mapping[str, Any]]) -> None:
        for row in rows:
            relationships = row["relationships"] or []
            if not relationships:
                continue
            src = self.repo.entity_for_record(row["id"])
            if src is None:
                continue
            for index, rel in enumerate(relationships):
                stub_external = relationship_stub_id(row["external_id"], rel["rel_type"], index)
                dst = self.repo.entity_for_record(
                    stable_uuid("source_record", row["source"], stub_external)
                )
                if dst is None:
                    dst = self._unique_org_by_name(rel["target"].get("name"))
                if dst is None or dst == src:
                    continue
                self.repo.upsert_relationship(
                    src=src,
                    dst=dst,
                    rel_type=rel["rel_type"],
                    properties=rel.get("properties") or {},
                    source=row["source"],
                    source_record_id=row["id"],
                    valid_from=rel.get("valid_from"),
                    valid_to=rel.get("valid_to"),
                )

    def _entity_for_hint(self, hint: Mapping[str, Any]) -> UUID | None:
        person = hint.get("entity_type") == EntityType.PERSON.value
        candidates: list[str] = []
        if hint.get("email_bidx"):
            candidates.append(f"email:{hint['email_bidx']}")
        if hint.get("linkedin_slug"):
            slug = hint["linkedin_slug"]
            candidates.append(
                f"li:{self._bidx.index(slug, field='key.li')}" if person else f"li_org:{slug}"
            )
        if hint.get("domain"):
            candidates.append(f"domain:{hint['domain']}")
        if hint.get("google_place_id"):
            candidates.append(f"gplace:{hint['google_place_id']}")
        for key in candidates:
            matches = self.repo.entity_ids_for_key(key)
            if len(matches) == 1:
                return matches[0]
        if hint.get("visitor_id") and (entity := self.repo.entity_for_visitor(hint["visitor_id"])):
            return entity
        if not person:
            return self._unique_org_by_name(hint.get("name"))
        return None

    def _resolve_signals(self) -> int:
        linked = 0
        # Two passes: form submissions (email + visitor id) create identity links that
        # let anonymous visits from the same visitor resolve on the second pass.
        for _ in range(2):
            for signal in self.repo.unresolved_signals():
                hint = signal["subject_hint"]
                entity_id = self._entity_for_hint(hint)
                if entity_id is None:
                    continue
                self.repo.set_signal_entity(signal["id"], entity_id)
                linked += 1
                if hint.get("visitor_id") and hint.get("email_bidx"):
                    self.repo.link_visitor(hint["visitor_id"], entity_id, "form_submission")
        return linked

    def _ensure_leads(self, entity_ids: Iterable[UUID]) -> None:
        for entity_id, entity_type in self.repo.entity_types(entity_ids).items():
            if entity_type is EntityType.ORGANIZATION:
                self.repo.ensure_lead(entity_id, None)
            elif self.repo.has_engaged_member(entity_id, SELF_IDENTIFYING_SOURCES):
                self.repo.ensure_lead(self.repo.employer_of(entity_id), entity_id)

    # ------------------------------------------------------------------ score

    def score(self, *, lead_ids: list[UUID] | None = None) -> int:
        now = self._clock()
        conn = self.repo.conn
        with conn.transaction():
            leads = self.repo.leads_for_scoring(lead_ids)
            for lead in leads:
                org_id, person_id = lead["organization_entity_id"], lead["person_entity_id"]
                org = self.repo.golden_values(org_id) or {}
                person = self.repo.golden_values(person_id)
                related = {e for e in (org_id, person_id) if e is not None}
                if org_id is not None and person_id is None:
                    related.update(self.repo.people_at(org_id))
                signals = self.repo.signals_for(related, since=now - SIGNAL_LOOKBACK)
                result = score_lead(org=org, person=person, signals=signals, icp=self._icp, now=now)
                territory = self.repo.territory_for_country(
                    org.get("hq_country") or (person or {}).get("country")
                )
                self.repo.save_score(lead["id"], result, territory_id=territory, now=now)
        return len(leads)
