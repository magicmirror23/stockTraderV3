"""Shared FastAPI app factory for all microservices."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def create_service_app(title: str, version: str = "0.1.0") -> FastAPI:
    """Create a FastAPI app with shared CORS and metadata config."""
    app = FastAPI(
        title=title,
        version=version,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    _raw_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:4200")
    _origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]
    if "*" in _origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "Authorization"],
        )
    else:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "Authorization"],
        )

    @app.api_route("/", methods=["GET", "HEAD"])
    async def root():
        return {"status": "ok", "service": title}

    return app
