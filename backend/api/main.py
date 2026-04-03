# Entry point for FastAPI application

"""StockTrader Backend – Monolith FastAPI application.

This is the original single-process entry point that bundles ALL routers.
For the microservices split (recommended for production), use the individual
service entry points in backend/api/services/:

  - gateway.py       → Port 8000 (API Gateway + static files)
  - market_data.py   → Port 8001 (WebSocket/SSE streaming, market status)
  - prediction.py    → Port 8002 (ML prediction, model management)
  - trading.py       → Port 8003 (Trade execution, paper trading, bot)
  - admin_backtest.py→ Port 8004 (Retrain, backtest, metrics, drift)

Start microservices with:
  docker compose -f docker-compose.microservices.yml up
  OR
  python -m scripts.start_services  (local dev)
"""

import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from backend.logging_config import setup_logging
setup_logging()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.api.routers import (
    health, predict, model, backtest, trade, admin, paper, stream, market, bot,
    risk, strategy, portfolio, intelligence, options, execution, orchestrator, log,
)

app = FastAPI(
    title="StockTrader API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS â€“ restrict origins in production via ALLOWED_ORIGINS env var
_origins = os.getenv("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----- Routers -----
app.include_router(health.router, prefix="/api/v1")
app.include_router(predict.router, prefix="/api/v1")
app.include_router(model.router, prefix="/api/v1")
app.include_router(backtest.router, prefix="/api/v1")
app.include_router(trade.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.include_router(paper.router, prefix="/api/v1")
app.include_router(stream.router, prefix="/api/v1")
app.include_router(market.router, prefix="/api/v1")
app.include_router(bot.router, prefix="/api/v1")
app.include_router(risk.router, prefix="/api/v1")
app.include_router(strategy.router, prefix="/api/v1")
app.include_router(portfolio.router, prefix="/api/v1")
app.include_router(intelligence.router, prefix="/api/v1")
app.include_router(options.router, prefix="/api/v1")
app.include_router(execution.router, prefix="/api/v1")
app.include_router(orchestrator.router, prefix="/api/v1")
app.include_router(log.router, prefix="/api/v1")


# ----- Startup: auto-download market data & background refresh -----
@app.on_event("startup")
async def _startup_download_data():
    """Download any missing/stale CSV data and start periodic refresh."""
    import threading, logging
    _log = logging.getLogger("stocktrader.startup")

    def _init_data():
        try:
            from backend.services.data_downloader import (
                get_all_symbols, refresh_all_symbols, start_background_refresh,
            )
            symbols = get_all_symbols()
            _log.info("Auto-downloading data for %d symbols...", len(symbols))
            results = refresh_all_symbols(symbols)
            ok = sum(1 for v in results.values() if v)
            _log.info("Initial download: %d/%d symbols OK", ok, len(results))
            # Start background thread to keep data fresh (every 6 hours)
            start_background_refresh(interval_hours=6.0)
        except Exception as exc:
            _log.error("Startup data download failed: %s", exc)

    # Run in a thread so it doesn't block server startup
    threading.Thread(target=_init_data, name="startup-data-dl", daemon=True).start()


# ----- Serve Angular frontend (production builds) -----
_STATIC_DIR = Path(__file__).resolve().parents[2] / "static"

if _STATIC_DIR.is_dir():
    # Serve static assets (JS, CSS, images)
    app.mount("/assets", StaticFiles(directory=_STATIC_DIR / "assets"), name="assets") \
        if (_STATIC_DIR / "assets").is_dir() else None
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static-root")

    @app.get("/{full_path:path}")
    async def serve_angular(full_path: str):
        """Catch-all: serve Angular index.html for client-side routing."""
        file_path = _STATIC_DIR / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(_STATIC_DIR / "index.html")
