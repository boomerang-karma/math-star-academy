#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# One-time account preparation for an environment.
#
#   scripts/aws/bootstrap.sh --env dev [--with-cicd]
#
# 1. CDK-bootstraps the main region and us-east-1 (the WAF for CloudFront lives there).
# 2. Optionally deploys the CI/CD stack: a GitHub OIDC provider and a deploy role that
#    can only assume the CDK bootstrap roles (no long-lived AWS keys in GitHub).
#
# The default bootstrap grants CloudFormation AdministratorAccess. For a tighter
# boundary pass --execution-policy <policy-arn> (see docs/SECURITY.md#deployment).
set -euo pipefail
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

ENV_NAME=""
WITH_CICD=false
EXECUTION_POLICY="arn:aws:iam::aws:policy/AdministratorAccess"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env) ENV_NAME="$2"; shift 2 ;;
    --with-cicd) WITH_CICD=true; shift ;;
    --execution-policy) EXECUTION_POLICY="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
[[ -n "$ENV_NAME" ]] || die "--env is required"

require_cmd aws jq npx
use_environment "$ENV_NAME"

log "Bootstrapping CDK in $ACCOUNT_ID ($AWS_REGION and us-east-1)"
regions=("$AWS_REGION")
[[ "$AWS_REGION" != "us-east-1" ]] && regions+=("us-east-1")
targets=()
for region in "${regions[@]}"; do targets+=("aws://$ACCOUNT_ID/$region"); done
cdk bootstrap "${targets[@]}" \
  --cloudformation-execution-policies "$EXECUTION_POLICY" \
  --tags project=leadintel --tags environment="$ENV_NAME" \
  -c env="$ENV_NAME"

if [[ "$WITH_CICD" == true ]]; then
  [[ -n "$(config_value "$ENV_NAME" github_repository)" ]] \
    || die "set github_repository in infra/config/$ENV_NAME.json to deploy the CI/CD stack"
  [[ -d "$BUILD_DIR/lambda" ]] || "$LEADGEN_ROOT/scripts/build/lambda_bundle.sh"
  log "Deploying the GitHub OIDC deploy role"
  cdk deploy "$STACK_PREFIX-cicd" -c env="$ENV_NAME" --require-approval never
  log "Deploy role: $(stack_output "$STACK_PREFIX-cicd" DeployRoleArn)"
fi
log "Bootstrap complete. Next: scripts/aws/setup.sh --env $ENV_NAME"
