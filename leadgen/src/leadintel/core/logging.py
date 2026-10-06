"""Structured JSON logging with PII redaction.

Every line is a single JSON object (CloudWatch Logs Insights can query fields
directly) and passes through :func:`leadintel.security.redaction.redact` so
emails, phone numbers and credentials never reach the log store.
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from leadintel.security.redaction import redact

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)

# Extra attributes callers may attach via ``logger.info(..., extra={...})``.
_EXTRA_FIELDS = (
    "event",
    "connector",
    "playbook",
    "run_id",
    "entity_id",
    "lead_id",
    "duration_ms",
    "status_code",
    "method",
    "path",
    "credits",
    "count",
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        request_id = request_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        for key in _EXTRA_FIELDS:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = redact(value) if isinstance(value, str) else value
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # Third-party clients log request URLs, which can carry query-string identifiers.
    for noisy in ("httpx", "httpcore", "botocore", "urllib3", "scrapebadger"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
