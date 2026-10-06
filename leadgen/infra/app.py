#!/usr/bin/env python3
"""CDK entry point.

    npx cdk synth  -c env=dev
    npx cdk deploy --all -c env=dev        (prefer scripts/aws/setup.sh)

Stacks are named ``leadintel-<env>-<unit>``. The edge stack (WAF for CloudFront)
always deploys to us-east-1; when the main region differs, the web stack reads
the ACL ARN through CDK cross-region references.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_lambda as lambda_

sys.path.insert(0, str(Path(__file__).resolve().parent))

from leadintel_infra.config import EnvConfig
from leadintel_infra.stacks.api import ApiStack
from leadintel_infra.stacks.cicd import CicdStack
from leadintel_infra.stacks.data import DataStack
from leadintel_infra.stacks.edge import EdgeStack
from leadintel_infra.stacks.ingestion import IngestionStack
from leadintel_infra.stacks.network import NetworkStack
from leadintel_infra.stacks.observability import ObservabilityStack
from leadintel_infra.stacks.security import SecurityStack
from leadintel_infra.stacks.web import WebStack


def build(app: cdk.App, cfg: EnvConfig) -> dict[str, cdk.Stack]:
    account = cfg.account or os.environ.get("CDK_DEFAULT_ACCOUNT")
    env = cdk.Environment(account=account, region=cfg.region)
    edge_env = cdk.Environment(account=account, region="us-east-1")
    cross_region = cfg.region != "us-east-1"
    asset_dir = str((Path(__file__).resolve().parent / cfg.lambda_asset_dir).resolve())
    p = cfg.prefix

    network = NetworkStack(app, f"{p}-network", cfg=cfg, env=env)
    security = SecurityStack(app, f"{p}-security", cfg=cfg, env=env)
    data = DataStack(app, f"{p}-data", cfg=cfg, network=network, security=security, env=env)
    ingestion = IngestionStack(
        app,
        f"{p}-ingestion",
        cfg=cfg,
        network=network,
        security=security,
        data=data,
        code=lambda_.Code.from_asset(asset_dir),
        env=env,
    )
    api = ApiStack(
        app,
        f"{p}-api",
        cfg=cfg,
        network=network,
        security=security,
        data=data,
        ingestion=ingestion,
        code=lambda_.Code.from_asset(asset_dir),
        env=env,
    )
    edge = EdgeStack(app, f"{p}-edge", cfg=cfg, env=edge_env, cross_region_references=cross_region)
    web = WebStack(
        app,
        f"{p}-web",
        cfg=cfg,
        api_domain=api.api_domain,
        web_acl_arn=edge.web_acl_arn,
        origin_verify_secret=security.origin_verify_secret,
        cognito_domain=f"{cfg.cognito_domain_prefix}.auth.{cfg.region}.amazoncognito.com",
        cognito_client_id=security.app_client.user_pool_client_id,
        logs_bucket=data.logs_bucket,
        env=env,
        cross_region_references=cross_region,
    )
    web.add_stack_dependency(edge)
    observability = ObservabilityStack(
        app,
        f"{p}-observability",
        cfg=cfg,
        security=security,
        data=data,
        ingestion=ingestion,
        api=api,
        env=env,
    )
    stacks: dict[str, cdk.Stack] = {
        "network": network,
        "security": security,
        "data": data,
        "ingestion": ingestion,
        "api": api,
        "edge": edge,
        "web": web,
        "observability": observability,
    }
    if cfg.github_repository:
        stacks["cicd"] = CicdStack(app, f"{p}-cicd", cfg=cfg, env=env)

    for stack in stacks.values():
        cdk.Tags.of(stack).add("project", "leadintel")
        cdk.Tags.of(stack).add("environment", cfg.name)
        cdk.Tags.of(stack).add("data-classification", "confidential")
        cdk.Tags.of(stack).add("managed-by", "cdk")
    return stacks


def main() -> None:
    app = cdk.App()
    env_name = app.node.try_get_context("env") or os.environ.get("LEADINTEL_DEPLOY_ENV", "dev")
    build(app, EnvConfig.load(env_name))
    app.synth()


if __name__ == "__main__":
    main()
