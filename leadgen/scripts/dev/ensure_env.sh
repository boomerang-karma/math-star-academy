#!/usr/bin/env bash
# Create leadgen/.env for local runs (once): throwaway keys + local database DSNs.
# The file is git-ignored and readable only by you.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
[[ -f "$ROOT/.env" ]] && exit 0

DSN="$("$ROOT/database/scripts/local_postgres.sh" dsn)"
HOSTPORT="${DSN#postgresql://postgres@}"
HOSTPORT="${HOSTPORT%/*}"
umask 077
cat > "$ROOT/.env" <<ENV
LEADINTEL_ENV=local
LEADINTEL_AUTH_MODE=local-dev
LEADINTEL_LOCAL_MASTER_KEY_B64=$(openssl rand -base64 32)
LEADINTEL_LOCAL_BLIND_INDEX_KEY_B64=$(openssl rand -base64 48)
LEADINTEL_DATABASE_URL=postgresql://leadintel_api@${HOSTPORT}/leadintel
LEADINTEL_WORKER_DATABASE_URL=postgresql://leadintel_worker@${HOSTPORT}/leadintel
LEADINTEL_BEACON_ALLOWED_ORIGINS=["http://localhost:5173"]
ENV
echo "wrote $ROOT/.env with fresh local keys"
