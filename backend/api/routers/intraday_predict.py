"""Intraday prediction router – ML inference for intraday signals."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from backend.intraday.prediction_engine import IntradayPredictor
from backend.intraday.schemas import (
    IntradayBatchPredictRequest,
    IntradayBatchResponse,
    IntradayModelStatus,
    IntradayPredictRequest,
    IntradaySignalResponse,
)
from backend.services.monitoring import record_intraday_prediction, set_intraday_model_info

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/intraday/predict", tags=["intraday-prediction"])

# Singleton predictor
_predictor = IntradayPredictor()


def get_predictor() -> IntradayPredictor:
    return _predictor


@router.on_event("startup")
async def _load_model():
    _predictor.load_latest()


@router.post("/signal", response_model=IntradaySignalResponse)
async def predict_signal(req: IntradayPredictRequest):
    """Generate a single intraday trading signal."""
    if not _predictor.is_loaded:
        raise HTTPException(503, "Intraday model not loaded")

    if req.features is None:
        raise HTTPException(400, "Features must be provided (or use /compute first)")

    t0 = time.perf_counter()
    signal = _predictor.predict(req.features, req.symbol)
    latency = time.perf_counter() - t0
    record_intraday_prediction(signal.signal_type, latency)
    return IntradaySignalResponse(
        symbol=signal.symbol,
        action=signal.action,
        confidence=signal.confidence,
        expected_return=signal.expected_return,
        score=signal.score,
        model_version=signal.model_version,
        features_used=signal.features_used,
        signal_type=signal.signal_type,
        eligible=signal.eligible,
        rejection_reason=signal.rejection_reason,
    )


@router.post("/batch", response_model=IntradayBatchResponse)
async def predict_batch(req: IntradayBatchPredictRequest):
    """Generate signals for multiple symbols."""
    if not _predictor.is_loaded:
        raise HTTPException(503, "Intraday model not loaded")

    # For batch, we'd normally compute features per symbol from cache
    # This is a placeholder that returns hold signals for uncomputed symbols
    from backend.api.routers.intraday_features import get_cache
    from backend.intraday.feature_engine import compute_latest_features

    cache = get_cache()
    signals = []

    for sym in req.symbols:
        df = cache.to_dataframe(sym, req.interval.value)
        if df.empty:
            signals.append(IntradaySignalResponse(
                symbol=sym, action="hold", confidence=0, expected_return=0,
                score=0.5, model_version=_predictor.model_version,
                features_used=0, signal_type="none",
                eligible=False, rejection_reason="no_candle_data",
            ))
            continue

        features = compute_latest_features(df)
        sig = _predictor.predict(features, sym)
        signals.append(IntradaySignalResponse(
            symbol=sig.symbol, action=sig.action, confidence=sig.confidence,
            expected_return=sig.expected_return, score=sig.score,
            model_version=sig.model_version, features_used=sig.features_used,
            signal_type=sig.signal_type, eligible=sig.eligible,
            rejection_reason=sig.rejection_reason,
        ))

    return IntradayBatchResponse(
        signals=signals,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/model/status", response_model=IntradayModelStatus)
async def model_status():
    """Get intraday model info."""
    info = _predictor.get_info()
    return IntradayModelStatus(**info)


@router.post("/model/reload")
async def reload_model():
    """Reload the latest intraday model."""
    ok = _predictor.load_latest()
    if not ok:
        raise HTTPException(500, "Failed to reload intraday model")
    return {"status": "ok", "version": _predictor.model_version}
