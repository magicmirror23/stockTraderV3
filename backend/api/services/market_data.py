"""Market Data Microservice – Port 8001.

Handles WebSocket/SSE price streaming, market status, and account profile.
Isolated because long-lived WebSocket connections should not compete with
REST endpoints for event-loop attention.
"""

from __future__ import annotations

import logging
import os
import threading
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

from fastapi import APIRouter, FastAPI
from backend.api.services.base import create_service_app
from backend.api.routers import stream
from backend.api.routers.market import market_status, account_profile

_log = logging.getLogger("stocktrader.market_data")


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on", "y"}


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Download market data on startup and start background refresh."""
    def _init_data():
        bootstrap_enabled = _env_bool("MARKET_DATA_BOOTSTRAP_DOWNLOAD", False)
        bg_enabled = _env_bool("MARKET_DATA_BACKGROUND_REFRESH_ENABLED", False)
        interval_h = float(os.getenv("MARKET_DATA_REFRESH_INTERVAL_HOURS", "6.0"))
        symbol_limit = int(os.getenv("MARKET_DATA_BOOTSTRAP_LIMIT", "12"))
        bootstrap_symbols = [
            s.strip().upper()
            for s in os.getenv("MARKET_DATA_BOOTSTRAP_SYMBOLS", "").split(",")
            if s.strip()
        ]

        try:
            from backend.services.data_downloader import (
                get_all_symbols, refresh_all_symbols, start_background_refresh,
            )

            if bootstrap_enabled:
                symbols = bootstrap_symbols or get_all_symbols()
                if symbol_limit > 0:
                    symbols = symbols[:symbol_limit]
                _log.info("Bootstrap download enabled for %d symbols", len(symbols))
                results = refresh_all_symbols(symbols)
                ok = sum(1 for v in results.values() if v)
                _log.info("Bootstrap download: %d/%d symbols OK", ok, len(results))
            else:
                _log.info("Bootstrap download disabled (MARKET_DATA_BOOTSTRAP_DOWNLOAD=false)")

            if bg_enabled:
                start_background_refresh(interval_hours=interval_h)
                _log.info("Background refresh enabled (interval=%.2fh)", interval_h)
            else:
                _log.info("Background refresh disabled (MARKET_DATA_BACKGROUND_REFRESH_ENABLED=false)")
        except Exception as exc:
            _log.error("Startup data download failed: %s", exc)

    threading.Thread(target=_init_data, name="startup-data-dl", daemon=True).start()
    yield


app = create_service_app(title="StockTrader – Market Data Service")
app.router.lifespan_context = _lifespan

app.include_router(stream.router, prefix="/api/v1")

# Only register market-status and account endpoints (not bot endpoints)
market_router = APIRouter(tags=["market"])
market_router.add_api_route("/market/status", market_status, methods=["GET"])
market_router.add_api_route("/account/profile", account_profile, methods=["GET"])
app.include_router(market_router, prefix="/api/v1")


@app.get("/api/v1/health")
async def health():
    return {"status": "ok", "service": "market-data"}
