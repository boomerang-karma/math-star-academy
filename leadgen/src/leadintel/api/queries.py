"""Read models and writes for the API. Always called inside ``principal_scope`` so RLS applies."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from leadintel.security.audit import AuditEvent
from leadintel.storage.db import Connection

LEAD_SORT_NULL = -1.0


# ---------------------------------------------------------------- users & audit


def user_territories(conn: Connection, subject: str) -> list[str]:
    try:
        UUID(subject)
    except ValueError:
        return []
    row = conn.execute(
        "SELECT territories FROM sales.app_user WHERE id = %s AND active", (subject,)
    ).fetchone()
    return [str(t) for t in row["territories"]] if row else []


def append_audit(conn: Connection, event: AuditEvent) -> None:
    conn.execute(
        """
        INSERT INTO audit.audit_log
            (actor_id, actor_type, action, resource_type, resource_id, outcome, request_id, ip,
                details)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            event.actor_id,
            event.actor_type.value,
            event.action,
            event.resource_type,
            event.resource_id,
            event.outcome.value,
            event.request_id,
            event.ip,
            Jsonb(event.details),
        ),
    )


def list_audit(
    conn: Connection, *, resource_type: str | None, resource_id: str | None, limit: int
) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT seq, occurred_at, actor_id, actor_type, action, resource_type, resource_id,
            outcome, details
          FROM audit.audit_log
         WHERE (%(rt)s::text IS NULL OR resource_type = %(rt)s)
           AND (%(rid)s::text IS NULL OR resource_id = %(rid)s)
         ORDER BY seq DESC LIMIT %(limit)s
        """,
        {"rt": resource_type, "rid": resource_id, "limit": limit},
    ).fetchall()


# ---------------------------------------------------------------- leads


def list_leads(
    conn: Connection,
    *,
    tier: str | None,
    status: str | None,
    hot: bool | None,
    query: str | None,
    limit: int,
    cursor: tuple[float, UUID] | None,
) -> list[dict[str, Any]]:
    """Keyset pagination on (score desc, id) so deep pages stay fast."""
    return conn.execute(
        """
        SELECT id, status, tier, score, fit_score, intent_score, engagement_score, hot, scored_at,
               organization_id, organization_name, organization_domain, industry, hq_country,
               employee_count, person_id, person_name, person_title, last_signal_at
          FROM sales.v_lead_overview
         WHERE (%(tier)s::text IS NULL OR tier = %(tier)s)
           AND (%(status)s::text IS NULL OR status = %(status)s)
           AND (%(hot)s::boolean IS NULL OR hot = %(hot)s)
           AND (%(q)s::text IS NULL OR organization_name ILIKE '%%' || %(q)s || '%%'
                OR organization_domain ILIKE %(q)s || '%%' OR person_name ILIKE '%%' || %(q)s
                  || '%%')
           AND (%(cursor_score)s::numeric IS NULL
                OR (coalesce(score, -1), id) < (%(cursor_score)s, %(cursor_id)s::uuid))
         ORDER BY coalesce(score, -1) DESC, id DESC
         LIMIT %(limit)s
        """,
        {
            "tier": tier,
            "status": status,
            "hot": hot,
            "q": query,
            "limit": limit,
            "cursor_score": cursor[0] if cursor else None,
            "cursor_id": cursor[1] if cursor else None,
        },
    ).fetchall()


def get_lead(conn: Connection, lead_id: UUID) -> dict[str, Any] | None:
    return conn.execute(
        """
        SELECT l.id, l.status, l.tier, l.score, l.fit_score, l.intent_score,
            l.engagement_score, l.hot,
               l.score_explanation, l.scored_at, l.organization_entity_id, l.person_entity_id,
               l.owner_user_id, u.display_name AS owner_name, t.name AS territory,
                   l.created_at, l.updated_at
          FROM sales.lead l
          LEFT JOIN sales.app_user u ON u.id = l.owner_user_id
          LEFT JOIN sales.territory t ON t.id = l.territory_id
         WHERE l.id = %s
        """,
        (lead_id,),
    ).fetchone()


def update_lead(
    conn: Connection,
    lead_id: UUID,
    *,
    status: str | None,
    owner_user_id: UUID | None,
    set_owner: bool,
) -> bool:
    cur = conn.execute(
        """
        UPDATE sales.lead
           SET status = coalesce(%s, status),
               owner_user_id = CASE WHEN %s THEN %s ELSE owner_user_id END
         WHERE id = %s
        """,
        (status, set_owner, owner_user_id, lead_id),
    )
    return cur.rowcount == 1


def score_history(conn: Connection, lead_id: UUID) -> list[dict[str, Any]]:
    return conn.execute(
        "SELECT scored_at, score, tier FROM sales.lead_score_history WHERE lead_id = %s"
        " ORDER BY scored_at DESC LIMIT 30",
        (lead_id,),
    ).fetchall()


# ---------------------------------------------------------------- entities


def get_entity(conn: Connection, entity_id: UUID) -> dict[str, Any] | None:
    return conn.execute(
        """
        SELECT id, entity_type, display_name, golden, pii_envelope, email_bidx, primary_domain,
               linkedin_slug, status, merged_into, created_at, updated_at
          FROM graph.entity WHERE id = %s
        """,
        (entity_id,),
    ).fetchone()


def entity_lineage(conn: Connection, entity_id: UUID) -> list[dict[str, Any]]:
    """Every source record behind an entity and why it was matched: the provenance trail."""
    return conn.execute(
        """
        SELECT sr.id AS record_id, sr.source, sr.external_id, sr.observed_at, sr.fetched_at,
               sr.source_url, sr.lawful_basis, m.method, m.match_probability, m.evidence,
               m.decided_by, m.decided_at
          FROM graph.entity_member m JOIN ingest.source_record sr ON sr.id = m.source_record_id
         WHERE m.entity_id = %s
         ORDER BY sr.observed_at DESC
        """,
        (entity_id,),
    ).fetchall()


def entity_signals(
    conn: Connection, entity_ids: list[UUID], *, days: int = 365, limit: int = 100
) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT id, signal_type, source, occurred_at, title, url, strength, entity_id
          FROM graph.signal
         WHERE entity_id = ANY(%s) AND occurred_at >= %s
         ORDER BY occurred_at DESC LIMIT %s
        """,
        (entity_ids, datetime.now(UTC) - timedelta(days=days), limit),
    ).fetchall()


def neighborhood(
    conn: Connection, entity_ids: list[UUID], *, depth: int = 1
) -> dict[str, list[dict[str, Any]]]:
    """Nodes and edges within ``depth`` hops. Entities the caller cannot see (RLS) drop out."""
    frontier = set(entity_ids)
    seen = set(entity_ids)
    edges: dict[UUID, dict[str, Any]] = {}
    for _ in range(depth):
        if not frontier:
            break
        rows = conn.execute(
            """
            SELECT r.id, r.src_entity_id, r.dst_entity_id, r.rel_type, r.properties, r.source,
                r.confidence
              FROM graph.relationship r
              JOIN graph.entity s ON s.id = r.src_entity_id
              JOIN graph.entity d ON d.id = r.dst_entity_id
             WHERE r.src_entity_id = ANY(%s) OR r.dst_entity_id = ANY(%s)
            """,
            (list(frontier), list(frontier)),
        ).fetchall()
        next_frontier: set[UUID] = set()
        for row in rows:
            edges[row["id"]] = row
            for node in (row["src_entity_id"], row["dst_entity_id"]):
                if node not in seen:
                    seen.add(node)
                    next_frontier.add(node)
        frontier = next_frontier
    nodes = conn.execute(
        "SELECT id, entity_type, display_name, primary_domain FROM graph.entity WHERE id = ANY(%s)",
        (list(seen),),
    ).fetchall()
    return {"nodes": nodes, "edges": list(edges.values())}


def search_entities(conn: Connection, query: str, *, limit: int) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT id, entity_type, display_name, primary_domain,
               extensions.similarity(display_name, %(q)s) AS rank
          FROM graph.entity
         WHERE status = 'active'
           AND (display_name OPERATOR(extensions.%%) %(q)s
                OR display_name ILIKE '%%' || %(q)s || '%%'
                OR primary_domain ILIKE %(q)s || '%%')
         ORDER BY rank DESC NULLS LAST, display_name
         LIMIT %(limit)s
        """,
        {"q": query, "limit": limit},
    ).fetchall()


def consent_status(conn: Connection, subject_bidx: str) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT DISTINCT ON (purpose) purpose, status, lawful_basis, source, captured_at
          FROM privacy.consent WHERE subject_bidx = %s
         ORDER BY purpose, captured_at DESC
        """,
        (subject_bidx,),
    ).fetchall()


def is_suppressed(conn: Connection, identifier_type: str, bidx: str) -> bool:
    row = conn.execute(
        "SELECT EXISTS (SELECT 1 FROM privacy.suppression"
        " WHERE identifier_type = %s AND identifier_bidx = %s)",
        (identifier_type, bidx),
    ).fetchone()
    return bool(row and row["exists"])


# ---------------------------------------------------------------- review queue


def pending_reviews(conn: Connection, *, limit: int) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT mc.id, mc.probability, mc.evidence, mc.created_at,
               mc.record_entity_id, re.display_name AS record_entity_name, re.entity_type,
               mc.candidate_entity_id, ce.display_name AS candidate_entity_name,
               sr.source AS record_source
          FROM graph.match_candidate mc
          JOIN graph.entity re ON re.id = mc.record_entity_id
          JOIN graph.entity ce ON ce.id = mc.candidate_entity_id
          JOIN ingest.source_record sr ON sr.id = mc.source_record_id
         WHERE mc.status = 'pending' AND re.status = 'active' AND ce.status = 'active'
         ORDER BY mc.probability DESC LIMIT %s
        """,
        (limit,),
    ).fetchall()


def get_review(conn: Connection, review_id: UUID) -> dict[str, Any] | None:
    return conn.execute(
        "SELECT id, status, record_entity_id, candidate_entity_id"
        " FROM graph.match_candidate WHERE id = %s",
        (review_id,),
    ).fetchone()


def reject_review(conn: Connection, review_id: UUID, actor: str) -> None:
    conn.execute(
        "UPDATE graph.match_candidate"
        " SET status = 'rejected', reviewed_by = %s, reviewed_at = now() WHERE id = %s",
        (actor, review_id),
    )


def merge_entities(conn: Connection, source: UUID, target: UUID, actor: str) -> None:
    conn.execute("SELECT graph.merge_entities(%s, %s, %s)", (source, target, actor))


# ---------------------------------------------------------------- privacy


def add_suppression(
    conn: Connection, *, identifier_type: str, bidx: str, reason: str, actor: str
) -> bool:
    cur = conn.execute(
        """
        INSERT INTO privacy.suppression (identifier_type, identifier_bidx, reason, created_by)
        VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING
        """,
        (identifier_type, bidx, reason, actor),
    )
    return cur.rowcount == 1


def create_dsar(
    conn: Connection,
    *,
    request_type: str,
    jurisdiction: str,
    subject_bidx: str,
    due_at: datetime,
    actor: str,
) -> dict[str, Any]:
    row = conn.execute(
        """
        INSERT INTO privacy.dsar_request
            (request_type, jurisdiction, subject_email_bidx, due_at, created_by)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id, request_type, jurisdiction, status, received_at, due_at
        """,
        (request_type, jurisdiction, subject_bidx, due_at, actor),
    ).fetchone()
    assert row is not None
    return row


def list_dsars(conn: Connection, *, open_only: bool) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT id, request_type, jurisdiction, status, received_at, due_at, completed_at, result
          FROM privacy.dsar_request
         WHERE NOT %s OR status NOT IN ('completed', 'rejected')
         ORDER BY due_at
        """,
        (open_only,),
    ).fetchall()


def approve_dsar(conn: Connection, dsar_id: UUID, actor: str) -> bool:
    cur = conn.execute(
        "UPDATE privacy.dsar_request SET status = 'in_progress', handled_by = %s"
        " WHERE id = %s AND status IN ('received', 'verifying')",
        (actor, dsar_id),
    )
    return cur.rowcount == 1


# ---------------------------------------------------------------- AI briefs


def cached_brief(conn: Connection, lead_id: UUID) -> dict[str, Any] | None:
    return conn.execute(
        "SELECT model_id, input_hash, brief, generated_at FROM sales.ai_brief WHERE lead_id = %s",
        (lead_id,),
    ).fetchone()


def store_brief(
    conn: Connection,
    lead_id: UUID,
    *,
    model_id: str,
    input_hash: str,
    brief: dict[str, Any],
    actor: str,
) -> None:
    conn.execute(
        """
        INSERT INTO sales.ai_brief (lead_id, model_id, input_hash, brief, generated_by)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (lead_id) DO UPDATE SET
            model_id = EXCLUDED.model_id, input_hash = EXCLUDED.input_hash, brief = EXCLUDED.brief,
            generated_by = EXCLUDED.generated_by, generated_at = now()
        """,
        (lead_id, model_id, input_hash, Jsonb(brief), actor),
    )
