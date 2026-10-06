#!/usr/bin/env bash
# Shared helpers for scripts/aws/*.sh. Source this file; do not execute it.
# shellcheck disable=SC2034  # variables here are used by the sourcing scripts

set -euo pipefail

LEADGEN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INFRA_DIR="$LEADGEN_ROOT/infra"
BUILD_DIR="$LEADGEN_ROOT/build"

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[1;33mWARN:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

require_cmd() {
  local cmd
  for cmd in "$@"; do
    command -v "$cmd" >/dev/null 2>&1 || die "required command not found: $cmd"
  done
}

config_file() {
  local file="$INFRA_DIR/config/$1.json"
  [[ -f "$file" ]] || die "no deployment config for environment '$1' ($file)"
  printf '%s' "$file"
}

# config_value <env> <key>  -> raw value, empty when null/missing
config_value() {
  jq -r --arg k "$2" '.[$k] // empty' "$(config_file "$1")"
}

is_protected() {
  [[ "$(jq -r '.deletion_protection' "$(config_file "$1")")" == "true" ]]
}

# Export region/account for the AWS CLI and CDK, refusing to touch the wrong account.
use_environment() {
  local env="$1" expected actual
  AWS_REGION="$(config_value "$env" region)"
  export AWS_REGION AWS_DEFAULT_REGION="$AWS_REGION" CDK_DEFAULT_REGION="$AWS_REGION"
  actual="$(aws sts get-caller-identity --query Account --output text)" \
    || die "AWS credentials are not configured (aws sts get-caller-identity failed)"
  expected="$(config_value "$env" account)"
  if [[ -n "$expected" && "$expected" != "$actual" ]]; then
    die "config for '$env' pins account $expected but your credentials are for $actual"
  fi
  if is_protected "$env" && [[ -z "$expected" ]]; then
    die "protected environment '$env' must pin an account id in its config"
  fi
  export CDK_DEFAULT_ACCOUNT="$actual"
  ACCOUNT_ID="$actual"
  STACK_PREFIX="leadintel-$env"
}

# stack_output <stack-name> <output-key> [region]
stack_output() {
  aws cloudformation describe-stacks --stack-name "$1" --region "${3:-$AWS_REGION}" \
    --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue | [0]" --output text 2>/dev/null \
    | grep -v '^None$' || true
}

stack_exists() {
  aws cloudformation describe-stacks --stack-name "$1" --region "${2:-$AWS_REGION}" >/dev/null 2>&1
}

# confirm <prompt> <exact expected answer>
confirm() {
  local answer
  read -r -p "$1 " answer
  [[ "$answer" == "$2" ]] || die "confirmation did not match; nothing was changed"
}

cdk() {
  (cd "$INFRA_DIR" && npx --yes aws-cdk@2 "$@")
}

# put_secret <secret-id> : reads the value from stdin so it never appears in argv or logs
put_secret() {
  aws secretsmanager put-secret-value --secret-id "$1" --secret-string file:///dev/stdin >/dev/null
}

# Print the header comment of the calling script (everything up to `set -euo pipefail`).
usage() {
  awk 'NR == 1 { next } /^set -euo/ { exit } /^# shellcheck/ { next } { sub(/^# ?/, ""); print }' "$0"
}
