"""API: the FastAPI Lambda behind an API Gateway HTTP API.

Routes under ``/api/v1`` require a Cognito access token (JWT authorizer at the
edge, re-verified in the app). The unauthenticated routes are deliberately few:
health checks, the tracking beacon (strict schema, origin allow-list, WAF rate
limit) and the LinkedIn webhook (HMAC signature). Every request must also carry
the CloudFront ``X-Origin-Verify`` header, so the execute-api URL is useless
on its own.
"""

from __future__ import annotations

import json
from typing import Any

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_apigatewayv2_authorizers as authorizers
from aws_cdk import aws_apigatewayv2_integrations as integrations
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from constructs import Construct

from leadintel_infra.config import EnvConfig
from leadintel_infra.constructs.grants import allow_secret_read
from leadintel_infra.constructs.python_function import PythonFunction, retention
from leadintel_infra.stacks.data import API_DB_USER, DataStack
from leadintel_infra.stacks.ingestion import IngestionStack, pii_key_statement
from leadintel_infra.stacks.network import NetworkStack
from leadintel_infra.stacks.security import SecurityStack


class ApiStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        cfg: EnvConfig,
        network: NetworkStack,
        security: SecurityStack,
        data: DataStack,
        ingestion: IngestionStack,
        code: lambda_.Code,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        removal = RemovalPolicy.RETAIN if cfg.is_production else RemovalPolicy.DESTROY

        environment = {
            "LEADINTEL_ENV": cfg.name,
            "LEADINTEL_AWS_REGION": self.region,
            "LEADINTEL_AUTH_MODE": "cognito",
            "LEADINTEL_COGNITO_USER_POOL_ID": security.user_pool.user_pool_id,
            "LEADINTEL_COGNITO_APP_CLIENT_ID": security.app_client.user_pool_client_id,
            "LEADINTEL_ORIGIN_VERIFY_SECRET_ARN": security.origin_verify_secret.secret_arn,
            "LEADINTEL_PII_KMS_KEY_ID": security.pii_key.key_arn,
            "LEADINTEL_BLIND_INDEX_SECRET_ARN": security.blind_index_secret.secret_arn,
            "LEADINTEL_DB_PROXY_HOST": data.proxy.endpoint,
            "LEADINTEL_DB_IAM_USER": API_DB_USER,
            "LEADINTEL_WEB_EVENTS_QUEUE_URL": ingestion.web_events_queue.queue_url,
            "LEADINTEL_LINKEDIN_QUEUE_URL": ingestion.linkedin_queue.queue_url,
            "LEADINTEL_LINKEDIN_CLIENT_SECRET_ARN": security.linkedin_client_secret.secret_arn,
            "LEADINTEL_ENRICHMENT_STATE_MACHINE_ARN": ingestion.state_machine.state_machine_arn,
            "LEADINTEL_BEACON_ALLOWED_ORIGINS": json.dumps(cfg.beacon_allowed_origins),
            "LEADINTEL_AI_ENABLED": "true" if cfg.ai_enabled else "false",
        }
        construct = PythonFunction(
            self,
            "Api",
            handler="leadintel.api.lambda_handler.handler",
            code=code,
            environment=environment,
            vpc=network.vpc,
            security_group=network.lambda_sg,
            log_key=security.data_key,
            log_retention_days=cfg.log_retention_days,
            removal_policy=removal,
            memory_mb=1024,
            timeout=Duration.seconds(29),
            description="LeadIntel API",
        )
        fn = construct.function
        fn.add_to_role_policy(pii_key_statement(security.pii_key.key_arn))
        allow_secret_read(
            fn,
            security.blind_index_secret,
            security.origin_verify_secret,
            security.linkedin_client_secret,
            key=security.data_key,
        )
        data.proxy.grant_connect(fn, API_DB_USER)
        ingestion.web_events_queue.grant_send_messages(fn)
        ingestion.linkedin_queue.grant_send_messages(fn)
        ingestion.state_machine.grant_start_execution(fn)
        if cfg.ai_enabled:
            # Claude in Amazon Bedrock (Messages API). Scope to the model ARNs shown in the
            # Bedrock console once model access is granted for the account.
            fn.add_to_role_policy(
                iam.PolicyStatement(actions=["bedrock-mantle:CreateInference"], resources=["*"])
            )

        target: lambda_.IFunction = fn
        if cfg.api_provisioned_concurrency > 0:
            target = fn.add_alias(
                "live", provisioned_concurrent_executions=cfg.api_provisioned_concurrency
            )

        integration = integrations.HttpLambdaIntegration("ApiIntegration", target)
        issuer = (
            f"https://cognito-idp.{self.region}.amazonaws.com/{security.user_pool.user_pool_id}"
        )
        jwt = authorizers.HttpJwtAuthorizer(
            "CognitoJwt", jwt_issuer=issuer, jwt_audience=[security.app_client.user_pool_client_id]
        )

        access_logs = logs.LogGroup(
            self,
            "AccessLogs",
            retention=retention(cfg.log_retention_days),
            encryption_key=security.data_key,
            removal_policy=removal,
        )
        self.http_api = apigw.HttpApi(
            self,
            "HttpApi",
            api_name=f"{cfg.prefix}-api",
            create_default_stage=False,
        )
        stage = apigw.HttpStage(
            self,
            "Stage",
            http_api=self.http_api,
            stage_name="$default",
            auto_deploy=True,
            throttle=apigw.ThrottleSettings(
                rate_limit=cfg.api_throttle_rate, burst_limit=cfg.api_throttle_burst
            ),
        )
        cfn_stage = stage.node.default_child
        assert isinstance(cfn_stage, apigw.CfnStage)
        cfn_stage.access_log_settings = apigw.CfnStage.AccessLogSettingsProperty(
            destination_arn=access_logs.log_group_arn,
            format=json.dumps(
                {
                    "requestId": "$context.requestId",
                    "ip": "$context.identity.sourceIp",
                    "method": "$context.httpMethod",
                    "path": "$context.path",
                    "status": "$context.status",
                    "latency": "$context.responseLatency",
                    "sub": "$context.authorizer.claims.sub",
                    "integrationError": "$context.integrationErrorMessage",
                }
            ),
        )

        self.http_api.add_routes(
            path="/api/v1/{proxy+}",
            methods=[apigw.HttpMethod.ANY],
            integration=integration,
            authorizer=jwt,
        )
        public_routes = {
            "/api/healthz": [apigw.HttpMethod.GET],
            "/api/readyz": [apigw.HttpMethod.GET],
            "/api/collect": [apigw.HttpMethod.POST, apigw.HttpMethod.OPTIONS],
            "/api/webhooks/linkedin": [apigw.HttpMethod.GET, apigw.HttpMethod.POST],
        }
        for path, methods in public_routes.items():
            self.http_api.add_routes(path=path, methods=methods, integration=integration)

        self.api_domain = f"{self.http_api.api_id}.execute-api.{self.region}.amazonaws.com"
        self.api_function = fn
        CfnOutput(self, "ApiDomain", value=self.api_domain)
