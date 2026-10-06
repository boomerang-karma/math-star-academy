"""Inbound webhook verification.

LinkedIn (Lead Sync ``leadNotifications``) validates endpoint ownership with a
challenge, then signs every POST with the app's client secret in the
``X-LI-Signature`` header (lowercase hex HMAC-SHA256). Always verify against the
raw request bytes; re-serialized JSON will not match.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Callable

from leadintel.core.errors import AuthenticationError


def _hmac_hex(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def linkedin_challenge_response(challenge_code: str, client_secret: str) -> dict[str, str]:
    """Body for the 200 response to LinkedIn's validation GET (must arrive within 3 s)."""
    return {
        "challengeCode": challenge_code,
        "challengeResponse": _hmac_hex(client_secret, challenge_code.encode()),
    }


def verify_linkedin_signature(
    raw_body: bytes, header_value: str | None, client_secret: str
) -> None:
    if not header_value:
        raise AuthenticationError("missing X-LI-Signature")
    received = header_value.strip().lower().removeprefix("hmacsha256=")
    # LinkedIn's guide signs "hmacsha256=" + body. The bare-body form is accepted too
    # because the documentation has been read both ways; both require the secret.
    candidates = (
        _hmac_hex(client_secret, b"hmacsha256=" + raw_body),
        _hmac_hex(client_secret, raw_body),
    )
    if not any(hmac.compare_digest(received, expected) for expected in candidates):
        raise AuthenticationError("invalid X-LI-Signature")


def verify_timestamped_hmac(
    raw_body: bytes,
    *,
    signature: str | None,
    timestamp: str | None,
    secret: str,
    tolerance_s: int = 300,
    clock: Callable[[], float] = time.time,
) -> None:
    """Generic ``HMAC(secret, f"{timestamp}.{body}")`` scheme with replay protection.

    Used for our own signed callbacks (CRM, scheduling tools that support it).
    """
    if not signature or not timestamp:
        raise AuthenticationError("missing signature headers")
    try:
        sent_at = int(timestamp)
    except ValueError as exc:
        raise AuthenticationError("malformed timestamp") from exc
    if abs(clock() - sent_at) > tolerance_s:
        raise AuthenticationError("stale or future-dated request")
    expected = _hmac_hex(secret, timestamp.encode() + b"." + raw_body)
    if not hmac.compare_digest(signature.strip().lower(), expected):
        raise AuthenticationError("invalid signature")
