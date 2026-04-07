"""Intraday Feature Service – Port 8005.

Manages intraday candle data pipeline and feature computation.
"""

from dotenv import load_dotenv
load_dotenv()

from backend.api.services.base import create_service_app
from backend.api.routers import intraday_features

app = create_service_app(title="StockTrader – Intraday Feature Service")

app.include_router(intraday_features.router, prefix="/api/v1")


@app.get("/api/v1/health")
async def health():
    return {"status": "ok", "service": "intraday-features"}
