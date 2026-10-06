"""Tracked companies: the admin page's API and the daily research job, on a real database."""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import psycopg
import pytest
from fastapi.testclient import TestClient

from leadintel.core.config import Settings
from leadintel.pipeline import handlers
from leadintel.pipeline.runtime import Runtime
from leadintel.storage.db import connect
from tests.conftest import TEST_BLIND_INDEX_KEY, TEST_MASTER_KEY
from tests.integration.test_api import ANALYST, client, seeded  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration

ADMIN = {"x-dev-user": "00000000-0000-0000-0000-0000000000e1", "x-dev-roles": "admin"}
BASE = "/api/v1/tracked-companies"


def test_admin_adds_and_lists_with_graph_match(client: TestClient) -> None:  # noqa: F811
    added = client.post(
        BASE,
        headers=ADMIN,
        json={
            "name": "  Northwind   Analytics ",
            "domain": "https://www.NorthwindAnalytics.com/about",
        },
    )
    assert added.status_code == 201, added.text
    body = added.json()
    assert body["name"] == "Northwind Analytics"
    assert body["domain"] == "northwindanalytics.com"
    assert body["status"] == "active"
    # The seeded pipeline already resolved this company, so the page links to it.
    assert body["entity"] is not None
    assert body["lead"] is not None
    assert body["lead"]["tier"] in {"A", "B", "C", "D"}

    listed = client.get(BASE, headers=ADMIN).json()["items"]
    assert [c["domain"] for c in listed] == ["northwindanalytics.com"]


def test_inputs_are_normalized_and_validated(client: TestClient) -> None:  # noqa: F811
    by_page = client.post(
        BASE,
        headers=ADMIN,
        json={"name": "Contoso", "linkedin": "https://www.linkedin.com/company/contoso-ltd/"},
    )
    assert by_page.status_code == 201, by_page.text
    assert by_page.json()["linkedin_slug"] == "contoso-ltd"
    assert by_page.json()["entity"] is None  # not collected yet

    duplicate = client.post(
        BASE, headers=ADMIN, json={"name": "NW", "domain": "northwindanalytics.com"}
    )
    assert duplicate.status_code == 409
    assert (
        client.post(BASE, headers=ADMIN, json={"name": "X", "domain": "gmail.com"}).status_code
        == 422
    )
    person = client.post(
        BASE, headers=ADMIN, json={"name": "X", "linkedin": "linkedin.com/in/someone"}
    )
    assert person.status_code == 422
    assert client.post(BASE, headers=ADMIN, json={"name": ""}).status_code == 422


def test_only_admins_manage_the_list(client: TestClient) -> None:  # noqa: F811
    assert client.get(BASE, headers=ANALYST).status_code == 403
    assert client.post(BASE, headers=ANALYST, json={"name": "Globex"}).status_code == 403


def test_pause_research_and_remove(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    company = client.post(BASE, headers=ADMIN, json={"name": "Initech"}).json()
    url = f"{BASE}/{company['id']}"

    paused = client.patch(url, headers=ADMIN, json={"status": "paused", "notes": "Q3 only"})
    assert paused.json()["status"] == "paused"
    assert paused.json()["notes"] == "Q3 only"
    assert client.patch(url, headers=ADMIN, json={"notes": ""}).json()["notes"] is None

    # Locally there is no Step Functions: a clear 503, not a crash.
    unavailable = client.post(f"{url}/research", headers=ADMIN)
    assert unavailable.status_code == 503
    assert unavailable.json()["type"].endswith("/enrichment_unavailable")

    services = client.services  # type: ignore[attr-defined]
    sfn = MagicMock()
    sfn.start_execution.return_value = {"executionArn": "arn:aws:states:us-east-1:1:execution:x:y"}
    monkeypatch.setattr(services, "stepfunctions", sfn)
    monkeypatch.setattr(services.settings, "enrichment_state_machine_arn", "arn:aws:states:sm")
    started = client.post(f"{url}/research", headers=ADMIN)
    assert started.status_code == 202, started.text
    task = json.loads(sfn.start_execution.call_args.kwargs["input"])["tasks"][0]
    assert task["playbook"] == "account_research"
    assert task["params"] == {"company_name": "Initech"}
    assert task["credit_budget"] == services.settings.tracked_research_credit_budget
    listed = {c["id"]: c for c in client.get(BASE, headers=ADMIN).json()["items"]}
    assert listed[company["id"]]["last_run_status"] == "queued"

    assert client.delete(url, headers=ADMIN).status_code == 204
    assert client.delete(url, headers=ADMIN).status_code == 404


@pytest.fixture
def worker_runtime(
    seeded: dict[str, str],  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Runtime]:
    rt = Runtime(
        Settings(
            env="local",
            tenant_id="test",
            local_master_key_b64=base64.b64encode(TEST_MASTER_KEY).decode(),
            local_blind_index_key_b64=base64.b64encode(TEST_BLIND_INDEX_KEY).decode(),
            local_data_dir=str(tmp_path),
            enrichment_state_machine_arn="arn:aws:states:us-east-1:123456789012:stateMachine:sm",
        )
    )
    rt._conn = connect(seeded["worker"])
    monkeypatch.setattr(handlers, "runtime", lambda: rt)
    yield rt
    rt._conn.close()


def test_daily_job_researches_active_companies_only(
    worker_runtime: Runtime,
    seeded: dict[str, str],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with psycopg.connect(seeded["owner"]) as conn:
        conn.execute("DELETE FROM sales.tracked_company")
        conn.execute(
            "INSERT INTO sales.tracked_company (name, domain, status, added_by) VALUES"
            " ('Active Co', 'active.example', 'active', 't'),"
            " ('Paused Co', 'paused.example', 'paused', 't')"
        )
    sfn = MagicMock()
    sfn.start_execution.return_value = {"executionArn": "arn:x"}
    monkeypatch.setattr("boto3.client", lambda *a, **k: sfn)

    assert handlers.tracked_companies({}) == {"companies": 1, "executions": 1}
    tasks: list[dict[str, Any]] = json.loads(sfn.start_execution.call_args.kwargs["input"])["tasks"]
    assert [t["params"]["domain"] for t in tasks] == ["active.example"]
    with psycopg.connect(seeded["owner"]) as conn:
        rows = dict(
            conn.execute(
                "SELECT name, last_run_status FROM sales.tracked_company ORDER BY name"
            ).fetchall()
        )
    assert rows == {"Active Co": "queued", "Paused Co": None}
