#!/usr/bin/env bash
# Rebuild the local database from scratch: drop, recreate, migrate, seed, create the
# login users the API and workers use, and optionally load the synthetic demo dataset.
#
#   database/scripts/reset_local.sh [--demo]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
PY="$ROOT/.venv/bin/python"
[[ -x "$PY" ]] || { echo "run 'make install' first" >&2; exit 1; }

"$HERE/local_postgres.sh" start >/dev/null
"$ROOT/scripts/dev/ensure_env.sh"
dsn="$("$HERE/local_postgres.sh" dsn)"
admin="${dsn%/*}/postgres"

psql "$admin" -q -v ON_ERROR_STOP=1 <<'SQL'
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'leadintel' AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS leadintel;
CREATE DATABASE leadintel;
SQL

"$PY" -m leadintel.storage.migrate up --dsn "$dsn"
"$PY" -m leadintel.storage.migrate seed --dsn "$dsn"

# Local login users mirroring production (API -> app role, workers -> pipeline role).
psql "$dsn" -q -v ON_ERROR_STOP=1 <<'SQL'
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'leadintel_api') THEN
    CREATE ROLE leadintel_api LOGIN PASSWORD 'local-api';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'leadintel_worker') THEN
    CREATE ROLE leadintel_worker LOGIN PASSWORD 'local-worker';
  END IF;
END $$;
GRANT leadintel_app TO leadintel_api;
GRANT leadintel_pipeline TO leadintel_worker;
SQL

if [[ "${1:-}" == "--demo" ]]; then
  (cd "$ROOT" && "$PY" -m leadintel.devtools.demo)   # reads .env from the project root
fi
echo "local database ready: $dsn"
