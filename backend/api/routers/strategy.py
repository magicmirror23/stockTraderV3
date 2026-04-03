"""Strategy intelligence and regime detection API endpoints."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["strategy-intelligence"])


# --------------- Regime Detection ---------------

@router.get("/regime/{symbol}")
async def detect_regime(symbol: str):
    """Detect current market regime for a symbol."""
    from backend.services.regime_detector import get_regime_detector
    result = get_regime_detector().detect_for_symbol(symbol)
    return {
        "symbol": result.symbol,
        "regime": result.regime.value,
        "confidence": result.confidence,
        "volatility": result.volatility,
        "trend": result.trend,
        "indicators": result.indicators,
    }


@router.get("/regime")
async def regime_heatmap(symbols: str = ""):
    """Market regime heatmap across watchlist.

    Query: ?symbols=RELIANCE,TCS,INFY  (comma-separated, or empty for defaults)
    """
    from backend.services.regime_detector import get_regime_detector
    sym_list = [s.strip() for s in symbols.split(",") if s.strip()] or None
    return get_regime_detector().get_market_heatmap(sym_list)


# --------------- Strategy Selection ---------------

@router.post("/strategy/select")
async def select_strategy(payload: dict):
    """Select optimal strategy for a ticker given prediction and regime.

    Body: {ticker, prediction, regime, risk_budget?, is_option_eligible?,
           iv_percentile?, liquidity_ok?}
    """
    from backend.services.strategy_intelligence import get_strategy_intelligence
    si = get_strategy_intelligence()
    decision = si.select(
        ticker=payload["ticker"],
        prediction=payload["prediction"],
        regime=payload.get("regime", "range_bound"),
        risk_budget=float(payload.get("risk_budget", 1.0)),
        is_option_eligible=payload.get("is_option_eligible", True),
        iv_percentile=float(payload.get("iv_percentile", 0.5)),
        liquidity_ok=payload.get("liquidity_ok", True),
    )
    return {
        "ticker": decision.ticker,
        "strategy": decision.strategy,
        "reason": decision.reason,
        "confidence": decision.confidence,
        "params": decision.params,
    }


@router.get("/strategy/decisions")
async def recent_decisions(limit: int = 20):
    """Recent strategy selection decisions."""
    from backend.services.strategy_intelligence import get_strategy_intelligence
    return get_strategy_intelligence().get_recent_decisions(limit)


@router.get("/strategy/stats")
async def strategy_stats():
    """Strategy selection statistics."""
    from backend.services.strategy_intelligence import get_strategy_intelligence
    return get_strategy_intelligence().get_stats()
