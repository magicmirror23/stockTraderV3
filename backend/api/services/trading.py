"""Trading Microservice – Port 8003.

Handles trade intents, execution, paper trading, and the auto-trading bot.
Isolated because the TradingBot spawns background threads and manages
stateful positions that should not interfere with other services.
"""

from dotenv import load_dotenv
load_dotenv()

from backend.api.services.base import create_service_app
from backend.api.routers import trade, paper, bot

app = create_service_app(title="StockTrader – Trading Service")

app.include_router(trade.router, prefix="/api/v1")
app.include_router(paper.router, prefix="/api/v1")
app.include_router(bot.router, prefix="/api/v1")


@app.get("/api/v1/health")
async def health():
    return {"status": "ok", "service": "trading"}
