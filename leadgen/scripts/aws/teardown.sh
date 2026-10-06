#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# Tear an environment down, safely.
#
#   scripts/aws/teardown.sh --env dev [--dry-run] [--yes] [--skip-snapshot] [--purge-retained]
#   scripts/aws/teardown.sh --env prod --i-understand-this-destroys-prod
#
# Safety rails
#   * Refuses to run against an account other than the one pinned in the config.
#   * Protected environments (deletion_protection=true) need the explicit flag above
#     AND a typed confirmation of "destroy <env> <account>"; --yes is ignored for them.
#   * Takes a final Aurora snapshot first (kept after teardown) unless --skip-snapshot,
#     which protected environments do not allow.
#   * --dry-run prints every action without changing anything.
#
# Order: snapshot -> lift deletion protection -> empty destroyable buckets ->
#        cdk destroy -> purge leftovers (non-protected only) -> report what remains.
set -euo pipefail
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

ENV_NAME=""
DRY_RUN=false
ASSUME_YES=false
SKIP_SNAPSHOT=false
PURGE=false
PROD_ACK=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env) ENV_NAME="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --yes) ASSUME_YES=true; shift ;;
    --skip-snapshot) SKIP_SNAPSHOT=true; shift ;;
    --purge-retained) PURGE=true; shift ;;
    --i-understand-this-destroys-prod) PROD_ACK=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
[[ -n "$ENV_NAME" ]] || die "--env is required"

require_cmd aws jq npx
use_environment "$ENV_NAME"

run() {
  if [[ "$DRY_RUN" == true ]]; then
    printf '   [dry-run] %s\n' "$*" >&2
  else
    "$@"
  fi
}

# ------------------------------------------------------------------ confirmation
protected=false
is_protected "$ENV_NAME" && protected=true
if [[ "$protected" == true ]]; then
  [[ "$PROD_ACK" == true ]] || die "'$ENV_NAME' is protected; pass --i-understand-this-destroys-prod"
  [[ "$SKIP_SNAPSHOT" == false ]] || die "a final snapshot is mandatory for protected environments"
  [[ "$PURGE" == false ]] || die "--purge-retained is not allowed for protected environments"
  [[ "$DRY_RUN" == true ]] || confirm "Type 'destroy $ENV_NAME $ACCOUNT_ID' to continue:" \
    "destroy $ENV_NAME $ACCOUNT_ID"
elif [[ "$ASSUME_YES" == false && "$DRY_RUN" == false ]]; then
  confirm "Type 'destroy $ENV_NAME' to tear down $ENV_NAME in $ACCOUNT_ID:" "destroy $ENV_NAME"
fi
log "Tearing down '$ENV_NAME' in $ACCOUNT_ID/$AWS_REGION$([[ "$DRY_RUN" == true ]] && echo ' (dry run)')"

# ------------------------------------------------------------------ final snapshot
cluster="$(stack_output "$STACK_PREFIX-data" ClusterIdentifier)"
if [[ -n "$cluster" && "$SKIP_SNAPSHOT" == false ]]; then
  snapshot="$STACK_PREFIX-final-$(date -u +%Y%m%d%H%M%S)"
  log "Final snapshot $snapshot of $cluster"
  run aws rds create-db-cluster-snapshot --db-cluster-identifier "$cluster" \
    --db-cluster-snapshot-identifier "$snapshot" --tags Key=project,Value=leadintel \
    Key=environment,Value="$ENV_NAME" Key=purpose,Value=final-teardown >/dev/null
  run aws rds wait db-cluster-snapshot-available --db-cluster-snapshot-identifier "$snapshot"
fi

# ------------------------------------------------------------------ lift protection
if [[ -n "$cluster" && "$protected" == true ]]; then
  log "Disabling deletion protection on $cluster"
  run aws rds modify-db-cluster --db-cluster-identifier "$cluster" --no-deletion-protection \
    --apply-immediately >/dev/null
  pool="$(stack_output "$STACK_PREFIX-security" UserPoolId)"
  [[ -n "$pool" ]] && run aws cognito-idp update-user-pool --user-pool-id "$pool" \
    --deletion-protection INACTIVE
fi

# ------------------------------------------------------------------ empty buckets
# Protected environments retain their buckets (RemovalPolicy.RETAIN): nothing to empty.
empty_bucket() {
  local bucket="$1" bypass="$2" batch
  aws s3api head-bucket --bucket "$bucket" >/dev/null 2>&1 || return 0
  log "Emptying s3://$bucket (all versions)"
  while true; do
    batch="$(aws s3api list-object-versions --bucket "$bucket" --max-items 1000 --output json \
      | jq -c '{Objects: ([.Versions[]?, .DeleteMarkers[]?] | map({Key, VersionId})), Quiet: true}')"
    [[ "$(jq '.Objects | length' <<<"$batch")" -eq 0 ]] && break
    if [[ "$DRY_RUN" == true ]]; then
      printf '   [dry-run] delete %s object versions from %s\n' "$(jq '.Objects | length' <<<"$batch")" "$bucket" >&2
      break
    fi
    if [[ "$bypass" == true ]]; then
      aws s3api delete-objects --bucket "$bucket" --delete "$batch" --bypass-governance-retention >/dev/null
    else
      aws s3api delete-objects --bucket "$bucket" --delete "$batch" >/dev/null
    fi
  done
}

if [[ "$protected" == false ]]; then
  for key in RawBucketName CuratedBucketName LogsBucketName; do
    bucket="$(stack_output "$STACK_PREFIX-data" "$key")"
    [[ -n "$bucket" ]] && empty_bucket "$bucket" false
  done
  audit="$(stack_output "$STACK_PREFIX-data" AuditBucketName)"
  if [[ -n "$audit" ]]; then
    if [[ "$(config_value "$ENV_NAME" audit_object_lock_mode)" == "governance" ]]; then
      empty_bucket "$audit" true
    else
      warn "s3://$audit uses COMPLIANCE object lock and cannot be emptied before retention ends"
    fi
  fi
  site="$(stack_output "$STACK_PREFIX-web" SiteBucketName)"
  [[ -n "$site" ]] && empty_bucket "$site" false
fi

# ------------------------------------------------------------------ destroy
log "Destroying stacks"
if [[ "$DRY_RUN" == true ]]; then
  printf '   [dry-run] cdk destroy --all -c env=%s --force\n' "$ENV_NAME" >&2
else
  [[ -d "$BUILD_DIR/lambda" ]] || mkdir -p "$BUILD_DIR/lambda"   # synth needs the asset path to exist
  cdk destroy --all -c env="$ENV_NAME" --force
fi

# ------------------------------------------------------------------ leftovers
if [[ "$protected" == false ]]; then
  # Secrets deleted by CloudFormation sit in a 30-day recovery window and block re-creation
  # under the same name; dev/staging purge them so setup.sh can run again immediately.
  log "Purging secrets pending deletion under $STACK_PREFIX/"
  aws secretsmanager list-secrets --include-planned-deletion \
    --filters Key=name,Values="$STACK_PREFIX/" --query 'SecretList[].ARN' --output text \
    | tr '\t' '\n' | while read -r arn; do
        [[ -z "$arn" || "$arn" == "None" ]] && continue
        run aws secretsmanager delete-secret --secret-id "$arn" --force-delete-without-recovery >/dev/null
      done
fi
if [[ "$PURGE" == true ]]; then
  log "Purging retained log groups"
  aws logs describe-log-groups --log-group-name-prefix "aws-waf-logs-$STACK_PREFIX" \
    --region us-east-1 --query 'logGroups[].logGroupName' --output text | tr '\t' '\n' \
    | while read -r group; do
        [[ -n "$group" && "$group" != "None" ]] && run aws logs delete-log-group \
          --log-group-name "$group" --region us-east-1
      done
fi

# ------------------------------------------------------------------ report
echo
log "Teardown finished. Still present (by design):"
aws rds describe-db-cluster-snapshots --snapshot-type manual \
  --query "DBClusterSnapshots[?starts_with(DBClusterSnapshotIdentifier, '$STACK_PREFIX-')].[DBClusterSnapshotIdentifier,SnapshotCreateTime]" \
  --output text | sed 's/^/  snapshot  /' || true
aws s3api list-buckets --query "Buckets[?starts_with(Name, '$STACK_PREFIX')].Name" --output text \
  | tr '\t' '\n' | sed '/^$/d;s/^/  bucket    /' || true
if [[ "$protected" == true ]]; then
  echo "  Retained by policy: KMS keys (scheduled deletion only after a manual decision),"
  echo "  S3 buckets, log groups and the Cognito pool data. Review before deleting anything."
fi
