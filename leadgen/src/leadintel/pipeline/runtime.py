"""Per-container wiring for Lambda workers: settings, crypto, database, raw store.

Built lazily on first use and reused across warm invocations (KMS data keys,
Secrets Manager values and the database connection all amortize).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from leadintel.core.config import Settings, get_settings
from leadintel.core.logging import configure_logging
from leadintel.pipeline.icp import IcpProfile, load_icp
from leadintel.pipeline.service import PipelineService
from leadintel.security.blind_index import BlindIndexer
from leadintel.security.crypto import FieldCipher
from leadintel.security.keyring import build_blind_indexer, build_field_cipher
from leadintel.storage.db import Connection, connect, dsn_from_settings
from leadintel.storage.pipeline_repo import PipelineRepository
from leadintel.storage.raw_store import LocalRawStore, RawStore, S3RawStore


@dataclass
class Runtime:
    settings: Settings

    @cached_property
    def cipher(self) -> FieldCipher:
        return build_field_cipher(self.settings)

    @cached_property
    def bidx(self) -> BlindIndexer:
        return build_blind_indexer(self.settings)

    @cached_property
    def icp(self) -> IcpProfile:
        return load_icp()

    @cached_property
    def raw_store(self) -> RawStore:
        if self.settings.raw_bucket:
            import boto3

            return S3RawStore(
                boto3.client("s3", region_name=self.settings.aws_region), self.settings.raw_bucket
            )
        return LocalRawStore(f"{self.settings.local_data_dir}/raw")

    _conn: Connection | None = None

    def connection(self) -> Connection:
        if self._conn is None or self._conn.closed or self._conn.broken:
            self._conn = connect(
                dsn_from_settings(self.settings), application_name="leadintel-worker"
            )
        return self._conn

    def service(self) -> PipelineService:
        repo = PipelineRepository(self.connection(), cipher=self.cipher, bidx=self.bidx)
        return PipelineService(repo, raw_store=self.raw_store, bidx=self.bidx, icp=self.icp)


_runtime: Runtime | None = None


def runtime() -> Runtime:
    global _runtime
    if _runtime is None:
        settings = get_settings()
        configure_logging(settings.log_level)
        _runtime = Runtime(settings)
    return _runtime
