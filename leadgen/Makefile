# LeadIntel developer entry points. `make help` lists everything.
SHELL := /bin/bash
.DEFAULT_GOAL := help
ENV ?= dev
PY := .venv/bin/python
SH_SCRIPTS := scripts/aws/*.sh scripts/build/*.sh scripts/dev/*.sh database/scripts/*.sh

.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ------------------------------------------------------------------ setup
.PHONY: install
install: ## Install Python (uv) and web (npm) dependencies
	uv sync --all-groups
	cd web && npm ci --no-audit --no-fund

# ------------------------------------------------------------------ quality
.PHONY: lint
lint: ## Ruff, formatting, strict mypy, shellcheck
	.venv/bin/ruff check src tests infra
	.venv/bin/ruff format --check src tests infra
	.venv/bin/mypy
	.venv/bin/shellcheck -x $(SH_SCRIPTS)

.PHONY: fmt
fmt: ## Auto-format Python
	.venv/bin/ruff format src tests infra
	.venv/bin/ruff check --fix src tests infra

.PHONY: test
test: ## Unit + contract + script tests (no database, no network)
	$(PY) -m pytest tests/unit tests/contract tests/scripts -q

.PHONY: test-integration
test-integration: ## Integration tests on PostgreSQL 16 (local binaries or LEADINTEL_TEST_DATABASE_URL)
	$(PY) -m pytest tests/integration -q

.PHONY: test-infra
test-infra: ## Synthesize the CDK app and assert its security posture
	$(PY) -m pytest tests/infra -q

.PHONY: test-web test-e2e
test-web: ## Web unit tests and type check
	cd web && npm run typecheck && npm test

test-e2e: ## Browser tests against the production build under the production CSP
	cd web && npx playwright test

.PHONY: test-all
test-all: lint test test-integration test-infra test-web test-e2e ## Everything CI runs

# ------------------------------------------------------------------ local stack
.PHONY: db-up db-down db-reset demo
db-up: ## Start the local PostgreSQL 16
	database/scripts/local_postgres.sh start
db-down: ## Stop the local PostgreSQL
	database/scripts/local_postgres.sh stop
db-reset: ## Recreate the local database (migrate + seed)
	database/scripts/reset_local.sh
demo: ## Recreate the local database and load the synthetic demo dataset
	database/scripts/reset_local.sh --demo

.PHONY: run-api run-web
run-api: ## Run the API on :8000 with local-dev identities
	scripts/dev/run_api.sh
run-web: ## Run the web app on :5173 (proxies /api to :8000)
	cd web && npm run dev

# ------------------------------------------------------------------ AWS
.PHONY: bundle synth bootstrap deploy status destroy destroy-dry-run
bundle: ## Build the arm64 Lambda bundle into build/lambda
	scripts/build/lambda_bundle.sh
synth: bundle ## Synthesize CloudFormation for ENV (default dev)
	cd infra && npx --yes aws-cdk@2 synth --all -c env=$(ENV) --quiet
bootstrap: ## One-time CDK bootstrap for ENV
	scripts/aws/bootstrap.sh --env $(ENV)
deploy: ## Build, deploy, migrate and initialize ENV
	scripts/aws/setup.sh --env $(ENV)
status: ## Show stack status for ENV
	scripts/aws/status.sh --env $(ENV)
destroy-dry-run: ## Print the teardown plan for ENV without changing anything
	scripts/aws/teardown.sh --env $(ENV) --dry-run
destroy: ## Tear down ENV (asks for typed confirmation)
	scripts/aws/teardown.sh --env $(ENV)
