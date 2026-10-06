# Roadmap

Delivery is phased so that every phase ends with something in use, measured
against explicit exit criteria. Durations assume a small team (two engineers, a
part-time product owner, and access to two or three sales reps for feedback).

## Phase 0: Foundation (this repository)

**Delivered**

- The modular codebase:
  - **core** and **ontology**: settings, errors, ids, logging, entity and
    signal models
  - **security**: envelope crypto, blind indexes, RBAC/RLS, audit chain,
    SSRF guard, redaction, webhook and JWT verification
  - **connectors**: ScrapeBadger playbooks, LinkedIn Lead Sync, GA4,
    first-party beacon
  - **pipeline**: normalization, entity resolution with a review queue,
    explainable scoring
  - **compliance**: consent, DSAR, retention
  - **api** and **ai** (Claude account briefs)
- Database: nine versioned migrations, seeds, a migration runner with drift
  detection, and local/backup/restore scripts.
- AWS: nine CDK stacks and lifecycle scripts (bootstrap, setup, status,
  rotate, teardown with safety rails).
- Web: React SPA (worklist, Lead 360, lineage, review queue) under a strict
  CSP.
- Tests: unit, contract, integration (PostgreSQL 16), infrastructure posture,
  scripts, web unit and browser tests, all in CI.

**Exit criteria**

- CI is green.
- `make demo` stitches the synthetic dataset end to end.
- A dev environment deploys and tears down cleanly.

## Phase 1: Pilot (about 6 weeks)

**Scope**

- Deploy dev and staging, with alarms routed.
- **Configure.** Set the ICP in `config/icp.json` with sales leadership, and
  the discovery tasks per market.
- **ScrapeBadger** in production use: company profiles, hiring scans, news
  triggers, website enrichment.
- **Website tracking.** Install the beacon snippet and register the GA4
  custom dimension `lead_visitor_id`.
- **LinkedIn.** Apply for LinkedIn Lead Sync access. Approval takes time, so
  start in week 1.
- **People.** Onboard two or three reps and one analyst. Clear the review
  queue weekly.

**Measures**

| Measure | Target |
| --- | --- |
| A-tier leads judged "worth working" by reps | ≥ 70% |
| Duplicate entities found by reps | < 2% of viewed entities |
| Cost per worked lead (AWS + credits) | Tracked; baseline set |
| Time from signal to lead in worklist | < 2 hours |

**Exit criteria**

- The targets above are met for two consecutive weeks.
- Score weights are adjusted once from rep feedback, through a reviewed change
  to `pipeline/scoring.py` with tests.

## Phase 2: Production (about 6 weeks)

**Security and privacy go-live gates**

- External penetration test, with findings fixed.
- DPIA and LIA signed off.
- Art. 14 notice process in place for any scraped person data.
- Vendor DPAs signed (AWS, ScrapeBadger, Google, LinkedIn).

**Platform**

- Production deploy with a custom domain and ACM certificate.
- Cognito users onboarded with MFA. Territories mapped.
- **LinkedIn Lead Sync live**, with webhook validation and deletion handling.
- **CRM sync** (HubSpot or Salesforce): push A/B-tier leads with their
  explanation and brief, and pull opportunity outcomes back.
- **Operations**: on-call rotation for alarms, a restore drill completed,
  runbook walkthrough.

**Exit criteria**

- A restore drill completes within the RTO.
- A DSAR dry run completes within the SLA.
- Alarms are acknowledged within agreed times.

## Phase 3: Intelligence (next quarter)

- **Outcome feedback loop.** Opportunity outcomes from the CRM become labels:
  - calibrate scoring weights (logistic regression on the factor
    contributions, so explanations stay intact)
  - calibrate resolution thresholds from review decisions
- **Lookalike accounts.** Embeddings of firmographics and descriptions in
  pgvector (migration `V0009` prepares the table), using Bedrock embeddings.
  "More like this" from any won account.
- **Analytics.** The curated S3 zone with an Athena/Glue catalog, and BI
  dashboards on the masked view `sales.v_lead_bi`.
- **Brief improvements.** Cite signal ids in the UI; add a feedback button that
  feeds evals.

**Exit criteria**

- Measurable lift in conversion rate of A/B tiers against the Phase 1
  baseline.
- Calibration documented and reproducible.

## Phase 4: Scale and enterprise (demand-driven)

- **Multi-tenancy.** `tenant_id` already flows through principals and
  encryption contexts. Add per-tenant KMS keys, tenant-scoped RLS and tenant
  onboarding.
- **Enterprise identity.** SAML/OIDC federation (Okta, Entra ID) through
  Cognito, and SCIM provisioning.
- **Data residency.** An EU-region deployment (the config already selects the
  region per environment) and a regional data map.
- **Security hardening backlog:**
  - backend-for-frontend auth with HttpOnly cookies (instead of
    `sessionStorage` tokens)
  - Workload Identity Federation for GA4
  - zero-downtime origin-verify rotation (accept current and previous values)
  - versioned blind-index keys with dual lookup and a re-index job
    ([RUNBOOK.md](RUNBOOK.md#blind-index-key))
- **Privacy.** Write website-form consents to the consent ledger, not only as
  the record's lawful basis.
- **More sources.** A CRM as a first-class connector, intent-data vendors, and
  technographic providers, each through the [connector checklist](DATA_SOURCES.md#adding-a-source).

## Backlog (unscheduled)

- **Cost.** Optional RDS Proxy and interface endpoints per environment.
- **Ops UI.** A screen for connector runs and credit burn.
- **Notifications.** Slack alerts for hot leads in the rep's territory.
- **Data quality.** Freshness SLOs per source, plus re-crawl of stale
  organizations.
