"""Turning tracked companies into enrichment executions."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from leadintel.pipeline.tracking import (
    TASKS_PER_EXECUTION,
    EnrichmentUnavailableError,
    research_task,
    start_research,
)


def test_task_carries_only_known_identifiers() -> None:
    assert research_task(
        {"name": "Acme", "domain": None, "linkedin_slug": "acme"}, credit_budget=50
    ) == {
        "connector": "scrapebadger",
        "playbook": "account_research",
        "params": {"company_name": "Acme", "linkedin_slug": "acme"},
        "credit_budget": 50,
    }


def test_large_lists_are_chunked_into_several_executions() -> None:
    sfn = MagicMock()
    sfn.start_execution.side_effect = lambda **kw: {"executionArn": kw["name"]}
    companies = [{"name": f"Co {i}"} for i in range(TASKS_PER_EXECUTION * 2 + 1)]
    arns = start_research(sfn, "arn:sm", companies, credit_budget=10, name_prefix="t")
    assert len(arns) == 3
    sizes = [
        len(json.loads(c.kwargs["input"])["tasks"]) for c in sfn.start_execution.call_args_list
    ]
    assert sizes == [TASKS_PER_EXECUTION, TASKS_PER_EXECUTION, 1]


def test_refuses_without_a_state_machine() -> None:
    with pytest.raises(EnrichmentUnavailableError):
        start_research(None, None, [{"name": "Acme"}], credit_budget=10, name_prefix="t")
