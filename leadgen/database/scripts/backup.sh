#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# Take a backup.
#
#   database/scripts/backup.sh --local                  # pg_dump of the local database
#   database/scripts/backup.sh --env dev [--label pre-release-42]
#
# AWS: a manual Aurora cluster snapshot (kept until deleted, independent of the
# automated backup window and of stack teardown). Automated backups with
# point-in-time recovery run continuously regardless.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
MODE=""
ENV_NAME=""
LABEL="manual"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --local) MODE=local; shift ;;
    --env) MODE=aws; ENV_NAME="$2"; shift 2 ;;
    --label) LABEL="$2"; shift 2 ;;
    -h|--help) awk 'NR == 1 { next } /^set -euo/ { exit } /^# shellcheck/ { next } { sub(/^# ?/, ""); print }' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
STAMP="$(date -u +%Y%m%d%H%M%S)"

case "$MODE" in
  local)
    mkdir -p "$ROOT/.data/backups"
    out="$ROOT/.data/backups/leadintel-$STAMP.dump"
    pg_dump --format=custom --no-owner --file "$out" "$("$HERE/local_postgres.sh" dsn)"
    echo "backup written: $out"
    ;;
  aws)
    # shellcheck source=../../scripts/aws/lib.sh
    source "$ROOT/scripts/aws/lib.sh"
    require_cmd aws jq
    use_environment "$ENV_NAME"
    cluster="$(stack_output "$STACK_PREFIX-data" ClusterIdentifier)"
    [[ -n "$cluster" ]] || die "no Aurora cluster found for $ENV_NAME"
    snapshot="$STACK_PREFIX-$LABEL-$STAMP"
    aws rds create-db-cluster-snapshot --db-cluster-identifier "$cluster" \
      --db-cluster-snapshot-identifier "$snapshot" \
      --tags Key=project,Value=leadintel Key=environment,Value="$ENV_NAME" Key=purpose,Value="$LABEL" >/dev/null
    log "Waiting for $snapshot"
    aws rds wait db-cluster-snapshot-available --db-cluster-snapshot-identifier "$snapshot"
    log "Snapshot ready: $snapshot"
    ;;
  *) echo "choose --local or --env <name>" >&2; exit 2 ;;
esac
