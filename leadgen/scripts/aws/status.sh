#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# Show the deployment state of an environment.
#
#   scripts/aws/status.sh --env dev
set -euo pipefail
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

ENV_NAME=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --env) ENV_NAME="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
[[ -n "$ENV_NAME" ]] || die "--env is required"
require_cmd aws jq
use_environment "$ENV_NAME"

printf '%-34s %-22s %s\n' STACK STATUS "LAST UPDATED"
for unit in network security data ingestion api edge web observability cicd; do
  region="$AWS_REGION"
  [[ "$unit" == "edge" ]] && region="us-east-1"
  aws cloudformation describe-stacks --stack-name "$STACK_PREFIX-$unit" --region "$region" \
    --query 'Stacks[0].[StackName,StackStatus,LastUpdatedTime||CreationTime]' --output text 2>/dev/null \
    | awk '{printf "%-34s %-22s %s\n", $1, $2, $3}' \
    || printf '%-34s %-22s\n' "$STACK_PREFIX-$unit" "NOT DEPLOYED"
done

echo
url="$(stack_output "$STACK_PREFIX-web" Url)"
[[ -n "$url" ]] && echo "App: $url"
sm="$(stack_output "$STACK_PREFIX-ingestion" EnrichmentStateMachineArn)"
if [[ -n "$sm" ]]; then
  echo "Recent enrichment runs:"
  aws stepfunctions list-executions --state-machine-arn "$sm" --max-results 5 \
    --query 'executions[].[name,status,startDate]' --output text | sed 's/^/  /'
fi
