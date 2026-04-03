"""Health & status routes.

Provides /health, /health/live, /health/ready, /status, and /metrics.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Response

from app.core.config import settings
from app.inference.predictor import get_active_model_version

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    """Basic liveness check."""
    return {
        "status": "ok",
        "service": "prediction-service",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/health/live")
async def liveness():
    """Kubernetes liveness probe."""
    return {"status": "alive"}


@router.get("/health/ready")
async def readiness():
    """Kubernetes readiness probe. Ready when a model is loaded."""
    model_version = get_active_model_version()
    is_ready = model_version is not None

    return {
        "status": "ready" if is_ready else "not_ready",
        "model_loaded": is_ready,
        "model_version": model_version,
    }


@router.get("/status")
async def status():
    """Detailed service status."""
    model_version = get_active_model_version()
    from app.services.market_session import get_session_state

    session = get_session_state()

    return {
        "service": "prediction-service",
        "version": "1.0.0",
        "model_version": model_version,
        "model_loaded": model_version is not None,
        "market_session": session,
        "config": {
            "data_provider": settings.DATA_PROVIDER,
            "confidence_threshold": settings.PREDICTION_CONFIDENCE_THRESHOLD,
            "default_tickers_count": len(settings.DEFAULT_TICKERS),
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
