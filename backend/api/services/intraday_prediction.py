"""Intraday Prediction Service – Port 8006.

ML inference for intraday trading signals.
"""

from dotenv import load_dotenv
load_dotenv()

from backend.api.services.base import create_service_app
from backend.api.routers import intraday_predict

app = create_service_app(title="StockTrader – Intraday Prediction Service")

app.include_router(intraday_predict.router, prefix="/api/v1")


@app.get("/api/v1/health")
async def health():
    return {"status": "ok", "service": "intraday-prediction"}
