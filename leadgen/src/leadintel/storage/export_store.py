"""Delivery of DSAR exports: an S3 bucket in AWS, a local directory in development.

An access or portability export is decrypted personal data about one person, so
the worker only ever writes it: the AWS bucket is KMS-encrypted, private and
expires objects after 30 days, and the compliance team retrieves the file from
there (docs/RUNBOOK.md#data-subject-requests).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Protocol

from leadintel.core.errors import ValidationFailedError


class ExportStore(Protocol):
    def put(self, key: str, body: bytes) -> str:
        """Store ``body`` under ``key`` and return a URI the compliance team can use."""
        ...


def _check_key(key: str) -> str:
    parts = key.split("/")
    if not key or key.startswith("/") or any(p in {"", ".", ".."} for p in parts):
        raise ValidationFailedError(f"invalid export key {key!r}")
    return key


class LocalExportStore:
    def __init__(self, base_dir: str | Path) -> None:
        self._base = Path(base_dir)

    def put(self, key: str, body: bytes) -> str:
        path = self._base / _check_key(key)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(body)
        return path.resolve().as_uri()


class S3ExportStore:
    def __init__(self, s3_client: Any, bucket: str) -> None:
        self._s3 = s3_client
        self._bucket = bucket

    def put(self, key: str, body: bytes) -> str:
        # The bucket's default encryption (SSE-KMS) applies; no ACLs, no public access.
        self._s3.put_object(
            Bucket=self._bucket, Key=_check_key(key), Body=body, ContentType="application/json"
        )
        return f"s3://{self._bucket}/{key}"
