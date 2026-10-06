"""Nightly retention job: enforce ``privacy.retention_policy``.

Bronze-zone objects (``raw_payload``) expire through an S3 lifecycle rule; the
database classes are enforced here. Each statement is bounded by the policy's
window, so the job is idempotent and safe to re-run.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from leadintel.storage.db import Connection

WEB_SIGNAL_TYPES = ["web_visit", "high_intent_page", "content_download"]


def _policies(conn: Connection) -> dict[str, int]:
    rows = conn.execute("SELECT data_class, retain_days FROM privacy.retention_policy").fetchall()
    return {row["data_class"]: int(row["retain_days"]) for row in rows}


def apply_retention(conn: Connection, *, now: datetime) -> dict[str, int]:
    policies = _policies(conn)
    results: dict[str, int] = {}

    def cutoff(data_class: str) -> datetime | None:
        days = policies.get(data_class)
        return now - timedelta(days=days) if days else None

    if (web_cutoff := cutoff("web_event")) is not None:
        results["web_event"] = conn.execute(
            "DELETE FROM graph.signal WHERE signal_type = ANY(%s) AND occurred_at < %s",
            (WEB_SIGNAL_TYPES, web_cutoff),
        ).rowcount
    if (signal_cutoff := cutoff("signal")) is not None:
        results["signal"] = conn.execute(
            "DELETE FROM graph.signal WHERE signal_type <> ALL(%s) AND occurred_at < %s",
            (WEB_SIGNAL_TYPES, signal_cutoff),
        ).rowcount
    if (person_cutoff := cutoff("person_unengaged")) is not None:
        # Scraped people never attached to a lead: drop the records; empty entities follow.
        results["person_unengaged"] = conn.execute(
            """
            DELETE FROM ingest.source_record sr
             WHERE sr.entity_type = 'person' AND sr.fetched_at < %s
               AND sr.source LIKE 'scrapebadger.%%'
               AND NOT EXISTS (
                   SELECT 1 FROM graph.entity_member m
                     JOIN sales.lead l ON l.person_entity_id = m.entity_id
                    WHERE m.source_record_id = sr.id)
            """,
            (person_cutoff,),
        ).rowcount
    if (record_cutoff := cutoff("source_record")) is not None:
        results["source_record"] = conn.execute(
            "DELETE FROM ingest.source_record WHERE entity_type = 'organization' AND"
            " fetched_at < %s",
            (record_cutoff,),
        ).rowcount
    if (lead_cutoff := cutoff("lead_disqualified")) is not None:
        results["lead_disqualified"] = conn.execute(
            "DELETE FROM sales.lead WHERE status = 'disqualified' AND person_entity_id IS NOT NULL"
            " AND updated_at < %s",
            (lead_cutoff,),
        ).rowcount
    # Person entities left without any member record hold no evidence anymore.
    results["orphan_people"] = conn.execute(
        """
        UPDATE graph.entity e
           SET status = 'erased', golden = '{}', display_name = NULL, pii_envelope = NULL,
               email_bidx = NULL, phone_bidx = NULL, linkedin_slug = NULL
         WHERE e.entity_type = 'person' AND e.status = 'active'
           AND NOT EXISTS (SELECT 1 FROM graph.entity_member m WHERE m.entity_id = e.id)
           AND NOT EXISTS (SELECT 1 FROM sales.lead l WHERE l.person_entity_id = e.id)
        """
    ).rowcount
    return results
