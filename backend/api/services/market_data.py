"""Market Data Microservice - Port 8001.

Primary responsibilities:
1) Canonical market-data ingest/query APIs (historical + quote + jobs)
2) Streaming endpoints (WebSocket/SSE)
3) Market status + account profile endpoints
"""

from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

from fastapi import APIRouter, FastAPI
from backend.api.services.base import create_service_app
from backend.api.routers import stream
from backend.api.routers import market_data_internal
from backend.api.routers.market import market_status, account_profile

_log = logging.getLogger("stocktrader.market_data")


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on", "y"}


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Startup hooks for market-data bootstrap and optional scheduler."""
    stop_event = threading.Event()

    def _scheduler_worker():
        from backend.api.routers.market_data_internal import _mds
        from backend.services.price_feed import SYMBOL_CATEGORIES

        refresh_minutes = int(os.getenv("MDS_SCHEDULER_REFRESH_MINUTES", "240"))
        retry_minutes = int(os.getenv("MDS_SCHEDULER_RETRY_MINUTES", "30"))
        metadata_minutes = int(os.getenv("MDS_SCHEDULER_METADATA_MINUTES", "120"))
        default_symbols = [
            s.strip().upper()
            for s in os.getenv("MDS_DEFAULT_SYMBOLS", "").split(",")
            if s.strip()
        ]
        if not default_symbols:
            seen = set()
            for symbols in SYMBOL_CATEGORIES.values():
                for symbol in symbols:
                    if symbol not in seen:
                        default_symbols.append(symbol)
                        seen.add(symbol)

        refresh_interval_s = max(60, refresh_minutes * 60)
        retry_interval_s = max(60, retry_minutes * 60)
        metadata_interval_s = max(60, metadata_minutes * 60)

        _log.info(
            "MDS scheduler started (refresh=%ss retry=%ss metadata=%ss symbols=%d)",
            refresh_interval_s,
            retry_interval_s,
            metadata_interval_s,
            len(default_symbols),
        )

        next_refresh = 0.0
        next_retry = 0.0
        next_metadata = 0.0
        while not stop_event.is_set():
            epoch = time.time()
            try:
                if epoch >= next_refresh:
                    _mds.job_refresh_latest_daily_bars(default_symbols, lookback_days=35)
                    next_refresh = epoch + refresh_interval_s
                if epoch >= next_retry:
                    _mds.job_retry_failed_symbols(interval="1d", limit=200)
                    next_retry = epoch + retry_interval_s
                if epoch >= next_metadata:
                    _mds.job_refresh_metadata()
                    next_metadata = epoch + metadata_interval_s
            except Exception as exc:
                _log.warning("MDS scheduler loop error: %s", exc)
            stop_event.wait(timeout=5.0)
        _log.info("MDS scheduler stopped")

    def _init_data():
        bootstrap_enabled = _env_bool("MARKET_DATA_BOOTSTRAP_DOWNLOAD", False)
        bg_enabled = _env_bool("MARKET_DATA_BACKGROUND_REFRESH_ENABLED", False)
        scheduler_enabled = _env_bool("MDS_SCHEDULER_ENABLED", True)
        interval_h = float(os.getenv("MARKET_DATA_REFRESH_INTERVAL_HOURS", "6.0"))
        symbol_limit = int(os.getenv("MARKET_DATA_BOOTSTRAP_LIMIT", "12"))
        bootstrap_symbols = [
            s.strip().upper()
            for s in os.getenv("MARKET_DATA_BOOTSTRAP_SYMBOLS", "").split(",")
            if s.strip()
        ]

        try:
            from backend.api.routers.market_data_internal import _mds
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

            if _env_bool("MDS_BACKFILL_ON_START", False):
                symbols = bootstrap_symbols or get_all_symbols()
                if symbol_limit > 0:
                    symbols = symbols[:symbol_limit]
                _log.info("MDS startup backfill for %d symbols", len(symbols))
                _mds.job_backfill_historical_data(symbols=symbols, years=3, interval="1d", min_rows=60)

            if scheduler_enabled:
                threading.Thread(
                    target=_scheduler_worker,
                    name="mds-scheduler",
                    daemon=True,
                ).start()
            else:
                _log.info("MDS scheduler disabled (MDS_SCHEDULER_ENABLED=false)")
        except Exception as exc:
            _log.error("Startup data download failed: %s", exc)

        # Auto-connect to AngelOne live feed when market is open
        try:
            from backend.services.market_hours import get_market_status, MarketPhase
            market = get_market_status()
            if market.phase in (MarketPhase.OPEN, MarketPhase.PRE_OPEN):
                from backend.api.routers.stream import _feed
                result = _feed.connect_live()
                if result.get("connected"):
                    _log.info("Auto-connected to AngelOne live feed (%d tokens)", result.get("tokens_resolved", 0))
                else:
                    _log.info("Live feed auto-connect skipped: %s", result.get("error", "unavailable"))
        except Exception as exc:
            _log.warning("Live feed auto-connect failed: %s", exc)

    threading.Thread(target=_init_data, name="startup-data-dl", daemon=True).start()
    yield
    stop_event.set()


app = create_service_app(title="StockTrader – Market Data Service")
app.router.lifespan_context = _lifespan

app.include_router(stream.router, prefix="/api/v1")
app.include_router(market_data_internal.router, prefix="/api/v1")

# Only register market-status and account endpoints (not bot endpoints)
market_router = APIRouter(tags=["market"])
market_router.add_api_route("/market/status", market_status, methods=["GET"])
market_router.add_api_route("/account/profile", account_profile, methods=["GET"])
app.include_router(market_router, prefix="/api/v1")


@app.get("/api/v1/health")
async def health():
    return {"status": "ok", "service": "market-data"}
