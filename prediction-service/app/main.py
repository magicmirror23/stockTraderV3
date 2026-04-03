"""Prediction service — FastAPI application entry point.

Start with:
    uvicorn app.main:app --host 0.0.0.0 --port 8010
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Starting prediction-service v1.0.0 on port %d", settings.SERVICE_PORT)

    # Initialize database
    from app.db.session import init_db, close_db
    await init_db()
    logger.info("Database initialized")

    # Load active model
    from app.inference.predictor import load_model
    model_loaded = load_model()
    if model_loaded:
        logger.info("Model loaded successfully")
    else:
        logger.warning("No model loaded — train one via POST /api/v1/models/train")

    yield

    # Shutdown
    await close_db()
    logger.info("Prediction service shut down")


app = FastAPI(
    title="Prediction Service",
    description="AI-powered stock direction prediction for NSE",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API routes
from app.api.routes_health import router as health_router
from app.api.routes_predict import router as predict_router
from app.api.routes_models import router as models_router
from app.api.routes_market_session import router as market_router

app.include_router(health_router, prefix="/api/v1")
app.include_router(predict_router, prefix="/api/v1")
app.include_router(models_router, prefix="/api/v1")
app.include_router(market_router, prefix="/api/v1")


@app.get("/")
async def root():
    return {
        "service": "prediction-service",
        "version": "1.0.0",
        "docs": "/docs",
    }
