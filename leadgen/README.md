# LeadIntel

A lead-intelligence platform for AWS. LeadIntel collects company and buyer
signals from these sources:

- **ScrapeBadger**: LinkedIn company pages and jobs, Google Maps, Search and
  News, company websites
- **LinkedIn Lead Gen Forms**
- **Google Analytics 4**
- **your own website**

It resolves them into one graph of organizations and people in which every
value carries its provenance, then scores leads with explanations a salesperson
can read. Each lead gets a Palantir-style 360-degree view, with an optional
account brief written by Claude on Amazon Bedrock.

```
sources -> connectors -> bronze (S3) + source records -> entity resolution -> golden records,
links, signals -> explainable scores -> API -> Lead 360 UI (+ AI brief)
```

- **Holistic plan:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). It covers
  goals, data flow, the AWS deployment, security, the cost model, delivery
  phases and risks.
- **Everything else:** [the documentation index](#documentation).

## What's in the box

| Area | Highlights |
| --- | --- |
| Connectors | ScrapeBadger playbooks (hiring scans, company profiles, news triggers, website enrichment, local discovery) with credit budgets; LinkedIn Lead Sync with webhook signature checks; GA4 per-visitor reports; first-party beacon |
| Ontology | Organizations, people, typed relationships, decayed signals; golden records with per-attribute source, time, confidence and losing alternatives; full lineage |
| Entity resolution | Blocking on selective keys, log-odds matching with stored evidence, conservative clustering, human review queue, audited merges |
| Scoring | Fit / intent / engagement with decay, diminishing returns and saturation; tiers A-D; "hot" flag; every point explained |
| Security | KMS envelope encryption of contact fields, HMAC blind indexes, RBAC plus PostgreSQL row-level security, hash-chained audit log anchored to S3 Object Lock, SSRF guard, log redaction, WAF, strict CSP |
| Privacy | Lawful basis per record, consent ledger, suppression list, DSAR export and erasure, nightly retention, person-scraping gate |
| AWS | CDK (Python): VPC, Aurora PostgreSQL Serverless v2 + RDS Proxy (IAM auth), Lambda, SQS, Step Functions, EventBridge, API Gateway, CloudFront + WAF, Cognito (MFA), alarms, budgets, GitHub OIDC |
| Operations | `setup.sh` / `teardown.sh` with safety rails, secret rotation, backup/restore scripts, runbook |
| Web | React + TypeScript SPA: ranked worklist, Lead 360 (score explanation, contact with masking and consent, AI brief, signal timeline, relationship graph, golden records), entity lineage, review queue |

## Repository layout

| Path | Module | Responsibility |
| --- | --- | --- |
| `src/leadintel/core` | core | Settings (`LEADINTEL_*`), errors, deterministic ids, JSON logging with redaction |
| `src/leadintel/ontology` | ontology | Entity, attribute, signal and provenance models; data classification |
| `src/leadintel/security` | security | Envelope crypto, blind indexes, RBAC, audit chain, secrets, SSRF guard, webhook and JWT verification |
| `src/leadintel/connectors` | connectors | ScrapeBadger gateway, mappers and playbooks; LinkedIn Lead Sync; GA4; first-party events |
| `src/leadintel/pipeline` | pipeline | Normalization, ICP, entity resolution, scoring, orchestration, Lambda handlers |
| `src/leadintel/compliance` | compliance | Consent, DSAR (export, erasure), retention |
| `src/leadintel/storage` | storage | Connections, migration runner, raw and export stores, repositories |
| `src/leadintel/api` | api | FastAPI app, routers, middleware, Lambda adapter |
| `src/leadintel/ai` | ai | Account briefs with Claude on Amazon Bedrock |
| `database/` | database scripts | Migrations, seeds, local PostgreSQL, backup/restore ([README](database/README.md)) |
| `infra/` | AWS infrastructure | CDK app, nine stacks, per-environment config |
| `scripts/aws/` | AWS lifecycle | `bootstrap`, `setup`, `status`, `rotate-secrets`, `teardown` |
| `scripts/build/`, `scripts/dev/` | build and dev | Lambda bundle (arm64), local env and API runner |
| `web/` | web UI | Vite + React SPA, unit tests (Vitest), browser tests (Playwright) |
| `tests/` | tests | `unit`, `contract`, `integration`, `infra`, `scripts` |
| `config/icp.json` | configuration | Ideal customer profile used by scoring |
| `docs/` | documentation | Architecture, ontology, sources, security, compliance, runbook, roadmap, ADRs |

## Quick start (local, no AWS)

Prerequisites:

- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- Node.js 22
- PostgreSQL 16 server binaries (`postgresql-16` on Debian/Ubuntu)

```bash
cd leadgen
make install        # Python and web dependencies
make demo           # local PostgreSQL on :54329, migrations, seeds, synthetic demo data
make run-api        # API on http://127.0.0.1:8000 (local-dev identities, no login)
make run-web        # in a second terminal: http://localhost:5173
```

The demo loads fictional companies and people through every connector's mapper.
It resolves them, queues a few uncertain matches for review, and scores the
leads. In the web app, switch personas in the header (admin, analyst, sales
rep, compliance, viewer) to see permissions, masking and row-level security
change what is visible.

## Tests

| Command | Covers | Needs |
| --- | --- | --- |
| `make lint` | Ruff, formatting, strict mypy, shellcheck | - |
| `make test` | Unit, contract (recorded vendor fixtures), script safety rails | - |
| `make test-integration` | Migrations, grants, RLS, audit chain, end-to-end pipeline, API, DSAR worker on a real PostgreSQL 16 | PostgreSQL 16 binaries, or `LEADINTEL_TEST_DATABASE_URL` |
| `make test-infra` | CDK synthesis and security-posture assertions | Node.js (jsii) |
| `make test-web` | TypeScript checks and Vitest unit tests | Node.js |
| `make test-e2e` | Playwright against the production build under the production CSP | Chromium (`PLAYWRIGHT_CHROMIUM_EXECUTABLE` to reuse a local one) |
| `make test-all` | Everything CI runs | |

CI: [`.github/workflows/leadgen-ci.yml`](../.github/workflows/leadgen-ci.yml).

## Deploying to AWS

```bash
# 1. Edit infra/config/dev.json: account, a unique cognito_domain_prefix, callback URLs, alarm email.
scripts/aws/bootstrap.sh --env dev                       # once per account
export SCRAPEBADGER_API_KEY=...                          # secrets come from your shell
scripts/aws/setup.sh --env dev --admin-email you@example.com
scripts/aws/status.sh --env dev
scripts/aws/teardown.sh --env dev --dry-run              # when you are done
```

`setup.sh` performs these steps in order:

1. Builds the arm64 Lambda bundle and the SPA.
2. Deploys every stack.
3. Stores the secrets.
4. Runs migrations inside the VPC.
5. Creates the first admin.
6. Prints the URL and the NAT egress IPs to allow-list at ScrapeBadger.

Production needs a custom domain and certificate, a pinned account id, and
deletion protection. See [docs/RUNBOOK.md](docs/RUNBOOK.md) and
[docs/SECURITY.md](docs/SECURITY.md#deployment).

## Documentation

| Document | Contents |
| --- | --- |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | The end-to-end plan: principles, data flow, AWS view, scalability, costs, phases, risks |
| [ONTOLOGY.md](docs/ONTOLOGY.md) | Object, link and signal types; provenance; survivorship; lineage |
| [DATA_SOURCES.md](docs/DATA_SOURCES.md) | ScrapeBadger, LinkedIn Lead Sync, GA4, beacon; adding a source |
| [SECURITY.md](docs/SECURITY.md) | Threat model and controls; deployment trust |
| [COMPLIANCE.md](docs/COMPLIANCE.md) | GDPR/CCPA posture, processing register, retention, DSARs, scraping policy |
| [RUNBOOK.md](docs/RUNBOOK.md) | Operations: deploys, alarms, DSARs, rotations, restores |
| [ROADMAP.md](docs/ROADMAP.md) | Delivery phases and exit criteria |
| [adr/](docs/adr/README.md) | Architecture decision records |

## Status and limits

- **Verified in this repository:**
  - The whole stack runs locally, including the demo, API and web app.
  - All test suites pass.
  - The CDK app synthesizes with its posture assertions.
- **Not yet verified against live services:**
  - **AWS deployment.** It has not been exercised against a live account from
    here; deploy to a sandbox account first.
  - **LinkedIn Lead Sync** needs LinkedIn program approval. Its mapping is
    pinned to a fixture shaped after LinkedIn's documented response; re-record
    the fixture once access is granted.
- **Legal review.** Person-level scraping is disabled by default. Enable it only
  after the legal steps in [docs/COMPLIANCE.md](docs/COMPLIANCE.md#scraping-policy).
