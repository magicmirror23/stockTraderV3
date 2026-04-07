"""Execution Engine Service – Port 8008.

Micro-trade execution with bracket orders, trailing stops, and position management.
"""

from dotenv import load_dotenv
load_dotenv()

from backend.api.services.base import create_service_app
from backend.api.routers import intraday_execution

app = create_service_app(title="StockTrader – Execution Engine Service")

app.include_router(intraday_execution.router, prefix="/api/v1")


@app.get("/api/v1/health")
async def health():
    return {"status": "ok", "service": "execution-engine"}
