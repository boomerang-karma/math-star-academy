# Runbook

Day-2 operations for LeadIntel. Commands assume the repository root
(`leadgen/`), an AWS CLI session for the target account, and `ENV` set to the
environment (`dev`, `staging`, `prod`). Stack names are `leadintel-$ENV-<unit>`.
`scripts/aws/status.sh --env $ENV` prints every stack, output and alarm state.

## Quick reference

| Task | Command |
| --- | --- |
| First-time account setup | `scripts/aws/bootstrap.sh --env $ENV [--with-cicd]` |
| Deploy everything | `scripts/aws/setup.sh --env $ENV` |
| Deploy one stack | `scripts/aws/setup.sh --env $ENV --skip-build --only web` |
| Status | `scripts/aws/status.sh --env $ENV` |
| Rotate a secret | `scripts/aws/rotate-secrets.sh --env $ENV --what <db-admin\|db-logins\|origin-verify\|scrapebadger>` |
| Manual snapshot | `database/scripts/backup.sh --env $ENV --label <why>` |
| Restore to a new cluster | `database/scripts/restore.sh --env $ENV --point-in-time <ISO-8601> --target <id>` |
| Tear down (preview) | `scripts/aws/teardown.sh --env $ENV --dry-run` |
| Local stack | `make demo && make run-api` (second terminal: `make run-web`) |

## Deploy

**First deployment**

1. Edit `infra/config/$ENV.json`. At minimum set:
   - `account`
   - a globally unique `cognito_domain_prefix`
   - `callback_urls`
   - `beacon_allowed_origins`
   - `alarm_email`
   - for production, `domain_name` and `certificate_arn` (see
     [SECURITY.md](SECURITY.md#deployment))
2. Run `scripts/aws/bootstrap.sh --env $ENV`.
3. Export the source secrets in your shell, then run
   `scripts/aws/setup.sh --env $ENV --admin-email you@example.com`:
   - `SCRAPEBADGER_API_KEY`
   - `LINKEDIN_CLIENT_SECRET`
   - `LINKEDIN_ACCESS_TOKEN`
   - `GA4_SERVICE_ACCOUNT_FILE`
4. Restrict the ScrapeBadger key to the NAT egress IPs printed at the end.
5. Confirm the SNS subscription email for alarms.

**Routine deployment.** CI (`.github/workflows/leadgen-ci.yml`) runs the full
test suite on every pull request and push to `main`. To deploy, either:

- run `setup.sh` yourself, or
- start the workflow manually with **deploy** checked and the target
  environment.

The CI route needs the repository variable `LEADINTEL_DEPLOY_ROLE_ARN` (the
cicd stack's `DeployRoleArn` output). For staging and production, also set
GitHub environment protection rules.

The script is idempotent: build, `cdk deploy`, store any secrets present in the
shell, run migrations and seeds in the VPC, and print a summary. In production,
changes that broaden IAM or security groups stop for approval.

**Rolling back.**

- **Application or infrastructure.** Re-deploy the previous commit
  (`git checkout <sha> && scripts/aws/setup.sh --env $ENV`). CloudFormation
  rolls back failed stack updates on its own.
- **Schema.** Migrations are forward-only and must stay backward compatible for
  one release: add columns before code uses them, and drop them a release
  later. To undo a migration, write a new one. Never edit an applied migration.
  The runner refuses checksum drift.

## Database migrations

- **Where they run.** The migrator Lambda runs them inside the VPC during
  `setup.sh`. The payload `{"seed": true}` applies pending migrations in order
  under a PostgreSQL advisory lock, applies the idempotent seeds, and creates or
  updates the proxy login users.
- **Locally.** Run
  `.venv/bin/python -m leadintel.storage.migrate status|up|verify|seed`
  (database from `LEADINTEL_DATABASE_URL`).
- **On failure.** The failing migration's transaction rolls back and the deploy
  stops. Fix forward with a new migration, then re-run `setup.sh`.

## Alarms

Alarm names are prefixed `leadintel-$ENV-`. All of them notify `alarm_email`.

| Alarm | Meaning | Action |
| --- | --- | --- |
| `dlq-0-not-empty` (web events), `dlq-1-not-empty` (LinkedIn) | Messages failed 5 times | Read a message (`aws sqs receive-message`) and the worker logs for its request id. Fix the cause, then [redrive](#dead-letter-queues) |
| `<worker>-errors` (connector-runner, resolver, scorer, web-events, linkedin-leads, dsar-worker, retention) | A worker invocation failed | CloudWatch Logs Insights on the function: `filter level = "ERROR"`. Batch workers retry automatically; scheduled jobs retry on the next run |
| `api-errors`, `api-5xx` | The API is failing | Check `readyz` and Aurora health. Search API logs by the `request_id` users report (shown in every error) |
| `enrichment-failed` | A Step Functions enrichment execution failed | Open the execution history. Connector errors are caught per task, so a failure usually means the resolver or scorer failed |
| `aurora-near-max-capacity` | Aurora ran at ≥ 90% of `db_max_acu` for 15 minutes | Look at Performance Insights top SQL. Raise `db_max_acu` if the load is legitimate |
| `scrapebadger-daily-credits` | Credit burn over 4× the per-run budget in a day | Query `ingest.connector_run` by `credits_used`. Disable the discovery schedule (`aws events disable-rule`) until explained |
| AWS Budget (80% actual / 100% forecast) | Spend trending over budget | Check Cost Explorer by service. See the cost levers in [ARCHITECTURE.md](ARCHITECTURE.md#13-cost-model) |

## Dead-letter queues

After fixing the cause, move messages back to the source queue:

```bash
dlq_arn=$(aws sqs get-queue-attributes --queue-url "$DLQ_URL" --attribute-names QueueArn \
  --query Attributes.QueueArn --output text)
aws sqs start-message-move-task --source-arn "$dlq_arn"   # back to the original queue
```

The workers are idempotent (deterministic ids), so replaying is safe.

## Connector incidents

| Symptom | Cause | Fix |
| --- | --- | --- |
| Runs fail with "out of credits" | ScrapeBadger balance exhausted (402) | Top up or upgrade the plan. Runs resume on the next schedule |
| "egress IP is not allowed" | The key's IP allowlist misses a NAT IP (e.g. after adding a NAT gateway) | Add the IPs from `status.sh` (network stack outputs) in the ScrapeBadger dashboard |
| Authentication errors | Key revoked or rotated | `SCRAPEBADGER_API_KEY=... scripts/aws/rotate-secrets.sh --env $ENV --what scrapebadger` |
| Many 429s and slow runs | Rate limits | Lower `LEADINTEL_SCRAPEBADGER_MAX_CONCURRENCY` or spread discovery tasks. Step Functions already backs off |
| Mapping or validation errors after an upstream change | Vendor response shape changed | Re-record the contract fixture, adapt the mapper, ship. Raw payloads from the last 30 days can be re-mapped |
| LinkedIn webhook returns 401/403 | Client secret mismatch | Update the secret with `setup.sh` (`LINKEDIN_CLIENT_SECRET`). LinkedIn re-validates the webhook |
| GA4 sync fails with 403 | Service account lost access to the property | Re-grant Viewer on the GA4 property |

## Review queue

Analysts should clear the queue weekly (`/review` in the app). If the same
kind of pair keeps appearing, that is a tuning signal:

- **Too many true matches waiting**: consider lowering the match threshold for
  that feature combination.
- **Too many rejections**: add a stronger distinguishing feature or an
  exclusive identifier.

Change thresholds in `pipeline/resolution/matching.py` (`Thresholds`) with a
test, never in production by hand.

## Data subject requests

1. A compliance officer creates the request in the app (or
   `POST /api/v1/privacy/dsar`) and verifies the requester's identity out of
   band.
2. Approve it (`POST /api/v1/privacy/dsar/{id}/approve`). The DSAR worker picks
   it up within 15 minutes.
3. Check completion with `GET /api/v1/privacy/dsar?open_only=false`. A
   completed access or portability request shows `result.export_uri`.
4. Deliver an export:
   - Grant your compliance team's IAM Identity Center permission set read access
     to the export bucket: `s3:GetObject` on
     `arn:aws:s3:::<DsarExportBucketName>/dsar/*`, and `kms:Decrypt` on the
     `alias/leadintel-$ENV/data` key via S3. The DSAR worker itself can only
     write.
   - Download it with `aws s3 cp s3://<DsarExportBucketName>/dsar/<id>.json .`
     (bucket name from the data stack outputs).
   - Send it over an encrypted channel, then delete your local copy. The bucket
     deletes exports after 30 days.
5. Erasure needs no delivery. The suppression added by the worker keeps the
   person from being re-collected. Do not delete that suppression.

Deadlines: GDPR and UK GDPR, 30 days from receipt; CCPA, 45 days. The request
list shows `due_at`.

## Secrets rotation

| Secret | Procedure | Impact |
| --- | --- | --- |
| Aurora admin | `rotate-secrets.sh --what db-admin` (Secrets Manager rotation) | None. Only the migrator uses it |
| Proxy login users | `rotate-secrets.sh --what db-logins` (new passwords, then the migrator updates the roles) | None. Clients use IAM tokens to the proxy |
| Origin-verify | `rotate-secrets.sh --what origin-verify` (stores the value, redeploys the web stack) | Up to several minutes of 403s while CloudFront deploys and API containers refresh their 5-minute secret cache. Use a quiet window |
| ScrapeBadger | `SCRAPEBADGER_API_KEY=... rotate-secrets.sh --what scrapebadger`, then revoke the old key at the vendor | Runs in flight may fail once and retry |
| LinkedIn, GA4 | Re-run `setup.sh` with the new values in the shell | None |

## Blind-index key

The blind-index key (an HMAC key in Secrets Manager) turns emails, phones and
other identifiers into the lookup keys stored across the schema:

- `email_bidx` and `phone_bidx` columns
- person blocking keys in `graph.entity_key`
- consent subjects, suppression entries and DSAR subjects

It **cannot be rotated in place**, and `rotate-secrets.sh` refuses to:

- A new key makes every stored index stop matching. Duplicates would then be
  created, and suppressed people could be re-collected.
- Suppression entries for erased people keep only the index. The plaintext is
  gone by design, so those entries can only ever be matched under the key that
  created them.

**If the key may be compromised.** On its own, the key reveals nothing.
Combined with read access to the database, it lets an attacker confirm guessed
identifiers (for example, "is jane@acme.com in the database?"). Respond in this
order:

1. Contain database access first: rotate database credentials and review
   CloudTrail and the audit log.
2. Plan a **versioned key migration**. This is a code change, tracked in the
   roadmap:
   - Store new indexes with a key version.
   - Look up under all active versions.
   - Recompute indexes wherever plaintext is still available: decrypt each
     `pii_envelope` with KMS, and use normalized attributes for blocking keys.
   - Keep the old key, in a restricted secret, only for matching legacy
     suppression entries.
3. Never delete the old key while any suppression depends on it.

## Backups

- **Continuous.** Aurora point-in-time recovery: 1 day (dev), 7 days
  (staging), 30 days (prod).
- **Manual.** `database/scripts/backup.sh --env $ENV --label pre-release-42`
  takes a cluster snapshot kept until deleted. It survives teardown. Take one
  before risky migrations.
- **Local.** `database/scripts/backup.sh --local` (pg_dump into
  `.data/backups/`).

## Restore

Targets: RPO about 5 minutes (PITR), RTO under 2 hours in production. Restores
never overwrite the live cluster.

1. **Freeze writes.** Disable the EventBridge schedules
   (`aws events disable-rule` for the stack's rules) and tell users. API reads
   can continue.
2. **Restore into a new cluster.** It uses the same subnets, security group and
   KMS key:
   ```bash
   database/scripts/restore.sh --env $ENV --point-in-time 2026-10-01T09:30:00Z --target leadintel-$ENV-restore-1
   ```
   Use `--snapshot <id>` instead for a manual snapshot.
3. **Validate.** Open an AWS CloudShell VPC environment in the private subnets
   with the Lambda security group, and connect with `psql` using the admin
   secret:
   - Check row counts for `sales.lead`, `graph.entity` and `audit.audit_log`.
   - Run `SELECT audit.verify_chain();`, which must return `NULL`.
4. **Cut over.** Re-point the RDS Proxy. The API and workers use the proxy
   endpoint, so they need no redeploy:
   ```bash
   aws rds deregister-db-proxy-targets --db-proxy-name <proxy> --db-cluster-identifiers <old-cluster>
   aws rds register-db-proxy-targets --db-proxy-name <proxy> --db-cluster-identifiers leadintel-$ENV-restore-1
   ```
5. **Re-apply privacy actions taken after the restore point.** Copy from the old
   cluster into the restored one:
   - `privacy.suppression` rows created after the restore time
   - `privacy.dsar_request` erasures completed after it, re-inserted with
     status `in_progress` so the DSAR worker re-executes them (erasure is
     idempotent)

   An erased person must never come back through a restore.
6. **Unfreeze.** Re-enable the schedules, then run the resolver and scorer
   once.
7. **Reconcile infrastructure** in a planned change. CloudFormation still
   describes the old cluster. Either swap the cluster identifiers during a
   maintenance window (rename old to `-retired`, restored to the original
   identifier, then re-register proxy targets) or import the restored cluster
   into the stack. Delete the old cluster only after a final snapshot.

**Drill.** Run steps 2-3 against staging every quarter, record the time taken,
and keep the RTO honest.

## Teardown

```bash
scripts/aws/teardown.sh --env dev --dry-run    # see exactly what would happen
scripts/aws/teardown.sh --env dev              # typed confirmation, final snapshot first
```

Protected environments additionally need `--i-understand-this-destroys-prod`
and a typed `destroy <env> <account>`. Retained resources (production buckets,
the final snapshot, CloudTrail logs) are listed at the end. Delete them
deliberately, if ever.

## Local development

```bash
make install                 # uv + npm dependencies
make demo                    # local PostgreSQL 16 on :54329, migrations, seeds, demo data
make run-api                 # API on :8000 (local-dev identities)
make run-web                 # SPA on :5173; persona picker in the header
make test test-integration test-infra test-web test-e2e
```

`make db-reset` recreates the database. The local database lives in `.data/`
(ignored by git).
