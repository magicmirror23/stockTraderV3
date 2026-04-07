"""Options Signal Service – Port 8007.

F&O derivatives signal generation.
"""

from dotenv import load_dotenv
load_dotenv()

from backend.api.services.base import create_service_app
from backend.api.routers import intraday_options

app = create_service_app(title="StockTrader – Options Signal Service")

app.include_router(intraday_options.router, prefix="/api/v1")


@app.get("/api/v1/health")
async def health():
    return {"status": "ok", "service": "options-signal"}
