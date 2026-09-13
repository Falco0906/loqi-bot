"""Centralized logging configuration (PR10.4).

Small standard-library setup: configurable level/format from environment,
structured JSON output for production, human-readable output for development.

Correlation: ``request_id`` and other safe identifiers may be attached to a
record via ``extra=`` (see ``structured_log``) and are emitted as JSON fields.

Secret safety: this module never formats secrets. Messages are emitted as-is;
the rest of the codebase is responsible for not passing secret values.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
STRUCTURED_FIELDS = (
    "request_id",
    "workspace_id",
    "user_id",
    "provider_id",
    "conversation_id",
    "thread_id",
    "discovery_id",
    "workflow_id",
    "duration_ms",
    "status",
    "error_type",
)


def log_level_from_env(env: dict[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    level = (source.get("LOG_LEVEL") or "INFO").strip().upper()
    if level not in VALID_LEVELS:
        return "INFO"
    return level


def log_format_from_env(env: dict[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    fmt = (source.get("LOG_FORMAT") or "text").strip().lower()
    return "json" if fmt == "json" else "text"


class JsonFormatter(logging.Formatter):
    """Minimal JSON log formatter (newline-delimited JSON)."""

    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for key in STRUCTURED_FIELDS:
            value = getattr(record, key, None)
            if value is not None:
                data[key] = value
        if record.exc_info:
            data["error_type"] = record.exc_info[0].__name__ if record.exc_info[0] else "Exception"
            data["exc"] = self.formatException(record.exc_info)
        try:
            return json.dumps(data, default=str)
        except (TypeError, ValueError):
            data["event"] = str(data.get("event", ""))[:500]
            return json.dumps(data, default=str)


def configure_logging(env: dict[str, str] | None = None) -> None:
    """Apply the configured level/formatter to the root logger.

    Safe to call more than once; only formatter/level are updated. Never sets
    DEBUG from this layer (production DEBUG is rejected by config validation).
    """
    source = os.environ if env is None else env
    level = log_level_from_env(source)
    fmt = log_format_from_env(source)

    root = logging.getLogger()
    root.setLevel(getattr(logging, level, logging.INFO))
    for handler in root.handlers:
        handler.setLevel(getattr(logging, level, logging.INFO))
        if fmt == "json":
            handler.setFormatter(JsonFormatter())

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def structured_log(
    logger: logging.Logger,
    level: int,
    event: str,
    **fields: Any,
) -> None:
    """Emit a log record with safe structured fields attached."""
    logger.log(level, event, extra={key: value for key, value in fields.items() if value is not None})
