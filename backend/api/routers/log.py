"""Frontend log receiver — writes Angular client logs to logs/frontend.log.

POST /api/v1/log  { level, message, context?, timestamp? }
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.logging_config import get_frontend_logger

router = APIRouter(tags=["logging"])

_fe_log = get_frontend_logger()

_LEVEL_MAP: dict[str, int] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warn": logging.WARNING,
    "error": logging.ERROR,
}


class FrontendLogEntry(BaseModel):
    level: Literal["debug", "info", "warn", "error"] = "info"
    message: str = Field(..., max_length=2000)
    context: str | None = Field(None, max_length=500)
    timestamp: str | None = None


@router.post("/log", status_code=204)
async def receive_frontend_log(entry: FrontendLogEntry):
    """Accept a log entry from the Angular frontend and write to frontend.log."""
    lvl = _LEVEL_MAP.get(entry.level, logging.INFO)
    prefix = f"[{entry.context}] " if entry.context else ""
    _fe_log.log(lvl, "%s%s", prefix, entry.message)
