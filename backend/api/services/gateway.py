"""API Gateway – Port 8000 (Main Entry Point).

Lightweight reverse-proxy that routes requests to the appropriate microservice.
Also serves the Angular frontend static files and health checks.

Service routing:
  /api/v1/health                    → handled locally
  /api/v1/stream/*, /api/v1/market/*, /api/v1/account/* → Market Data (8001)
  /api/v1/predict*, /api/v1/batch_predict, /api/v1/model/* → Prediction (8002)
  /api/v1/trade_intent, /api/v1/execute, /api/v1/paper/*, /api/v1/bot/* → Trading (8003)
  /api/v1/retrain*, /api/v1/backtest/*, /api/v1/metrics, /api/v1/registry/*, /api/v1/drift/*, /api/v1/canary/* → Admin (8004)
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

# Service URLs (configurable via env vars)
MARKET_DATA_URL = os.getenv("MARKET_DATA_URL", "http://localhost:8001")
PREDICTION_URL = os.getenv("PREDICTION_URL", "http://localhost:8002")
TRADING_URL = os.getenv("TRADING_URL", "http://localhost:8003")
ADMIN_URL = os.getenv("ADMIN_URL", "http://localhost:8004")

app = FastAPI(
    title="StockTrader API Gateway",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

_origins = os.getenv("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Route mapping ──────────────────────────────────────────────────────────

def _resolve_upstream(path: str) -> str | None:
    """Map an API path to the upstream service base URL."""
    p = path.lstrip("/")

    # Market Data Service
    if p.startswith("api/v1/stream/") or p.startswith("api/v1/stream"):
        return MARKET_DATA_URL
    if p.startswith("api/v1/market/"):
        return MARKET_DATA_URL
    if p.startswith("api/v1/account/"):
        return MARKET_DATA_URL

    # Prediction Service
    if p.startswith("api/v1/predict") or p.startswith("api/v1/batch_predict"):
        return PREDICTION_URL
    if p.startswith("api/v1/model/"):
        return PREDICTION_URL

    # Trading Service
    if p.startswith("api/v1/trade_intent") or p.startswith("api/v1/execute"):
        return TRADING_URL
    if p.startswith("api/v1/paper/") or p.startswith("api/v1/paper"):
        return TRADING_URL
    if p.startswith("api/v1/bot/") or p.startswith("api/v1/bot"):
        return TRADING_URL

    # Admin / Backtest Service
    if p.startswith("api/v1/retrain") or p.startswith("api/v1/backtest"):
        return ADMIN_URL
    if p.startswith("api/v1/metrics") or p.startswith("api/v1/registry/"):
        return ADMIN_URL
    if p.startswith("api/v1/drift/") or p.startswith("api/v1/canary/"):
        return ADMIN_URL

    return None


# ── Health check (local) ──────────────────────────────────────────────────

@app.get("/api/v1/health")
async def health_check():
    """Gateway health check – also pings downstream services."""
    services = {}
    async with httpx.AsyncClient(timeout=5.0) as client:
        for name, url in [
            ("market_data", MARKET_DATA_URL),
            ("prediction", PREDICTION_URL),
            ("trading", TRADING_URL),
            ("admin", ADMIN_URL),
        ]:
            try:
                resp = await client.get(f"{url}/api/v1/health")
                services[name] = "ok" if resp.status_code == 200 else "degraded"
            except Exception:
                services[name] = "unreachable"

    overall = "ok" if all(v == "ok" for v in services.values()) else "degraded"
    return {"status": overall, "services": services}


# ── Reverse proxy for REST ────────────────────────────────────────────────

@app.api_route(
    "/api/v1/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
)
async def proxy_rest(request: Request, path: str):
    """Forward REST requests to the appropriate microservice."""
    full_path = f"/api/v1/{path}"
    upstream = _resolve_upstream(full_path)

    if upstream is None:
        return {"detail": f"No upstream service for path: {full_path}"}, 404

    target_url = f"{upstream}{full_path}"
    if request.url.query:
        target_url += f"?{request.url.query}"

    body = await request.body()
    headers = dict(request.headers)
    # Remove host header to avoid conflicts
    headers.pop("host", None)

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.request(
            method=request.method,
            url=target_url,
            content=body,
            headers=headers,
        )

    # Stream SSE responses
    if "text/event-stream" in resp.headers.get("content-type", ""):
        async def _stream():
            async with httpx.AsyncClient(timeout=None) as stream_client:
                async with stream_client.stream(
                    method=request.method,
                    url=target_url,
                    content=body,
                    headers=headers,
                ) as stream_resp:
                    async for chunk in stream_resp.aiter_bytes():
                        yield chunk

        return StreamingResponse(_stream(), media_type="text/event-stream")

    return StreamingResponse(
        iter([resp.content]),
        status_code=resp.status_code,
        headers=dict(resp.headers),
        media_type=resp.headers.get("content-type"),
    )


# ── WebSocket proxy ───────────────────────────────────────────────────────

@app.websocket("/api/v1/stream/price/{symbol}")
async def ws_price_proxy(websocket: WebSocket, symbol: str):
    """Proxy single-symbol WebSocket to Market Data service."""
    await _proxy_websocket(
        websocket,
        f"{MARKET_DATA_URL.replace('http', 'ws')}/api/v1/stream/price/{symbol}",
    )


@app.websocket("/api/v1/stream/multi")
async def ws_multi_proxy(websocket: WebSocket):
    """Proxy multi-symbol WebSocket to Market Data service."""
    await _proxy_websocket(
        websocket,
        f"{MARKET_DATA_URL.replace('http', 'ws')}/api/v1/stream/multi",
    )


async def _proxy_websocket(client_ws: WebSocket, upstream_url: str):
    """Bidirectional WebSocket proxy."""
    import asyncio
    import websockets

    await client_ws.accept()

    try:
        async with websockets.connect(upstream_url) as upstream_ws:
            async def client_to_upstream():
                try:
                    while True:
                        data = await client_ws.receive_text()
                        await upstream_ws.send(data)
                except WebSocketDisconnect:
                    await upstream_ws.close()
                except Exception:
                    pass

            async def upstream_to_client():
                try:
                    async for msg in upstream_ws:
                        await client_ws.send_text(msg)
                except Exception:
                    pass

            await asyncio.gather(client_to_upstream(), upstream_to_client())
    except Exception:
        try:
            await client_ws.close()
        except Exception:
            pass


# ── Serve Angular frontend (production builds) ────────────────────────────

_STATIC_DIR = Path(__file__).resolve().parents[3] / "static"

if _STATIC_DIR.is_dir():
    if (_STATIC_DIR / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=_STATIC_DIR / "assets"), name="assets")
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static-root")

    @app.get("/{full_path:path}")
    async def serve_angular(full_path: str):
        """Catch-all: serve Angular index.html for client-side routing."""
        file_path = _STATIC_DIR / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(_STATIC_DIR / "index.html")
