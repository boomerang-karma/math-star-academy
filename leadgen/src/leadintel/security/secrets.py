"""Secret retrieval with a short in-memory cache.

Secret references may address a JSON key inside a secret with ``<arn>#<key>``,
e.g. ``arn:aws:secretsmanager:...:secret:leadintel/dev/db#password``.
"""

from __future__ import annotations

import base64
import json
import os
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

from leadintel.core.errors import ConfigurationError


class SecretsProvider(Protocol):
    def get(self, reference: str) -> str: ...


class EnvSecretsProvider:
    """Resolves ``reference`` as an environment variable name. Local runs only."""

    def get(self, reference: str) -> str:
        value = os.environ.get(reference)
        if value is None:
            raise ConfigurationError(f"environment variable {reference!r} is not set")
        return value


class AwsSecretsManagerProvider:
    def __init__(
        self,
        client: Any,
        *,
        ttl_s: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._ttl = ttl_s
        self._clock = clock
        self._cache: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def _fetch(self, secret_id: str) -> str:
        now = self._clock()
        with self._lock:
            hit = self._cache.get(secret_id)
            if hit and now - hit[1] < self._ttl:
                return hit[0]
        response = self._client.get_secret_value(SecretId=secret_id)
        if "SecretString" in response:
            value = str(response["SecretString"])
        else:
            value = base64.b64encode(response["SecretBinary"]).decode()
        with self._lock:
            self._cache[secret_id] = (value, now)
        return value

    def get(self, reference: str) -> str:
        secret_id, _, json_key = reference.partition("#")
        value = self._fetch(secret_id)
        if not json_key:
            return value
        try:
            document = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ConfigurationError(f"secret {secret_id!r} is not JSON") from exc
        if json_key not in document:
            raise ConfigurationError(f"secret {secret_id!r} has no key {json_key!r}")
        return str(document[json_key])

    def invalidate(self, reference: str | None = None) -> None:
        with self._lock:
            if reference is None:
                self._cache.clear()
            else:
                self._cache.pop(reference.partition("#")[0], None)
