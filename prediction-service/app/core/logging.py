"""Structured JSON logging setup.

Call ``setup_logging()`` once at application startup.  Every module then uses
the standard ``logging.getLogger(__name__)`` pattern and gets JSON output with
correlation ids, service name, and ISO timestamps.
"""

from __future__ import annotations

import logging
import sys
import json
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings


class _JSONFormatter(logging.Formatter):
    """Emit one JSON object per log line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": settings.SERVICE_NAME,
            "environment": settings.ENVIRONMENT,
        }
        if record.exc_info and record.exc_info[1]:
            payload["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "correlation_id"):
            payload["correlation_id"] = record.correlation_id
        return json.dumps(payload, default=str)


def setup_logging() -> None:
    """Configure the root logger to emit structured JSON to stderr."""
    root = logging.getLogger()
    root.setLevel(settings.LOG_LEVEL)

    # Remove existing handlers
    for h in root.handlers[:]:
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_JSONFormatter())
    root.addHandler(handler)

    # Quieten noisy third-party loggers
    for name in ("uvicorn.access", "httpx", "httpcore", "urllib3", "watchfiles"):
        logging.getLogger(name).setLevel(logging.WARNING)

    logging.getLogger("app").setLevel(settings.LOG_LEVEL)
