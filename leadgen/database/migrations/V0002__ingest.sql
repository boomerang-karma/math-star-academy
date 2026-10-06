-- Bronze/silver boundary: connector runs and normalized source records.

CREATE TABLE ingest.connector_run (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    connector       text NOT NULL,
    playbook        text NOT NULL,
    status          text NOT NULL DEFAULT 'running'
                    CHECK (status IN ('running', 'succeeded', 'partial', 'failed')),
    params          jsonb NOT NULL DEFAULT '{}',
    started_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz,
    records_in      integer NOT NULL DEFAULT 0,
    signals_in      integer NOT NULL DEFAULT 0,
    credits_used    integer NOT NULL DEFAULT 0,
    error           text
);
CREATE INDEX connector_run_recent_idx ON ingest.connector_run (connector, started_at DESC);

-- One row per (source, external_id). Re-fetches update in place; the history of
-- asserted values is kept in graph.attribute_assertion.
CREATE TABLE ingest.source_record (
    id              uuid PRIMARY KEY,          -- uuid5(source, external_id): idempotent upserts
    source          text NOT NULL,
    external_id     text NOT NULL,
    entity_type     text NOT NULL CHECK (entity_type IN ('person', 'organization')),
    run_id          uuid REFERENCES ingest.connector_run (id) ON DELETE SET NULL,
    observed_at     timestamptz NOT NULL,
    fetched_at      timestamptz NOT NULL DEFAULT now(),
    attributes      jsonb NOT NULL DEFAULT '{}',   -- internal + confidential attributes
    relationships   jsonb NOT NULL DEFAULT '[]',
    pii_envelope    bytea,                         -- KMS envelope of restricted attributes
    email_bidx      text,                          -- blind indexes of restricted identifiers
    phone_bidx      text,
    content_hash    text NOT NULL,
    lawful_basis    text NOT NULL
                    CHECK (lawful_basis IN ('consent', 'legitimate_interest', 'contract')),
    source_url      text,
    raw_uri         text,                          -- s3://bucket/key?versionId=... (bronze)
    resolution_state text NOT NULL DEFAULT 'pending'
                    CHECK (resolution_state IN ('pending', 'resolved', 'review', 'suppressed')),
    UNIQUE (source, external_id)
);
CREATE INDEX source_record_pending_idx ON ingest.source_record (fetched_at)
    WHERE resolution_state = 'pending';
CREATE INDEX source_record_email_bidx_idx ON ingest.source_record (email_bidx) WHERE email_bidx IS NOT NULL;
CREATE INDEX source_record_phone_bidx_idx ON ingest.source_record (phone_bidx) WHERE phone_bidx IS NOT NULL;
