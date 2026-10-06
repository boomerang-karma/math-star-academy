#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# Restore a backup. Never overwrites a live database in place.
#
#   database/scripts/restore.sh --local --file .data/backups/leadintel-20261001.dump
#   database/scripts/restore.sh --env dev --snapshot <snapshot-id> [--target <new-cluster-id>]
#   database/scripts/restore.sh --env dev --point-in-time 2026-10-01T09:30:00Z [--target <id>]
#
# AWS restores create a NEW cluster next to the current one (same subnets, security
# group and KMS key). Validate it, then cut over by following docs/RUNBOOK.md#restore
# (re-point the RDS Proxy target or swap the cluster in the data stack).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
MODE=""
ENV_NAME=""
FILE=""
SNAPSHOT=""
PITR=""
TARGET=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --local) MODE=local; shift ;;
    --env) MODE=aws; ENV_NAME="$2"; shift 2 ;;
    --file) FILE="$2"; shift 2 ;;
    --snapshot) SNAPSHOT="$2"; shift 2 ;;
    --point-in-time) PITR="$2"; shift 2 ;;
    --target) TARGET="$2"; shift 2 ;;
    -h|--help) awk 'NR == 1 { next } /^set -euo/ { exit } /^# shellcheck/ { next } { sub(/^# ?/, ""); print }' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

case "$MODE" in
  local)
    [[ -f "$FILE" ]] || { echo "--file must point to a pg_dump archive" >&2; exit 2; }
    base_dsn="$("$HERE/local_postgres.sh" dsn)"
    restore_db="leadintel_restore_$(date -u +%Y%m%d%H%M%S)"
    psql "${base_dsn%/*}/postgres" -v ON_ERROR_STOP=1 -c "CREATE DATABASE $restore_db"
    pg_restore --no-owner --exit-on-error --dbname "${base_dsn%/*}/$restore_db" "$FILE"
    echo "restored into database '$restore_db' (the original 'leadintel' database is untouched)"
    ;;
  aws)
    # shellcheck source=../../scripts/aws/lib.sh
    source "$ROOT/scripts/aws/lib.sh"
    require_cmd aws jq
    use_environment "$ENV_NAME"
    [[ -n "$SNAPSHOT" || -n "$PITR" ]] || die "--snapshot or --point-in-time is required"
    source_cluster="$(stack_output "$STACK_PREFIX-data" ClusterIdentifier)"
    [[ -n "$source_cluster" ]] || die "no Aurora cluster found for $ENV_NAME"
    TARGET="${TARGET:-$STACK_PREFIX-restore-$(date -u +%Y%m%d%H%M)}"
    info="$(aws rds describe-db-clusters --db-cluster-identifier "$source_cluster" --query 'DBClusters[0]')"
    subnet_group="$(jq -r '.DBSubnetGroup' <<<"$info")"
    security_groups="$(jq -r '[.VpcSecurityGroups[].VpcSecurityGroupId] | join(" ")' <<<"$info")"
    kms_key="$(jq -r '.KmsKeyId' <<<"$info")"
    engine_version="$(jq -r '.EngineVersion' <<<"$info")"
    # shellcheck disable=SC2054  # the comma is AWS CLI shorthand syntax, not an array separator
    common=(--db-cluster-identifier "$TARGET" --db-subnet-group-name "$subnet_group"
            --kms-key-id "$kms_key" --enable-iam-database-authentication
            --serverless-v2-scaling-configuration MinCapacity=0.5,MaxCapacity=8
            --deletion-protection --copy-tags-to-snapshot)
    # shellcheck disable=SC2086  # security group ids are intentionally word-split
    if [[ -n "$SNAPSHOT" ]]; then
      log "Restoring snapshot $SNAPSHOT into new cluster $TARGET"
      aws rds restore-db-cluster-from-snapshot "${common[@]}" --snapshot-identifier "$SNAPSHOT" \
        --engine aurora-postgresql --engine-version "$engine_version" \
        --vpc-security-group-ids $security_groups >/dev/null
    else
      log "Restoring $source_cluster to $PITR into new cluster $TARGET"
      aws rds restore-db-cluster-to-point-in-time "${common[@]}" \
        --source-db-cluster-identifier "$source_cluster" --restore-to-time "$PITR" \
        --vpc-security-group-ids $security_groups >/dev/null
    fi
    aws rds create-db-instance --db-instance-identifier "$TARGET-writer" --db-cluster-identifier "$TARGET" \
      --engine aurora-postgresql --db-instance-class db.serverless >/dev/null
    log "Waiting for $TARGET-writer to become available"
    aws rds wait db-instance-available --db-instance-identifier "$TARGET-writer"
    log "Restored cluster $TARGET is available. Validate it, then follow docs/RUNBOOK.md#restore to cut over."
    ;;
  *) echo "choose --local or --env <name>" >&2; exit 2 ;;
esac
