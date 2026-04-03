"""Prediction routes — /predict and /predict/batch.

Core inference endpoints.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.config import settings

router = APIRouter(prefix="/predict", tags=["predictions"])


class PredictRequest(BaseModel):
    instrument: str = Field(..., description="NSE symbol, e.g. RELIANCE")
    include_explanation: bool = False


class BatchPredictRequest(BaseModel):
    instruments: list[str] = Field(..., description="List of NSE symbols")
    include_explanation: bool = False


class PredictionResponse(BaseModel):
    instrument: str
    direction_probability: float | None = None
    confidence_score: float | None = None
    recommendation: str | None = None
    model_version: str | None = None
    timestamp: str | None = None
    top_features: dict[str, float] | None = None
    latency_ms: float | None = None
    error: str | None = None


@router.post("", response_model=PredictionResponse)
async def predict_single(req: PredictRequest):
    """Generate a prediction for a single instrument."""
    from app.inference.predictor import predict

    result = predict(req.instrument)

    if "error" in result and result["error"]:
        raise HTTPException(status_code=422, detail=result["error"])

    # Persist prediction
    try:
        await _save_prediction(result)
    except Exception:
        pass  # Non-critical

    return PredictionResponse(**result)


@router.post("/batch", response_model=list[PredictionResponse])
async def predict_batch(req: BatchPredictRequest):
    """Generate predictions for multiple instruments."""
    from app.inference.predictor import predict_batch

    results = await predict_batch(req.instruments)

    # Persist all predictions
    for result in results:
        try:
            await _save_prediction(result)
        except Exception:
            pass

    return [PredictionResponse(**r) for r in results]


@router.get("/{instrument}", response_model=PredictionResponse)
async def predict_get(instrument: str):
    """GET-based prediction (convenience)."""
    from app.inference.predictor import predict

    result = predict(instrument.upper())
    if "error" in result and result["error"]:
        raise HTTPException(status_code=422, detail=result["error"])
    return PredictionResponse(**result)


async def _save_prediction(result: dict[str, Any]) -> None:
    """Persist prediction to the database."""
    from app.db.session import async_session_factory
    from app.db.models import PredictionRecord

    if result.get("error"):
        return

    async with async_session_factory() as session:
        record = PredictionRecord(
            instrument=result.get("instrument", ""),
            direction_probability=result.get("direction_probability"),
            confidence_score=result.get("confidence_score"),
            recommendation=result.get("recommendation"),
            model_version=result.get("model_version"),
            top_features=result.get("top_features"),
        )
        session.add(record)
        await session.commit()
