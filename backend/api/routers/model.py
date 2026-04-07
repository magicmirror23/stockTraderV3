# Model management endpoint
"""Model management endpoints: GET /model/status and POST /model/reload."""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException

from backend.api.schemas import (
    ModelActivateRequest,
    ModelActivateResponse,
    ModelMetadataResponse,
    ModelReloadRequest,
    ModelReloadResponse,
    ModelStatusResponse,
)
from backend.services.model_manager import ModelManager
from backend.services.model_sync import apply_model_sync_payload

router = APIRouter(prefix="/model", tags=["model"])


@router.get("/status", response_model=ModelStatusResponse)
async def model_status():
    mgr = ModelManager()
    info = mgr.get_model_info()
    return ModelStatusResponse(
        model_version=info["model_version"],
        status=info["status"],
        last_trained=info.get("last_trained"),
        accuracy=info.get("accuracy"),
        executed_trade_win_rate=info.get("executed_trade_win_rate"),
        inference_only=bool(info.get("inference_only", False)),
        feature_count=int(info.get("feature_count", 0) or 0),
    )


@router.post("/reload", response_model=ModelReloadResponse)
async def model_reload(req: ModelReloadRequest | None = None):
    mgr = ModelManager()
    try:
        if req and req.version:
            new_version = mgr.load_version(req.version)
        else:
            new_version = mgr.load_latest()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return ModelReloadResponse(
        message="Model reload initiated.",
        new_version=new_version,
        status=mgr.status,
    )


@router.get("/metadata", response_model=ModelMetadataResponse)
async def model_metadata():
    mgr = ModelManager()
    try:
        payload = mgr.get_model_metadata()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ModelMetadataResponse(
        model_version=payload.get("model_version"),
        feature_columns=list(payload.get("feature_columns") or []),
        metadata=dict(payload.get("metadata") or {}),
        metrics=dict(payload.get("metrics") or {}),
        active_model_dir=payload.get("active_model_dir"),
    )


@router.post("/activate-version", response_model=ModelActivateResponse)
async def model_activate_version(req: ModelActivateRequest):
    mgr = ModelManager()
    try:
        active_version = mgr.activate_version(req.version)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ModelActivateResponse(
        status="activated",
        active_version=active_version,
        model_status=mgr.status,
    )


@router.post("/sync")
async def model_sync(payload: dict):
    """Receive a model artifact bundle from admin service and hot-load it."""
    expected_token = os.getenv("MODEL_SYNC_TOKEN", "").strip()
    supplied_token = str(payload.get("sync_token", "")).strip()
    if expected_token and supplied_token != expected_token:
        raise HTTPException(status_code=401, detail="Invalid model sync token")

    try:
        result = apply_model_sync_payload(payload, set_latest=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Model sync failed: {exc}") from exc

    mgr = ModelManager()
    try:
        mgr.load_version(result["version"])
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Model synced but failed to load: {exc}",
        ) from exc

    return {
        "status": "synced",
        "version": result["version"],
        "model_status": mgr.status,
    }

