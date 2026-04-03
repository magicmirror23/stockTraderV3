"""Admin / Backtest Microservice – Port 8004.

Handles model retraining, backtesting, metrics, drift detection, and
model registry management. Isolated because training and backtesting are
compute-heavy operations that would starve real-time endpoints.
"""

from dotenv import load_dotenv
load_dotenv()

from backend.api.services.base import create_service_app
from backend.api.routers import admin, backtest

app = create_service_app(title="StockTrader – Admin & Backtest Service")

app.include_router(admin.router, prefix="/api/v1")
app.include_router(backtest.router, prefix="/api/v1")


@app.get("/api/v1/health")
async def health():
    return {"status": "ok", "service": "admin"}
