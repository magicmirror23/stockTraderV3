"""Portfolio intelligence API endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter

router = APIRouter(tags=["portfolio-intelligence"])
logger = logging.getLogger(__name__)


def _pi():
    from backend.services.portfolio_intelligence import get_portfolio_intelligence
    return get_portfolio_intelligence()


def _ensure_dict(val) -> dict:
    """Convert list to empty dict if needed — positions must be dict[str, dict]."""
    if isinstance(val, dict):
        return val
    return {}


@router.post("/portfolio/metrics")
async def compute_metrics(payload: dict):
    """Compute comprehensive portfolio metrics."""
    try:
        metrics = _pi().compute_metrics(
            equity_curve=payload.get("equity_curve", []),
            trades=payload.get("trades", []),
            positions=_ensure_dict(payload.get("positions")),
            cash=float(payload.get("cash", 0)),
            initial_capital=float(payload.get("initial_capital", 100000)),
        )
        return metrics.to_dict()
    except Exception as exc:
        logger.exception("compute_metrics failed")
        return {"error": str(exc)}


@router.post("/portfolio/exposure")
async def exposure_heatmap(payload: dict):
    """Exposure heatmap by sector and instrument type."""
    try:
        return _pi().exposure_heatmap(_ensure_dict(payload.get("positions")))
    except Exception as exc:
        logger.exception("exposure_heatmap failed")
        return {}


@router.post("/portfolio/allocation")
async def capital_allocation(payload: dict):
    """Capital allocation recommendation based on regime."""
    try:
        return _pi().capital_allocation_recommendation(
            total_capital=float(payload.get("total_capital", 100000)),
            current_positions=_ensure_dict(payload.get("current_positions")),
            regime=payload.get("regime", "range_bound"),
        )
    except Exception as exc:
        logger.exception("capital_allocation failed")
        return {"error": str(exc)}


@router.post("/portfolio/daily-summary")
async def daily_summary(payload: dict):
    """End-of-day portfolio summary."""
    try:
        return _pi().daily_summary(
            equity_curve=payload.get("equity_curve", []),
            trades_today=payload.get("trades_today", []),
            positions=_ensure_dict(payload.get("positions")),
        )
    except Exception as exc:
        logger.exception("daily_summary failed")
        return {"error": str(exc)}
