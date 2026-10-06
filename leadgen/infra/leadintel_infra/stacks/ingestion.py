"""Ingestion: queues, worker Lambdas, the enrichment state machine and schedules.

Enrichment flow (Step Functions)::

    Map(tasks, max 2 in parallel)
      -> connector-runner      retry RateLimitedError with backoff, retryable ConnectorError
                               twice; any other failure is caught so one bad task never
                               sinks the batch
    -> resolver               drain pending source records (entity resolution)
    -> scorer                 rescore leads

Event-driven paths
  /api/collect      -> SQS web-events -> web-events worker
  LinkedIn webhook  -> SQS linkedin   -> linkedin-leads worker
Scheduled
  discovery (config), resolver every 15 min, scorer hourly, GA4 daily,
  retention nightly, DSAR worker every 15 min, audit anchor hourly.
"""

from __future__ import annotations

import json
from typing import Any

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_lambda_event_sources as sources
from aws_cdk import aws_logs as logs
from aws_cdk import aws_sqs as sqs
from aws_cdk import aws_stepfunctions as sfn
from aws_cdk import aws_stepfunctions_tasks as tasks
from constructs import Construct

from leadintel_infra.config import EnvConfig
from leadintel_infra.constructs.grants import allow_secret_read
from leadintel_infra.constructs.python_function import PythonFunction, retention
from leadintel_infra.stacks.data import WORKER_DB_USER, DataStack
from leadintel_infra.stacks.network import NetworkStack
from leadintel_infra.stacks.security import SecurityStack

ICP_PATH = "/var/task/config/icp.json"


def pii_key_statement(key_arn: str) -> iam.PolicyStatement:
    """Use of the PII key only with the platform's encryption context."""
    return iam.PolicyStatement(
        actions=["kms:GenerateDataKey", "kms:Decrypt"],
        resources=[key_arn],
        conditions={"StringEquals": {"kms:EncryptionContext:app": "leadintel"}},
    )


class IngestionStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        cfg: EnvConfig,
        network: NetworkStack,
        security: SecurityStack,
        data: DataStack,
        code: lambda_.Code,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        removal = RemovalPolicy.RETAIN if cfg.is_production else RemovalPolicy.DESTROY
        key = security.data_key

        def queue(name: str, visibility: Duration) -> sqs.Queue:
            dlq = sqs.Queue(
                self,
                f"{name}Dlq",
                encryption=sqs.QueueEncryption.KMS,
                encryption_master_key=key,
                retention_period=Duration.days(14),
                enforce_ssl=True,
            )
            return sqs.Queue(
                self,
                name,
                encryption=sqs.QueueEncryption.KMS,
                encryption_master_key=key,
                visibility_timeout=visibility,
                enforce_ssl=True,
                dead_letter_queue=sqs.DeadLetterQueue(max_receive_count=5, queue=dlq),
            )

        self.web_events_queue = queue("WebEvents", Duration.minutes(6))
        self.linkedin_queue = queue("LinkedInLeads", Duration.minutes(12))
        self.dead_letter_queues = [
            q.dead_letter_queue.queue
            for q in (self.web_events_queue, self.linkedin_queue)
            if q.dead_letter_queue
        ]

        base_env = {
            "LEADINTEL_ENV": cfg.name,
            "LEADINTEL_AWS_REGION": self.region,
            "LEADINTEL_LOG_LEVEL": "INFO",
            "LEADINTEL_PII_KMS_KEY_ID": security.pii_key.key_arn,
            "LEADINTEL_BLIND_INDEX_SECRET_ARN": security.blind_index_secret.secret_arn,
            "LEADINTEL_DB_PROXY_HOST": data.proxy.endpoint,
            "LEADINTEL_DB_IAM_USER": WORKER_DB_USER,
            "LEADINTEL_RAW_BUCKET": data.raw_bucket.bucket_name,
            "LEADINTEL_AUDIT_ANCHOR_BUCKET": data.audit_bucket.bucket_name,
            "LEADINTEL_SCRAPEBADGER_SECRET_ARN": security.scrapebadger_secret.secret_arn,
            "LEADINTEL_SCRAPEBADGER_RUN_CREDIT_BUDGET": str(cfg.scrapebadger_run_credit_budget),
            "LEADINTEL_LINKEDIN_ACCESS_TOKEN_SECRET_ARN": security.linkedin_token_secret.secret_arn,
            "LEADINTEL_GA4_CREDENTIALS_SECRET_ARN": security.ga4_secret.secret_arn,
            "LEADINTEL_ICP_PATH": ICP_PATH,
        }

        def worker(
            name: str,
            handler: str,
            *,
            timeout: Duration,
            memory: int = 1024,
            env: dict[str, str] | None = None,
            concurrency: int | None = None,
        ) -> lambda_.Function:
            fn = PythonFunction(
                self,
                name,
                handler=handler,
                code=code,
                environment={**base_env, **(env or {})},
                vpc=network.vpc,
                security_group=network.lambda_sg,
                log_key=key,
                log_retention_days=cfg.log_retention_days,
                removal_policy=removal,
                memory_mb=memory,
                timeout=timeout,
                reserved_concurrency=concurrency,
                description=f"LeadIntel {name}",
            ).function
            fn.add_to_role_policy(pii_key_statement(security.pii_key.key_arn))
            allow_secret_read(fn, security.blind_index_secret, key=key)
            data.proxy.grant_connect(fn, WORKER_DB_USER)
            return fn

        handlers = "leadintel.pipeline.handlers"
        self.connector_runner = worker(
            "ConnectorRunner",
            f"{handlers}.connector_run",
            timeout=Duration.minutes(10),
            concurrency=4,
        )
        allow_secret_read(self.connector_runner, security.scrapebadger_secret, key=key)
        data.raw_bucket.grant_put(self.connector_runner)

        self.resolver = worker(
            "Resolver",
            f"{handlers}.resolve",
            timeout=Duration.minutes(15),
            memory=1536,
            concurrency=1,
        )
        self.scorer = worker(
            "Scorer", f"{handlers}.score", timeout=Duration.minutes(10), concurrency=1
        )

        self.web_events = worker(
            "WebEventsWorker", f"{handlers}.web_events", timeout=Duration.minutes(1), memory=512
        )
        self.web_events.add_event_source(
            sources.SqsEventSource(
                self.web_events_queue,
                batch_size=25,
                max_batching_window=Duration.seconds(10),
                report_batch_item_failures=True,
            )
        )

        self.linkedin_worker = worker(
            "LinkedInLeadsWorker",
            f"{handlers}.linkedin_leads",
            timeout=Duration.minutes(2),
            memory=512,
        )
        allow_secret_read(self.linkedin_worker, security.linkedin_token_secret, key=key)
        self.linkedin_worker.add_event_source(
            sources.SqsEventSource(
                self.linkedin_queue, batch_size=5, report_batch_item_failures=True
            )
        )

        self.ga4_sync = worker("Ga4Sync", f"{handlers}.ga4_sync", timeout=Duration.minutes(5))
        allow_secret_read(self.ga4_sync, security.ga4_secret, key=key)

        self.retention = worker(
            "RetentionJob", f"{handlers}.retention", timeout=Duration.minutes(10), concurrency=1
        )
        self.dsar_worker = worker(
            "DsarWorker",
            f"{handlers}.dsar_worker",
            timeout=Duration.minutes(10),
            concurrency=1,
            env={"LEADINTEL_DSAR_EXPORT_BUCKET": data.dsar_export_bucket.bucket_name},
        )
        data.raw_bucket.grant_delete(self.dsar_worker)
        data.dsar_export_bucket.grant_put(self.dsar_worker, "dsar/*")  # write-only
        self.audit_anchor = worker(
            "AuditAnchor",
            f"{handlers}.audit_anchor",
            timeout=Duration.minutes(1),
            memory=256,
            concurrency=1,
        )
        data.audit_bucket.grant_put(self.audit_anchor)

        # The migrator connects as the cluster admin, directly to the writer (no proxy pinning).
        self.migrator = worker(
            "Migrator",
            f"{handlers}.migrate",
            timeout=Duration.minutes(10),
            concurrency=1,
            env={
                "LEADINTEL_DB_IAM_USER": "",
                "LEADINTEL_DB_PROXY_HOST": "",
                "LEADINTEL_DB_SECRET_ARN": data.admin_secret.secret_arn,
                "LEADINTEL_DB_LOGIN_USER_SECRETS": json.dumps(
                    {
                        "leadintel_app": data.api_db_secret.secret_arn,
                        "leadintel_pipeline": data.worker_db_secret.secret_arn,
                    }
                ),
            },
        )
        allow_secret_read(
            self.migrator,
            data.admin_secret,
            data.api_db_secret,
            data.worker_db_secret,
            key=data.db_key,
        )

        self.state_machine = self._enrichment_flow(cfg, removal)
        self._schedules(cfg)

        CfnOutput(self, "MigratorFunctionName", value=self.migrator.function_name)
        CfnOutput(self, "DsarWorkerFunctionName", value=self.dsar_worker.function_name)
        CfnOutput(self, "EnrichmentStateMachineArn", value=self.state_machine.state_machine_arn)

    def _enrichment_flow(self, cfg: EnvConfig, removal: RemovalPolicy) -> sfn.StateMachine:
        run = tasks.LambdaInvoke(
            self,
            "RunConnector",
            lambda_function=self.connector_runner,
            payload_response_only=True,
            result_path="$.result",
        )
        run.add_retry(
            errors=["RateLimitedError"],
            interval=Duration.seconds(30),
            backoff_rate=2,
            max_attempts=4,
        )
        run.add_retry(
            errors=["ConnectorError"], interval=Duration.seconds(10), backoff_rate=2, max_attempts=2
        )
        run.add_retry(
            errors=[
                "Lambda.TooManyRequestsException",
                "Lambda.ServiceException",
                "Lambda.SdkClientException",
            ],
            interval=Duration.seconds(5),
            max_attempts=3,
        )
        run.add_catch(sfn.Pass(self, "RecordTaskFailure"), result_path="$.error")

        fan_out = sfn.Map(
            self, "ForEachTask", items_path="$.tasks", max_concurrency=2, result_path="$.runs"
        )
        fan_out.item_processor(run)
        resolve = tasks.LambdaInvoke(
            self,
            "Resolve",
            lambda_function=self.resolver,
            payload_response_only=True,
            result_path="$.resolution",
        )
        score = tasks.LambdaInvoke(
            self,
            "Score",
            lambda_function=self.scorer,
            payload_response_only=True,
            result_path="$.scoring",
        )
        for step in (resolve, score):
            step.add_retry(
                errors=["States.TaskFailed"], interval=Duration.seconds(20), max_attempts=2
            )

        flow_logs = logs.LogGroup(
            self,
            "EnrichmentLogs",
            retention=retention(cfg.log_retention_days),
            removal_policy=removal,
        )
        return sfn.StateMachine(
            self,
            "Enrichment",
            state_machine_name=f"{cfg.prefix}-enrichment",
            definition_body=sfn.DefinitionBody.from_chainable(fan_out.next(resolve).next(score)),
            timeout=Duration.hours(2),
            tracing_enabled=True,
            logs=sfn.LogOptions(destination=flow_logs, level=sfn.LogLevel.ERROR),
        )

    def _schedules(self, cfg: EnvConfig) -> None:
        if cfg.discovery_tasks:
            payload = {
                "tasks": [
                    {
                        "connector": t.connector,
                        "playbook": t.playbook,
                        "params": t.params,
                        "credit_budget": t.credit_budget,
                    }
                    for t in cfg.discovery_tasks
                ]
            }
            events.Rule(
                self,
                "DiscoverySchedule",
                schedule=events.Schedule.expression(cfg.discovery_schedule),
                targets=[
                    targets.SfnStateMachine(
                        self.state_machine, input=events.RuleTargetInput.from_object(payload)
                    )
                ],
            )
        jobs = [
            ("ResolveEvery15Min", "rate(15 minutes)", self.resolver),
            ("ScoreHourly", "rate(1 hour)", self.scorer),
            ("Ga4Daily", "cron(30 3 * * ? *)", self.ga4_sync),
            ("RetentionNightly", "cron(0 4 * * ? *)", self.retention),
            ("DsarEvery15Min", "rate(15 minutes)", self.dsar_worker),
            ("AuditAnchorHourly", "rate(1 hour)", self.audit_anchor),
        ]
        for name, expression, fn in jobs:
            events.Rule(
                self,
                name,
                schedule=events.Schedule.expression(expression),
                targets=[targets.LambdaFunction(fn, retry_attempts=2)],
            )
