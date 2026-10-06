-- Leads, the people who work them, and the territories that scope access.

CREATE TABLE sales.territory (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name         text NOT NULL UNIQUE,
    countries    text[] NOT NULL DEFAULT '{}',   -- ISO 3166-1 alpha-2, upper case
    description  text
);

CREATE TABLE sales.app_user (
    id            uuid PRIMARY KEY,                -- Cognito sub
    display_name  text NOT NULL,
    email_bidx    text UNIQUE,
    territories   uuid[] NOT NULL DEFAULT '{}',
    active        boolean NOT NULL DEFAULT true,
    created_at    timestamptz NOT NULL DEFAULT now()
);

-- A lead is an account (organization) optionally narrowed to a person at it.
CREATE TABLE sales.lead (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_entity_id  uuid REFERENCES graph.entity (id),
    person_entity_id        uuid REFERENCES graph.entity (id),
    status                  text NOT NULL DEFAULT 'new' CHECK (status IN (
                                'new', 'working', 'nurture', 'qualified', 'disqualified', 'converted')),
    owner_user_id           uuid REFERENCES sales.app_user (id),
    territory_id            uuid REFERENCES sales.territory (id),
    score                   numeric(5, 2),
    tier                    char(1) CHECK (tier IN ('A', 'B', 'C', 'D')),
    fit_score               numeric(5, 2),
    intent_score            numeric(5, 2),
    engagement_score        numeric(5, 2),
    hot                     boolean NOT NULL DEFAULT false,
    score_explanation       jsonb NOT NULL DEFAULT '[]',
    scored_at               timestamptz,
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now(),
    CHECK (organization_entity_id IS NOT NULL OR person_entity_id IS NOT NULL)
);
CREATE UNIQUE INDEX lead_identity_uidx ON sales.lead (
    coalesce(organization_entity_id, '00000000-0000-0000-0000-000000000000'::uuid),
    coalesce(person_entity_id, '00000000-0000-0000-0000-000000000000'::uuid));
CREATE INDEX lead_rank_idx ON sales.lead (score DESC NULLS LAST, id);
CREATE INDEX lead_territory_idx ON sales.lead (territory_id);
CREATE INDEX lead_owner_idx ON sales.lead (owner_user_id);
CREATE INDEX lead_person_idx ON sales.lead (person_entity_id) WHERE person_entity_id IS NOT NULL;
CREATE TRIGGER lead_touch BEFORE UPDATE ON sales.lead
    FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at();

CREATE TABLE sales.lead_score_history (
    lead_id     uuid NOT NULL REFERENCES sales.lead (id) ON DELETE CASCADE,
    scored_at   timestamptz NOT NULL,
    score       numeric(5, 2) NOT NULL,
    tier        char(1) NOT NULL,
    components  jsonb NOT NULL,
    PRIMARY KEY (lead_id, scored_at)
);

-- Cached AI account briefs; regenerated when the input fingerprint changes.
CREATE TABLE sales.ai_brief (
    lead_id       uuid PRIMARY KEY REFERENCES sales.lead (id) ON DELETE CASCADE,
    model_id      text NOT NULL,
    input_hash    text NOT NULL,
    brief         jsonb NOT NULL,
    generated_by  text NOT NULL,
    generated_at  timestamptz NOT NULL DEFAULT now()
);
