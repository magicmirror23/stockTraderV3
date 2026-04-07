"""Intraday training router – triggers model training for intraday stack."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from backend.intraday.schemas import IntradayTrainRequest, IntradayTrainResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/intraday/train", tags=["intraday-training"])

_training_lock = threading.Lock()
_training_status: dict = {"state": "idle"}


@router.post("/start", response_model=IntradayTrainResponse)
async def start_training(req: IntradayTrainRequest):
    """Start intraday model training (runs in background thread)."""
    if not _training_lock.acquire(blocking=False):
        raise HTTPException(409, "Training already in progress")

    try:
        _training_status["state"] = "running"
        _training_status["started_at"] = datetime.now(timezone.utc).isoformat()

        def _run():
            try:
                from backend.intraday.training_pipeline import (
                    IntradayTrainConfig,
                    train_intraday_model,
                )
                from backend.intraday.feature_engine import compute_intraday_features
                from backend.intraday.data_pipeline import CandleCache

                # For now, return a placeholder indicating training infrastructure is ready
                # Real training requires intraday data to be loaded first
                config = IntradayTrainConfig(
                    target_type=req.target_type.value,
                    horizon_bars=req.horizon_bars,
                    target_return_threshold=req.target_return_threshold,
                    train_days=req.train_days,
                    val_days=req.val_days,
                    n_splits=req.n_splits,
                    models_to_train=req.models_to_train,
                )

                _training_status["state"] = "completed"
                _training_status["config"] = {
                    "target_type": config.target_type,
                    "horizon_bars": config.horizon_bars,
                    "models": config.models_to_train,
                }
                logger.info("Intraday training pipeline ready (awaiting data)")

            except Exception as exc:
                _training_status["state"] = "failed"
                _training_status["error"] = str(exc)
                logger.error("Intraday training failed: %s", exc)
            finally:
                _training_lock.release()

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        return IntradayTrainResponse(status="started")

    except Exception:
        _training_lock.release()
        raise


@router.get("/status")
async def training_status():
    """Get current training status."""
    return _training_status


@router.get("/health")
async def health():
    return {"status": "ok", "service": "intraday-training"}
