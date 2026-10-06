"""Observability: alarms to an SNS topic, an operations dashboard, and a cost budget.

Alarms are deliberately few and actionable: a dead-letter queue with messages,
a worker that errors, a failed enrichment run, API 5xx, Aurora near its ACU
ceiling, and ScrapeBadger credit burn above the daily allowance.
"""

from __future__ import annotations

from typing import Any

from aws_cdk import Duration, Stack
from aws_cdk import aws_budgets as budgets
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subscriptions
from constructs import Construct

from leadintel_infra.config import EnvConfig
from leadintel_infra.stacks.api import ApiStack
from leadintel_infra.stacks.data import DataStack
from leadintel_infra.stacks.ingestion import IngestionStack
from leadintel_infra.stacks.security import SecurityStack


class ObservabilityStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        cfg: EnvConfig,
        security: SecurityStack,
        data: DataStack,
        ingestion: IngestionStack,
        api: ApiStack,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        topic = sns.Topic(
            self,
            "Alarms",
            topic_name=f"{cfg.prefix}-alarms",
            master_key=security.data_key,
            enforce_ssl=True,
        )
        if cfg.alarm_email:
            topic.add_subscription(subscriptions.EmailSubscription(cfg.alarm_email))
        action = cw_actions.SnsAction(topic)

        def alarm(
            name: str,
            metric: cw.IMetric,
            threshold: float,
            *,
            periods: int = 1,
            comparison: cw.ComparisonOperator = cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
        ) -> cw.Alarm:
            created = cw.Alarm(
                self,
                name,
                alarm_name=f"{cfg.prefix}-{name}",
                metric=metric,
                threshold=threshold,
                evaluation_periods=periods,
                comparison_operator=comparison,
                treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            )
            created.add_alarm_action(action)
            return created

        for index, dlq in enumerate(ingestion.dead_letter_queues):
            alarm(
                f"dlq-{index}-not-empty",
                dlq.metric_approximate_number_of_messages_visible(period=Duration.minutes(5)),
                0,
            )
        workers = {
            "connector-runner": ingestion.connector_runner,
            "resolver": ingestion.resolver,
            "scorer": ingestion.scorer,
            "web-events": ingestion.web_events,
            "linkedin-leads": ingestion.linkedin_worker,
            "dsar-worker": ingestion.dsar_worker,
            "retention": ingestion.retention,
            "tracked-companies": ingestion.tracked_worker,
            "api": api.api_function,
        }
        for name, fn in workers.items():
            alarm(
                f"{name}-errors",
                fn.metric_errors(period=Duration.minutes(5)),
                0 if name != "api" else 5,
            )
        alarm(
            "enrichment-failed",
            ingestion.state_machine.metric_failed(period=Duration.minutes(5)),
            0,
        )
        api_5xx = cw.Metric(
            namespace="AWS/ApiGateway",
            metric_name="5xx",
            dimensions_map={"ApiId": api.http_api.api_id},
            statistic="Sum",
            period=Duration.minutes(5),
        )
        alarm("api-5xx", api_5xx, 10)
        capacity = cw.Metric(
            namespace="AWS/RDS",
            metric_name="ServerlessDatabaseCapacity",
            dimensions_map={"DBClusterIdentifier": data.cluster.cluster_identifier},
            statistic="Maximum",
            period=Duration.minutes(5),
        )
        alarm("aurora-near-max-capacity", capacity, cfg.db_max_acu * 0.9, periods=3)
        credits = cw.Metric(
            namespace="LeadIntel",
            metric_name="CreditsUsed",
            statistic="Sum",
            period=Duration.days(1),
        )
        # Workers also publish CreditsUsed without dimensions, so it can be alarmed on directly.
        alarm("scrapebadger-daily-credits", credits, cfg.scrapebadger_run_credit_budget * 4)

        dashboard = cw.Dashboard(self, "Dashboard", dashboard_name=f"{cfg.prefix}-operations")
        dashboard.add_widgets(
            cw.GraphWidget(
                title="API latency (p95) and errors",
                left=[api.api_function.metric_duration(statistic="p95")],
                right=[api_5xx],
            ),
            cw.GraphWidget(
                title="Worker errors", left=[fn.metric_errors() for fn in workers.values()]
            ),
        )
        dashboard.add_widgets(
            cw.GraphWidget(title="Aurora capacity (ACU)", left=[capacity]),
            cw.GraphWidget(title="ScrapeBadger credits", left=[credits]),
            cw.GraphWidget(
                title="Queues",
                left=[
                    ingestion.web_events_queue.metric_approximate_number_of_messages_visible(),
                    ingestion.linkedin_queue.metric_approximate_number_of_messages_visible(),
                ],
            ),
        )

        if cfg.alarm_email:
            budgets.CfnBudget(
                self,
                "MonthlyBudget",
                budget=budgets.CfnBudget.BudgetDataProperty(
                    budget_name=f"{cfg.prefix}-monthly",
                    budget_type="COST",
                    time_unit="MONTHLY",
                    budget_limit=budgets.CfnBudget.SpendProperty(
                        amount=cfg.monthly_budget_usd, unit="USD"
                    ),
                    cost_filters={"TagKeyValue": [f"user:environment${cfg.name}"]},
                ),
                notifications_with_subscribers=[
                    budgets.CfnBudget.NotificationWithSubscribersProperty(
                        notification=budgets.CfnBudget.NotificationProperty(
                            comparison_operator="GREATER_THAN",
                            notification_type=kind,
                            threshold=threshold,
                            threshold_type="PERCENTAGE",
                        ),
                        subscribers=[
                            budgets.CfnBudget.SubscriberProperty(
                                address=cfg.alarm_email, subscription_type="EMAIL"
                            )
                        ],
                    )
                    for kind, threshold in (("FORECASTED", 100), ("ACTUAL", 80))
                ],
            )
