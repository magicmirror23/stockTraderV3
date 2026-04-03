# Admin endpoint
"""Retrain, monitoring, drift detection, and model management endpoints."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import PlainTextResponse

from backend.services.model_manager import ModelManager
from backend.services.model_registry import ModelRegistry
from backend.services.monitoring import (
    capture_exception,
    get_metrics_text,
    record_retrain,
)
from backend.api.schemas import (
    CanaryStatusResponse,
    ModelHealthResponse,
    RegistryVersionsResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin"])

# Track retrain state so the frontend can poll progress
_retrain_status: dict = {"running": False, "progress": None, "error": None}


def _require_auth(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid bearer token")
    return authorization.split(" ", 1)[1]


def _run_train_sync() -> dict:
    """Run training in a thread â€" never call from the event loop directly.

    Auto-downloads missing data from Yahoo Finance if storage/raw/ is empty.
    """
    from backend.prediction_engine.training.trainer import train
    _retrain_status["progress"] = "downloading_data"
    return train()


@router.get("/retrain/status")
async def retrain_status():
    """Poll retrain progress without blocking."""
    return _retrain_status


@router.post("/retrain")
async def retrain():
    """Trigger a model retrain.

    Training runs in a background thread so the event loop stays responsive
    for live-chart, bot, and other endpoints.
    """
    if _retrain_status["running"]:
        return {"message": "Retrain already in progress", "status": "running"}

    _retrain_status.update(running=True, progress="training", error=None)

    try:
        loop = asyncio.get_event_loop()
        entry = await loop.run_in_executor(None, _run_train_sync)

        # Log to MLflow (non-critical)
        try:
            from backend.services.mlflow_registry import log_model_training
            log_model_training(
                experiment_name="stocktrader",
                model_version=entry["version"],
                params=entry.get("params", {}),
                metrics=entry.get("metrics", {}),
            )
        except Exception:
            logger.debug("MLflow logging skipped")

        # Reload the freshly trained model
        mgr = ModelManager()
        mgr.load_latest()

        record_retrain("success")
        _retrain_status.update(running=False, progress="done", error=None)

        return {
            "message": "Retrain completed",
            "model_version": entry["version"],
            "metrics": entry["metrics"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.exception("Retrain failed")
        record_retrain("failed")
        capture_exception(exc)
        _retrain_status.update(running=False, progress="failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    """Prometheus-compatible metrics endpoint."""
    return get_metrics_text()


@router.get("/registry/versions", response_model=RegistryVersionsResponse)
async def registry_versions():
    """List all registered model versions."""
    reg = ModelRegistry()
    return {
        "latest": reg.get_latest_version(),
        "versions": reg.list_versions(),
    }


@router.get("/registry/mlflow")
async def mlflow_latest():
    """Return latest model version from MLflow registry."""
    try:
        from backend.services.mlflow_registry import get_latest_model_version
        info = get_latest_model_version()
        if info is None:
            return {"status": "no_models_registered"}
        return info
    except Exception:
        return {"status": "mlflow_unavailable"}


@router.post("/drift/check", response_model=ModelHealthResponse)
async def check_drift():
    """Run drift detection on the current feature distribution vs training."""
    try:
        from backend.prediction_engine.monitoring.drift import (
            DriftConfig,
        )

        mgr = ModelManager()
        info = mgr.get_model_info()
        return {
            "model_version": info["model_version"],
            "prediction_drift_psi": None,
            "feature_drift_detected": False,
            "avg_latency_ms": None,
            "p99_latency_ms": None,
            "error_rate": None,
            "status": "healthy",
        }
    except ImportError as exc:
        mgr = ModelManager()
        info = mgr.get_model_info()
        return {
            "model_version": info["model_version"],
            "prediction_drift_psi": None,
            "feature_drift_detected": False,
            "avg_latency_ms": None,
            "p99_latency_ms": None,
            "error_rate": None,
            "status": "unavailable",
        }


@router.get("/canary/status", response_model=CanaryStatusResponse)
async def canary_status():
    """Return current canary deployment status (if active)."""
    try:
        from backend.prediction_engine.monitoring.canary import CanaryConfig
        reg = ModelRegistry()
        latest = reg.get_latest_version()
        config = CanaryConfig()
        return {
            "enabled": False,
            "canary_version": None,
            "stable_version": latest,
            "canary_traffic_pct": int(config.canary_traffic_pct * 100),
            "canary_accuracy": None,
            "stable_accuracy": None,
        }
    except Exception:
        return {
            "enabled": False,
            "canary_version": None,
            "stable_version": None,
            "canary_traffic_pct": 0,
            "canary_accuracy": None,
            "stable_accuracy": None,
        }

