from __future__ import annotations

import base64

import boto3
import pytest
from cryptography.exceptions import InvalidTag
from moto import mock_aws

from leadintel.core.config import Settings
from leadintel.core.errors import ConfigurationError
from leadintel.security.crypto import MAGIC, FieldCipher, KmsKeyProvider, LocalKeyProvider
from leadintel.security.keyring import build_blind_indexer, build_field_cipher
from tests.conftest import TEST_BLIND_INDEX_KEY, TEST_MASTER_KEY


class CountingProvider(LocalKeyProvider):
    def __init__(self) -> None:
        super().__init__(TEST_MASTER_KEY)
        self.generated = 0
        self.unwrapped = 0

    def generate_data_key(self, context):  # type: ignore[no-untyped-def]
        self.generated += 1
        return super().generate_data_key(context)

    def decrypt_data_key(self, wrapped_key, context):  # type: ignore[no-untyped-def]
        self.unwrapped += 1
        return super().decrypt_data_key(wrapped_key, context)


def test_round_trip(cipher: FieldCipher) -> None:
    envelope = cipher.encrypt(b"jane@acme.example")
    assert envelope.startswith(MAGIC)
    assert b"jane" not in envelope
    assert cipher.decrypt(envelope) == b"jane@acme.example"


def test_json_round_trip(cipher: FieldCipher) -> None:
    payload = {"email": "jane@acme.example", "phone": "+14155550100"}
    assert cipher.decrypt_json(cipher.encrypt_json(payload)) == payload


def test_ciphertexts_are_randomized(cipher: FieldCipher) -> None:
    assert cipher.encrypt(b"same") != cipher.encrypt(b"same")


def test_tenant_binding_prevents_transplant() -> None:
    provider = LocalKeyProvider(TEST_MASTER_KEY)
    tenant_a = FieldCipher(provider, tenant_id="a")
    tenant_b = FieldCipher(provider, tenant_id="b")
    with pytest.raises(InvalidTag):
        tenant_b.decrypt(tenant_a.encrypt(b"secret"))


def test_tampering_is_detected(cipher: FieldCipher) -> None:
    envelope = bytearray(cipher.encrypt(b"secret"))
    envelope[-1] ^= 0x01
    with pytest.raises(InvalidTag):
        cipher.decrypt(bytes(envelope))


def test_rejects_foreign_envelopes(cipher: FieldCipher) -> None:
    with pytest.raises(ValueError, match="envelope"):
        cipher.decrypt(b"not-an-envelope")


def test_data_key_cache_bounds_kms_calls() -> None:
    clock = [0.0]
    provider = CountingProvider()
    cipher = FieldCipher(
        provider, tenant_id="t", cache_ttl_s=60, cache_max_uses=3, clock=lambda: clock[0]
    )
    envelopes = [cipher.encrypt(b"x") for _ in range(3)]
    assert provider.generated == 1
    cipher.encrypt(b"x")  # 4th use rotates the data key
    assert provider.generated == 2
    clock[0] = 61.0
    cipher.encrypt(b"x")  # TTL expiry rotates too
    assert provider.generated == 3
    for envelope in envelopes:
        cipher.decrypt(envelope)
    assert provider.unwrapped == 1  # same wrapped key, unwrapped once


def test_local_provider_requires_32_byte_key() -> None:
    with pytest.raises(ConfigurationError):
        LocalKeyProvider(b"short")


@mock_aws
def test_kms_provider_round_trip_with_encryption_context() -> None:
    kms = boto3.client("kms", region_name="us-east-1")
    key_id = kms.create_key(Description="test")["KeyMetadata"]["KeyId"]
    cipher = FieldCipher(KmsKeyProvider(kms, key_id), tenant_id="acme")
    assert cipher.decrypt(cipher.encrypt(b"pii")) == b"pii"


def _local_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "env": "local",
        "local_master_key_b64": base64.b64encode(TEST_MASTER_KEY).decode(),
        "local_blind_index_key_b64": base64.b64encode(TEST_BLIND_INDEX_KEY).decode(),
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_keyring_builds_local_primitives() -> None:
    settings = _local_settings()
    cipher = build_field_cipher(settings)
    assert cipher.decrypt(cipher.encrypt(b"v")) == b"v"
    assert len(build_blind_indexer(settings).index("a@b.example", field="email")) == 64


def test_keyring_refuses_missing_keys() -> None:
    with pytest.raises(ConfigurationError):
        build_field_cipher(Settings(env="local"))  # type: ignore[arg-type]
