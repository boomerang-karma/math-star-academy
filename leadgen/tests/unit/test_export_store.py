"""DSAR export delivery: private files locally, private objects in S3, never silently dropped."""

from __future__ import annotations

import stat
from pathlib import Path
from typing import Any

import pytest

from leadintel.core.config import Settings
from leadintel.core.errors import ConfigurationError, ValidationFailedError
from leadintel.pipeline.runtime import Runtime
from leadintel.storage.export_store import LocalExportStore, S3ExportStore


class FakeS3:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def put_object(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


def test_local_store_writes_owner_only_files(tmp_path: Path) -> None:
    store = LocalExportStore(tmp_path / "exports")
    uri = store.put("dsar/abc.json", b'{"a": 1}')
    path = tmp_path / "exports" / "dsar" / "abc.json"
    assert uri == path.resolve().as_uri()
    assert path.read_bytes() == b'{"a": 1}'
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "key", ["../escape.json", "/abs.json", "dsar//x.json", "", "dsar/./x.json"]
)
def test_keys_cannot_escape_the_store(tmp_path: Path, key: str) -> None:
    with pytest.raises(ValidationFailedError):
        LocalExportStore(tmp_path).put(key, b"{}")
    with pytest.raises(ValidationFailedError):
        S3ExportStore(FakeS3(), "bucket").put(key, b"{}")


def test_s3_store_puts_json_objects() -> None:
    s3 = FakeS3()
    uri = S3ExportStore(s3, "leadintel-dev-dsar").put("dsar/abc.json", b"{}")
    assert uri == "s3://leadintel-dev-dsar/dsar/abc.json"
    assert s3.calls == [
        {
            "Bucket": "leadintel-dev-dsar",
            "Key": "dsar/abc.json",
            "Body": b"{}",
            "ContentType": "application/json",
        }
    ]


def _aws_settings(**overrides: Any) -> Settings:
    return Settings(
        env="dev",
        pii_kms_key_id="arn:aws:kms:us-east-1:123456789012:key/00000000-0000-0000-0000-000000000000",
        blind_index_secret_arn="arn:aws:secretsmanager:us-east-1:123456789012:secret:bidx",
        **overrides,
    )


def test_runtime_refuses_to_drop_exports_outside_local() -> None:
    with pytest.raises(ConfigurationError):
        _ = Runtime(_aws_settings()).export_store


def test_runtime_uses_the_configured_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    s3 = FakeS3()
    monkeypatch.setattr("boto3.client", lambda *args, **kwargs: s3)
    store = Runtime(_aws_settings(dsar_export_bucket="leadintel-dev-dsar")).export_store
    assert store.put("dsar/x.json", b"{}") == "s3://leadintel-dev-dsar/dsar/x.json"
