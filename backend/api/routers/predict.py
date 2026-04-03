# Prediction endpoint
"""Prediction endpoints: POST /predict, POST /predict/options, POST /batch_predict."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from backend.api.schemas import (
    ActionEnum,
    BatchPredictRequest,
    BatchPredictResponse,
    Greeks,
    OptionPredictRequest,
    OptionPredictResponse,
    OptionSignal,
    PredictRequest,
    PredictResponse,
    PredictionEntry,
)
from backend.services.model_manager import ModelManager

router = APIRouter(tags=["prediction"])


def _get_model():
    mgr = ModelManager()
    if mgr.model is None or mgr.status != "loaded":
        raise HTTPException(status_code=503, detail="Model not loaded")
    return mgr


def _shap_top_features(model, X, top_k: int = 5) -> list[str]:
    """Extract top-k SHAP feature names. Returns empty list on failure."""
    try:
        from backend.prediction_engine.feature_store.feature_selection import shap_importance
        raw_model = getattr(model, "_model", None)
        if raw_model is None:
            return []
        importance = shap_importance(raw_model, X, top_k=top_k)
        return list(importance.keys())
    except Exception:
        return []


@router.post("/predict", response_model=PredictResponse)
async def predict(req: PredictRequest):
    mgr = _get_model()
    model = mgr.model

    from backend.prediction_engine.feature_store.feature_store import (
        get_features_for_inference,
        FEATURE_COLUMNS,
    )
    import pandas as pd

    try:
        feat_dict = get_features_for_inference(req.ticker)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    numeric_cols = [c for c in FEATURE_COLUMNS if c not in ("ticker", "date")]
    X = pd.DataFrame([{c: feat_dict[c] for c in numeric_cols}])

    results = model.predict_with_expected_return(X)
    r = results[0]
    now = datetime.now(timezone.utc)
    shap_features = _shap_top_features(model, X)

    entry = PredictionEntry(
        ticker=req.ticker,
        action=ActionEnum(r["action"]),
        confidence=r["confidence"],
        expected_return=r["expected_return"],
        model_version=model.get_version(),
        calibration_score=r.get("calibration_score"),
        shap_top_features=shap_features if shap_features else None,
        timestamp=now,
    )

    return PredictResponse(
        ticker=req.ticker,
        horizon_days=req.horizon_days,
        predicted_price=float(feat_dict["close"]) * (1 + r["expected_return"]),
        confidence=r["confidence"],
        model_version=model.get_version(),
        timestamp=now,
        prediction=entry,
    )


@router.post("/predict/options", response_model=OptionPredictResponse)
async def predict_options(req: OptionPredictRequest):
    """Option signal prediction with greeks and IV data."""
    mgr = _get_model()
    model = mgr.model

    from backend.prediction_engine.feature_store.feature_store import (
        get_features_for_inference,
        FEATURE_COLUMNS,
    )
    from backend.prediction_engine.feature_store.transforms import greeks_estimate
    import pandas as pd

    try:
        feat_dict = get_features_for_inference(req.underlying)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    numeric_cols = [c for c in FEATURE_COLUMNS if c not in ("ticker", "date")]
    X = pd.DataFrame([{c: feat_dict[c] for c in numeric_cols}])

    results = model.predict_with_expected_return(X)
    r = results[0]
    now = datetime.now(timezone.utc)

    spot = float(feat_dict["close"])
    vol = float(feat_dict.get("volatility_20", 0.3)) or 0.3
    days_to_exp = max((pd.Timestamp(req.expiry) - pd.Timestamp.now()).days, 1)
    greeks_dict = greeks_estimate(spot, req.strike, days_to_exp, vol, option_type=req.option_type.value)

    signal = OptionSignal(
        underlying=req.underlying,
        strike=req.strike,
        expiry=req.expiry,
        option_type=req.option_type,
        action=ActionEnum(r["action"]),
        confidence=r["confidence"],
        expected_return=r["expected_return"],
        greeks=Greeks(**greeks_dict),
        model_version=model.get_version(),
        calibration_score=r.get("calibration_score"),
        shap_top_features=_shap_top_features(model, X),
        timestamp=now,
    )

    return OptionPredictResponse(
        signal=signal,
        model_version=model.get_version(),
        timestamp=now,
    )


@router.post("/batch_predict", response_model=BatchPredictResponse)
async def batch_predict(req: BatchPredictRequest):
    mgr = _get_model()
    model = mgr.model

    from backend.prediction_engine.feature_store.feature_store import (
        get_features_for_inference,
        FEATURE_COLUMNS,
    )
    import pandas as pd

    numeric_cols = [c for c in FEATURE_COLUMNS if c not in ("ticker", "date")]
    now = datetime.now(timezone.utc)
    predictions = []

    for ticker in req.tickers:
        try:
            feat_dict = get_features_for_inference(ticker)
        except (FileNotFoundError, ValueError):
            # Fallback: return confidence=0 with explicit reason
            predictions.append(PredictionEntry(
                ticker=ticker,
                action=ActionEnum.HOLD,
                confidence=0.0,
                expected_return=0.0,
                model_version="fallback",
                timestamp=now,
            ))
            continue

        X = pd.DataFrame([{c: feat_dict[c] for c in numeric_cols}])
        results = model.predict_with_expected_return(X)
        r = results[0]

        predictions.append(PredictionEntry(
            ticker=ticker,
            action=ActionEnum(r["action"]),
            confidence=r["confidence"],
            expected_return=r["expected_return"],
            model_version=model.get_version(),
            calibration_score=r.get("calibration_score"),
            timestamp=now,
        ))

    return BatchPredictResponse(
        predictions=predictions,
        model_version=model.get_version(),
        timestamp=now,
    )