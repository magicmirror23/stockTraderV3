# Streaming endpoint
"""Live price streaming endpoints (WebSocket + SSE) â€” single & multi-symbol."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from starlette.responses import StreamingResponse

from backend.services.market_hours import get_market_status, MarketPhase
from backend.services.price_feed import PriceFeed

router = APIRouter(tags=["streaming"])

_feed = PriceFeed(mode="auto")


def _tick_dict(tick) -> dict:
    return {
        "symbol": tick.symbol,
        "timestamp": tick.timestamp.isoformat(),
        "price": tick.price,
        "volume": tick.volume,
        "bid": tick.bid,
        "ask": tick.ask,
        "open": tick.open,
        "high": tick.high,
        "low": tick.low,
        "close": tick.close,
        "prev_close": tick.prev_close,
        "change": tick.change,
        "change_pct": tick.change_pct,
        "feed_mode": _feed.feed_mode,
    }


# â”€â”€ Feed status & live connection â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get("/stream/feed-status")
async def feed_status():
    """Check whether the feed is live (AngelOne) or replay (CSV), plus market status."""
    market = get_market_status()
    is_open = market.phase in (MarketPhase.OPEN, MarketPhase.PRE_OPEN)
    return {
        **_feed.feed_status,
        "market_phase": market.phase.value,
        "market_message": market.message,
        "is_market_open": is_open,
        "next_event": market.next_event,
        "next_event_time": market.next_event_time,
        "seconds_to_next": market.seconds_to_next,
    }


@router.post("/stream/connect-live")
async def connect_live(
    symbols: str = Query(default="", description="Comma-separated symbols (empty = all)")
):
    """Connect to AngelOne SmartAPI WebSocket for real-time market data.

    Requires ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_MPIN, ANGEL_TOTP_SECRET
    to be set in the .env file.
    """
    import asyncio
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()] or None
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _feed.connect_live, sym_list)
    return result


@router.post("/stream/disconnect-live")
async def disconnect_live():
    """Disconnect from AngelOne live feed and fall back to CSV replay."""
    return _feed.disconnect_live()


# â”€â”€ Single-symbol endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get("/stream/last_close/{symbol}")
async def last_close(symbol: str):
    """Return the most recent closing price for a symbol."""
    tick = _feed.get_latest_price(symbol)
    if tick is None:
        from datetime import datetime, timezone
        return {
            "symbol": symbol,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "price": 0.0,
            "volume": 0,
            "bid": None,
            "ask": None,
            "open": None,
            "high": None,
            "low": None,
            "close": None,
            "prev_close": None,
            "change": None,
            "change_pct": None,
        }
    return _tick_dict(tick)


@router.websocket("/stream/price/{symbol}")
async def price_websocket(websocket: WebSocket, symbol: str):
    """WebSocket endpoint for real-time price streaming (single symbol)."""
    await websocket.accept()
    try:
        async for tick in _feed.stream(symbol, speed=15.0, recent_days=30):
            await websocket.send_json(_tick_dict(tick))
    except WebSocketDisconnect:
        pass


@router.get("/stream/price/{symbol}")
async def price_sse(symbol: str):
    """SSE fallback for live price streaming (single symbol)."""

    async def event_generator():
        async for tick in _feed.stream(symbol, speed=15.0, recent_days=30):
            data = json.dumps(_tick_dict(tick))
            yield f"data: {data}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# â”€â”€ Multi-symbol endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get("/stream/symbols")
async def available_symbols():
    """List all symbols that have price data available for streaming."""
    return {"symbols": _feed.available_symbols()}


@router.get("/stream/categories")
async def symbol_categories():
    """Return symbols grouped by sector/category."""
    return _feed.get_categories()


@router.get("/stream/watchlist")
async def watchlist_snapshot(
    symbols: str = Query(default="", description="Comma-separated symbols (empty = all)")
):
    """Get latest prices for multiple symbols at once."""
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()] or None
    return {"data": _feed.get_watchlist_snapshot(sym_list)}


@router.get("/stream/market-overview")
async def market_overview():
    """Top gainers, losers, and volume leaders."""
    return _feed.get_market_overview()


@router.get("/stream/market-snapshot")
async def market_snapshot():
    """Return last close data for all available symbols with market status.

    When market is closed, this provides the most recent closing prices
    so the frontend can display them automatically.
    """
    market = get_market_status()
    is_open = market.phase in (MarketPhase.OPEN, MarketPhase.PRE_OPEN)
    snapshot = _feed.get_watchlist_snapshot()
    return {
        "market_phase": market.phase.value,
        "market_message": market.message,
        "is_market_open": is_open,
        "next_event": market.next_event,
        "next_event_time": market.next_event_time,
        "seconds_to_next": market.seconds_to_next,
        "data": snapshot,
    }


@router.websocket("/stream/multi")
async def multi_price_websocket(websocket: WebSocket):
    """WebSocket for streaming multiple symbols simultaneously.

    Client sends a JSON message to subscribe:
        {"action": "subscribe", "symbols": ["RELIANCE", "TCS", ...]}
    Server streams ticks for all requested symbols interleaved.
    Client can send {"action": "unsubscribe"} or close to stop.
    """
    await websocket.accept()

    symbols: list[str] = []
    stream_task: asyncio.Task | None = None

    async def _stream_loop(syms: list[str]):
        try:
            async for tick in _feed.stream_multi(syms, speed=25.0, recent_days=30):
                await websocket.send_json(_tick_dict(tick))
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass

    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            action = msg.get("action", "")

            if action == "subscribe":
                if stream_task and not stream_task.done():
                    stream_task.cancel()
                symbols = [s.upper() for s in msg.get("symbols", []) if s.strip()]
                if symbols:
                    stream_task = asyncio.create_task(_stream_loop(symbols))

            elif action == "unsubscribe":
                if stream_task and not stream_task.done():
                    stream_task.cancel()
                    stream_task = None

    except WebSocketDisconnect:
        pass
    finally:
        if stream_task and not stream_task.done():
            stream_task.cancel()


@router.get("/stream/multi")
async def multi_price_sse(
    symbols: str = Query(description="Comma-separated symbols to stream")
):
    """SSE stream for multiple symbols interleaved."""
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not sym_list:
        raise HTTPException(status_code=400, detail="Provide at least one symbol")

    async def event_generator():
        async for tick in _feed.stream_multi(sym_list, speed=25.0, recent_days=30):
            data = json.dumps(_tick_dict(tick))
            yield f"data: {data}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
