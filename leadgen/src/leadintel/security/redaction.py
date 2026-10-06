"""Scrub personal identifiers and credentials from free text (log lines, error strings)."""

from __future__ import annotations

import logging
import re

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Credentials first, so later patterns do not partially match inside them.
    (re.compile(r"\beyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,}"), "[REDACTED_JWT]"),
    (re.compile(r"(?i)\bbearer\s+[\w.~+/=-]{8,}"), "Bearer [REDACTED_TOKEN]"),
    (re.compile(r"\bsb_(?:live|test)_[A-Za-z0-9]{6,}"), "[REDACTED_API_KEY]"),
    (re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"), "[REDACTED_AWS_KEY]"),
    (
        re.compile(r"(?i)\b(api[_-]?key|secret|password|token)\b\s*[=:]\s*['\"]?[^\s'\",;]{4,}"),
        r"\1=[REDACTED]",
    ),
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[REDACTED_EMAIL]"),
    # Phone-like: optional +, 9-15 digits with common separators.
    (re.compile(r"(?<![\w.])\+?\d[\d ().-]{7,18}\d(?![\w.])"), "[REDACTED_PHONE]"),
)


def redact(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFilter(logging.Filter):
    """For handlers that do not use JsonFormatter (e.g. third-party log forwarders)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None
        return True
