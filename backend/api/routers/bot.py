"""Auto-trading bot API endpoints.

Uses BotLifecycleManager (persistent state machine with crash recovery)
instead of the old TradingBot class.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException

from backend.services.bot_lifecycle import get_bot_manager
from backend.services.account_verification import get_angel_profile_sync

logger = logging.getLogger(__name__)

router = APIRouter(tags=["trading-bot"])


@router.post("/bot/start")
async def bot_start(config: dict | None = None):
    """Start the auto-trading bot with optional configuration."""
    mgr = get_bot_manager()
    return mgr.start(config)


@router.post("/bot/stop")
async def bot_stop():
    """Stop the auto-trading bot."""
    mgr = get_bot_manager()
    return mgr.stop()


@router.get("/bot/status")
async def bot_status():
    """Get current bot status, positions, and trade log."""
    mgr = get_bot_manager()
    return mgr.status


@router.get("/bot/account/profile")
async def bot_account_profile():
    """Verify AngelOne credentials from the trading-service environment."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, get_angel_profile_sync)


@router.post("/bot/pause")
async def bot_pause():
    """Pause trading (keep positions, no new trades)."""
    mgr = get_bot_manager()
    return mgr.pause()


@router.post("/bot/resume")
async def bot_resume():
    """Resume trading from paused state."""
    mgr = get_bot_manager()
    return mgr.resume()


@router.put("/bot/config")
async def bot_config(config: dict):
    """Update bot configuration without restarting."""
    mgr = get_bot_manager()
    return mgr.update_config(config)


@router.post("/bot/consent")
async def bot_consent(action: dict | None = None):
    """User responds to the consent prompt when market reopens.

    Body: {"resume": true} to resume, {"resume": false} to stop.
    """
    mgr = get_bot_manager()
    resume = True
    if action and "resume" in action:
        resume = action["resume"]
    if resume:
        return mgr.grant_consent()
    else:
        return mgr.decline_consent()


@router.get("/bot/transitions")
async def bot_transitions(limit: int = 50):
    """Get recent bot state transitions for audit."""
    try:
        from backend.db.session import SessionLocal
        from backend.db.models import BotStateTransition
        db = SessionLocal()
        try:
            rows = (
                db.query(BotStateTransition)
                .order_by(BotStateTransition.timestamp.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "from_state": r.from_state,
                    "to_state": r.to_state,
                    "reason": r.reason,
                    "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                }
                for r in rows
            ]
        finally:
            db.close()
    except Exception as exc:
        logger.exception("Bot endpoint error")
        raise HTTPException(status_code=500, detail="Internal server error")
