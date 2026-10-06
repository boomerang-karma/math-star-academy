"""Lambda functions built from the shared ``build/lambda`` bundle.

``scripts/build/lambda_bundle.sh`` produces one arm64/Python 3.12 bundle with the
``leadintel`` package and its dependencies; every function points a different
handler at it. Defaults: Graviton, X-Ray tracing, JSON logs with bounded
retention in a KMS-encrypted log group, VPC placement in the private subnets,
and environment variables that hold only pointers (ARNs, ids), never secrets.
"""

from __future__ import annotations

from collections.abc import Mapping

from aws_cdk import Duration, RemovalPolicy
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_kms as kms
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from constructs import Construct

RETENTION_DAYS = {
    1: logs.RetentionDays.ONE_DAY,
    7: logs.RetentionDays.ONE_WEEK,
    14: logs.RetentionDays.TWO_WEEKS,
    30: logs.RetentionDays.ONE_MONTH,
    90: logs.RetentionDays.THREE_MONTHS,
    180: logs.RetentionDays.SIX_MONTHS,
    365: logs.RetentionDays.ONE_YEAR,
}


def retention(days: int) -> logs.RetentionDays:
    return RETENTION_DAYS.get(days, logs.RetentionDays.ONE_MONTH)


class PythonFunction(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        handler: str,
        code: lambda_.Code,
        environment: Mapping[str, str],
        vpc: ec2.IVpc,
        security_group: ec2.ISecurityGroup,
        log_key: kms.IKey,
        log_retention_days: int,
        removal_policy: RemovalPolicy,
        memory_mb: int = 512,
        timeout: Duration | None = None,
        reserved_concurrency: int | None = None,
        description: str = "",
    ) -> None:
        super().__init__(scope, construct_id)
        self.log_group = logs.LogGroup(
            self,
            "Logs",
            encryption_key=log_key,
            retention=retention(log_retention_days),
            removal_policy=removal_policy,
        )
        self.function = lambda_.Function(
            self,
            "Function",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler=handler,
            code=code,
            memory_size=memory_mb,
            timeout=timeout or Duration.minutes(1),
            environment=dict(environment),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_groups=[security_group],
            tracing=lambda_.Tracing.ACTIVE,
            log_group=self.log_group,
            logging_format=lambda_.LoggingFormat.JSON,
            reserved_concurrent_executions=reserved_concurrency,
            description=description,
        )
