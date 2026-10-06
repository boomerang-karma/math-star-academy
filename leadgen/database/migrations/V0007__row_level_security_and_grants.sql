-- Least-privilege grants and row-level security.
--
-- leadintel_app (the API) can read the graph, but:
--   * leads are filtered to the caller's territories/ownership unless app.scope = 'global';
--   * person entities are visible only through a lead the caller can see;
--   * writes are limited to specific columns, and merges go through a checked function.
-- leadintel_pipeline gets explicit allow-all policies; it never serves end users.

GRANT USAGE ON SCHEMA app, ingest, graph, sales, privacy, audit TO leadintel_app, leadintel_pipeline;

-- ---------------------------------------------------------------- pipeline (workers)
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA ingest, graph, sales
    TO leadintel_pipeline;
GRANT SELECT, INSERT, UPDATE, DELETE ON privacy.consent TO leadintel_pipeline;
GRANT SELECT ON privacy.suppression, privacy.retention_policy, privacy.dsar_request
    TO leadintel_pipeline;
GRANT INSERT ON privacy.suppression TO leadintel_pipeline;  -- DSAR erasure adds a suppression
GRANT UPDATE (status, completed_at, handled_by, result) ON privacy.dsar_request TO leadintel_pipeline;
GRANT SELECT, INSERT ON audit.audit_log TO leadintel_pipeline;

-- ---------------------------------------------------------------- app (API)
GRANT SELECT ON ALL TABLES IN SCHEMA ingest, graph, sales TO leadintel_app;
GRANT UPDATE (status, owner_user_id) ON sales.lead TO leadintel_app;
GRANT INSERT, UPDATE ON sales.ai_brief TO leadintel_app;
GRANT INSERT, UPDATE ON sales.app_user TO leadintel_app;
GRANT UPDATE (status, reviewed_by, reviewed_at) ON graph.match_candidate TO leadintel_app;
GRANT SELECT ON privacy.consent, privacy.suppression, privacy.retention_policy, privacy.dsar_request
    TO leadintel_app;
GRANT INSERT ON privacy.suppression, privacy.dsar_request TO leadintel_app;
GRANT UPDATE (status, handled_by) ON privacy.dsar_request TO leadintel_app;
GRANT SELECT, INSERT ON audit.audit_log TO leadintel_app;

-- ---------------------------------------------------------------- RLS: leads
ALTER TABLE sales.lead ENABLE ROW LEVEL SECURITY;

CREATE POLICY lead_pipeline_all ON sales.lead TO leadintel_pipeline
    USING (true) WITH CHECK (true);

CREATE POLICY lead_app_select ON sales.lead FOR SELECT TO leadintel_app
    USING (
        app.current_scope() = 'global'
        OR (app.current_scope() = 'territory'
            AND (territory_id = ANY (app.current_territories())
                 OR owner_user_id = app.current_user_id()))
    );

CREATE POLICY lead_app_update ON sales.lead FOR UPDATE TO leadintel_app
    USING (
        app.current_scope() = 'global'
        OR (app.current_scope() = 'territory'
            AND (territory_id = ANY (app.current_territories())
                 OR owner_user_id = app.current_user_id()))
    )
    WITH CHECK (
        app.current_scope() = 'global'
        OR (app.current_scope() = 'territory'
            AND (territory_id = ANY (app.current_territories())
                 OR owner_user_id = app.current_user_id()))
    );

-- ---------------------------------------------------------------- RLS: entities
ALTER TABLE graph.entity ENABLE ROW LEVEL SECURITY;

CREATE POLICY entity_pipeline_all ON graph.entity TO leadintel_pipeline
    USING (true) WITH CHECK (true);

-- Organizations are business data; people are visible only via a visible lead.
-- The EXISTS subquery is itself filtered by lead_app_select.
CREATE POLICY entity_app_select ON graph.entity FOR SELECT TO leadintel_app
    USING (
        app.current_scope() = 'global'
        OR (app.current_scope() = 'territory'
            AND (entity_type = 'organization'
                 OR EXISTS (SELECT 1 FROM sales.lead l WHERE l.person_entity_id = entity.id)))
    );

-- ---------------------------------------------------------------- RLS: source records
-- Raw person records carry the same personal data as person entities.
ALTER TABLE ingest.source_record ENABLE ROW LEVEL SECURITY;

CREATE POLICY source_record_pipeline_all ON ingest.source_record TO leadintel_pipeline
    USING (true) WITH CHECK (true);

CREATE POLICY source_record_app_select ON ingest.source_record FOR SELECT TO leadintel_app
    USING (
        app.current_scope() = 'global'
        OR (app.current_scope() = 'territory'
            AND (entity_type = 'organization'
                 OR EXISTS (SELECT 1 FROM graph.entity_member m
                            JOIN sales.lead l ON l.person_entity_id = m.entity_id
                            WHERE m.source_record_id = source_record.id)))
    );

-- ---------------------------------------------------------------- merges
-- The only way the API can restructure the graph. Validates, re-points every reference,
-- and flags the survivor for golden-record recomputation by the resolver.
CREATE FUNCTION graph.merge_entities(p_source uuid, p_target uuid, p_actor text) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, graph, sales AS
$$
DECLARE
    s graph.entity;
    t graph.entity;
BEGIN
    IF p_source = p_target THEN
        RAISE EXCEPTION 'cannot merge an entity into itself';
    END IF;
    SELECT * INTO s FROM graph.entity WHERE id = p_source FOR UPDATE;
    SELECT * INTO t FROM graph.entity WHERE id = p_target FOR UPDATE;
    IF s.id IS NULL OR t.id IS NULL THEN
        RAISE EXCEPTION 'entity not found';
    END IF;
    IF s.status <> 'active' OR t.status <> 'active' THEN
        RAISE EXCEPTION 'only active entities can be merged';
    END IF;
    IF s.entity_type <> t.entity_type THEN
        RAISE EXCEPTION 'cannot merge a % into a %', s.entity_type, t.entity_type;
    END IF;

    UPDATE graph.entity_member
       SET entity_id = p_target, method = 'manual', decided_by = p_actor, decided_at = now()
     WHERE entity_id = p_source;

    INSERT INTO graph.entity_key (key, entity_id)
        SELECT key, p_target FROM graph.entity_key WHERE entity_id = p_source
        ON CONFLICT DO NOTHING;
    DELETE FROM graph.entity_key WHERE entity_id = p_source;

    -- Relationships: drop edges that would become self-loops or duplicates, then re-point.
    DELETE FROM graph.relationship
     WHERE (src_entity_id = p_source AND dst_entity_id = p_target)
        OR (src_entity_id = p_target AND dst_entity_id = p_source);
    DELETE FROM graph.relationship r
     WHERE r.src_entity_id = p_source
       AND EXISTS (SELECT 1 FROM graph.relationship x
                    WHERE x.src_entity_id = p_target AND x.dst_entity_id = r.dst_entity_id
                      AND x.rel_type = r.rel_type AND x.source = r.source);
    UPDATE graph.relationship SET src_entity_id = p_target WHERE src_entity_id = p_source;
    DELETE FROM graph.relationship r
     WHERE r.dst_entity_id = p_source
       AND EXISTS (SELECT 1 FROM graph.relationship x
                    WHERE x.dst_entity_id = p_target AND x.src_entity_id = r.src_entity_id
                      AND x.rel_type = r.rel_type AND x.source = r.source);
    UPDATE graph.relationship SET dst_entity_id = p_target WHERE dst_entity_id = p_source;

    UPDATE graph.signal SET entity_id = p_target WHERE entity_id = p_source;

    DELETE FROM graph.identity_link il
     WHERE il.entity_id = p_source
       AND EXISTS (SELECT 1 FROM graph.identity_link x
                    WHERE x.entity_id = p_target AND x.visitor_id = il.visitor_id);
    UPDATE graph.identity_link SET entity_id = p_target WHERE entity_id = p_source;

    -- Leads: re-point unless the survivor already has the equivalent lead.
    DELETE FROM sales.lead l
     WHERE (l.organization_entity_id = p_source AND EXISTS (
                SELECT 1 FROM sales.lead x WHERE x.organization_entity_id = p_target
                   AND x.person_entity_id IS NOT DISTINCT FROM l.person_entity_id))
        OR (l.person_entity_id = p_source AND EXISTS (
                SELECT 1 FROM sales.lead x WHERE x.person_entity_id = p_target
                   AND x.organization_entity_id IS NOT DISTINCT FROM l.organization_entity_id));
    UPDATE sales.lead SET organization_entity_id = p_target WHERE organization_entity_id = p_source;
    UPDATE sales.lead SET person_entity_id = p_target WHERE person_entity_id = p_source;

    UPDATE graph.match_candidate
       SET status = 'accepted', reviewed_by = p_actor, reviewed_at = now()
     WHERE status = 'pending' AND record_entity_id = p_source AND candidate_entity_id = p_target;
    DELETE FROM graph.match_candidate
     WHERE status = 'pending' AND (record_entity_id = p_source OR candidate_entity_id = p_source);

    UPDATE graph.entity SET status = 'merged', merged_into = p_target WHERE id = p_source;
    UPDATE graph.entity SET golden_stale = true WHERE id = p_target;
END
$$;

REVOKE ALL ON FUNCTION graph.merge_entities(uuid, uuid, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION graph.merge_entities(uuid, uuid, text) TO leadintel_app, leadintel_pipeline;
REVOKE ALL ON FUNCTION audit.chain_before_insert() FROM PUBLIC;
