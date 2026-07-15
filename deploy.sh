#!/usr/bin/env bash
set -euo pipefail

# Deploy Lumi's Math Garden to Azure Static Web Apps.
#
#   Usage:  SWA_TOKEN='<your-deployment-token>' ./deploy.sh
#
# Why it runs from the parent folder: the SWA CLI refuses to deploy when the
# current directory is the same as (or inside) the artifact folder. So we cd to
# the parent and point at this app folder as a subfolder — which is the
# documented workaround for:
#   "Current directory cannot be identical to or contained within artifact folders."

if [ -z "${SWA_TOKEN:-}" ]; then
  echo "❌ Set SWA_TOKEN first, e.g.:" >&2
  echo "     SWA_TOKEN='paste-token-here' ./deploy.sh" >&2
  exit 1
fi

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARENT="$(dirname "$APP_DIR")"
NAME="$(basename "$APP_DIR")"

echo "🌱 Deploying '$NAME' to Azure Static Web Apps (production)…"
cd "$PARENT"
npx --yes @azure/static-web-apps-cli deploy "./$NAME" \
  --env production \
  --deployment-token "$SWA_TOKEN"
