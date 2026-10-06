# Database

PostgreSQL 16 (Aurora PostgreSQL Serverless v2 in AWS) is the system of record:
the ontology graph, leads, privacy records and the audit trail. Everything here
is plain SQL plus small shell scripts. The runner lives in
`src/leadintel/storage/migrate.py`.

```
database/
  migrations/   V<4 digits>__<description>.sql, applied in order, never edited once applied
  seeds/        idempotent reference data (territories, retention policies)
  scripts/      local_postgres.sh, reset_local.sh, backup.sh, restore.sh
```

## Schemas

| Schema | Contents |
| --- | --- |
| `extensions` | `pg_trgm` (and `vector` when available), kept out of `public` |
| `app` | Session helpers read by RLS: `app.current_user_id()`, `app.current_scope()`, `app.current_territories()` |
| `ingest` | `connector_run`, `source_record` (immutable, content-hashed, lawful basis, encrypted PII envelope, blind indexes) |
| `graph` | `entity` (golden records), `entity_member` (lineage + match evidence), `entity_key` (blocking keys), `attribute_assertion` (every asserted value), `relationship`, `signal`, `identity_link`, `match_candidate` (review queue), `merge_entities()` |
| `sales` | `territory`, `app_user`, `lead`, `lead_score_history`, `ai_brief`, views `v_lead_overview` and `v_lead_bi` (masked, for BI) |
| `privacy` | `consent`, `suppression`, `dsar_request`, `retention_policy` |
| `audit` | `audit_log` (append-only, hash-chained), `verify_chain()` |

The model is described in [docs/ONTOLOGY.md](../docs/ONTOLOGY.md).

## Roles

| Role | Login? | Used by | Rights |
| --- | --- | --- | --- |
| `leadintel_owner` | no | Migration runner (`SET ROLE`) | Owns every object |
| `leadintel_app` | via `leadintel_api` | API | Reads and writes what the API needs; **subject to RLS**; insert-only on the audit log |
| `leadintel_pipeline` | via `leadintel_worker` | Workers | Cross-territory writes for ingestion, resolution, scoring, retention and DSARs; reads suppressions and inserts new ones (erasure) |
| `leadintel_readonly` | (grant to BI users) | Analytics | Masked views only |

Login users are created outside migrations:

- **In AWS**, by the migrator Lambda. Passwords come from Secrets Manager and
  are used only by RDS Proxy; clients authenticate to the proxy with IAM.
- **Locally**, by `scripts/reset_local.sh`.

## Migrations

Each file runs in its own transaction as `leadintel_owner`. The runner:

- takes a PostgreSQL advisory lock, so concurrent deploys queue
- records every applied version with a SHA-256 checksum, and **refuses to run
  when an applied file has changed**

Directives (comment lines in the file):

- `-- leadintel:as-login-user`: run as the connecting user. This is needed for
  `CREATE EXTENSION` and role grants.
- `-- leadintel:no-transaction`: run outside a transaction, for
  `CREATE INDEX CONCURRENTLY`.

```bash
.venv/bin/python -m leadintel.storage.migrate status --dsn postgresql://...
.venv/bin/python -m leadintel.storage.migrate up     --dsn ...   # apply pending
.venv/bin/python -m leadintel.storage.migrate verify --dsn ...   # checksum drift only
.venv/bin/python -m leadintel.storage.migrate seed   --dsn ...   # idempotent reference data
```

In AWS, `scripts/aws/setup.sh` invokes the migrator Lambda inside the VPC. You
never need network access to the database.

### Writing a migration

1. Add `migrations/V<next>__<what>.sql`. One concern per file, forward-only.
2. Keep it backward compatible with the running code for one release: add
   before use, drop a release later.
3. New tables need privileges in a new grants migration:
   - grants for `leadintel_app` and/or `leadintel_pipeline`
   - RLS policies if the table holds personal or territory-scoped data
   - an entry in the retention schedule if it holds personal data
4. Run `make db-reset` and the integration tests (`make test-integration`).
   They migrate a fresh database and assert grants, RLS and the audit chain.

### Current migrations

| Version | Purpose |
| --- | --- |
| V0001 | Extensions, roles, schemas, session helpers |
| V0002 | Ingest: connector runs, source records |
| V0003 | Graph: entities, members, keys, assertions, relationships, signals, identity links, review queue |
| V0004 | Sales: territories, users, leads, score history, AI briefs |
| V0005 | Privacy: consent, suppression, DSAR requests, retention policies |
| V0006 | Audit log with trigger-computed hash chain and immutability |
| V0007 | Grants, row-level security, `graph.merge_entities` |
| V0008 | Views for the API and BI |
| V0009 | Optional `pgvector` entity embeddings (skipped when the extension is unavailable) |

## Seeds

Seeds are idempotent (`ON CONFLICT ... DO UPDATE`) and run on every deploy:

- `0001_territories.sql`: sales territories by country. Edit them to match
  your sales organization.
- `0002_retention_policies.sql`: the retention schedule. Keep it in sync with
  [docs/COMPLIANCE.md](../docs/COMPLIANCE.md#retention-schedule).

## Local database

```bash
database/scripts/local_postgres.sh start     # PostgreSQL 16 on 127.0.0.1:54329, data in .data/pg
database/scripts/reset_local.sh [--demo]     # drop, migrate, seed, login users, optional demo data
database/scripts/local_postgres.sh stop
```

The scripts find PostgreSQL 16 binaries on the PATH or in the usual Debian
location. When run as root, they drop privileges with `runuser`.

## Backups and restores

`backup.sh` and `restore.sh` work locally (pg_dump/pg_restore into a new
database) and in AWS (cluster snapshots, point-in-time restore into a **new**
cluster). The cutover procedure, including re-applying privacy actions taken
after the restore point, is in
[docs/RUNBOOK.md](../docs/RUNBOOK.md#restore).
