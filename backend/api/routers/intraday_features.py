"""Intraday feature service router – exposes intraday feature computation."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from backend.intraday.data_pipeline import CandleCache
from backend.intraday.feature_engine import compute_latest_features
from backend.intraday.schemas import FeatureRequest, FeatureResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/intraday/features", tags=["intraday-features"])

# Shared candle cache (populated by data feed or backtest replay)
_cache = CandleCache(max_bars=500)


def get_cache() -> CandleCache:
    return _cache


@router.post("/compute", response_model=FeatureResponse)
async def compute_features(req: FeatureRequest):
    """Compute intraday features for a symbol from cached candles."""
    df = _cache.to_dataframe(req.symbol, req.interval.value)
    if df.empty:
        raise HTTPException(404, f"No candle data for {req.symbol} @ {req.interval.value}")

    # Trim to requested bars
    if len(df) > req.bars:
        df = df.iloc[-req.bars:]

    features = compute_latest_features(df)
    return FeatureResponse(
        symbol=req.symbol,
        interval=req.interval.value,
        features=features,
        bars_used=len(df),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/symbols")
async def list_symbols():
    """List symbols with cached candle data."""
    return {"symbols": sorted(_cache.symbols)}


@router.get("/health")
async def health():
    return {"status": "ok", "service": "intraday-features", "symbols": len(_cache.symbols)}
