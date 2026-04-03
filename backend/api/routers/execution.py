"""Execution quality API endpoints."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["execution-quality"])


def _engine():
    from backend.services.execution_quality import get_execution_engine
    return get_execution_engine()


@router.get("/execution/stats")
async def execution_stats():
    """Aggregate execution quality statistics."""
    return _engine().get_stats()


@router.get("/execution/reports")
async def recent_reports(limit: int = 20):
    """Recent execution reports."""
    return _engine().get_recent_reports(limit)


@router.post("/execution/decide-order-type")
async def decide_order_type(payload: dict):
    """Decide between market vs limit order for given conditions.

    Body: {confidence, volatility?, spread_pct?, is_option?}
    """
    return {
        "order_type": _engine().decide_order_type(
            confidence=float(payload.get("confidence", 0.5)),
            volatility=float(payload.get("volatility", 0.02)),
            spread_pct=float(payload.get("spread_pct", 0.001)),
            is_option=payload.get("is_option", False),
        )
    }


@router.post("/execution/price-check")
async def price_protection_check(payload: dict):
    """Check if execution price is within acceptable bounds.

    Body: {signal_price, current_price, side}
    """
    ok, msg = _engine().check_price_protection(
        signal_price=float(payload["signal_price"]),
        current_price=float(payload["current_price"]),
        side=payload.get("side", "buy"),
    )
    return {"ok": ok, "message": msg}


@router.post("/execution/liquidity-check")
async def liquidity_check(payload: dict):
    """Check liquidity for a ticker.

    Body: {volume, bid_ask_spread_pct, is_option?}
    """
    ok, warnings = _engine().check_liquidity(
        volume=float(payload["volume"]),
        bid_ask_spread_pct=float(payload["bid_ask_spread_pct"]),
        is_option=payload.get("is_option", False),
    )
    return {"ok": ok, "warnings": warnings}
