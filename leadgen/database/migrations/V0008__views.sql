-- Read models.
--
-- v_lead_overview runs with the caller's privileges (security_invoker), so RLS on
-- sales.lead and graph.entity applies exactly as it does to the base tables.
-- v_lead_bi is for the readonly/BI role: no person names, no contact data.

CREATE VIEW sales.v_lead_overview WITH (security_invoker = true, security_barrier = true) AS
SELECT
    l.id,
    l.status,
    l.tier,
    l.score,
    l.fit_score,
    l.intent_score,
    l.engagement_score,
    l.hot,
    l.scored_at,
    l.territory_id,
    l.owner_user_id,
    l.updated_at,
    o.id                                        AS organization_id,
    o.display_name                              AS organization_name,
    o.primary_domain                            AS organization_domain,
    o.golden -> 'industry' ->> 'value'          AS industry,
    o.golden -> 'hq_country' ->> 'value'        AS hq_country,
    (o.golden -> 'employee_count' ->> 'value')::integer AS employee_count,
    p.id                                        AS person_id,
    p.display_name                              AS person_name,
    p.golden -> 'title' ->> 'value'             AS person_title,
    (SELECT max(s.occurred_at) FROM graph.signal s
      WHERE s.entity_id = o.id OR s.entity_id = p.id) AS last_signal_at
FROM sales.lead l
LEFT JOIN graph.entity o ON o.id = l.organization_entity_id
LEFT JOIN graph.entity p ON p.id = l.person_entity_id;

GRANT SELECT ON sales.v_lead_overview TO leadintel_app, leadintel_pipeline;

CREATE VIEW sales.v_lead_bi WITH (security_barrier = true) AS
SELECT
    l.id,
    l.status,
    l.tier,
    l.score,
    l.fit_score,
    l.intent_score,
    l.engagement_score,
    l.scored_at,
    t.name                                   AS territory,
    o.display_name                           AS organization_name,
    o.primary_domain                         AS organization_domain,
    o.golden -> 'industry' ->> 'value'       AS industry,
    o.golden -> 'hq_country' ->> 'value'     AS hq_country,
    (l.person_entity_id IS NOT NULL)         AS has_contact
FROM sales.lead l
LEFT JOIN graph.entity o ON o.id = l.organization_entity_id
LEFT JOIN sales.territory t ON t.id = l.territory_id;

GRANT USAGE ON SCHEMA sales TO leadintel_readonly;
GRANT SELECT ON sales.v_lead_bi TO leadintel_readonly;
