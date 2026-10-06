"""Per-environment deployment configuration (``infra/config/<env>.json``).

Everything that differs between dev, staging and prod lives in these files:
sizing, retention, protection flags, schedules. Stacks never branch on the
environment *name*, only on these explicit settings.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


@dataclass(frozen=True)
class ScheduledTask:
    connector: str
    playbook: str
    params: dict[str, Any]
    credit_budget: int | None = None


@dataclass(frozen=True)
class EnvConfig:
    name: str
    account: str | None
    region: str
    vpc_cidr: str
    max_azs: int
    nat_gateways: int
    # Aurora Serverless v2 (ACUs). min 0 enables auto-pause (dev).
    db_min_acu: float
    db_max_acu: float
    db_reader: bool
    db_backup_days: int
    db_removal: str  # "snapshot" | "destroy"
    deletion_protection: bool
    raw_retention_days: int
    log_retention_days: int
    audit_object_lock_mode: str  # "governance" | "compliance"
    audit_object_lock_days: int
    api_provisioned_concurrency: int
    api_throttle_rate: int
    api_throttle_burst: int
    waf_rate_limit_per_5min: int
    beacon_rate_limit_per_5min: int
    cognito_domain_prefix: str
    callback_urls: list[str]
    beacon_allowed_origins: list[str]
    alarm_email: str | None
    monthly_budget_usd: int
    scrapebadger_run_credit_budget: int
    ai_enabled: bool
    account_guardrails: bool
    domain_name: str | None = None
    certificate_arn: str | None = None
    github_repository: str | None = None
    discovery_schedule: str = "cron(0 2 * * ? *)"
    discovery_tasks: list[ScheduledTask] = field(default_factory=list)
    lambda_asset_dir: str = "../build/lambda"
    web_asset_dir: str = "../web/dist"

    @property
    def prefix(self) -> str:
        return f"leadintel-{self.name}"

    @property
    def is_production(self) -> bool:
        return self.deletion_protection

    @classmethod
    def load(cls, name: str, *, directory: Path = CONFIG_DIR) -> EnvConfig:
        path = directory / f"{name}.json"
        if not path.exists():
            raise FileNotFoundError(f"no deployment config for environment {name!r} ({path})")
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw.pop("$comment", None)
        tasks = [ScheduledTask(**t) for t in raw.pop("discovery_tasks", [])]
        config = cls(name=name, discovery_tasks=tasks, **raw)
        config.validate()
        return config

    def validate(self) -> None:
        if self.db_removal not in {"snapshot", "destroy"}:
            raise ValueError("db_removal must be 'snapshot' or 'destroy'")
        if self.audit_object_lock_mode not in {"governance", "compliance"}:
            raise ValueError("audit_object_lock_mode must be 'governance' or 'compliance'")
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", self.cognito_domain_prefix):
            raise ValueError("cognito_domain_prefix: lowercase letters, digits and hyphens only")
        if self.db_min_acu < 0 or self.db_max_acu < max(self.db_min_acu, 1):
            raise ValueError("invalid Aurora capacity range")
        if self.is_production:
            if self.account is None:
                raise ValueError("protected environments must pin their AWS account id")
            if self.db_removal != "snapshot":
                raise ValueError("protected environments must snapshot the database on removal")
            if self.nat_gateways < 2:
                raise ValueError("protected environments need a NAT gateway per AZ (>= 2)")
