"""Model management routes — train, validate, list models.

Provides endpoints for triggering training, inspecting model versions,
and promoting/retiring models.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field

router = APIRouter(prefix="/models", tags=["models"])


class TrainRequest(BaseModel):
    model_type: str = Field(default="lightgbm", description="Model type: lightgbm, xgboost, ensemble, etc.")
    tickers: list[str] | None = None
    retrain: bool = False


class TrainResponse(BaseModel):
    status: str
    message: str
    version: str | None = None
    metrics: dict[str, Any] | None = None


class ModelInfo(BaseModel):
    version: str
    model_type: str | None = None
    status: str | None = None
    registered_at: str | None = None
    metrics: dict | None = None


# Track background training state
_training_status: dict[str, Any] = {"running": False, "last_result": None}


@router.post("/train", response_model=TrainResponse)
async def train_model(req: TrainRequest, background_tasks: BackgroundTasks):
    """Trigger model training (runs in background)."""
    if _training_status["running"]:
        raise HTTPException(status_code=409, detail="Training already in progress")

    _training_status["running"] = True
    background_tasks.add_task(_run_training, req.model_type, req.tickers, req.retrain)

    return TrainResponse(
        status="started",
        message=f"Training {req.model_type} model in background",
    )


async def _run_training(model_type: str, tickers: list[str] | None, retrain: bool) -> None:
    """Background training task."""
    from app.training.train import run_training

    try:
        result = await run_training(model_type=model_type, tickers=tickers, retrain=retrain)
        _training_status["last_result"] = result
        _training_status["running"] = False

        # Auto-promote new model
        from app.services.model_registry import get_registry
        registry = get_registry()
        registry.register(
            version=result["version"],
            model_type=model_type,
            metrics=result.get("test_metrics"),
            artifact_path=result.get("artifact_path"),
        )
        registry.promote(result["version"])

        # Reload model in predictor
        from app.inference.predictor import load_model
        load_model(result["version"])

    except Exception as exc:
        _training_status["last_result"] = {"error": str(exc)}
        _training_status["running"] = False


@router.get("/train/status")
async def training_status():
    """Check training status."""
    return _training_status


@router.get("/active")
async def active_model():
    """Get currently active model info."""
    from app.inference.predictor import get_active_model_version
    from app.services.model_registry import get_registry

    version = get_active_model_version()
    if not version:
        return {"status": "no_model_loaded"}

    registry = get_registry()
    models = registry.list_versions()
    info = next((m for m in models if m["version"] == version), None)

    return {
        "version": version,
        "info": info,
    }


@router.get("/list", response_model=list[ModelInfo])
async def list_models():
    """List all registered model versions."""
    from app.services.model_registry import get_registry

    registry = get_registry()
    versions = registry.list_versions()
    return [ModelInfo(**v) for v in versions]


@router.post("/promote/{version}")
async def promote_model(version: str):
    """Promote a model version to active."""
    from app.services.model_registry import get_registry
    from app.inference.predictor import load_model

    registry = get_registry()
    if not registry.promote(version):
        raise HTTPException(status_code=404, detail=f"Version {version} not found")

    load_model(version)
    return {"status": "promoted", "version": version}


@router.post("/retire/{version}")
async def retire_model(version: str):
    """Retire a model version."""
    from app.services.model_registry import get_registry

    registry = get_registry()
    if not registry.retire(version):
        raise HTTPException(status_code=404, detail=f"Version {version} not found")

    return {"status": "retired", "version": version}


@router.post("/validate/{version}")
async def validate_model(version: str):
    """Run validation on a specific model version."""
    raise HTTPException(status_code=501, detail="Not yet implemented")
