"""Security foundations: keys, secrets, identity, and (optionally) account guardrails.

Keys
  data  Aurora storage, S3 zones, SQS, Secrets Manager, CloudWatch Logs.
  pii   Application-level envelope encryption of restricted attributes. Usable only
        with the encryption context ``app=leadintel`` (enforced in grants), so a
        stolen role credential cannot use it as a general-purpose decrypt oracle.

Secrets (values are never in CloudFormation)
  scrapebadger-api-key, linkedin-client-secret, linkedin-access-token,
  ga4-service-account: placeholders, set by ``scripts/aws/setup.sh`` from your shell.
  blind-index-key, origin-verify: generated here.

Identity
  Cognito user pool: no self sign-up, TOTP MFA required, threat protection on,
  one group per role (``leadintel-analyst`` ...), and a public PKCE client for the SPA.
"""

from __future__ import annotations

from typing import Any

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_cloudtrail as cloudtrail
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_guardduty as guardduty
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_securityhub as securityhub
from constructs import Construct

from leadintel_infra.config import EnvConfig
from leadintel_infra.constructs.secure_bucket import secure_bucket

ROLES = ("admin", "analyst", "sales_rep", "compliance_officer", "viewer")


class SecurityStack(Stack):
    def __init__(
        self, scope: Construct, construct_id: str, *, cfg: EnvConfig, **kwargs: Any
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        removal = RemovalPolicy.RETAIN if cfg.is_production else RemovalPolicy.DESTROY

        self.data_key = kms.Key(
            self,
            "DataKey",
            alias=f"alias/{cfg.prefix}/data",
            enable_key_rotation=True,
            description="LeadIntel data at rest",
            removal_policy=removal,
            pending_window=Duration.days(30 if cfg.is_production else 7),
        )
        # CloudWatch Logs encrypts log groups with this key.
        self.data_key.add_to_resource_policy(
            iam.PolicyStatement(
                principals=[iam.ServicePrincipal(f"logs.{self.region}.amazonaws.com")],
                actions=[
                    "kms:Encrypt*",
                    "kms:Decrypt*",
                    "kms:ReEncrypt*",
                    "kms:GenerateDataKey*",
                    "kms:Describe*",
                ],
                resources=["*"],
                conditions={
                    "ArnLike": {
                        "kms:EncryptionContext:aws:logs:arn": (
                            f"arn:aws:logs:{self.region}:{self.account}:*"
                        )
                    }
                },
            )
        )
        self.pii_key = kms.Key(
            self,
            "PiiKey",
            alias=f"alias/{cfg.prefix}/pii",
            enable_key_rotation=True,
            description="LeadIntel envelope encryption of restricted attributes",
            removal_policy=removal,
            pending_window=Duration.days(30 if cfg.is_production else 7),
        )

        def placeholder(name: str, description: str) -> secretsmanager.Secret:
            return secretsmanager.Secret(
                self,
                name.replace("-", " ").title().replace(" ", ""),
                secret_name=f"{cfg.prefix}/{name}",
                description=description,
                encryption_key=self.data_key,
                removal_policy=removal,
            )

        self.scrapebadger_secret = placeholder(
            "scrapebadger-api-key", "ScrapeBadger API key (set by setup.sh)"
        )
        self.linkedin_client_secret = placeholder(
            "linkedin-client-secret", "LinkedIn app client secret"
        )
        self.linkedin_token_secret = placeholder(
            "linkedin-access-token", "LinkedIn Lead Sync access token"
        )
        self.ga4_secret = placeholder("ga4-service-account", "GA4 service account JSON (read-only)")
        # 64 alphanumerics are valid base64 (48 bytes of key material for the HMAC).
        self.blind_index_secret = secretsmanager.Secret(
            self,
            "BlindIndexKey",
            secret_name=f"{cfg.prefix}/blind-index-key",
            description="HMAC key for blind indexes; rotating it requires a re-index",
            encryption_key=self.data_key,
            removal_policy=removal,
            generate_secret_string=secretsmanager.SecretStringGenerator(
                password_length=64, exclude_punctuation=True, include_space=False
            ),
        )
        self.origin_verify_secret = secretsmanager.Secret(
            self,
            "OriginVerify",
            secret_name=f"{cfg.prefix}/origin-verify",
            description="Shared header value proving a request came through CloudFront",
            encryption_key=self.data_key,
            removal_policy=removal,
            generate_secret_string=secretsmanager.SecretStringGenerator(
                password_length=48, exclude_punctuation=True, include_space=False
            ),
        )

        self.user_pool = cognito.UserPool(
            self,
            "Users",
            user_pool_name=f"{cfg.prefix}-users",
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(email=True),
            mfa=cognito.Mfa.REQUIRED,
            mfa_second_factor=cognito.MfaSecondFactor(sms=False, otp=True),
            password_policy=cognito.PasswordPolicy(
                min_length=14,
                require_digits=True,
                require_lowercase=True,
                require_uppercase=True,
                require_symbols=True,
                temp_password_validity=Duration.days(3),
            ),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            feature_plan=cognito.FeaturePlan.PLUS,
            standard_threat_protection_mode=cognito.StandardThreatProtectionMode.FULL_FUNCTION,
            deletion_protection=cfg.is_production,
            removal_policy=removal,
        )
        for role in ROLES:
            cognito.CfnUserPoolGroup(
                self,
                f"Group{role.title().replace('_', '')}",
                user_pool_id=self.user_pool.user_pool_id,
                group_name=f"leadintel-{role}",
                description=f"LeadIntel role: {role}",
            )
        self.domain = self.user_pool.add_domain(
            "Domain",
            cognito_domain=cognito.CognitoDomainOptions(domain_prefix=cfg.cognito_domain_prefix),
        )
        callback_urls = list(cfg.callback_urls) or ["https://localhost/auth/callback"]
        self.app_client = self.user_pool.add_client(
            "WebClient",
            user_pool_client_name=f"{cfg.prefix}-web",
            generate_secret=False,  # public SPA client: authorization code + PKCE
            auth_flows=cognito.AuthFlow(user_srp=True),
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[
                    cognito.OAuthScope.OPENID,
                    cognito.OAuthScope.EMAIL,
                    cognito.OAuthScope.PROFILE,
                ],
                callback_urls=callback_urls,
                logout_urls=[u.removesuffix("/auth/callback") + "/" for u in callback_urls],
            ),
            prevent_user_existence_errors=True,
            enable_token_revocation=True,
            access_token_validity=Duration.hours(1),
            id_token_validity=Duration.hours(1),
            refresh_token_validity=Duration.hours(12),
        )

        if cfg.account_guardrails:
            self._account_guardrails(cfg, removal)

        CfnOutput(self, "UserPoolId", value=self.user_pool.user_pool_id)
        CfnOutput(self, "AppClientId", value=self.app_client.user_pool_client_id)
        CfnOutput(self, "HostedUiDomain", value=self.domain.base_url())
        CfnOutput(self, "ScrapeBadgerSecretArn", value=self.scrapebadger_secret.secret_arn)

    def _account_guardrails(self, cfg: EnvConfig, removal: RemovalPolicy) -> None:
        """Account-level detective controls. Skip if a landing zone (Control Tower) owns them."""
        trail_bucket = secure_bucket(
            self, "TrailBucket", encryption_key=None, removal_policy=removal
        )
        trail = cloudtrail.Trail(
            self,
            "Trail",
            bucket=trail_bucket,
            is_multi_region_trail=True,
            enable_file_validation=True,
            include_global_service_events=True,
            encryption_key=self.data_key,
        )
        trail.add_s3_event_selector([], read_write_type=cloudtrail.ReadWriteType.WRITE_ONLY)
        guardduty.CfnDetector(
            self,
            "GuardDuty",
            enable=True,
            features=[
                guardduty.CfnDetector.CFNFeatureConfigurationProperty(
                    name="S3_DATA_EVENTS", status="ENABLED"
                ),
                guardduty.CfnDetector.CFNFeatureConfigurationProperty(
                    name="RDS_LOGIN_EVENTS", status="ENABLED"
                ),
                guardduty.CfnDetector.CFNFeatureConfigurationProperty(
                    name="LAMBDA_NETWORK_LOGS", status="ENABLED"
                ),
            ],
        )
        hub = securityhub.CfnHub(self, "SecurityHub")
        standard = securityhub.CfnStandard(
            self,
            "FoundationalBestPractices",
            standards_arn=f"arn:aws:securityhub:{self.region}::standards/aws-foundational-security-best-practices/v/1.0.0",
        )
        standard.node.add_dependency(hub)
