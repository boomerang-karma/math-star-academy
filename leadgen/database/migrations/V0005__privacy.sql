-- Privacy operations: consent ledger, suppression list, data-subject requests, retention.
-- Identifiers are stored only as blind indexes (HMAC), never in plaintext.

CREATE TABLE privacy.consent (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_bidx    text NOT NULL,                 -- blind index of the subject's email
    purpose         text NOT NULL CHECK (purpose IN (
                        'marketing_email', 'sales_outreach', 'analytics', 'profiling')),
    status          text NOT NULL CHECK (status IN ('granted', 'denied', 'withdrawn')),
    lawful_basis    text NOT NULL CHECK (lawful_basis IN ('consent', 'legitimate_interest', 'contract')),
    source          text NOT NULL,
    evidence        jsonb NOT NULL DEFAULT '{}',   -- form id, consent text version, timestamp
    captured_at     timestamptz NOT NULL,
    expires_at      timestamptz
);
CREATE INDEX consent_subject_idx ON privacy.consent (subject_bidx, purpose, captured_at DESC);

-- Checked before ingestion, enrichment and outreach. Survives erasure so a deleted
-- person is not silently re-collected by the next scrape.
CREATE TABLE privacy.suppression (
    identifier_type  text NOT NULL CHECK (identifier_type IN ('email', 'phone', 'domain', 'linkedin_slug')),
    identifier_bidx  text NOT NULL,
    reason           text NOT NULL CHECK (reason IN ('erasure', 'objection', 'unsubscribe', 'do_not_contact')),
    created_by       text NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (identifier_type, identifier_bidx)
);

CREATE TABLE privacy.dsar_request (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    request_type        text NOT NULL CHECK (request_type IN (
                            'access', 'erasure', 'rectification', 'restriction', 'objection', 'portability')),
    jurisdiction        text NOT NULL CHECK (jurisdiction IN ('gdpr', 'uk_gdpr', 'ccpa', 'other')),
    subject_email_bidx  text NOT NULL,
    status              text NOT NULL DEFAULT 'received' CHECK (status IN (
                            'received', 'verifying', 'in_progress', 'completed', 'rejected')),
    received_at         timestamptz NOT NULL DEFAULT now(),
    due_at              timestamptz NOT NULL,
    completed_at        timestamptz,
    created_by          text NOT NULL,
    handled_by          text,
    result              jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX dsar_open_idx ON privacy.dsar_request (due_at) WHERE status NOT IN ('completed', 'rejected');

CREATE TABLE privacy.retention_policy (
    data_class   text PRIMARY KEY,
    retain_days  integer NOT NULL CHECK (retain_days > 0),
    action       text NOT NULL CHECK (action IN ('delete', 'anonymize')),
    description  text NOT NULL
);
