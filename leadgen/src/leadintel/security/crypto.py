"""Envelope encryption for restricted attributes (email, personal phone).

Each value is encrypted with AES-256-GCM under a *data key*; the data key is
wrapped by a KMS customer-managed key and stored inside the envelope. The
encryption context (tenant, purpose, app) is bound twice: into the KMS call
(so the key policy can require it and CloudTrail records it) and into the GCM
associated data (so a ciphertext cannot be transplanted to another tenant).

Envelope layout (version 1)::

    b"LI" 0x01 | u16 wrapped_key_len | wrapped_key | 12-byte nonce | ciphertext+tag

Data keys are cached for a short time and a bounded number of messages, the
same trade-off the AWS Encryption SDK's caching CMM makes: a handful of KMS
calls per Lambda container instead of one per field.
"""

from __future__ import annotations

import json
import os
import struct
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from leadintel.core.errors import ConfigurationError

MAGIC = b"LI\x01"
_NONCE_LEN = 12
_KEY_LEN = 32


class KeyProvider(Protocol):
    def generate_data_key(self, context: Mapping[str, str]) -> tuple[bytes, bytes]:
        """Return ``(plaintext_key, wrapped_key)``."""
        ...

    def decrypt_data_key(self, wrapped_key: bytes, context: Mapping[str, str]) -> bytes: ...


def _context_bytes(context: Mapping[str, str]) -> bytes:
    return json.dumps(dict(sorted(context.items())), separators=(",", ":")).encode()


class KmsKeyProvider:
    """Data keys from AWS KMS. ``kms_client`` is a ``boto3.client("kms")``."""

    def __init__(self, kms_client: Any, key_id: str) -> None:
        self._kms = kms_client
        self._key_id = key_id

    def generate_data_key(self, context: Mapping[str, str]) -> tuple[bytes, bytes]:
        response = self._kms.generate_data_key(
            KeyId=self._key_id, KeySpec="AES_256", EncryptionContext=dict(context)
        )
        return response["Plaintext"], response["CiphertextBlob"]

    def decrypt_data_key(self, wrapped_key: bytes, context: Mapping[str, str]) -> bytes:
        response = self._kms.decrypt(
            CiphertextBlob=wrapped_key, KeyId=self._key_id, EncryptionContext=dict(context)
        )
        plaintext: bytes = response["Plaintext"]
        return plaintext


class LocalKeyProvider:
    """Wraps data keys with an in-process master key. For local runs and tests only."""

    def __init__(self, master_key: bytes) -> None:
        if len(master_key) != _KEY_LEN:
            raise ConfigurationError("local master key must be exactly 32 bytes")
        self._aead = AESGCM(master_key)

    def generate_data_key(self, context: Mapping[str, str]) -> tuple[bytes, bytes]:
        data_key = AESGCM.generate_key(bit_length=256)
        nonce = os.urandom(_NONCE_LEN)
        wrapped = nonce + self._aead.encrypt(nonce, data_key, _context_bytes(context))
        return data_key, wrapped

    def decrypt_data_key(self, wrapped_key: bytes, context: Mapping[str, str]) -> bytes:
        nonce, sealed = wrapped_key[:_NONCE_LEN], wrapped_key[_NONCE_LEN:]
        return self._aead.decrypt(nonce, sealed, _context_bytes(context))


@dataclass
class _CachedKey:
    plaintext: bytes
    wrapped: bytes
    created: float
    uses: int = 0


class FieldCipher:
    def __init__(
        self,
        provider: KeyProvider,
        *,
        tenant_id: str,
        purpose: str = "pii",
        cache_ttl_s: float = 300.0,
        cache_max_uses: int = 10_000,
        decrypt_cache_size: int = 256,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._provider = provider
        self._context = {"app": "leadintel", "tenant": tenant_id, "purpose": purpose}
        self._aad = _context_bytes(self._context)
        self._ttl = cache_ttl_s
        self._max_uses = cache_max_uses
        self._clock = clock
        self._current: _CachedKey | None = None
        self._unwrapped: OrderedDict[bytes, tuple[bytes, float]] = OrderedDict()
        self._unwrapped_max = decrypt_cache_size
        self._lock = threading.Lock()

    @property
    def encryption_context(self) -> dict[str, str]:
        return dict(self._context)

    def _data_key(self) -> _CachedKey:
        with self._lock:
            now = self._clock()
            key = self._current
            if key is None or key.uses >= self._max_uses or now - key.created > self._ttl:
                plaintext, wrapped = self._provider.generate_data_key(self._context)
                key = _CachedKey(plaintext=plaintext, wrapped=wrapped, created=now)
                self._current = key
            key.uses += 1
            return key

    def _unwrap(self, wrapped: bytes) -> bytes:
        now = self._clock()
        with self._lock:
            hit = self._unwrapped.get(wrapped)
            if hit is not None and now - hit[1] <= self._ttl:
                self._unwrapped.move_to_end(wrapped)
                return hit[0]
        plaintext = self._provider.decrypt_data_key(wrapped, self._context)
        with self._lock:
            self._unwrapped[wrapped] = (plaintext, now)
            while len(self._unwrapped) > self._unwrapped_max:
                self._unwrapped.popitem(last=False)
        return plaintext

    def encrypt(self, plaintext: bytes) -> bytes:
        key = self._data_key()
        nonce = os.urandom(_NONCE_LEN)
        sealed = AESGCM(key.plaintext).encrypt(nonce, plaintext, self._aad)
        return MAGIC + struct.pack(">H", len(key.wrapped)) + key.wrapped + nonce + sealed

    def decrypt(self, envelope: bytes) -> bytes:
        if not envelope.startswith(MAGIC):
            raise ValueError("not a LeadIntel v1 envelope")
        offset = len(MAGIC)
        (wrapped_len,) = struct.unpack_from(">H", envelope, offset)
        offset += 2
        wrapped = envelope[offset : offset + wrapped_len]
        offset += wrapped_len
        nonce = envelope[offset : offset + _NONCE_LEN]
        sealed = envelope[offset + _NONCE_LEN :]
        return AESGCM(self._unwrap(wrapped)).decrypt(nonce, sealed, self._aad)

    def encrypt_json(self, value: Mapping[str, Any]) -> bytes:
        return self.encrypt(json.dumps(dict(value), sort_keys=True).encode())

    def decrypt_json(self, envelope: bytes) -> dict[str, Any]:
        decoded: dict[str, Any] = json.loads(self.decrypt(envelope))
        return decoded
