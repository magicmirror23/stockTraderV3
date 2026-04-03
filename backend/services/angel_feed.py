# Angel One feed service

"""AngelOne SmartAPI live market data feed.

Provides real-time tick data via SmartAPI WebSocket (SmartWebSocketV2).
Falls back to LTP REST polling if WebSocket is unavailable.

Usage:
    feed = AngelLiveFeed()
    if feed.connect(["RELIANCE", "TCS", "INFY"]):
        tick = feed.get_latest("RELIANCE")
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

ANGEL_API_KEY = os.getenv("ANGEL_API_KEY", "")
ANGEL_CLIENT_ID = os.getenv("ANGEL_CLIENT_ID", "")
ANGEL_MPIN = os.getenv("ANGEL_MPIN", "")
ANGEL_TOTP_SECRET = os.getenv("ANGEL_TOTP_SECRET", "")

TOKEN_CACHE = Path(
    os.getenv("ANGEL_TOKEN_CACHE_PATH", "storage/runtime/angel_tokens.json")
)

# Exchange type constants (AngelOne SmartAPI)
NSE_CM = 1   # NSE Cash Market
NSE_FO = 2   # NSE F&O
BSE_CM = 3   # BSE Cash Market

# Well-known index tokens (these don't change)
_INDEX_TOKENS: dict[str, dict] = {
    "NIFTY50": {"token": "99926000", "exchange": NSE_CM, "tradingsymbol": "Nifty 50"},
    "BANKNIFTY": {"token": "99926009", "exchange": NSE_CM, "tradingsymbol": "Nifty Bank"},
    "SENSEX": {"token": "99919000", "exchange": BSE_CM, "tradingsymbol": "SENSEX"},
}


class AngelLiveFeed:
    """Singleton real-time price feed using AngelOne SmartAPI WebSocket.

    Thread-safe: WebSocket runs in a daemon thread; ticks are stored in
    a lock-protected dict accessible from the asyncio event loop.
    """

    _instance: AngelLiveFeed | None = None
    _cls_lock = threading.Lock()

    def __new__(cls) -> AngelLiveFeed:
        with cls._cls_lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._inited = False
                cls._instance = inst
            return cls._instance

    def __init__(self) -> None:
        if self._inited:
            return
        self._inited = True
        self._smart_api = None
        self._sws = None
        self._auth_token: str | None = None
        self._feed_token: str | None = None
        self._authenticated = False
        self._connected = False
        self._token_map: dict[str, dict] = {}    # symbol â†’ {token, exchange, tradingsymbol}
        self._reverse_map: dict[str, str] = {}   # "exchange:token" â†’ symbol
        self._latest: dict[str, dict] = {}        # symbol â†’ latest tick dict
        self._buffers: dict[str, deque] = {}      # symbol â†’ recent tick history
        self._lock = threading.Lock()
        self._ws_thread: threading.Thread | None = None
        self._error: str | None = None
        self._tick_count = 0
        self._load_cache()

    # â”€â”€ Properties â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    @property
    def is_available(self) -> bool:
        """Whether AngelOne credentials are configured."""
        return all([ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_MPIN, ANGEL_TOTP_SECRET])

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def status(self) -> dict:
        return {
            "available": self.is_available,
            "authenticated": self._authenticated,
            "connected": self._connected,
            "symbols_streaming": len(self._latest),
            "tokens_resolved": len(self._token_map),
            "tick_count": self._tick_count,
            "error": self._error,
        }

    # â”€â”€ Token cache â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _load_cache(self) -> None:
        if TOKEN_CACHE.exists():
            try:
                data = json.loads(TOKEN_CACHE.read_text(encoding="utf-8"))
                self._token_map = data.get("tokens", {})
                self._rebuild_reverse()
            except Exception:
                pass

    def _save_cache(self) -> None:
        TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_CACHE.write_text(
            json.dumps({"tokens": self._token_map}, indent=2),
            encoding="utf-8",
        )

    def _rebuild_reverse(self) -> None:
        self._reverse_map = {
            f"{v['exchange']}:{v['token']}": k
            for k, v in self._token_map.items()
        }

    # â”€â”€ Authentication â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def authenticate(self) -> bool:
        """Login to SmartAPI and obtain auth + feed tokens."""
        if self._authenticated:
            return True
        if not self.is_available:
            self._error = "AngelOne credentials not configured in .env"
            return False
        try:
            from SmartApi import SmartConnect
            import pyotp

            totp = pyotp.TOTP(ANGEL_TOTP_SECRET).now()
            self._smart_api = SmartConnect(api_key=ANGEL_API_KEY)
            data = self._smart_api.generateSession(ANGEL_CLIENT_ID, ANGEL_MPIN, totp)

            if not data or data.get("status") is False:
                self._error = f"Login failed: {data.get('message', 'unknown')}"
                logger.error("AngelOne login failed: %s", data)
                return False

            self._auth_token = data["data"]["jwtToken"]
            self._feed_token = self._smart_api.getfeedToken()
            self._authenticated = True
            self._error = None
            logger.info("AngelOne authenticated for live market feed")
            return True

        except ImportError:
            self._error = "smartapi-python or pyotp not installed"
            return False
        except Exception as exc:
            self._error = str(exc)
            logger.error("AngelOne auth error: %s", exc)
            return False

    # â”€â”€ Token resolution â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def resolve_tokens(self, symbols: list[str]) -> int:
        """Map stock symbols to AngelOne instrument tokens via searchScrip.

        Returns count of successfully resolved tokens.
        """
        if not self._smart_api:
            return 0

        resolved = 0
        for sym in symbols:
            if sym in self._token_map:
                resolved += 1
                continue

            # Indices â€” use well-known map
            if sym in _INDEX_TOKENS:
                self._token_map[sym] = dict(_INDEX_TOKENS[sym])
                resolved += 1
                continue

            # NSE equity â€” look up via searchScrip API
            try:
                search_name = sym.replace("_", "&")  # M_M â†’ M&M
                result = self._smart_api.searchScrip("NSE", search_name)
                if result and result.get("data"):
                    for item in result["data"]:
                        ts = item.get("tradingsymbol", "")
                        if ts in (search_name + "-EQ", search_name):
                            self._token_map[sym] = {
                                "token": item["symboltoken"],
                                "exchange": NSE_CM,
                                "tradingsymbol": ts,
                            }
                            resolved += 1
                            logger.debug("Resolved %s â†’ token %s", sym, item["symboltoken"])
                            break
                time.sleep(0.05)  # gentle rate-limit
            except Exception as exc:
                logger.warning("Token resolve failed for %s: %s", sym, exc)

        self._rebuild_reverse()
        self._save_cache()
        logger.info("Token resolution complete: %d/%d resolved", resolved, len(symbols))
        return resolved

    # â”€â”€ WebSocket streaming â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def connect(self, symbols: list[str]) -> bool:
        """Authenticate, resolve tokens, and start WebSocket streaming."""
        if self._connected:
            return True

        # Clean up any stale state from previous connection
        if self._ws_thread and self._ws_thread.is_alive():
            self.disconnect()

        if not self.authenticate():
            return False

        self.resolve_tokens(symbols)

        # Group tokens by exchange type
        ex_tokens: dict[int, list[str]] = {}
        for sym in symbols:
            info = self._token_map.get(sym)
            if info:
                ex_tokens.setdefault(info["exchange"], []).append(info["token"])

        if not ex_tokens:
            self._error = "No instrument tokens resolved â€” check symbol names"
            return False

        token_list = [
            {"exchangeType": ex, "tokens": toks}
            for ex, toks in ex_tokens.items()
        ]

        try:
            from SmartApi.smartWebSocketV2 import SmartWebSocketV2

            self._sws = SmartWebSocketV2(
                self._auth_token,
                ANGEL_API_KEY,
                ANGEL_CLIENT_ID,
                self._feed_token,
            )

            def on_open(wsapp):
                n = sum(len(t["tokens"]) for t in token_list)
                logger.info("AngelOne WS connected â€” subscribing to %d tokens", n)
                self._sws.subscribe("stocktrader", 2, token_list)  # mode 2 = Quote
                self._connected = True

            def on_data(wsapp, message):
                self._on_tick(message)

            def on_error(wsapp, error):
                logger.error("AngelOne WS error: %s", error)
                self._error = str(error)

            def on_close(wsapp):
                logger.info("AngelOne WS closed")
                self._connected = False

            self._sws.on_open = on_open
            self._sws.on_data = on_data
            self._sws.on_error = on_error
            self._sws.on_close = on_close

            self._ws_thread = threading.Thread(
                target=self._sws.connect, daemon=True, name="angel-ws",
            )
            self._ws_thread.start()

            # Wait up to 5 seconds for connection
            for _ in range(50):
                if self._connected:
                    logger.info("AngelOne live feed active")
                    return True
                time.sleep(0.1)

            if not self._connected:
                self._error = "WebSocket connection timed out (5s)"
            return self._connected

        except ImportError:
            self._error = "SmartApi.smartWebSocketV2 not available"
            return False
        except Exception as exc:
            self._error = str(exc)
            logger.error("WS connect failed: %s", exc)
            return False

    def _on_tick(self, msg: dict) -> None:
        """Process incoming WebSocket tick (called from WS thread)."""
        token = str(msg.get("token", ""))
        exchange = msg.get("exchange_type", NSE_CM)
        symbol = self._reverse_map.get(f"{exchange}:{token}")
        if not symbol:
            return

        # SmartWebSocketV2 returns prices in paisa â€” divide by 100
        raw_price = msg.get("last_traded_price", 0)
        if not raw_price:
            return
        price = raw_price / 100.0

        prev_close = msg.get("closed_price", 0) / 100.0
        change = round(price - prev_close, 2) if prev_close else 0
        change_pct = round((change / prev_close) * 100, 2) if prev_close else 0

        # Best bid/ask from top-of-book data
        bid = None
        ask = None
        buy5 = msg.get("best_5_buy_data")
        sell5 = msg.get("best_5_sell_data")
        if buy5 and len(buy5) > 0:
            raw_bid = buy5[0].get("price", 0)
            bid = raw_bid / 100.0 if raw_bid else None
        if sell5 and len(sell5) > 0:
            raw_ask = sell5[0].get("price", 0)
            ask = raw_ask / 100.0 if raw_ask else None

        tick = {
            "symbol": symbol,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "price": round(price, 2),
            "volume": msg.get("volume_trade_for_the_day", 0),
            "bid": round(bid, 2) if bid else None,
            "ask": round(ask, 2) if ask else None,
            "open": round(msg.get("open_price_of_the_day", 0) / 100.0, 2),
            "high": round(msg.get("high_price_of_the_day", 0) / 100.0, 2),
            "low": round(msg.get("low_price_of_the_day", 0) / 100.0, 2),
            "close": round(price, 2),
            "prev_close": round(prev_close, 2),
            "change": change,
            "change_pct": change_pct,
        }

        with self._lock:
            self._latest[symbol] = tick
            buf = self._buffers.setdefault(symbol, deque(maxlen=500))
            buf.append(tick)
            self._tick_count += 1

    # â”€â”€ Data access (thread-safe) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def get_latest(self, symbol: str) -> dict | None:
        """Get the most recent tick for a symbol."""
        with self._lock:
            return self._latest.get(symbol)

    def get_all_latest(self) -> dict[str, dict]:
        """Get latest ticks for all streaming symbols."""
        with self._lock:
            return dict(self._latest)

    def get_buffer(self, symbol: str) -> list[dict]:
        """Get recent tick history for a symbol."""
        with self._lock:
            return list(self._buffers.get(symbol, []))

    # â”€â”€ LTP REST fallback â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def fetch_ltp(self, symbol: str) -> dict | None:
        """Fetch last traded price via SmartAPI REST (one-shot)."""
        if not self._authenticated or not self._smart_api:
            return None
        info = self._token_map.get(symbol)
        if not info:
            return None
        try:
            exchange = "NSE" if info["exchange"] == NSE_CM else "BSE"
            ts = info.get("tradingsymbol", symbol)
            data = self._smart_api.ltpData(exchange, ts, info["token"])
            if data and data.get("data"):
                ltp = float(data["data"].get("ltp", 0))
                return {
                    "symbol": symbol,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "price": ltp,
                    "volume": 0,
                    "bid": None,
                    "ask": None,
                    "open": float(data["data"].get("open", 0)),
                    "high": float(data["data"].get("high", 0)),
                    "low": float(data["data"].get("low", 0)),
                    "close": ltp,
                    "prev_close": float(data["data"].get("close", 0)),
                    "change": 0,
                    "change_pct": 0,
                }
        except Exception as exc:
            logger.warning("LTP REST failed for %s: %s", symbol, exc)
        return None

    # â”€â”€ Cleanup â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def disconnect(self) -> None:
        """Close WebSocket and reset session state."""
        self._connected = False
        if self._sws:
            try:
                self._sws.close_connection()
            except Exception:
                pass
            self._sws = None
        # Wait for WS thread to die
        if self._ws_thread and self._ws_thread.is_alive():
            self._ws_thread.join(timeout=3)
        self._ws_thread = None
        self._authenticated = False
        self._smart_api = None
        self._auth_token = None
        self._feed_token = None
        self._error = None
        with self._lock:
            self._latest.clear()
            self._buffers.clear()
            self._tick_count = 0
        logger.info("AngelOne live feed disconnected")

    def reset(self) -> None:
        """Full reset â€” clears singleton so next instantiation re-inits."""
        self.disconnect()
        with self._lock:
            self._latest.clear()
            self._buffers.clear()
            self._tick_count = 0
        self._inited = False
        AngelLiveFeed._instance = None
