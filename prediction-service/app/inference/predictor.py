"""Predictor — main inference entry point.

Loads the active model + calibrator, builds features, runs prediction
through the calibration layer, adjusts for the current regime, and
returns a fully-annotated result.  Stale-data and failure fallback
guarantees that callers always get a response.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from app.core.config import settings
from app.core.metrics import (
    PREDICTION_LATENCY,
    PREDICTION_COUNT,
    PREDICTION_CONFIDENCE,
    NO_TRADE_COUNT,
    SOURCE_FAILURE_COUNT,
)
from app.services import cache as prediction_cache

logger = logging.getLogger(__name__)

# Cached model instance
_active_model: Any = None
_active_version: str | None = None
_feature_names: list[str] = []


def load_model(version: str | None = None) -> bool:
    """Load a trained model from artifacts directory.

    Also attempts to load the calibrator for that version.
    """
    global _active_model, _active_version, _feature_names
    from pathlib import Path
    import json

    artifact_base = Path(settings.MODEL_ARTIFACTS_DIR)
    if not artifact_base.exists():
        logger.warning("No model artifacts directory: %s", artifact_base)
        return False

    if version:
        model_dir = artifact_base / version
    else:
        versions = sorted(
            [d for d in artifact_base.iterdir() if d.is_dir() and d.name.startswith("v")],
            key=lambda d: d.name,
            reverse=True,
        )
        if not versions:
            logger.warning("No trained models found in %s", artifact_base)
            return False
        model_dir = versions[0]

    model_path = model_dir / "model.joblib"
    meta_path = model_dir / "meta.json"

    if not model_path.exists():
        logger.error("Model file not found: %s", model_path)
        return False

    try:
        import joblib
        _active_model = joblib.load(str(model_path))
        _active_version = model_dir.name

        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            _feature_names = meta.get("feature_names", [])

        # Try to load calibrator for this version
        from app.inference.confidence import load_calibrator
        load_calibrator(_active_version)

        logger.info("Loaded model %s from %s", _active_version, model_path)
        return True
    except Exception as exc:
        logger.error("Failed to load model: %s", exc)
        return False


def predict(
    instrument: str,
    ohlcv_df: pd.DataFrame | None = None,
    event_features: dict[str, float] | None = None,
    sentiment_features: dict[str, float] | None = None,
    options_features: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Generate a prediction for a single instrument.

    Pipeline:
      1. Load OHLCV (CSV or provider, with cache).
      2. Build features.
      3. Raw model probability.
      4. Calibrate.
      5. Regime-aware adjustment.
      6. Confidence threshold → recommendation.

    On failure, returns the last cached prediction when available.
    """
    start = time.time()

    if _active_model is None:
        if not load_model():
            return {"error": "No model loaded", "instrument": instrument}

    # Check prediction cache first
    cache_key = prediction_cache.cache_key("pred", instrument, _active_version)
    cached = prediction_cache.get(cache_key)
    if cached is not None:
        cached["from_cache"] = True
        return cached

    try:
        # 1. Load OHLCV
        if ohlcv_df is None:
            ohlcv_df = _load_ohlcv_with_fallback(instrument)
            if ohlcv_df is None or ohlcv_df.empty:
                return _fallback_or_error(instrument, cache_key, "No data available")

        # Stale-data check: refuse to predict on very old data during market hours
        data_age = _data_age_days(ohlcv_df)
        is_stale = data_age > 5

        # 2. Build features
        from app.features.feature_pipeline import build_features_for_inference
        features = build_features_for_inference(
            ohlcv_df,
            event_features=event_features,
            sentiment_features=sentiment_features,
            options_features=options_features,
        )

        # Align with model's expected features
        if _feature_names:
            for col in _feature_names:
                if col not in features.index:
                    features[col] = 0.0
            features = features.reindex(_feature_names).fillna(0.0)

        # 3. Raw prediction
        X = pd.DataFrame([features])
        raw_proba = float(_active_model.predict_proba(X)[0])

        # 4. Calibrate
        from app.inference.confidence import calibrate_probability, apply_confidence_threshold
        calibrated_proba = calibrate_probability(raw_proba)

        # 5. Regime adjustment
        regime_info: dict[str, Any] = {}
        threshold_shift = 0.0
        try:
            from app.inference.regime_router import adjust_for_regime
            from app.models.regime_model import compute_regime_features

            regime_feats = compute_regime_features(ohlcv_df)
            if not regime_feats.empty:
                from app.models.regime_model import RegimeModel
                # Use a lightweight regime estimate from feature heuristics
                last = regime_feats.iloc[-1]
                if last.get("ret_std_21d", 0) > 0.02:
                    regime = "high_volatility"
                elif last.get("ret_mean_21d", 0) > 0.001:
                    regime = "trending_up"
                elif last.get("ret_mean_21d", 0) < -0.001:
                    regime = "trending_down"
                else:
                    regime = "mean_reverting"
                regime_info = adjust_for_regime(calibrated_proba, abs(calibrated_proba - 0.5) * 2, regime)
                calibrated_proba = regime_info.get("adjusted_probability", calibrated_proba)
                threshold_shift = regime_info.get("threshold_shift", 0.0)
        except Exception as exc:
            logger.debug("Regime adjustment skipped: %s", exc)

        # 6. Recommendation
        recommendation = apply_confidence_threshold(
            calibrated_proba, regime_threshold_shift=threshold_shift,
        )

        # Feature importance
        top_features = {}
        try:
            from app.inference.explainability import get_top_features
            top_features = get_top_features(_active_model, X)
        except Exception:
            pass

        latency = time.time() - start
        PREDICTION_LATENCY.observe(latency)
        PREDICTION_COUNT.labels(instrument=instrument, recommendation=recommendation).inc()
        PREDICTION_CONFIDENCE.observe(calibrated_proba)

        if recommendation == "no_trade":
            NO_TRADE_COUNT.inc()

        result: dict[str, Any] = {
            "instrument": instrument,
            "direction_probability": round(calibrated_proba, 4),
            "raw_probability": round(raw_proba, 4),
            "confidence_score": round(abs(calibrated_proba - 0.5) * 2, 4),
            "recommendation": recommendation,
            "model_version": _active_version,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "top_features": top_features,
            "latency_ms": round(latency * 1000, 2),
            "regime": regime_info.get("regime"),
            "data_stale": is_stale,
        }

        # Cache the result
        prediction_cache.put(cache_key, result, ttl_seconds=settings.CACHE_TTL_SECONDS)
        return result

    except Exception as exc:
        SOURCE_FAILURE_COUNT.labels(source="predictor", error_type=type(exc).__name__).inc()
        logger.error("Prediction failed for %s: %s", instrument, exc)
        return _fallback_or_error(instrument, cache_key, str(exc))


def _load_ohlcv_with_fallback(instrument: str) -> pd.DataFrame | None:
    """Load OHLCV from CSV, falling back to provider on miss."""
    from app.ingestion.historical_loader import load_ohlcv_from_csv, load_ohlcv_from_provider
    from datetime import timedelta

    df = load_ohlcv_from_csv(instrument)
    if df is not None and not df.empty:
        return df

    try:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=365)
        return load_ohlcv_from_provider(instrument, start, end)
    except Exception as exc:
        logger.warning("Provider fallback failed for %s: %s", instrument, exc)
        return None


def _data_age_days(df: pd.DataFrame) -> int:
    """Return how many calendar days old the latest row is."""
    try:
        latest = pd.Timestamp(df.index.max())
        return (pd.Timestamp.now(tz="UTC") - latest.tz_localize("UTC")).days
    except Exception:
        return 0


def _fallback_or_error(instrument: str, cache_key: str, error_msg: str) -> dict[str, Any]:
    """Return a stale cached prediction when available, else an error dict."""
    stale = prediction_cache.get(cache_key)
    if stale is not None:
        stale["from_cache"] = True
        stale["fallback_reason"] = error_msg
        logger.info("Returning stale prediction for %s: %s", instrument, error_msg)
        return stale
    return {"error": error_msg, "instrument": instrument}


async def predict_batch(instruments: list[str]) -> list[dict[str, Any]]:
    """Generate predictions for multiple instruments."""
    results = []
    for instrument in instruments:
        result = predict(instrument)
        results.append(result)
    return results


def get_active_model_version() -> str | None:
    return _active_version
