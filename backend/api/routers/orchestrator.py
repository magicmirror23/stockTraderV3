"""Market orchestrator API endpoints."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["market-orchestrator"])


def _orch():
    from backend.services.market_orchestrator import get_market_orchestrator
    return get_market_orchestrator()


@router.get("/orchestrator/session")
async def session_info():
    """Current market session information (phase, status, dry-run)."""
    return _orch().get_session_info()


@router.post("/orchestrator/start")
async def start_orchestrator():
    """Start the background market orchestrator loop."""
    _orch().start()
    return {"status": "started"}


@router.post("/orchestrator/stop")
async def stop_orchestrator():
    """Stop the background market orchestrator loop."""
    _orch().stop()
    return {"status": "stopped"}


@router.post("/orchestrator/dry-run/enable")
async def enable_dry_run(payload: dict | None = None):
    """Enable dry-run mode (simulate a market phase).

    Body: {phase?: "pre_open" | "open" | "close_only" | "closed"}
    """
    phase = "open"
    if payload and "phase" in payload:
        phase = payload["phase"]
    return _orch().enable_dry_run(phase)


@router.post("/orchestrator/dry-run/disable")
async def disable_dry_run():
    """Disable dry-run mode, return to live market hours."""
    return _orch().disable_dry_run()


@router.post("/orchestrator/simulate")
async def simulate_transition(payload: dict):
    """Simulate a market phase transition (for testing/demo).

    Body: {phase: str}
    """
    return _orch().simulate_transition(payload["phase"])
