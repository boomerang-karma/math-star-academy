# Security

LeadIntel stores personal data about prospects, credentials for paid data
sources, and a commercially sensitive picture of the market. This document is
the threat model and the controls that answer it, layer by layer, with pointers
to where each control lives. For privacy law, see [COMPLIANCE.md](COMPLIANCE.md).
For procedures, see [RUNBOOK.md](RUNBOOK.md).

## Assets and trust boundaries

| Asset | Why it matters |
| --- | --- |
| Contact details (email, personal phone) | Personal data; regulatory and reputational exposure |
| Person profiles, consent and DSAR records | Personal data; evidence of lawful processing |
| The entity graph, scores and briefs | Commercially sensitive |
| Source credentials (ScrapeBadger key, LinkedIn secrets, GA4 service account) | Billing abuse, data exfiltration from vendors |
| The audit log | Evidence; must be tamper-evident |
| Deployment credentials | Full control of the environment |

Trust boundaries:

1. The browser and CloudFront (internet).
2. CloudFront and API Gateway (shared-secret header).
3. API Gateway and the Lambdas (JWT authorizer).
4. The Lambdas and PostgreSQL (IAM-authenticated, TLS, RLS).
5. The Lambdas and third-party APIs (NAT egress, SSRF guard).
6. The Lambdas and Bedrock (IAM, AWS network).
7. CI and AWS (OIDC).

## Threat model

| # | Threat (STRIDE) | Scenario | Controls |
| --- | --- | --- | --- |
| T1 | Spoofing | Stolen or forged tokens call the API | Cognito MFA required, 14+ char passwords, threat protection (full function); JWT verified by API Gateway **and** in the app (signature, issuer, expiry, `token_use = access`, pinned `client_id`); 1-hour access tokens; refresh-token revocation on logout |
| T2 | Spoofing | Requests bypass CloudFront/WAF and hit API Gateway directly | API requires the `X-Origin-Verify` secret, compared in constant time, on every request; secret in Secrets Manager, rotatable |
| T3 | Spoofing | Forged LinkedIn webhook injects leads | HMAC-SHA256 over the raw body (`X-LI-Signature`), constant-time compare; challenge-response validation |
| T4 | Tampering | Someone edits or deletes audit entries to hide access | Append-only by privilege (no `UPDATE`/`DELETE` grants) and trigger (even the owner is blocked); hash chain computed in the database; hourly anchor of the chain head to S3 Object Lock (compliance mode in production); `GET /api/v1/audit/verify` |
| T5 | Tampering | A wrong or malicious merge corrupts the graph | Entity-entity merges only through `graph.merge_entities` (validates, re-points every reference) by `entities:merge` holders; audited; lineage kept |
| T6 | Repudiation | A user denies reading contact data | Every unmasked PII read, merge, status change, suppression, DSAR action, connector run and authorization denial is audited with actor, request id and IP |
| T7 | Information disclosure | A sales rep reads leads outside their territory | PostgreSQL RLS on leads, people and person source records, driven by per-transaction session settings (`set_config(..., true)`); the API role cannot bypass RLS |
| T8 | Information disclosure | Database snapshot, backup or log leak exposes contact data | Field-level envelope encryption (contact fields unreadable without KMS access and the encryption context); blind indexes instead of plaintext keys; log redaction; KMS-encrypted storage |
| T9 | Information disclosure | SSRF through website enrichment reaches the metadata service or VPC hosts | `security/ssrf.py`: http(s) only, every resolved address must be public (blocks 169.254.169.254, private, loopback, link-local, CGNAT and other reserved ranges) |
| T10 | Information disclosure | Prompt injection in scraped text makes the AI brief leak data or mislead | Brief input excludes contact data; scraped text fenced as untrusted data; the model has no tools that act; output validated against a schema; claims must cite signals |
| T11 | Information disclosure | XSS steals tokens or data | React escaping; no `dangerouslySetInnerHTML`; strict CSP (`script-src 'self'`, no inline scripts or styles, verified by the browser tests); only http(s) URLs rendered as links; tokens in tab-scoped `sessionStorage` |
| T12 | Denial of service / cost | Floods of beacon or API requests; credit burn | WAF rate limits (global and beacon-specific); API Gateway throttling; 1 MB request-body cap; credit budgets per run and a daily credit alarm; AWS Budgets |
| T13 | Elevation of privilege | A compromised Lambda escalates in AWS | One role per function with resource-scoped grants; secrets readable only by the functions that need them; PII key use conditioned on the encryption context; no wildcard admin policies (asserted in `tests/infra`) |
| T14 | Elevation of privilege | Supply-chain compromise via dependencies or CI | Locked dependency versions (`uv.lock`, `package-lock.json`); GitHub OIDC with branch/environment-scoped trust (no stored AWS keys); production IAM/SG broadening needs human approval |

## Identity and access

**Users.** Users authenticate through the Cognito user pool:

- Self sign-up is disabled. An admin invites users (`setup.sh --admin-email`
  creates the first one).
- MFA is required (TOTP).
- Passwords need at least 14 characters with all character classes.
- Recovery is by email only.
- Threat protection runs in full-function mode, so risky sign-ins are blocked.

The SPA uses the Hosted UI with the authorization code flow and PKCE
(`web/src/auth/`). There is no client secret.

**Roles** are Cognito groups named `leadintel-<role>`. Permissions per role
(`security/authz.py`):

| Permission | admin | analyst | sales_rep | compliance_officer | viewer |
| --- | :-: | :-: | :-: | :-: | :-: |
| `leads:read`, `entities:read` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `leads:write` | ✓ | ✓ | ✓ | | |
| `leads:assign` | ✓ | | | | |
| `entities:merge` (review queue) | ✓ | ✓ | | | |
| `pii:read` (unmasked contact data) | ✓ | | ✓ | ✓ | |
| `ai:brief` | ✓ | ✓ | ✓ | | |
| `connectors:run` | ✓ | ✓ | | | |
| `connectors:configure`, `users:admin` | ✓ | | | | |
| `compliance:dsar`, `compliance:suppress`, `audit:read` | ✓ | | | ✓ | |
| Row scope | global | global | **territory** | global | **territory** |

Sales reps see leads in their territories or assigned to them, the
organizations, and only the people attached to visible leads. Analysts work the
data across territories but see contact details masked. Enforcement happens in
two places:

- The API checks permissions per route (`api/deps.py:require`) and audits every
  denial.
- The database applies row scope through RLS (`V0007`), so a bug in a query
  cannot widen it.

## Field-level encryption

Restricted attributes (email, personal phone) use envelope encryption
(`security/crypto.py`):

- **Encryption.** Each value is encrypted with **AES-256-GCM** under a data
  key. The data key is wrapped by the `pii` KMS key and stored in the envelope
  (`b"LI\x01" | wrapped key | nonce | ciphertext+tag`).
- **Encryption context.** The context (tenant, purpose, application) is bound
  into the KMS call, so the key policy can require it and CloudTrail records
  it. It is also bound into the GCM associated data, so a ciphertext cannot be
  transplanted to another tenant or purpose.
- **Data-key cache.** Data keys are cached briefly and for a bounded number of
  messages, the same trade-off the AWS Encryption SDK's caching makes.
- **Blind indexes** (`security/blind_index.py`) are
  `HMAC-SHA256(key, field || 0x00 || value)` with a 32+ byte key held in
  Secrets Manager. They answer equality lookups ("do we know this email?", "is
  this phone suppressed?") without plaintext. The field name is mixed in, so the
  same value has unrelated indexes in different columns.
- **Rotation.** The KMS keys rotate yearly (automatic). The blind-index key
  cannot be rotated in place: a new key invalidates every index. See
  [RUNBOOK.md](RUNBOOK.md#blind-index-key).

Only holders of `pii:read` get decrypted values, and every such read is audited.
Everyone else gets masked values (`j***@acme.com`).

## Data protection at rest and in transit

**At rest**

| Data | Protection |
| --- | --- |
| Aurora storage, Performance Insights, database secrets | `database` KMS key |
| S3 bronze, curated and audit zones | `data` KMS key; block public access; TLS-only bucket policies; versioning |
| Audit anchor bucket | Object Lock: governance mode in dev and staging, compliance mode for 7 years in production |
| Secrets | Secrets Manager, KMS-encrypted |

**In transit**

- TLS everywhere.
- CloudFront requires TLS 1.2 (2021 policy) with a custom domain and certificate.
- The API origin is HTTPS-only (TLS 1.2).
- The database is reached through RDS Proxy with TLS required and **IAM
  authentication**. Login users get short-lived tokens; there are no static
  passwords in Lambda environments.

## Network

The VPC has three subnet tiers:

- **public**: NAT gateways only
- **private with egress**: Lambdas
- **isolated**: Aurora

The rest of the network design:

- Security groups allow only Lambda → RDS Proxy → Aurora.
- VPC endpoints (S3, Secrets Manager, KMS, SQS, STS, CloudWatch Logs, Step
  Functions) keep AWS API traffic off the internet.
- Outbound calls to vendors leave through NAT gateways with **static Elastic
  IPs** (stack outputs). ScrapeBadger keys are restricted to those IPs.
- VPC flow logs are on. The default security group is locked down.

## Edge and web application

**WAF** (web ACL in us-east-1) runs these rules:

- AWS IP reputation list
- Common rule set
- Known bad inputs
- SQL injection
- an IP rate limit across the site
- a stricter rate limit for the public beacon

WAF logs redact the `authorization` and `cookie` headers.

**CloudFront** serves the SPA from a private bucket (Origin Access Control) and
proxies `/api/*`. One origin means no CORS for the app and no cross-site
cookies. Response headers:

- HSTS (2 years, preload)
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: no-referrer`
- `Permissions-Policy`
- a strict **CSP**: `default-src 'self'; script-src 'self'; style-src 'self'`,
  `connect-src` limited to self and the Cognito domain, `frame-ancestors
  'none'`, `object-src 'none'`

The SPA has no inline scripts or style attributes. The Playwright suite runs the
production build under the same CSP and fails on any violation.

**API hardening** (`api/middleware.py`):

- Every response carries security headers and `Cache-Control: no-store`.
- Request bodies over 1 MB get 413.
- Pydantic models reject unknown fields.
- Errors are RFC 7807 problem documents with a request id and no stack traces.

## Secrets

| Secret | Used by | Rotation |
| --- | --- | --- |
| Aurora admin | Migrator only | Secrets Manager hosted rotation (`rotate-secrets.sh --what db-admin`) |
| Login passwords for `leadintel_api` / `leadintel_worker` (proxy auth) | RDS Proxy | `--what db-logins` |
| Origin-verify header value | CloudFront, API | `--what origin-verify` (see [Deployment](#deployment)) |
| ScrapeBadger API key | connector-runner | `--what scrapebadger`, then revoke the old key at the vendor |
| LinkedIn client secret, access token | webhook, linkedin-leads worker | Re-run `setup.sh` with new values |
| GA4 service-account key | ga4-sync | Re-run `setup.sh`; Workload Identity Federation planned |
| Blind-index key | API, pipeline | Not rotatable in place ([RUNBOOK.md](RUNBOOK.md#blind-index-key)) |

Secrets are read at runtime with a 5-minute in-memory cache. They are never put
in environment variables, CloudFormation templates or the repository.
`setup.sh` reads them from the operator's shell environment.

## Audit trail

`audit.audit_log` is append-only. A `BEFORE INSERT` trigger computes
`hash = sha256(prev_hash || canonical_line(row))`, and the Python implementation
(`security/audit.py`) is byte-for-byte identical, so either side can verify the
chain. The `audit-anchor` Lambda writes the chain head to the Object Lock bucket
every hour. Rewriting history would need both database owner access and
deleting locked objects, which compliance mode makes impossible even for the
account root until retention expires.

Audited actions:

- unmasked PII reads
- lead updates
- AI brief generation
- entity review decisions and merges
- suppressions
- DSAR creation and approval
- connector runs
- every authorization denial

## AI-specific controls

Account briefs use Claude on Amazon Bedrock (see
[ADR 0008](adr/0008-claude-on-bedrock-for-briefs.md)):

- **Data minimization.** Only firmographics, signal titles and dates, score
  factors, and the person's title and seniority are sent. Names, emails and
  phones are not.
- **Data residency.** Requests stay inside AWS under the function's IAM role
  (`bedrock-mantle:CreateInference`). There is no third-party API key.
- **Untrusted input.** Scraped text is wrapped in tagged data blocks the system
  prompt marks as untrusted. The model has no tools that act. It returns JSON
  through a tool whose input is validated, with one retry.
- **Refusals** fall back to the configured fallback model client-side, and
  briefs are labelled AI-generated in the UI.

## Detection and response

- **Production guardrails**: CloudTrail (multi-region, log file validation),
  GuardDuty and Security Hub.
- **Alarms** on errors, DLQs and anomalies route to SNS email
  (`alarm_email`).
- **Investigation**: query the audit log by actor or resource
  (`GET /api/v1/audit`). The request id ties the audit entry, the JSON logs and
  the API Gateway access logs together.
- **Credential compromise**: rotate (see the secrets table) and review the
  audit log and CloudTrail for the window.

## Deployment

**Account pinning.** Production configs pin the AWS account id, and every
script refuses to run against a different account. Protected environments
(`deletion_protection: true`) need an explicit flag and a typed confirmation to
tear down.

**CDK bootstrap trust.** `cdk bootstrap` by default gives the CloudFormation
execution role `AdministratorAccess`. For a tighter boundary:

- Create a customer-managed policy covering the services LeadIntel uses (EC2/VPC,
  RDS, Lambda, API Gateway, CloudFront, WAF, S3, SQS, Step Functions, Events,
  KMS, Secrets Manager, Cognito, IAM roles scoped to the `leadintel-*` prefix,
  CloudWatch, Budgets, Athena, CloudTrail, GuardDuty, Security Hub).
- Bootstrap with
  `scripts/aws/bootstrap.sh --env <env> --execution-policy <policy-arn>`.
- Add a permissions boundary on created roles if your organization requires one.

**CI/CD.** `bootstrap.sh --with-cicd` deploys a GitHub OIDC provider and a
deploy role:

- Trust is limited to `repo:<owner>/<repo>:ref:refs/heads/main` and to the
  GitHub environment named after the AWS environment. Use GitHub environment
  protection rules for production approvals.
- The role deploys by assuming the CDK bootstrap roles. Beyond that, it may
  only read this environment's stack outputs and invoke the migrator Lambda,
  which is what `setup.sh` needs after `cdk deploy`. Secrets and users stay with
  operators. There are no long-lived AWS keys in GitHub.
- The deploy job in `.github/workflows/leadgen-ci.yml` is manual (workflow
  dispatch) and runs after the full test suite.
- In production, `setup.sh` deploys with `--require-approval broadening`, so a
  change that widens IAM or security groups needs a human.

**Custom domain and TLS.**

1. Request an ACM certificate in **us-east-1** for the domain.
2. Set `domain_name` and `certificate_arn` in `infra/config/<env>.json`.
3. Add `https://<domain>/auth/callback` to `callback_urls`.
4. Deploy, then point DNS at the distribution.

With a certificate, CloudFront enforces `TLSv1.2_2021`. Without one, it serves
the `cloudfront.net` name with CloudFront's default certificate, which is fine
for dev but not for production.

**Origin-verify rotation.** `rotate-secrets.sh --what origin-verify` stores a new
value and redeploys the web stack. Two delays overlap:

- CloudFront takes several minutes to deploy the new header.
- API containers cache the secret for up to 5 minutes.

Expect some `403` responses for a few minutes, so rotate in a quiet window. The
zero-downtime alternative is to accept both the `AWSCURRENT` and `AWSPREVIOUS`
values during the switch (roadmap).

## Known gaps and planned hardening

| Gap | Plan |
| --- | --- |
| Tokens live in `sessionStorage` (exposed to any XSS) | Backend-for-frontend with HttpOnly cookies (ADR 0009 upgrade path) |
| GA4 uses a service-account JSON key | Workload Identity Federation from AWS |
| Origin-verify rotation has a short 403 window | Dual-value acceptance during rotation |
| Single shared PII key | Per-tenant KMS keys when multi-tenant |
| No external penetration test yet | Before production go-live (roadmap phase 2) |

## Reporting a vulnerability

Report suspected vulnerabilities privately to the security contact for this
deployment (set `alarm_email` / your security mailbox), not in public issues.
Include reproduction steps and the request id from any error response.
