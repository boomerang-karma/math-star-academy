#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# Build, deploy and initialize an environment end to end.
#
#   scripts/aws/setup.sh --env dev [--admin-email you@example.com] [--skip-build] [--only <stack>]
#
# Secrets are read from your shell, never from arguments or files in the repo:
#   SCRAPEBADGER_API_KEY            ScrapeBadger key (restrict it to the NAT IPs printed at the end)
#   LINKEDIN_CLIENT_SECRET          LinkedIn app secret (webhook signatures)
#   LINKEDIN_ACCESS_TOKEN           Lead Sync access token
#   GA4_SERVICE_ACCOUNT_FILE        path to a read-only GA4 service-account JSON
#
# Steps: preflight -> build bundle + SPA -> cdk deploy -> store secrets ->
#        migrate + seed (in-VPC Lambda) -> optional first admin -> summary.
# Re-running is safe: every step is idempotent.
set -euo pipefail
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

ENV_NAME=""
ADMIN_EMAIL=""
SKIP_BUILD=false
ONLY=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env) ENV_NAME="$2"; shift 2 ;;
    --admin-email) ADMIN_EMAIL="$2"; shift 2 ;;
    --skip-build) SKIP_BUILD=true; shift ;;
    --only) ONLY="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
[[ -n "$ENV_NAME" ]] || die "--env is required"

# ------------------------------------------------------------------ preflight
require_cmd aws jq node npx uv
use_environment "$ENV_NAME"
log "Environment '$ENV_NAME' -> account $ACCOUNT_ID, region $AWS_REGION"

prefix="$(config_value "$ENV_NAME" cognito_domain_prefix)"
[[ "$prefix" != *changeme* ]] \
  || die "set a globally unique cognito_domain_prefix in infra/config/$ENV_NAME.json (currently '$prefix')"

for region in "$AWS_REGION" us-east-1; do
  stack_exists CDKToolkit "$region" \
    || die "CDK is not bootstrapped in $region; run scripts/aws/bootstrap.sh --env $ENV_NAME"
done

# ------------------------------------------------------------------ build
if [[ "$SKIP_BUILD" == false ]]; then
  log "Building the Lambda bundle"
  "$LEADGEN_ROOT/scripts/build/lambda_bundle.sh"
  if [[ -f "$LEADGEN_ROOT/web/package.json" ]]; then
    require_cmd npm
    log "Building the web app"
    (cd "$LEADGEN_ROOT/web" && npm ci --no-audit --no-fund && npm run build)
  fi
fi
[[ -d "$BUILD_DIR/lambda" ]] || die "missing build/lambda; run without --skip-build"

# ------------------------------------------------------------------ deploy
approval="never"
is_protected "$ENV_NAME" && approval="broadening"   # humans approve IAM/security-group widening in prod
mkdir -p "$BUILD_DIR"
outputs="$BUILD_DIR/outputs-$ENV_NAME.json"
if [[ -n "$ONLY" ]]; then
  log "Deploying $STACK_PREFIX-$ONLY"
  cdk deploy "$STACK_PREFIX-$ONLY" --exclusively -c env="$ENV_NAME" --require-approval "$approval" \
    --outputs-file "$outputs"
else
  log "Deploying all stacks (this takes a while the first time: Aurora, CloudFront)"
  cdk deploy --all -c env="$ENV_NAME" --require-approval "$approval" --concurrency 3 \
    --outputs-file "$outputs"
fi

# ------------------------------------------------------------------ secrets
store_if_set() {
  local var="$1" name="$2"
  if [[ -n "${!var:-}" ]]; then
    printf '%s' "${!var}" | put_secret "$STACK_PREFIX/$name"
    log "Stored $name"
  else
    warn "$var not set: $name keeps its current value"
  fi
}
store_if_set SCRAPEBADGER_API_KEY scrapebadger-api-key
store_if_set LINKEDIN_CLIENT_SECRET linkedin-client-secret
store_if_set LINKEDIN_ACCESS_TOKEN linkedin-access-token
if [[ -n "${GA4_SERVICE_ACCOUNT_FILE:-}" ]]; then
  [[ -f "$GA4_SERVICE_ACCOUNT_FILE" ]] || die "GA4_SERVICE_ACCOUNT_FILE does not exist"
  jq -e '.client_email and .private_key' "$GA4_SERVICE_ACCOUNT_FILE" >/dev/null \
    || die "GA4_SERVICE_ACCOUNT_FILE is not a service-account key"
  put_secret "$STACK_PREFIX/ga4-service-account" < "$GA4_SERVICE_ACCOUNT_FILE"
  log "Stored ga4-service-account"
fi

# ------------------------------------------------------------------ database
migrator="$(stack_output "$STACK_PREFIX-ingestion" MigratorFunctionName)"
if [[ -n "$migrator" ]]; then
  log "Running migrations and seeds inside the VPC ($migrator)"
  result="$(mktemp)"
  trap 'rm -f "$result"' EXIT
  status="$(aws lambda invoke --function-name "$migrator" --payload '{"seed": true}' \
    --cli-binary-format raw-in-base64-out --cli-read-timeout 900 "$result" \
    --query 'FunctionError' --output text)"
  if [[ "$status" != "None" ]]; then
    cat "$result" >&2
    die "migration failed (see above and the Migrator log group)"
  fi
  log "Database: $(jq -c '{applied, login_users}' "$result")"
fi

# ------------------------------------------------------------------ first admin
if [[ -n "$ADMIN_EMAIL" ]]; then
  pool="$(stack_output "$STACK_PREFIX-security" UserPoolId)"
  if aws cognito-idp admin-get-user --user-pool-id "$pool" --username "$ADMIN_EMAIL" >/dev/null 2>&1; then
    log "Admin $ADMIN_EMAIL already exists"
  else
    aws cognito-idp admin-create-user --user-pool-id "$pool" --username "$ADMIN_EMAIL" \
      --user-attributes Name=email,Value="$ADMIN_EMAIL" Name=email_verified,Value=true \
      --desired-delivery-mediums EMAIL >/dev/null
    log "Invited $ADMIN_EMAIL (temporary password by email; TOTP MFA is enforced at first sign-in)"
  fi
  aws cognito-idp admin-add-user-to-group --user-pool-id "$pool" --username "$ADMIN_EMAIL" \
    --group-name leadintel-admin
fi

# ------------------------------------------------------------------ summary
echo
log "Environment '$ENV_NAME' is up"
echo "  App URL:        $(stack_output "$STACK_PREFIX-web" Url)"
echo "  Sign-in:        $(stack_output "$STACK_PREFIX-security" HostedUiDomain)"
echo "  API (origin):   https://$(stack_output "$STACK_PREFIX-api" ApiDomain) (direct calls are rejected)"
echo "  NAT egress IPs: restrict the ScrapeBadger key to these addresses:"
for i in 1 2 3; do
  ip="$(stack_output "$STACK_PREFIX-network" "NatEgressIp$i")"
  [[ -n "$ip" ]] && echo "                  $ip"
done
echo "  Outputs file:   $outputs"
