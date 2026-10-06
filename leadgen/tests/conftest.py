"""Shared fixtures. Integration fixtures (PostgreSQL) live in tests/integration/conftest.py."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from leadintel.core.config import Settings
from leadintel.security.blind_index import BlindIndexer
from leadintel.security.crypto import FieldCipher, LocalKeyProvider

# Fixed test keys. Never used outside tests (Settings refuses inline keys outside env=local).
TEST_MASTER_KEY = bytes(range(32))
TEST_BLIND_INDEX_KEY = bytes(range(32, 64))

# Tests must not depend on the developer's machine: no real AWS credentials, no
# LEADINTEL_* variables from the shell, and no leadgen/.env written by `make run-api`.
# LEADINTEL_TEST_* configure the test harness itself (e.g. CI's PostgreSQL) and stay.
for _var in list(os.environ):
    if (_var.startswith("LEADINTEL_") and not _var.startswith("LEADINTEL_TEST_")) or _var in (
        "AWS_PROFILE",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
    ):
        os.environ.pop(_var, None)
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
Settings.model_config["env_file"] = None


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def cipher() -> FieldCipher:
    return FieldCipher(LocalKeyProvider(TEST_MASTER_KEY), tenant_id="test")


@pytest.fixture
def bidx() -> BlindIndexer:
    return BlindIndexer(TEST_BLIND_INDEX_KEY)
