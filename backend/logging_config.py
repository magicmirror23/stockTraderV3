"""Centralized logging configuration for StockTrader backend.

Call `setup_logging()` once at application startup (before any routers run).
All existing `logging.getLogger(__name__)` calls will automatically pick up
the file handler + formatter configured here.

Logs are written to:
  - logs/backend.log  (all backend logs, rotating at 10 MB, 5 backups)
  - logs/frontend.log (Angular client logs forwarded via /api/v1/log endpoint)
  - console           (standard stderr output)
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOGS_DIR = Path(__file__).resolve().parents[1] / "logs"

_LOG_FORMAT = (
    "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"
)
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_MAX_BYTES = 10 * 1024 * 1024   # 10 MB
_BACKUP_COUNT = 5


def setup_logging(level: str | None = None) -> None:
    """Configure root logger with console + file handlers."""
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)

    log_level = getattr(logging, (level or os.getenv("LOG_LEVEL", "INFO")).upper(), logging.INFO)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    # --- File handler (backend.log) ---
    file_handler = RotatingFileHandler(
        _LOGS_DIR / "backend.log",
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)

    # --- Console handler ---
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)

    # --- Root logger ---
    root = logging.getLogger()
    root.setLevel(log_level)
    # Avoid duplicate handlers on reload
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    logging.getLogger("stocktrader").info(
        "Logging initialised — level=%s, file=%s", log_level, _LOGS_DIR / "backend.log"
    )


def get_frontend_logger() -> logging.Logger:
    """Return a dedicated logger that writes to logs/frontend.log."""
    logger = logging.getLogger("stocktrader.frontend")

    # Only add the handler once
    if not logger.handlers:
        _LOGS_DIR.mkdir(parents=True, exist_ok=True)
        formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

        fh = RotatingFileHandler(
            _LOGS_DIR / "frontend.log",
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(formatter)
        logger.addHandler(fh)
        logger.setLevel(logging.DEBUG)
        # Don't propagate to root (avoids duplicating in backend.log)
        logger.propagate = False

    return logger
