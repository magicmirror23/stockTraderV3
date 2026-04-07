"""Trade supervisor router – centralized risk control API."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from backend.intraday.trade_supervisor import TradeSupervisor
from backend.intraday.schemas import (
    SupervisorApprovalRequest,
    SupervisorApprovalResponse,
    SupervisorResumeRequest,
    SupervisorStatusResponse,
)
from backend.services.monitoring import set_supervisor_state, record_supervisor_trigger

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/intraday/supervisor", tags=["intraday-supervisor"])

_supervisor = TradeSupervisor()


def get_supervisor() -> TradeSupervisor:
    return _supervisor


@router.post("/approve", response_model=SupervisorApprovalResponse)
async def approve_trade(req: SupervisorApprovalRequest):
    """Request trade approval from the risk supervisor."""
    approval = _supervisor.approve_trade(
        symbol=req.symbol,
        side=req.side,
        price=req.price,
        quantity=req.quantity,
        confidence=req.confidence,
        spread_pct=req.spread_pct,
        volume=req.volume,
        volatility=req.volatility,
    )
    return SupervisorApprovalResponse(
        approved=approval.approved,
        reasons=approval.reasons,
        warnings=approval.warnings,
        risk_score=approval.risk_score,
        adjusted_quantity=approval.adjusted_quantity,
    )


@router.get("/status", response_model=SupervisorStatusResponse)
async def supervisor_status():
    """Get trade supervisor status."""
    status = _supervisor.get_status()
    set_supervisor_state(status.get("state", ""))
    return SupervisorStatusResponse(**status)


@router.post("/resume")
async def resume_trading(req: SupervisorResumeRequest):
    """Resume trading after a pause."""
    ok = _supervisor.resume(force=req.force)
    if not ok:
        raise HTTPException(400, "Cannot resume from HALTED state without force=True")
    set_supervisor_state(_supervisor.state.value)
    return {"status": "resumed", "state": _supervisor.state.value}


@router.post("/pause")
async def pause_trading():
    """Manually pause trading."""
    from backend.intraday.trade_supervisor import PauseReason
    _supervisor._pause(PauseReason.MANUAL)
    record_supervisor_trigger("manual_pause")
    set_supervisor_state(_supervisor.state.value)
    return {"status": "paused", "state": _supervisor.state.value}


@router.post("/halt")
async def halt_trading(reason: str = "manual"):
    """Hard halt trading (requires manual restart)."""
    _supervisor.halt(reason)
    record_supervisor_trigger(f"halt_{reason}")
    set_supervisor_state(_supervisor.state.value)
    return {"status": "halted", "state": _supervisor.state.value}


@router.post("/reset-daily")
async def reset_daily(initial_equity: float = 100000):
    """Reset daily counters."""
    _supervisor.reset_daily(initial_equity)
    return {"status": "ok", "state": _supervisor.state.value}


@router.post("/heartbeat/data")
async def heartbeat_data():
    """Data feed heartbeat."""
    _supervisor.heartbeat_data_feed()
    return {"status": "ok"}


@router.post("/heartbeat/broker")
async def heartbeat_broker():
    """Broker API heartbeat."""
    _supervisor.heartbeat_broker()
    return {"status": "ok"}


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "intraday-supervisor",
        "state": _supervisor.state.value,
    }
