"""Portfolio Risk Microservice - Port 8005.

Provides portfolio and risk endpoints as an isolated service so risk checks can
scale independently from trade execution.
"""

from dotenv import load_dotenv
load_dotenv()

from backend.api.services.base import create_service_app
from backend.api.routers import risk, portfolio

app = create_service_app(title="StockTrader – Portfolio Risk Service")

app.include_router(risk.router, prefix="/api/v1")
app.include_router(portfolio.router, prefix="/api/v1")


@app.get("/api/v1/health")
async def health():
    return {"status": "ok", "service": "portfolio-risk"}

