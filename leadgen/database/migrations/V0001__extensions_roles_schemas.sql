-- Extensions, database roles, schemas and session helpers.
--
-- Roles (cluster-wide, created idempotently):
--   leadintel_owner      NOLOGIN. Owns every object. The migration runner SET ROLEs to it.
--   leadintel_app        API runtime. Subject to row-level security. No DDL.
--   leadintel_pipeline   Ingestion/resolution/scoring workers. Cross-territory writes.
--   leadintel_readonly   BI/analytics. Reads masked views only.
-- Login users (passwords in Secrets Manager, or IAM auth through RDS Proxy) are created and
-- granted these roles outside migrations: by the migrator Lambda in AWS
-- (MigrationRunner.ensure_login_user) and by database/scripts/reset_local.sh locally.
-- No credentials live in migrations.
--
-- leadintel:as-login-user   (extensions and grants below need the connecting user)

DO $$
DECLARE
    r text;
BEGIN
    FOREACH r IN ARRAY ARRAY['leadintel_owner', 'leadintel_app', 'leadintel_pipeline', 'leadintel_readonly']
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('CREATE ROLE %I NOLOGIN', r);
        END IF;
    END LOOP;
    -- Let the migrating user act as the owner, and let the owner create schemas.
    EXECUTE format('GRANT leadintel_owner TO %I', current_user);
    EXECUTE format('GRANT CREATE ON DATABASE %I TO leadintel_owner', current_database());
END
$$;

-- Extensions live in their own schema so `public` can be locked down completely.
CREATE SCHEMA IF NOT EXISTS extensions;
GRANT USAGE ON SCHEMA extensions
    TO leadintel_owner, leadintel_app, leadintel_pipeline, leadintel_readonly;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm') THEN
        IF (SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace
            WHERE e.extname = 'pg_trgm') <> 'extensions' THEN
            ALTER EXTENSION pg_trgm SET SCHEMA extensions;
        END IF;
    ELSE
        CREATE EXTENSION pg_trgm WITH SCHEMA extensions;
    END IF;
END
$$;

REVOKE ALL ON SCHEMA public FROM PUBLIC;

SET LOCAL ROLE leadintel_owner;

CREATE SCHEMA IF NOT EXISTS app;      -- session/security helpers
CREATE SCHEMA IF NOT EXISTS ingest;   -- source records, connector runs
CREATE SCHEMA IF NOT EXISTS graph;    -- entities, links, signals, review queue
CREATE SCHEMA IF NOT EXISTS sales;    -- leads, users, territories
CREATE SCHEMA IF NOT EXISTS privacy;  -- consent, suppression, DSAR, retention
CREATE SCHEMA IF NOT EXISTS audit;    -- append-only audit trail

-- The API sets these per transaction with set_config(name, value, is_local => true):
--   app.user_id      Cognito sub of the caller
--   app.scope        'global' | 'territory'
--   app.territories  comma-separated territory ids
-- Missing settings resolve to the most restrictive value.
CREATE FUNCTION app.current_user_id() RETURNS uuid
    LANGUAGE sql STABLE AS
$$ SELECT nullif(current_setting('app.user_id', true), '')::uuid $$;

CREATE FUNCTION app.current_scope() RETURNS text
    LANGUAGE sql STABLE AS
$$ SELECT coalesce(nullif(current_setting('app.scope', true), ''), 'none') $$;

CREATE FUNCTION app.current_territories() RETURNS uuid[]
    LANGUAGE sql STABLE AS
$$ SELECT coalesce(string_to_array(nullif(current_setting('app.territories', true), ''), ',')::uuid[], '{}') $$;

CREATE FUNCTION app.touch_updated_at() RETURNS trigger
    LANGUAGE plpgsql AS
$$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END
$$;
