"""Synthesize the CDK app and assert the security posture of the generated templates.

These run without AWS credentials or Docker. They need the ``infra`` dependency
group (aws-cdk-lib) and Node.js for jsii; otherwise they are skipped.
"""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path
from typing import Any

import pytest

cdk = pytest.importorskip("aws_cdk")
from aws_cdk.assertions import Match, Template  # noqa: E402

from leadintel_infra.config import EnvConfig  # noqa: E402

pytestmark = pytest.mark.infra


@dataclasses.dataclass
class Synth:
    templates: dict[str, Template]
    outdir: Path


def _synth(name: str, tmp: Path) -> Synth:
    import app as cdk_app

    lambda_dir = tmp / "lambda"
    (lambda_dir / "leadintel").mkdir(parents=True)
    (lambda_dir / "leadintel" / "__init__.py").write_text("")
    # Shaped like `npm run build` output, including the local-dev config.json from public/.
    web_dir = tmp / "web"
    (web_dir / "assets").mkdir(parents=True)
    (web_dir / "index.html").write_text("<!doctype html><title>LeadIntel</title>")
    (web_dir / "favicon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    (web_dir / "config.json").write_text('{"authMode": "local-dev"}')
    (web_dir / "assets" / "index-abc123.js").write_text("console.log(1)")
    cfg = dataclasses.replace(
        EnvConfig.load(name), lambda_asset_dir=str(lambda_dir), web_asset_dir=str(web_dir)
    )
    outdir = tmp / "cdk.out"
    app = cdk.App(outdir=str(outdir))
    stacks = cdk_app.build(app, cfg)
    return Synth({key: Template.from_stack(stack) for key, stack in stacks.items()}, outdir)


@pytest.fixture(scope="module")
def dev_synth(tmp_path_factory: pytest.TempPathFactory) -> Synth:
    return _synth("dev", tmp_path_factory.mktemp("dev"))


@pytest.fixture(scope="module")
def dev(dev_synth: Synth) -> dict[str, Template]:
    return dev_synth.templates


@pytest.fixture(scope="module")
def prod(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Template]:
    return _synth("prod", tmp_path_factory.mktemp("prod")).templates


def _resources(template: Template, kind: str) -> dict[str, Any]:
    found: dict[str, Any] = template.find_resources(kind)
    return found


def test_all_stacks_synthesize(dev: dict[str, Template], prod: dict[str, Template]) -> None:
    assert set(dev) == {
        "network",
        "security",
        "data",
        "ingestion",
        "api",
        "edge",
        "web",
        "observability",
    }
    assert "cicd" in prod  # prod config names a GitHub repository


def test_network_tiers_and_endpoints(dev: dict[str, Template]) -> None:
    network = dev["network"]
    network.resource_count_is("AWS::EC2::NatGateway", 1)
    network.resource_count_is("AWS::EC2::FlowLog", 1)
    network.resource_count_is("AWS::EC2::VPCEndpoint", 7)  # S3 gateway + 6 interface endpoints
    network.has_output("NatEgressIp1", {})


def test_keys_rotate_and_identity_is_locked_down(dev: dict[str, Template]) -> None:
    security = dev["security"]
    for key in _resources(security, "AWS::KMS::Key").values():
        assert key["Properties"]["EnableKeyRotation"] is True
    security.has_resource_properties(
        "AWS::Cognito::UserPool",
        {
            "MfaConfiguration": "ON",
            "AdminCreateUserConfig": {"AllowAdminCreateUserOnly": True},
            "UserPoolTier": "PLUS",
        },
    )
    security.resource_count_is("AWS::Cognito::UserPoolGroup", 5)
    security.has_resource_properties(
        "AWS::Cognito::UserPoolClient",
        {
            "GenerateSecret": False,
            "AllowedOAuthFlows": ["code"],
            "PreventUserExistenceErrors": "ENABLED",
        },
    )
    # No secret value is ever embedded in the template.
    for secret in _resources(security, "AWS::SecretsManager::Secret").values():
        assert "SecretString" not in secret["Properties"]


def test_database_is_encrypted_private_and_iam_only(
    dev: dict[str, Template], prod: dict[str, Template]
) -> None:
    data = dev["data"]
    data.has_resource_properties(
        "AWS::RDS::DBCluster",
        {
            "StorageEncrypted": True,
            "EnableIAMDatabaseAuthentication": True,
            "EngineVersion": Match.string_like_regexp("^16\\."),
            "ServerlessV2ScalingConfiguration": {"MinCapacity": 0, "MaxCapacity": 4},
        },
    )
    data.has_resource_properties("AWS::RDS::DBProxy", {"RequireTLS": True})
    for proxy in _resources(data, "AWS::RDS::DBProxy").values():
        assert all(a["IAMAuth"] == "REQUIRED" for a in proxy["Properties"]["Auth"])
    data.has_resource_properties(
        "AWS::RDS::DBClusterParameterGroup",
        {"Parameters": Match.object_like({"rds.force_ssl": "1"})},
    )

    prod["data"].has_resource(
        "AWS::RDS::DBCluster",
        {
            "DeletionPolicy": "Snapshot",
            "Properties": Match.object_like(
                {"DeletionProtection": True, "BackupRetentionPeriod": 30}
            ),
        },
    )


def test_buckets_block_public_access_and_require_tls(dev: dict[str, Template]) -> None:
    for name in ("data", "web"):
        template = dev[name]
        for bucket in _resources(template, "AWS::S3::Bucket").values():
            props = bucket["Properties"]
            assert props["PublicAccessBlockConfiguration"] == {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            }
            assert "BucketEncryption" in props
        policies = json.dumps(_resources(template, "AWS::S3::BucketPolicy"))
        assert '"aws:SecureTransport": "false"' in policies
    dev["data"].has_resource_properties(
        "AWS::S3::Bucket",
        {
            "ObjectLockEnabled": True,
            "ObjectLockConfiguration": {
                "ObjectLockEnabled": "Enabled",
                "Rule": {"DefaultRetention": {"Mode": "GOVERNANCE", "Days": 1}},
            },
        },
    )


def test_workers_are_private_arm64_and_traced(dev: dict[str, Template]) -> None:
    functions = _resources(dev["ingestion"], "AWS::Lambda::Function")
    platform = {
        k: v for k, v in functions.items() if v["Properties"].get("Runtime") == "python3.12"
    }
    assert len(platform) == 10
    for fn in platform.values():
        props = fn["Properties"]
        assert props["Architectures"] == ["arm64"]
        assert props["TracingConfig"] == {"Mode": "Active"}
        assert "VpcConfig" in props
        for value in props["Environment"]["Variables"].values():
            assert "password" not in json.dumps(value).lower()
    for queue in _resources(dev["ingestion"], "AWS::SQS::Queue").values():
        assert "KmsMasterKeyId" in queue["Properties"]
    dev["ingestion"].resource_count_is("AWS::StepFunctions::StateMachine", 1)
    dev["ingestion"].has_resource_properties(
        "AWS::Events::Rule", {"ScheduleExpression": "rate(15 minutes)"}
    )


def test_pii_key_use_requires_encryption_context(dev: dict[str, Template]) -> None:
    policies = json.dumps(_resources(dev["api"], "AWS::IAM::Policy"))
    assert '"kms:EncryptionContext:app": "leadintel"' in policies


def test_api_routes_require_jwt_except_public_ingress(dev: dict[str, Template]) -> None:
    routes = _resources(dev["api"], "AWS::ApiGatewayV2::Route")
    by_key = {r["Properties"]["RouteKey"]: r["Properties"] for r in routes.values()}
    assert by_key["ANY /api/v1/{proxy+}"]["AuthorizationType"] == "JWT"
    public = {k for k, v in by_key.items() if v.get("AuthorizationType", "NONE") == "NONE"}
    assert public == {
        "GET /api/healthz",
        "GET /api/readyz",
        "POST /api/collect",
        "OPTIONS /api/collect",
        "GET /api/webhooks/linkedin",
        "POST /api/webhooks/linkedin",
    }
    dev["api"].has_resource_properties(
        "AWS::ApiGatewayV2::Stage",
        {"DefaultRouteSettings": {"ThrottlingRateLimit": 50, "ThrottlingBurstLimit": 100}},
    )


def test_edge_and_cdn_hardening(dev: dict[str, Template]) -> None:
    edge = dev["edge"]
    edge.has_resource_properties("AWS::WAFv2::WebACL", {"Scope": "CLOUDFRONT"})
    acl = next(iter(_resources(edge, "AWS::WAFv2::WebACL").values()))
    rule_names = {r["Name"] for r in acl["Properties"]["Rules"]}
    assert {"beacon-rate-limit", "ip-rate-limit", "AWSManagedRulesCommonRuleSet"} <= rule_names

    web = dev["web"]
    web.has_resource_properties(
        "AWS::CloudFront::Distribution",
        {
            "DistributionConfig": Match.object_like(
                {
                    "WebACLId": Match.any_value(),
                    "HttpVersion": "http2and3",
                    "CacheBehaviors": [
                        Match.object_like(
                            {
                                "PathPattern": "/api/*",
                                "ViewerProtocolPolicy": "https-only",
                                # Managed-CachingDisabled
                                "CachePolicyId": "4135ea2d-6df8-44a3-9df3-4b5a84be39ad",
                            }
                        )
                    ],
                }
            )
        },
    )
    web.has_resource_properties(
        "AWS::CloudFront::ResponseHeadersPolicy",
        {
            "ResponseHeadersPolicyConfig": Match.object_like(
                {
                    "SecurityHeadersConfig": Match.object_like(
                        {
                            "StrictTransportSecurity": Match.object_like({"Preload": True}),
                            "FrameOptions": {"FrameOption": "DENY", "Override": True},
                        }
                    )
                }
            )
        },
    )
    web.resource_count_is("AWS::CloudFront::OriginAccessControl", 1)


def test_spa_deploys_runtime_config_with_split_caching(dev_synth: Synth) -> None:
    web = dev_synth.templates["web"]
    deployments = _resources(web, "Custom::CDKBucketDeployment")
    assert len(deployments) == 2
    by_cache = {d["Properties"]["SystemMetadata"]["cache-control"]: d for d in deployments.values()}
    assert set(by_cache) == {"public, max-age=31536000, immutable", "no-cache"}

    bundles = by_cache["public, max-age=31536000, immutable"]["Properties"]
    assert bundles["Prune"] is False  # open tabs may still load superseded bundles
    entry_resource = by_cache["no-cache"]
    entry = entry_resource["Properties"]
    assert entry["DistributionPaths"] == ["/index.html", "/favicon.svg", "/config.json"]
    # Entry files go up only after the bundles they reference.
    assert any(dep.startswith("DeployBundles") for dep in entry_resource.get("DependsOn", [])), (
        entry_resource.get("DependsOn")
    )
    # The Cognito client id is a deploy-time value substituted into config.json.
    assert "Fn::ImportValue" in json.dumps(entry["SourceMarkers"])

    # The build's local-dev config.json is never staged; the generated one is (with
    # deploy-time markers where the client id goes).
    configs = [
        json.loads(re.sub(r"<<marker:0xbaba:\d+>>", '"deploy-time"', path.read_text()))
        for path in dev_synth.outdir.glob("asset.*/config.json")
    ]
    assert [c["authMode"] for c in configs] == ["cognito"]
    assert configs[0]["environment"] == "dev"
    assert configs[0]["clientId"] == "deploy-time"
    staged = {
        str(path.relative_to(path.parents[0]))
        for path in dev_synth.outdir.glob("asset.*/*")
        if path.name in {"index.html", "favicon.svg", "assets"}
    }
    assert staged == {"index.html", "favicon.svg", "assets"}


def test_custom_domain_enforces_tls12(tmp_path: Path) -> None:
    # The TLS minimum only applies with a custom domain + ACM certificate (prod should set both).
    import app as cdk_app

    lambda_dir = tmp_path / "lambda"
    lambda_dir.mkdir()
    cfg = dataclasses.replace(
        EnvConfig.load("dev"),
        lambda_asset_dir=str(lambda_dir),
        web_asset_dir=str(tmp_path / "none"),
        domain_name="leads.example.com",
        certificate_arn="arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000000",
    )
    stacks = cdk_app.build(cdk.App(outdir=str(tmp_path / "out")), cfg)
    Template.from_stack(stacks["web"]).has_resource_properties(
        "AWS::CloudFront::Distribution",
        {
            "DistributionConfig": Match.object_like(
                {
                    "Aliases": ["leads.example.com"],
                    "ViewerCertificate": Match.object_like(
                        {"MinimumProtocolVersion": "TLSv1.2_2021", "SslSupportMethod": "sni-only"}
                    ),
                }
            )
        },
    )


def test_ci_deploy_role_is_narrow(prod: dict[str, Template]) -> None:
    cicd = prod["cicd"]
    statements = [
        statement
        for policy in _resources(cicd, "AWS::IAM::Policy").values()
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]
    ]
    actions = sorted(
        action
        for statement in statements
        for action in (
            [statement["Action"]] if isinstance(statement["Action"], str) else statement["Action"]
        )
    )
    # Deploy through the CDK roles, read stack outputs, run migrations: nothing else.
    assert actions == ["cloudformation:DescribeStacks", "lambda:InvokeFunction", "sts:AssumeRole"]
    invoke = next(s for s in statements if s["Action"] == "lambda:InvokeFunction")
    assert "leadintel-prod-ingestion-Migrator*" in json.dumps(invoke["Resource"])
    [trust] = [
        doc
        for role in _resources(cicd, "AWS::IAM::Role").values()
        if "token.actions.githubusercontent.com"
        in (doc := json.dumps(role["Properties"]["AssumeRolePolicyDocument"]))
    ]
    assert "ref:refs/heads/main" in trust
    assert "environment:prod" in trust


def test_no_wildcard_admin_policies(dev: dict[str, Template]) -> None:
    for name, template in dev.items():
        for policy in _resources(template, "AWS::IAM::Policy").values():
            for statement in policy["Properties"]["PolicyDocument"]["Statement"]:
                actions = (
                    statement["Action"]
                    if isinstance(statement["Action"], list)
                    else [statement["Action"]]
                )
                assert "*" not in actions, f"{name}: wildcard action in {statement}"


def test_alarms_exist(dev: dict[str, Template]) -> None:
    alarms = _resources(dev["observability"], "AWS::CloudWatch::Alarm")
    names = {a["Properties"]["AlarmName"] for a in alarms.values()}
    assert "leadintel-dev-enrichment-failed" in names
    assert "leadintel-dev-scrapebadger-daily-credits" in names
    assert any("dlq" in n for n in names)


def test_config_guardrails() -> None:
    prod = EnvConfig.load("prod")
    with pytest.raises(ValueError, match="pin their AWS account"):
        dataclasses.replace(prod, account=None).validate()
    with pytest.raises(ValueError, match="snapshot"):
        dataclasses.replace(prod, db_removal="destroy").validate()
    with pytest.raises(FileNotFoundError):
        EnvConfig.load("nonexistent")
