-- The entity graph: resolved entities, their member source records, blocking keys,
-- per-attribute assertion history, typed relationships, signals and the review queue.

CREATE TABLE graph.entity (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type     text NOT NULL CHECK (entity_type IN ('person', 'organization')),
    display_name    text,
    golden          jsonb NOT NULL DEFAULT '{}',   -- survivorship output with provenance
    pii_envelope    bytea,                         -- survived restricted attributes (KMS envelope)
    email_bidx      text,
    phone_bidx      text,
    primary_domain  text,
    linkedin_slug   text,
    status          text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'merged', 'erased')),
    merged_into     uuid REFERENCES graph.entity (id),
    golden_stale    boolean NOT NULL DEFAULT false, -- set by merges; the resolver recomputes
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CHECK ((status = 'merged') = (merged_into IS NOT NULL))
);
CREATE INDEX entity_name_trgm_idx ON graph.entity USING gin (display_name extensions.gin_trgm_ops)
    WHERE status = 'active';
CREATE INDEX entity_domain_idx ON graph.entity (primary_domain) WHERE status = 'active';
CREATE INDEX entity_email_bidx_idx ON graph.entity (email_bidx) WHERE email_bidx IS NOT NULL;
CREATE INDEX entity_stale_idx ON graph.entity (id) WHERE golden_stale;
CREATE TRIGGER entity_touch BEFORE UPDATE ON graph.entity
    FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at();

-- Which source records make up an entity, and why the resolver put them there.
CREATE TABLE graph.entity_member (
    source_record_id  uuid PRIMARY KEY REFERENCES ingest.source_record (id) ON DELETE CASCADE,
    entity_id         uuid NOT NULL REFERENCES graph.entity (id),
    match_probability numeric(5, 4) NOT NULL CHECK (match_probability BETWEEN 0 AND 1),
    method            text NOT NULL CHECK (method IN ('seed', 'deterministic', 'probabilistic', 'manual')),
    evidence          jsonb NOT NULL DEFAULT '[]',
    decided_by        text NOT NULL DEFAULT 'system',
    decided_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX entity_member_entity_idx ON graph.entity_member (entity_id);

-- Blocking keys (e.g. 'domain:acme.com', 'li:acme', 'email:<bidx>') for incremental resolution.
CREATE TABLE graph.entity_key (
    key        text NOT NULL,
    entity_id  uuid NOT NULL REFERENCES graph.entity (id) ON DELETE CASCADE,
    PRIMARY KEY (key, entity_id)
);
CREATE INDEX entity_key_entity_idx ON graph.entity_key (entity_id);

-- Every non-restricted value any source asserted: provenance drill-down and time travel.
CREATE TABLE graph.attribute_assertion (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_record_id  uuid NOT NULL REFERENCES ingest.source_record (id) ON DELETE CASCADE,
    attribute         text NOT NULL,
    value             jsonb NOT NULL,
    observed_at       timestamptz NOT NULL,
    recorded_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_record_id, attribute, observed_at)
);

CREATE TABLE graph.relationship (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    src_entity_id     uuid NOT NULL REFERENCES graph.entity (id),
    dst_entity_id     uuid NOT NULL REFERENCES graph.entity (id),
    rel_type          text NOT NULL CHECK (rel_type IN (
                          'works_at', 'worked_at', 'alumni_of', 'uses_technology',
                          'mentioned_in', 'subsidiary_of', 'competitor_of')),
    properties        jsonb NOT NULL DEFAULT '{}',
    source            text NOT NULL,
    source_record_id  uuid REFERENCES ingest.source_record (id) ON DELETE CASCADE,
    confidence        numeric(4, 3) NOT NULL DEFAULT 1 CHECK (confidence BETWEEN 0 AND 1),
    valid_from        timestamptz,
    valid_to          timestamptz,
    created_at        timestamptz NOT NULL DEFAULT now(),
    CHECK (src_entity_id <> dst_entity_id),
    UNIQUE (src_entity_id, dst_entity_id, rel_type, source)
);
CREATE INDEX relationship_dst_idx ON graph.relationship (dst_entity_id);

CREATE TABLE graph.signal (
    id            uuid PRIMARY KEY,                -- uuid5(source, type, external_id)
    signal_type   text NOT NULL CHECK (signal_type IN (
                      'job_posting', 'funding', 'acquisition', 'expansion', 'leadership_change',
                      'news_mention', 'tech_detected', 'web_visit', 'high_intent_page',
                      'content_download', 'form_submission', 'email_click', 'meeting_booked')),
    source        text NOT NULL,
    occurred_at   timestamptz NOT NULL,
    title         text NOT NULL,
    url           text,
    strength      numeric(4, 3) NOT NULL CHECK (strength BETWEEN 0 AND 1),
    subject_hint  jsonb NOT NULL,
    entity_id     uuid REFERENCES graph.entity (id),
    attributes    jsonb NOT NULL DEFAULT '{}',
    ingested_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX signal_entity_time_idx ON graph.signal (entity_id, occurred_at DESC)
    WHERE entity_id IS NOT NULL;
CREATE INDEX signal_unresolved_idx ON graph.signal (ingested_at) WHERE entity_id IS NULL;

-- Identity graph: anonymous web visitors linked to people once they identify themselves.
CREATE TABLE graph.identity_link (
    visitor_id  text NOT NULL,
    entity_id   uuid NOT NULL REFERENCES graph.entity (id) ON DELETE CASCADE,
    method      text NOT NULL CHECK (method IN ('form_submission', 'email_click', 'login', 'crm_match')),
    linked_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (visitor_id, entity_id)
);
CREATE INDEX identity_link_entity_idx ON graph.identity_link (entity_id);

-- Human-in-the-loop queue for matches the resolver was not sure about. The record keeps
-- its own provisional entity; accepting merges it into the candidate.
CREATE TABLE graph.match_candidate (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_record_id     uuid NOT NULL REFERENCES ingest.source_record (id) ON DELETE CASCADE,
    record_entity_id     uuid NOT NULL REFERENCES graph.entity (id) ON DELETE CASCADE,
    candidate_entity_id  uuid NOT NULL REFERENCES graph.entity (id) ON DELETE CASCADE,
    probability          numeric(5, 4) NOT NULL CHECK (probability BETWEEN 0 AND 1),
    evidence             jsonb NOT NULL DEFAULT '[]',
    status               text NOT NULL DEFAULT 'pending'
                         CHECK (status IN ('pending', 'accepted', 'rejected')),
    reviewed_by          text,
    reviewed_at          timestamptz,
    created_at           timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_record_id, candidate_entity_id)
);
CREATE INDEX match_candidate_pending_idx ON graph.match_candidate (probability DESC)
    WHERE status = 'pending';
