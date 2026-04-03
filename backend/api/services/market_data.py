"""Market Data Microservice – Port 8001.

Handles WebSocket/SSE price streaming, market status, and account profile.
Isolated because long-lived WebSocket connections should not compete with
REST endpoints for event-loop attention.
"""

from dotenv import load_dotenv
load_dotenv()

from fastapi import APIRouter
from backend.api.services.base import create_service_app
from backend.api.routers import stream
from backend.api.routers.market import market_status, account_profile

app = create_service_app(title="StockTrader – Market Data Service")

app.include_router(stream.router, prefix="/api/v1")

# Only register market-status and account endpoints (not bot endpoints)
market_router = APIRouter(tags=["market"])
market_router.add_api_route("/market/status", market_status, methods=["GET"])
market_router.add_api_route("/account/profile", account_profile, methods=["GET"])
app.include_router(market_router, prefix="/api/v1")


@app.get("/api/v1/health")
async def health():
    return {"status": "ok", "service": "market-data"}
