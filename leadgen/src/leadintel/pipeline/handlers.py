"""AWS Lambda entry points for the data plane.

Each handler is a thin adapter (event in, JSON summary out) around the
pipeline service, so the same code runs from Step Functions, SQS, EventBridge
Scheduler, the CLI and the tests. Errors are raised with their class name as
the Lambda error type, which the state machine matches for retry policy:
``RateLimitedError`` and retryable ``ConnectorError`` back off and retry,
``BudgetExceededError`` ends the branch gracefully, everything else fails it.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from leadintel.compliance import dsar
from leadintel.compliance.retention import apply_retention
from leadintel.connectors import registry
from leadintel.connectors.base import CreditBudget, RunContext
from leadintel.connectors.first_party import TrackEvent, event_signals, form_source_records
from leadintel.core.errors import BudgetExceededError, SourceNotFoundError
from leadintel.ontology.models import FetchBatch
from leadintel.pipeline.runtime import runtime

logger = logging.getLogger("leadintel.handlers")


def _emit_metric(name: str, value: float, *, unit: str = "Count", **dimensions: str) -> None:
    """CloudWatch Embedded Metric Format: a structured log line becomes a metric, no API call."""
    print(
        json.dumps(
            {
                "_aws": {
                    "Timestamp": int(datetime.now(UTC).timestamp() * 1000),
                    "CloudWatchMetrics": [
                        {
                            "Namespace": "LeadIntel",
                            # Per-dimension series plus an undimensioned total that alarms can use.
                            "Dimensions": [sorted(dimensions), []],
                            "Metrics": [{"Name": name, "Unit": unit}],
                        }
                    ],
                },
                name: value,
                **dimensions,
            }
        )
    )


def connector_run(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Step Functions task: run one connector playbook and ingest the result."""
    rt = runtime()
    name, playbook = event["connector"], event["playbook"]
    params = event.get("params") or {}
    budget = CreditBudget(
        int(event.get("credit_budget") or rt.settings.scrapebadger_run_credit_budget)
    )
    connector = registry.create(name, rt.settings)
    ctx = RunContext(budget=budget, icp=rt.icp)
    try:
        batch = asyncio.run(connector.run(playbook, params, ctx))
    except BudgetExceededError as exc:
        logger.warning("credit budget exhausted", extra={"connector": name, "playbook": playbook})
        return {"status": "budget_exceeded", "detail": exc.details}
    except SourceNotFoundError as exc:
        return {"status": "not_found", "detail": exc.message}
    batch.credits_used = budget.used
    summary = rt.service().ingest(batch, connector=name, playbook=playbook, params=params)
    _emit_metric("CreditsUsed", budget.used, connector=name, playbook=playbook)
    return {"status": "ok", **summary}


def resolve(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Drain the pending queue in batches until empty or the invocation is nearly out of time."""
    service = runtime().service()
    totals: dict[str, int] = {}
    while True:
        result = service.resolve_pending(limit=int(event.get("batch_size", 500)))
        for key, value in result.items():
            totals[key] = totals.get(key, 0) + int(value)
        if result["records"] == 0:
            break
        if context is not None and context.get_remaining_time_in_millis() < 60_000:
            totals["more_pending"] = 1
            break
    _emit_metric("RecordsResolved", totals.get("records", 0))
    _emit_metric("ReviewItemsCreated", totals.get("reviews", 0))
    return totals


def score(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    lead_ids = [UUID(x) for x in event["lead_ids"]] if event.get("lead_ids") else None
    return {"scored": runtime().service().score(lead_ids=lead_ids)}


def web_events(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """SQS consumer for the first-party beacon. Reports per-message failures for retry."""
    rt = runtime()
    failures: list[dict[str, str]] = []
    batch = FetchBatch()
    for message in event.get("Records", []):
        try:
            track = TrackEvent.model_validate_json(message["body"])
        except ValueError:
            logger.warning("dropping malformed beacon event")  # poison message: do not retry
            continue
        try:
            batch.records.extend(form_source_records(track))
            batch.signals.extend(event_signals(track, icp=rt.icp, bidx=rt.bidx))
        except Exception:  # noqa: BLE001 - isolate one bad message from the batch
            failures.append({"itemIdentifier": message["messageId"]})
    if batch.records or batch.signals:
        rt.service().ingest(batch, connector="first_party", playbook="beacon", params={})
    return {"batchItemFailures": failures}


def linkedin_leads(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """SQS consumer for verified LinkedIn lead notifications (CREATED / DELETED)."""
    import httpx

    from leadintel.connectors.linkedin_leadsync import (
        LinkedInLeadSyncClient,
        map_lead_form_response,
    )
    from leadintel.security.keyring import build_secrets_provider

    rt = runtime()
    settings = rt.settings
    secrets = build_secrets_provider(settings)

    async def token() -> str:
        return secrets.get(settings.linkedin_access_token_secret_arn or "")

    failures: list[dict[str, str]] = []

    async def process() -> None:
        async with httpx.AsyncClient() as http:
            client = LinkedInLeadSyncClient(
                http, token=token, api_version=settings.linkedin_api_version
            )
            for message in event.get("Records", []):
                body = json.loads(message["body"])
                response_id = str(body["response_id"])
                try:
                    if body.get("action") == "DELETED":
                        _erase_lead_form_response(response_id)
                        continue
                    response = await client.get_response(response_id)
                    records, signals, consents = map_lead_form_response(response, bidx=rt.bidx)
                    rt.service().ingest(
                        FetchBatch(records=records, signals=signals),
                        connector="linkedin_leadsync",
                        playbook="webhook",
                        params={"response_id": response_id},
                        consents=consents,
                    )
                except SourceNotFoundError:
                    continue
                except Exception:
                    logger.exception("lead notification failed")
                    failures.append({"itemIdentifier": message["messageId"]})

    asyncio.run(process())
    return {"batchItemFailures": failures}


def _erase_lead_form_response(response_id: str) -> None:
    conn = runtime().connection()
    with conn.transaction():
        conn.execute(
            "DELETE FROM ingest.source_record WHERE source = 'linkedin.lead_sync'"
            " AND (external_id = %s OR external_id LIKE %s)",
            (response_id, f"{response_id}#%"),
        )


def ga4_sync(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Daily: pull yesterday's per-visitor activity from GA4."""
    import httpx

    from leadintel.connectors.ga4 import (
        Ga4Client,
        GoogleServiceAccountTokenProvider,
        map_visitor_activity,
        visitor_activity_request,
    )
    from leadintel.security.keyring import build_secrets_provider

    rt = runtime()
    settings = rt.settings
    day = (
        date.fromisoformat(event["date"]) if event.get("date") else date.today() - timedelta(days=1)
    )
    service_account = json.loads(
        build_secrets_provider(settings).get(settings.ga4_credentials_secret_arn or "")
    )

    async def fetch() -> list[Any]:
        async with httpx.AsyncClient() as http:
            client = Ga4Client(
                http,
                property_id=settings.ga4_property_id or "",
                token=GoogleServiceAccountTokenProvider(http, service_account),
            )
            signals: list[Any] = []
            offset = 0
            while True:
                report = await client.run_report(
                    visitor_activity_request(
                        start=day,
                        end=day,
                        visitor_dimension=settings.ga4_visitor_dimension,
                        offset=offset,
                    )
                )
                signals.extend(map_visitor_activity(report, icp=rt.icp))
                offset += 10_000
                if offset >= int(report.get("rowCount", 0)):
                    return signals

    signals = asyncio.run(fetch())
    return rt.service().ingest(
        FetchBatch(signals=signals),
        connector="ga4",
        playbook="daily_sync",
        params={"date": day.isoformat()},
    )


def retention(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    conn = runtime().connection()
    with conn.transaction():
        return apply_retention(conn, now=datetime.now(UTC))


def dsar_worker(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Process DSARs approved for execution (status in_progress)."""
    rt = runtime()
    conn = rt.connection()
    processed = 0
    with conn.transaction():
        requests = conn.execute(
            "SELECT id, request_type, subject_email_bidx FROM privacy.dsar_request"
            " WHERE status = 'in_progress' ORDER BY due_at LIMIT 20 FOR UPDATE SKIP LOCKED"
        ).fetchall()
        for request in requests:
            if request["request_type"] == "erasure":
                result: dict[str, Any] = dsar.erase_subject(
                    conn,
                    email_bidx=request["subject_email_bidx"],
                    actor="dsar-worker",
                    raw_store=rt.raw_store,
                )
            elif request["request_type"] in {"access", "portability"}:
                export = dsar.export_subject(
                    conn, email_bidx=request["subject_email_bidx"], cipher=rt.cipher
                )
                result = {"records": len(export["records"]), "signals": len(export["signals"])}
                # The export goes to the restricted DSAR bucket; the DB keeps only counts.
            else:
                continue
            dsar.complete_request(conn, request["id"], handled_by="dsar-worker", result=result)
            processed += 1
    return {"processed": processed}


def audit_anchor(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Copy the audit chain head to the Object Lock bucket (tamper evidence)."""
    import boto3

    rt = runtime()
    conn = rt.connection()
    row = conn.execute(
        "SELECT seq, encode(hash, 'hex') AS hash FROM audit.audit_log ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    conn.rollback()
    if row is None or not rt.settings.audit_anchor_bucket:
        return {"anchored": False}
    body = json.dumps({"seq": row["seq"], "hash": row["hash"], "at": datetime.now(UTC).isoformat()})
    boto3.client("s3").put_object(
        Bucket=rt.settings.audit_anchor_bucket,
        Key=f"audit-anchors/{date.today():%Y/%m/%d}/{row['seq']}.json",
        Body=body.encode(),
        ContentType="application/json",
    )
    return {"anchored": True, "seq": row["seq"]}


def migrate(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Run migrations (and seeds) from inside the VPC; invoked by scripts/aws/setup.sh."""
    from leadintel.security.keyring import build_secrets_provider
    from leadintel.storage.migrate import MigrationRunner, discover

    rt = runtime()
    secrets = build_secrets_provider(rt.settings)
    with rt.connection() as conn:
        conn.autocommit = False
        runner = MigrationRunner(conn)
        applied = runner.migrate(discover())
        seeded = runner.seed() if event.get("seed", True) else []
        users = []
        for group_role, secret_arn in rt.settings.db_login_user_secrets.items():
            login = json.loads(secrets.get(secret_arn))
            runner.ensure_login_user(login["username"], login["password"], group_role)
            users.append(login["username"])
    return {"applied": applied, "seeded": seeded, "login_users": users}
