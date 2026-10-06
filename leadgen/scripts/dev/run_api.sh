#!/usr/bin/env bash
# Run the API locally against the local PostgreSQL, with developer identities.
#
#   scripts/dev/run_api.sh            # http://127.0.0.1:8000/api/docs
#
# First run writes .env with throwaway local keys (git-ignored). Identities come from
# headers (X-Dev-User, X-Dev-Roles, X-Dev-Territories); this mode is refused outside
# LEADINTEL_ENV=local by the settings validator.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

"$ROOT/database/scripts/local_postgres.sh" start >/dev/null
"$ROOT/scripts/dev/ensure_env.sh"

exec "$ROOT/.venv/bin/uvicorn" leadintel.api.app:create_app --factory --host 127.0.0.1 --port 8000 --reload
