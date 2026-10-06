"""Tracked companies: turning the admin's watch list into enrichment runs.

Each active tracked company becomes one ``account_research`` task (company page,
website, news) on the enrichment state machine. Executions are chunked so one
run stays well inside the state machine's two-hour timeout.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any
from uuid import uuid4

from leadintel.core.errors import LeadIntelError

TASKS_PER_EXECUTION = 20


class EnrichmentUnavailableError(LeadIntelError):
    status_code = 503
    code = "enrichment_unavailable"


def research_task(company: Mapping[str, Any], *, credit_budget: int | None) -> dict[str, Any]:
    params: dict[str, Any] = {"company_name": company["name"]}
    if company.get("domain"):
        params["domain"] = company["domain"]
    if company.get("linkedin_slug"):
        params["linkedin_slug"] = company["linkedin_slug"]
    return {
        "connector": "scrapebadger",
        "playbook": "account_research",
        "params": params,
        "credit_budget": credit_budget,
    }


def start_research(
    stepfunctions: Any,
    state_machine_arn: str | None,
    companies: Iterable[Mapping[str, Any]],
    *,
    credit_budget: int | None,
    name_prefix: str,
) -> list[str]:
    """Start one execution per chunk of companies; returns the execution ARNs."""
    if stepfunctions is None or not state_machine_arn:
        raise EnrichmentUnavailableError(
            "research runs on the AWS enrichment pipeline, which is not configured here"
        )
    tasks = [research_task(c, credit_budget=credit_budget) for c in companies]
    arns = []
    for start in range(0, len(tasks), TASKS_PER_EXECUTION):
        execution = stepfunctions.start_execution(
            stateMachineArn=state_machine_arn,
            name=f"{name_prefix}-{uuid4().hex[:12]}",
            input=json.dumps({"tasks": tasks[start : start + TASKS_PER_EXECUTION]}),
        )
        arns.append(execution["executionArn"])
    return arns
