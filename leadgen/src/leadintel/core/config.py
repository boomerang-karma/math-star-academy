"""Runtime configuration, read from ``LEADINTEL_*`` environment variables.

In AWS, Lambda environment variables carry only *pointers* (secret ARNs, KMS
key ids, bucket names). Secret values are fetched at runtime through
:mod:`leadintel.security.secrets`, so nothing sensitive sits in the function
configuration or CloudFormation templates.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"
    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"


class AuthMode(StrEnum):
    COGNITO = "cognito"
    # Trusts X-Dev-User / X-Dev-Roles headers. Refused outside env=local (see validator).
    LOCAL_DEV = "local-dev"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LEADINTEL_", env_file=".env", extra="ignore")

    env: Environment = Environment.LOCAL
    tenant_id: str = "default"
    aws_region: str = "us-east-1"
    log_level: str = "INFO"

    # --- Database -----------------------------------------------------------------
    # Local: a DSN. AWS: an RDS-format Secrets Manager secret plus the RDS Proxy host.
    database_url: SecretStr | None = None
    db_secret_arn: str | None = None
    db_proxy_host: str | None = None
    db_name: str = "leadintel"
    # Lambdas authenticate to RDS Proxy with short-lived IAM tokens as this user (no password).
    db_iam_user: str | None = None
    # Migrator only: group role -> secret holding the login user the proxy uses for it.
    db_login_user_secrets: dict[str, str] = Field(default_factory=dict)
    # Local tooling only (demo loader): DSN of the pipeline-role login user.
    worker_database_url: SecretStr | None = None

    # --- Cryptography -------------------------------------------------------------
    pii_kms_key_id: str | None = None
    blind_index_secret_arn: str | None = None
    # Inline keys exist only so local runs and tests need no AWS. Refused elsewhere.
    local_master_key_b64: SecretStr | None = None
    local_blind_index_key_b64: SecretStr | None = None

    # --- Authentication -----------------------------------------------------------
    auth_mode: AuthMode = AuthMode.COGNITO
    cognito_user_pool_id: str | None = None
    cognito_app_client_id: str | None = None
    # CloudFront adds this header; requests without it did not come through the CDN/WAF.
    origin_verify_secret_arn: str | None = None
    cors_allowed_origins: list[str] = Field(default_factory=list)
    max_request_body_bytes: int = 1_000_000

    # --- ScrapeBadger -------------------------------------------------------------
    scrapebadger_api_key: SecretStr | None = None
    scrapebadger_secret_arn: str | None = None
    scrapebadger_timeout_s: float = 60.0
    scrapebadger_max_retries: int = 3
    scrapebadger_max_concurrency: int = 4
    scrapebadger_run_credit_budget: int = 2_000
    # Person-profile scraping is off until legal signs off (see docs/COMPLIANCE.md).
    allow_person_profile_scraping: bool = False

    # --- LinkedIn (official Lead Sync API) ----------------------------------------
    linkedin_client_secret_arn: str | None = None
    linkedin_access_token_secret_arn: str | None = None
    linkedin_api_version: str = "202608"

    # --- Google Analytics 4 -------------------------------------------------------
    ga4_property_id: str | None = None
    ga4_credentials_secret_arn: str | None = None
    ga4_visitor_dimension: str = "customUser:lead_visitor_id"

    # --- Storage & queues -----------------------------------------------------------
    raw_bucket: str | None = None
    audit_anchor_bucket: str | None = None
    dsar_export_bucket: str | None = None  # access/portability exports (DSAR worker)
    local_data_dir: str = ".data"
    web_events_queue_url: str | None = None
    linkedin_queue_url: str | None = None
    enrichment_state_machine_arn: str | None = None
    # Origins of the marketing site(s) allowed to post to the tracking beacon.
    beacon_allowed_origins: list[str] = Field(default_factory=list)

    # --- AI (Claude on Amazon Bedrock) --------------------------------------------
    ai_enabled: bool = False
    ai_model_id: str = "anthropic.claude-opus-5-5"
    ai_fallback_model_id: str = "anthropic.claude-opus-4-8"
    ai_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"

    @model_validator(mode="after")
    def _guardrails(self) -> Settings:
        local = self.env is Environment.LOCAL
        if self.auth_mode is AuthMode.LOCAL_DEV and not local:
            raise ValueError("auth_mode=local-dev is only permitted when env=local")
        if not local:
            if self.local_master_key_b64 or self.local_blind_index_key_b64:
                raise ValueError("inline crypto keys are local-only; use KMS and Secrets Manager")
            if not self.pii_kms_key_id:
                raise ValueError("pii_kms_key_id is required outside env=local")
            if not self.blind_index_secret_arn:
                raise ValueError("blind_index_secret_arn is required outside env=local")
            if self.scrapebadger_api_key is not None:
                raise ValueError(
                    "pass the ScrapeBadger key via scrapebadger_secret_arn outside local"
                )
        return self

    @property
    def is_local(self) -> bool:
        return self.env is Environment.LOCAL


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
