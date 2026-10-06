"""Bronze zone: upstream payloads kept verbatim so mappers can be re-run.

Object keys never contain upstream identifiers (which can be names or emails):
``raw/source=<source>/dt=<yyyy-mm-dd>/run=<run id>/<sha256(external_id)>.json``.
The S3 bucket enforces SSE-KMS, TLS-only access and a 30-day expiry; DSAR
erasure deletes a subject's objects immediately via ``source_record.raw_uri``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from leadintel.ontology.models import RawPayload


def object_key(payload: RawPayload, run_id: UUID) -> str:
    digest = hashlib.sha256(payload.external_id.encode()).hexdigest()[:32]
    extension = "html" if payload.content_type.startswith("text/html") else "json"
    return (
        f"raw/source={payload.source.value}/dt={payload.fetched_at:%Y-%m-%d}"
        f"/run={run_id}/{digest}.{extension}"
    )


def _body(payload: RawPayload) -> bytes:
    if isinstance(payload.body, str | bytes):
        return payload.body.encode() if isinstance(payload.body, str) else payload.body
    return json.dumps(payload.body, default=str, sort_keys=True).encode()


class RawStore(Protocol):
    def put(self, payload: RawPayload, *, run_id: UUID) -> str: ...

    def delete(self, uri: str) -> None: ...


class LocalRawStore:
    def __init__(self, base_dir: str | Path) -> None:
        self._base = Path(base_dir)

    def put(self, payload: RawPayload, *, run_id: UUID) -> str:
        path = self._base / object_key(payload, run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_body(payload))
        return path.resolve().as_uri()

    def delete(self, uri: str) -> None:
        Path(uri.removeprefix("file://")).unlink(missing_ok=True)


class S3RawStore:
    def __init__(self, s3_client: Any, bucket: str) -> None:
        self._s3 = s3_client
        self._bucket = bucket

    def put(self, payload: RawPayload, *, run_id: UUID) -> str:
        key = object_key(payload, run_id)
        response = self._s3.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=_body(payload),
            ContentType=payload.content_type,
            ServerSideEncryption="aws:kms",  # bucket key policy pins the CMK
        )
        version = response.get("VersionId")
        return f"s3://{self._bucket}/{key}" + (f"?versionId={version}" if version else "")

    def delete(self, uri: str) -> None:
        location, _, version = uri.removeprefix("s3://").partition("?versionId=")
        bucket, _, key = location.partition("/")
        kwargs: dict[str, Any] = {"Bucket": bucket, "Key": key}
        if version:
            kwargs["VersionId"] = version
        self._s3.delete_object(**kwargs)
