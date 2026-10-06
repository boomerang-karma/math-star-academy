-- Append-only, hash-chained audit log. See src/leadintel/security/audit.py.
--
-- hash = sha256(coalesce(prev_hash, 32 zero bytes) || utf8(audit.canonical_line(row)))
-- seq and occurred_at are assigned inside the trigger *after* taking an advisory lock,
-- so the chain order equals seq order even under concurrent writers.
-- Appends must run under READ COMMITTED (the default) so the trigger sees the latest head.

CREATE SEQUENCE audit.audit_log_seq;

CREATE TABLE audit.audit_log (
    seq            bigint PRIMARY KEY,
    occurred_at    timestamptz NOT NULL,
    actor_id       text NOT NULL,
    actor_type     text NOT NULL CHECK (actor_type IN ('user', 'service', 'system')),
    action         text NOT NULL,
    resource_type  text NOT NULL,
    resource_id    text,
    outcome        text NOT NULL CHECK (outcome IN ('success', 'denied', 'error')),
    request_id     text,
    ip             inet,
    details        jsonb NOT NULL DEFAULT '{}',
    prev_hash      bytea,
    hash           bytea NOT NULL
);
CREATE INDEX audit_resource_idx ON audit.audit_log (resource_type, resource_id, seq DESC);
CREATE INDEX audit_actor_idx ON audit.audit_log (actor_id, seq DESC);

CREATE FUNCTION audit.canonical_line(r audit.audit_log) RETURNS text
    LANGUAGE sql IMMUTABLE AS
$$
    SELECT concat_ws('|',
        r.seq::text,
        ((extract(epoch FROM r.occurred_at) * 1000000)::bigint)::text,
        r.actor_id,
        r.actor_type,
        r.action,
        r.resource_type,
        coalesce(r.resource_id, ''),
        r.outcome,
        coalesce(r.request_id, ''),
        coalesce(host(r.ip), ''),
        r.details::text)
$$;

CREATE FUNCTION audit.chain_before_insert() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, audit AS
$$
DECLARE
    prev bytea;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('leadintel.audit_chain'));
    NEW.seq := nextval('audit.audit_log_seq');
    NEW.occurred_at := clock_timestamp();
    SELECT a.hash INTO prev FROM audit.audit_log a ORDER BY a.seq DESC LIMIT 1;
    NEW.prev_hash := prev;
    NEW.hash := sha256(coalesce(prev, decode(repeat('00', 32), 'hex'))
                       || convert_to(audit.canonical_line(NEW), 'UTF8'));
    RETURN NEW;
END
$$;

CREATE FUNCTION audit.forbid_mutation() RETURNS trigger
    LANGUAGE plpgsql AS
$$
BEGIN
    RAISE EXCEPTION 'audit.audit_log is append-only';
END
$$;

CREATE TRIGGER audit_log_chain BEFORE INSERT ON audit.audit_log
    FOR EACH ROW EXECUTE FUNCTION audit.chain_before_insert();
CREATE TRIGGER audit_log_no_mutation BEFORE UPDATE OR DELETE ON audit.audit_log
    FOR EACH ROW EXECUTE FUNCTION audit.forbid_mutation();
CREATE TRIGGER audit_log_no_truncate BEFORE TRUNCATE ON audit.audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION audit.forbid_mutation();

-- Returns the first seq whose link or hash does not verify, or NULL if the chain is intact.
CREATE FUNCTION audit.verify_chain(from_seq bigint DEFAULT 0) RETURNS bigint
    LANGUAGE plpgsql STABLE AS
$$
DECLARE
    r      audit.audit_log;
    prev   bytea;
    first  boolean := true;
BEGIN
    FOR r IN SELECT * FROM audit.audit_log WHERE seq >= from_seq ORDER BY seq LOOP
        IF NOT first AND r.prev_hash IS DISTINCT FROM prev THEN
            RETURN r.seq;
        END IF;
        IF r.hash <> sha256(coalesce(r.prev_hash, decode(repeat('00', 32), 'hex'))
                            || convert_to(audit.canonical_line(r), 'UTF8')) THEN
            RETURN r.seq;
        END IF;
        prev := r.hash;
        first := false;
    END LOOP;
    RETURN NULL;
END
$$;
