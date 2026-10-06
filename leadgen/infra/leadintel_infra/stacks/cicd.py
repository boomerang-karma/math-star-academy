"""CI/CD trust: GitHub Actions deploys with short-lived OIDC credentials, no stored keys.

Deployed once per account by ``scripts/aws/bootstrap.sh``. The role can only be
assumed by workflows of the configured repository on ``main`` or a protected
GitHub environment. It deploys by assuming the CDK bootstrap roles (which carry
the actual deployment permissions); beyond that it may only read this
environment's stack outputs and invoke the in-VPC migrator, which is what
``scripts/aws/setup.sh`` does after ``cdk deploy``. Secrets and users are managed
by operators, not by CI.
"""

from __future__ import annotations

from typing import Any

from aws_cdk import CfnOutput, Duration, Stack
from aws_cdk import aws_iam as iam
from constructs import Construct

from leadintel_infra.config import EnvConfig


class CicdStack(Stack):
    def __init__(
        self, scope: Construct, construct_id: str, *, cfg: EnvConfig, **kwargs: Any
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        if not cfg.github_repository:
            raise ValueError(
                "set github_repository in the environment config to deploy the CI/CD stack"
            )
        provider = iam.OpenIdConnectProvider(
            self,
            "GitHubOidc",
            url="https://token.actions.githubusercontent.com",
            client_ids=["sts.amazonaws.com"],
        )
        role = iam.Role(
            self,
            "DeployRole",
            role_name=f"{cfg.prefix}-github-deploy",
            max_session_duration=Duration.hours(1),
            assumed_by=iam.WebIdentityPrincipal(
                provider.open_id_connect_provider_arn,
                conditions={
                    "StringEquals": {
                        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
                    },
                    "StringLike": {
                        "token.actions.githubusercontent.com:sub": [
                            f"repo:{cfg.github_repository}:ref:refs/heads/main",
                            f"repo:{cfg.github_repository}:environment:{cfg.name}",
                        ]
                    },
                },
            ),
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["sts:AssumeRole"],
                resources=[f"arn:aws:iam::{self.account}:role/cdk-*"],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["cloudformation:DescribeStacks"],
                resources=[
                    f"arn:aws:cloudformation:*:{self.account}:stack/CDKToolkit/*",
                    f"arn:aws:cloudformation:*:{self.account}:stack/{cfg.prefix}-*/*",
                ],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["lambda:InvokeFunction"],
                resources=[
                    f"arn:aws:lambda:{cfg.region}:{self.account}:function:"
                    f"{cfg.prefix}-ingestion-Migrator*"
                ],
            )
        )
        CfnOutput(self, "DeployRoleArn", value=role.role_arn)
