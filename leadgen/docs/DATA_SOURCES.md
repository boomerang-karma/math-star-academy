# Data sources

Each source sits behind a connector in `src/leadintel/connectors/`. A connector
turns vendor data into ontology objects (`SourceRecord`, `Signal`,
`RelationshipAssertion`) and nothing else. Vendor SDK models and HTTP shapes
never leave the connector, and contract tests on recorded fixtures pin each
mapping.

| Source | Connector | Access model | What it contributes | Lawful basis recorded |
| --- | --- | --- | --- | --- |
| ScrapeBadger | `scrapebadger/` | API key (Secrets Manager), credit-metered | Organizations, hiring/news/technology signals, local businesses; person profiles only when enabled | legitimate interest |
| LinkedIn Lead Sync | `linkedin_leadsync.py` | LinkedIn program approval, OAuth token, webhook | People who submitted our Lead Gen Forms, their companies, consent | consent |
| Google Analytics 4 | `ga4.py` | Service account with read-only property access | Per-visitor engagement keyed by our first-party visitor id | consent (analytics) |
| Our website | `first_party.py` | Public beacon `POST /api/collect` (origin allowlist, WAF rate limit) | Page views, high-intent pages, form submissions, identity links | consent / legitimate interest per jurisdiction |
| CRM (roadmap) | - | Vendor API | Accounts, contacts, opportunity outcomes for calibration | contract / legitimate interest |

## ScrapeBadger

[ScrapeBadger](https://scrapebadger.com) is a unified, credit-based scraping
API: one key covers LinkedIn public pages (companies, jobs, profiles, schools),
Google (Search, Maps, News and more), generic web pages and other platforms.
LeadIntel uses the official Python SDK
([`scrapebadger` on PyPI](https://pypi.org/project/scrapebadger/), pinned
`~=0.54.0`) through an anti-corruption layer
(`connectors/scrapebadger/gateway.py`).

### Playbooks and the SDK calls they make

| Playbook | SDK calls | Output |
| --- | --- | --- |
| `market_hiring_scan` | `linkedin.jobs_search` | `job_posting` signals; hiring organizations |
| `company_profile` | `google.search.search` (to find the LinkedIn page when only a name or domain is known), `linkedin.get_company` | Organization firmographics, specialties, HQ, size |
| `website_enrichment` | `web.scrape(format="html", escalate=True)` | Description, technologies (`tech_detected`), contact pages |
| `news_triggers` | `google.news.search` | `funding`, `acquisition`, `expansion`, `leadership_change`, `news_mention` signals |
| `local_discovery` | `google.maps.search` (paged) | Local organizations with phone, address, rating, place id |
| `account_research` | the above, for one account | Full account enrichment |
| `person_profile` | `linkedin.get_profile` | Person record. **Disabled** unless `LEADINTEL_ALLOW_PERSON_PROFILE_SCRAPING=true` after legal sign-off ([COMPLIANCE.md](COMPLIANCE.md#scraping-policy)) |

Runs start on a schedule (`discovery_tasks` in `infra/config/<env>.json`,
through Step Functions) or on demand
(`POST /api/v1/connectors/scrapebadger/runs`, permission `connectors:run`).

### Cost control

- Every run has a **credit budget**: the task's `credit_budget`, or
  `scrapebadger_run_credit_budget` when the task sets none. On-demand runs
  accept at most 50,000. The gateway charges the budget before each call and
  stops cleanly when it is exhausted. The run is then recorded as `partial`
  with `credits_used`.
- Concurrency per run is capped (`LEADINTEL_SCRAPEBADGER_MAX_CONCURRENCY`,
  default 4), and the state machine runs at most two tasks in parallel.
- An alarm fires when daily credit use exceeds four times the per-run budget.
- Published pricing at the time of writing:
  - 1,000 free credits for new accounts
  - pay-as-you-go credits that do not expire
  - subscriptions from $49 to $699 a month
  - failed requests are not charged

  Check [scrapebadger.com](https://scrapebadger.com) for current prices.

### Failure handling (gateway)

| Upstream | Mapped to | Behaviour |
| --- | --- | --- |
| 401 | `AuthenticationError` | Fail the run; rotate the key (`rotate-secrets.sh --what scrapebadger`) |
| 402 | `BudgetExceededError` | Account out of credits: stop all runs, alarm |
| 403 IP not allowed | `ConnectorError` | Egress IP missing from the key's allowlist. Add the NAT IPs printed by `setup.sh` |
| 403 insufficient scope | `ConnectorError` | Key lacks a scope a playbook needs |
| 404 | `SourceNotFoundError` | Recorded and skipped (company page gone) |
| 422 | `ConnectorError` (not retryable) | Bad parameters: a bug, fix the playbook |
| 429 | `RateLimitedError(retry_after_s)` | Step Functions retries with backoff |
| 5xx / transport | retried by the SDK, then `ConnectorError(retryable=True)` | Retried by Step Functions, then isolated |

Key hygiene: restrict the production key to the scopes the playbooks use, and
to the NAT gateway Elastic IPs the network stack exports.

## LinkedIn Lead Sync

The compliant way to bring LinkedIn **people** into the platform is through the
member themselves. They submit one of our LinkedIn Lead Gen Forms and choose to
share their details. Access is a separate LinkedIn program: apply for Lead Sync
API access, because Advertising API access does not include it
([Lead Sync API](https://learn.microsoft.com/en-us/linkedin/marketing/lead-sync/leadsync?view=li-lms-2024-05)).

The flow:

```
LinkedIn --(lead notification webhook, X-LI-Signature)--> /api/webhooks/linkedin
   -> SQS linkedin queue -> linkedin-leads worker
   -> GET /rest/leadFormResponses/{id} (Linkedin-Version header, Rest.li 2.0)
   -> person + organization source records, works_at link, form_submission signal,
      consent records for the purposes the member ticked
```

Details:

- **Webhook validation.** LinkedIn sends a `challengeCode` on `GET`. The API
  answers with `challengeResponse` = hex HMAC-SHA256 of the code under the app
  client secret. Notifications are accepted only when `X-LI-Signature` matches
  HMAC-SHA256 of `"hmacsha256=" + raw body`, compared in constant time
  ([webhook validation](https://learn.microsoft.com/en-ca/linkedin/shared/api-guide/webhook-validation)).
- **Deletions.** A `DELETED` notification means the member withdrew the lead,
  so the worker erases the corresponding source record.
- **Versioning.** The API version is pinned (`LEADINTEL_LINKEDIN_API_VERSION`).
  Field paths are isolated in the connector and pinned by
  `tests/contract/test_official_connectors.py` (fixture
  `tests/contract/fixtures/linkedin/lead_form_response.json`). Re-record the fixture when access
  is granted and whenever the version is bumped.

## Google Analytics 4

GA4 reports are aggregated, so per-visitor data needs a join key we control.
The website's tag sets a random first-party UUID cookie and sends it to GA4 as
the user-scoped custom dimension `lead_visitor_id`. It is never an email or
other personal data, which Google's terms prohibit sending to GA4.

The daily `ga4-sync` job:

1. Authenticates as a Google service account (JSON key in Secrets Manager,
   OAuth 2.0 JWT-bearer grant, scope `analytics.readonly`).
2. Calls the Data API `runReport`, grouped by
   `customUser:lead_visitor_id` and page/event dimensions
   ([Data API custom dimensions](https://developers.google.com/analytics/devguides/reporting/data/v1/advanced)).
3. Emits `web_visit` and `high_intent_page` signals with the visitor id as
   subject hint.

Signals attach to a person once the identity graph links the visitor id
(see [ONTOLOGY.md](ONTOLOGY.md#identity-graph)).

Setup checklist:

1. Register the user-scoped custom dimension `lead_visitor_id` in the GA4
   property.
2. Grant the service account Viewer on the property.
3. Store the key with `GA4_SERVICE_ACCOUNT_FILE=... scripts/aws/setup.sh`.

Hardening: replace the JSON key with Workload Identity Federation from AWS
(roadmap).

## First-party beacon

`POST /api/collect` receives page views and form submissions from our website.
Its controls:

- **CORS and rate limits.** Only origins in `beacon_allowed_origins` may call
  it, and a dedicated WAF rate limit protects it.
- **Validation.** Events are validated against a strict schema. IP addresses
  are never stored.
- **Personal data.** Form emails are blind-indexed and envelope-encrypted before
  they reach storage.
- **Consent.** The snippet loads only after analytics consent where the
  visitor's jurisdiction requires it.

A form submission carries both the visitor id and an email. That links every
earlier anonymous visit, ours and GA4's, to the person and their organization.
High-intent paths (pricing, demo, contact, ...) come from `config/icp.json`.

## Adding a source

1. **Contract first.** Record a few real (or documented) responses as fixtures
   under `tests/contract/fixtures/`, with personal data replaced by fictional
   values.
2. **Write the connector.** Implement the `Connector` protocol
   (`connectors/base.py`). Map responses with pure functions into
   `SourceRecord`, `Signal` and `RelationshipAssertion`. Set `lawful_basis`
   correctly, and put emails and personal phones in `restricted`, never in
   `attributes`.
3. **Errors.** Map vendor errors onto `core/errors.py`: authentication,
   not-found, rate limit (with `retry_after_s`), budget, and retryable versus
   permanent failures.
4. **Register it** with `@register("<name>")` in `connectors/registry.py`. Add
   a `Source` enum value and a trust level in survivorship.
5. **Wire it in.** Use a scheduled task (`discovery_tasks`), a dedicated worker
   and queue, or a webhook route, depending on the delivery model.
6. **Compliance.** Add the source to the processing register in
   [COMPLIANCE.md](COMPLIANCE.md#record-of-processing-activities) and decide
   retention.
7. **Tests.** Write contract tests for mapping and error translation, and an
   integration test through `PipelineService` if the source introduces new
   entity patterns.
