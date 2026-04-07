"""Trade Supervisor Service – Port 8009.

Centralized risk supervisor for all automated intraday trading.
Also hosts intraday model training endpoints.
"""

from dotenv import load_dotenv
load_dotenv()

from backend.api.services.base import create_service_app
from backend.api.routers import intraday_supervisor, intraday_train

app = create_service_app(title="StockTrader – Trade Supervisor Service")

app.include_router(intraday_supervisor.router, prefix="/api/v1")
app.include_router(intraday_train.router, prefix="/api/v1")


@app.get("/api/v1/health")
async def health():
    return {"status": "ok", "service": "trade-supervisor"}
