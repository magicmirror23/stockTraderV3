"""Execution engine router – micro-trade management API."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from backend.intraday.execution_engine import MicroTradeExecutor
from backend.intraday.schemas import (
    ExecuteTradeRequest,
    ExecuteTradeResponse,
    ExecutionStatsResponse,
    ForceCloseRequest,
)
from backend.services.monitoring import record_intraday_trade, set_intraday_stats

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/intraday/execution", tags=["intraday-execution"])

_executor = MicroTradeExecutor()


def get_executor() -> MicroTradeExecutor:
    return _executor


@router.post("/trade", response_model=ExecuteTradeResponse)
async def execute_trade(req: ExecuteTradeRequest):
    """Execute a micro-trade with bracket order."""
    result = _executor.execute(
        symbol=req.symbol,
        side=req.side,
        price=req.price,
        capital=req.capital,
        confidence=req.confidence,
        signal_type=req.signal_type,
        model_version=req.model_version,
        is_option=req.is_option,
        option_type=req.option_type,
        strike=req.strike,
        expiry=req.expiry,
    )

    if not result.success:
        return ExecuteTradeResponse(success=False, message=result.message)

    order = result.order
    record_intraday_trade(order.side, "opened", result.latency_ms / 1000)
    return ExecuteTradeResponse(
        success=True,
        order_id=order.order_id,
        symbol=order.symbol,
        side=order.side,
        quantity=order.filled_qty,
        entry_price=round(order.avg_fill_price, 2),
        stop_loss=round(order.stop_loss, 2),
        take_profit=round(order.take_profit, 2),
        latency_ms=round(result.latency_ms, 2),
    )


@router.post("/update-prices")
async def update_prices(prices: dict[str, float]):
    """Update prices for all open positions and trigger exits."""
    closed = _executor.update_prices(prices)
    return {
        "closed_count": len(closed),
        "closed_orders": [
            {
                "order_id": o.order_id,
                "symbol": o.symbol,
                "side": o.side,
                "pnl": round(o.realized_pnl, 2),
                "reason": o.close_reason,
                "bars_held": o.bars_held,
            }
            for o in closed
        ],
    }


@router.post("/force-close")
async def force_close(req: ForceCloseRequest):
    """Force-close all open positions."""
    closed = _executor.force_close_all(req.prices)
    total_pnl = sum(o.realized_pnl for o in closed)
    return {
        "closed_count": len(closed),
        "total_pnl": round(total_pnl, 2),
    }


@router.get("/stats", response_model=ExecutionStatsResponse)
async def execution_stats():
    """Get execution statistics."""
    stats = _executor.get_stats()
    set_intraday_stats(
        pnl=stats.get("total_pnl", 0),
        open_positions=stats.get("open_positions", 0),
        win_rate=stats.get("win_rate", 0),
        profit_factor=stats.get("profit_factor", 0),
    )
    return ExecutionStatsResponse(**stats)


@router.get("/positions")
async def open_positions():
    """List all open positions."""
    positions = _executor.open_positions
    return {
        "count": len(positions),
        "positions": [
            {
                "order_id": o.order_id,
                "symbol": o.symbol,
                "side": o.side,
                "quantity": o.filled_qty,
                "entry_price": round(o.avg_fill_price, 2),
                "stop_loss": round(o.stop_loss, 2),
                "take_profit": round(o.take_profit, 2),
                "unrealized_pnl": round(o.unrealized_pnl, 2),
                "bars_held": o.bars_held,
                "confidence": o.signal_confidence,
                "signal_type": o.signal_type,
            }
            for o in positions
        ],
    }


@router.post("/reset-daily")
async def reset_daily():
    """Reset daily stats (for new trading day)."""
    _executor.reset_daily()
    return {"status": "ok"}


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "intraday-execution",
        "open_positions": _executor.open_count,
    }
