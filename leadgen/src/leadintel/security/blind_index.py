"""Blind indexes: searchable fingerprints of encrypted identifiers.

``HMAC-SHA256(key, field || 0x00 || value)`` lets the database answer "do we
already know jane@acme.com?" or "is this phone suppressed?" with an equality
lookup, without ever storing the plaintext. The field name is mixed in so the
same value yields unrelated indexes in different columns.

The key lives in Secrets Manager. Rotating it means re-indexing (the re-index
job decrypts each envelope and recomputes), which is why it is a separate secret
from the KMS key that protects the values themselves.
"""

from __future__ import annotations

import hashlib
import hmac

from leadintel.core.errors import ConfigurationError


class BlindIndexer:
    def __init__(self, key: bytes) -> None:
        if len(key) < 32:
            raise ConfigurationError("blind index key must be at least 32 bytes")
        self._key = key

    def index(self, value: str, *, field: str) -> str:
        # Callers pass normalized values; casefold+strip is a last line of defence.
        normalized = value.strip().casefold()
        if not normalized:
            raise ValueError("cannot blind-index an empty value")
        message = field.encode() + b"\x00" + normalized.encode()
        return hmac.new(self._key, message, hashlib.sha256).hexdigest()

    def maybe_index(self, value: str | None, *, field: str) -> str | None:
        if value is None or not value.strip():
            return None
        return self.index(value, field=field)
