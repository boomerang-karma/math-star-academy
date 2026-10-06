"""Wire crypto primitives to configuration: inline keys locally, KMS/Secrets Manager in AWS."""

from __future__ import annotations

import base64
from typing import Any

from leadintel.core.config import Settings
from leadintel.core.errors import ConfigurationError
from leadintel.security.blind_index import BlindIndexer
from leadintel.security.crypto import FieldCipher, KmsKeyProvider, LocalKeyProvider
from leadintel.security.secrets import AwsSecretsManagerProvider, SecretsProvider


def _b64(value: str, what: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise ConfigurationError(f"{what} is not valid base64") from exc


def build_secrets_provider(settings: Settings, *, client: Any = None) -> SecretsProvider:
    if client is None:
        import boto3

        client = boto3.client("secretsmanager", region_name=settings.aws_region)
    return AwsSecretsManagerProvider(client)


def build_field_cipher(settings: Settings, *, kms_client: Any = None) -> FieldCipher:
    if settings.pii_kms_key_id:
        if kms_client is None:
            import boto3

            kms_client = boto3.client("kms", region_name=settings.aws_region)
        provider: KmsKeyProvider | LocalKeyProvider = KmsKeyProvider(
            kms_client, settings.pii_kms_key_id
        )
    elif settings.is_local and settings.local_master_key_b64 is not None:
        key = _b64(settings.local_master_key_b64.get_secret_value(), "local master key")
        provider = LocalKeyProvider(key)
    else:
        raise ConfigurationError("no PII key configured (pii_kms_key_id or local_master_key_b64)")
    return FieldCipher(provider, tenant_id=settings.tenant_id)


def build_blind_indexer(
    settings: Settings, *, secrets: SecretsProvider | None = None
) -> BlindIndexer:
    if settings.blind_index_secret_arn:
        provider = secrets or build_secrets_provider(settings)
        return BlindIndexer(_b64(provider.get(settings.blind_index_secret_arn), "blind index key"))
    if settings.is_local and settings.local_blind_index_key_b64 is not None:
        return BlindIndexer(
            _b64(settings.local_blind_index_key_b64.get_secret_value(), "blind index key")
        )
    raise ConfigurationError("no blind index key configured")
