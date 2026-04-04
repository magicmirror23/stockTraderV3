"""Prediction / ML Microservice – Port 8002.

Handles prediction endpoints and model management.
Isolated because ML inference is CPU-intensive and should not starve
WebSocket streams or trading operations.
"""

from dotenv import load_dotenv
load_dotenv()

from backend.api.services.base import create_service_app
from backend.api.routers import predict, model, strategy, intelligence

app = create_service_app(title="StockTrader – Prediction Service")

app.include_router(predict.router, prefix="/api/v1")
app.include_router(model.router, prefix="/api/v1")
app.include_router(strategy.router, prefix="/api/v1")
app.include_router(intelligence.router, prefix="/api/v1")


@app.get("/api/v1/health")
async def health():
    return {"status": "ok", "service": "prediction"}
