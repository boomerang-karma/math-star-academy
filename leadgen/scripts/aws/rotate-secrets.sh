#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# Rotate a platform secret.
#
#   scripts/aws/rotate-secrets.sh --env dev --what db-admin       # Secrets Manager hosted rotation
#   scripts/aws/rotate-secrets.sh --env dev --what db-logins      # new passwords for leadintel_api/_worker
#   scripts/aws/rotate-secrets.sh --env dev --what origin-verify  # new CloudFront<->API shared header
#   SCRAPEBADGER_API_KEY=... scripts/aws/rotate-secrets.sh --env dev --what scrapebadger
#
# The blind-index key is intentionally not rotatable here: changing it invalidates
# every blind index and needs the re-index job (docs/RUNBOOK.md#blind-index-key).
set -euo pipefail
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

ENV_NAME=""
WHAT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --env) ENV_NAME="$2"; shift 2 ;;
    --what) WHAT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
[[ -n "$ENV_NAME" && -n "$WHAT" ]] || die "--env and --what are required"
require_cmd aws jq openssl
use_environment "$ENV_NAME"

random_secret() { openssl rand -base64 48 | tr -dc 'A-Za-z0-9' | head -c "$1"; }

case "$WHAT" in
  db-admin)
    aws secretsmanager rotate-secret --secret-id "$STACK_PREFIX/db/admin" >/dev/null
    log "Rotation of the Aurora admin secret started (hosted rotation Lambda)"
    ;;
  db-logins)
    migrator="$(stack_output "$STACK_PREFIX-ingestion" MigratorFunctionName)"
    [[ -n "$migrator" ]] || die "ingestion stack not deployed"
    for user in leadintel_api leadintel_worker; do
      id="$STACK_PREFIX/db/$user"
      aws secretsmanager get-secret-value --secret-id "$id" --query SecretString --output text \
        | jq --arg p "$(random_secret 40)" '.password = $p' | put_secret "$id"
    done
    # The migrator re-applies login passwords from the secrets (ALTER ROLE ... PASSWORD).
    out="$(mktemp)"; trap 'rm -f "$out"' EXIT
    aws lambda invoke --function-name "$migrator" --payload '{"seed": false}' \
      --cli-binary-format raw-in-base64-out "$out" >/dev/null
    jq -e '.login_users | length == 2' "$out" >/dev/null || die "migrator did not update login users: $(cat "$out")"
    log "Login passwords rotated; RDS Proxy picks up the new secrets for new connections"
    ;;
  origin-verify)
    random_secret 48 | put_secret "$STACK_PREFIX/origin-verify"
    log "New origin-verify value stored; redeploying the web stack so CloudFront sends it"
    warn "requests may be rejected with 403 for a few minutes until CloudFront finishes deploying"
    "$LEADGEN_ROOT/scripts/aws/setup.sh" --env "$ENV_NAME" --skip-build --only web
    ;;
  scrapebadger)
    [[ -n "${SCRAPEBADGER_API_KEY:-}" ]] || die "export SCRAPEBADGER_API_KEY with the new key"
    printf '%s' "$SCRAPEBADGER_API_KEY" | put_secret "$STACK_PREFIX/scrapebadger-api-key"
    log "ScrapeBadger key replaced; revoke the old key in the ScrapeBadger dashboard"
    ;;
  blind-index)
    die "blind-index key rotation requires a re-index; follow docs/RUNBOOK.md#blind-index-key"
    ;;
  *) die "unknown secret '$WHAT'" ;;
esac
