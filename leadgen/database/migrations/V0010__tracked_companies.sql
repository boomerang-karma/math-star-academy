-- Companies an admin has chosen to track. Active ones are researched on a schedule
-- (account_research playbook) and on demand from the admin page. Business data only:
-- no personal data lives here, so there is no row-level security.

CREATE TABLE sales.tracked_company (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name              text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 200),
    domain            text CHECK (domain ~ '^[a-z0-9.-]+\.[a-z]{2,}$'),
    linkedin_slug     text CHECK (linkedin_slug ~ '^[a-z0-9-]{2,100}$'),
    notes             text CHECK (length(notes) <= 1000),
    status            text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused')),
    added_by          text NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    last_research_at  timestamptz,
    last_run_status   text
);
-- One row per company: by domain when known, otherwise by normalized name.
CREATE UNIQUE INDEX tracked_company_domain_key ON sales.tracked_company (domain)
    WHERE domain IS NOT NULL;
CREATE UNIQUE INDEX tracked_company_name_key ON sales.tracked_company (lower(btrim(name)))
    WHERE domain IS NULL;
CREATE TRIGGER tracked_company_touch BEFORE UPDATE ON sales.tracked_company
    FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at();

GRANT SELECT, INSERT, UPDATE, DELETE ON sales.tracked_company TO leadintel_app;
GRANT SELECT ON sales.tracked_company TO leadintel_pipeline;
GRANT UPDATE (last_research_at, last_run_status) ON sales.tracked_company TO leadintel_pipeline;
