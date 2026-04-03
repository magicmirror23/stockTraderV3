"""Angel One SmartAPI market-data provider.

Implements ``MarketDataProvider`` using Angel One's REST + WebSocket API.
Requires environment variables:
  ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_CLIENT_PIN, ANGEL_TOTP_SECRET
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from app.core.config import settings
from app.core.metrics import SOURCE_FAILURE_COUNT
from app.providers.base import (
    OHLCV,
    MarketDataProvider,
    OptionChain,
    OptionChainRow,
    Tick,
)

logger = logging.getLogger(__name__)

# Symbol token map for Angel One (loaded lazily)
_TOKEN_MAP: dict[str, dict] | None = None

# IST offset
_IST = timezone(timedelta(hours=5, minutes=30))


def _nse_symbol_to_token(symbol: str) -> str | None:
    """Map NSE symbol to Angel One token/symbol_token. Returns None if unknown."""
    global _TOKEN_MAP
    if _TOKEN_MAP is None:
        _load_token_map()
    info = (_TOKEN_MAP or {}).get(symbol)
    return info.get("token") if info else None


def _load_token_map() -> None:
    """Load Angel One instrument master (cached locally)."""
    global _TOKEN_MAP
    cache_path = Path("storage/runtime/angel_instruments.json")
    if cache_path.exists():
        age = time.time() - cache_path.stat().st_mtime
        if age < 86_400:  # refresh daily
            try:
                _TOKEN_MAP = json.loads(cache_path.read_text())
                return
            except Exception:
                pass

    # Fetch from Angel One
    try:
        import httpx
        resp = httpx.get(
            "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json",
            timeout=60,
        )
        resp.raise_for_status()
        instruments = resp.json()
        mapping: dict[str, dict] = {}
        for inst in instruments:
            if inst.get("exch_seg") == "NSE" and inst.get("symbol"):
                sym = inst["symbol"].split("-")[0]
                mapping[sym] = {
                    "token": inst.get("token", ""),
                    "symbol_token": inst.get("token", ""),
                    "trading_symbol": inst.get("symbol", ""),
                    "exchange": "NSE",
                }
        _TOKEN_MAP = mapping
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(mapping, indent=2))
        logger.info("Loaded %d Angel One instrument mappings", len(mapping))
    except Exception as exc:
        logger.error("Failed to load Angel One instrument master: %s", exc)
        _TOKEN_MAP = {}


class AngelOneProvider(MarketDataProvider):
    """Angel One SmartAPI data provider."""

    def __init__(self) -> None:
        self._session: Any | None = None
        self._auth_token: str | None = None
        self._last_auth: float = 0.0

    @property
    def name(self) -> str:
        return "angel_one"

    @property
    def is_available(self) -> bool:
        return bool(settings.ANGEL_API_KEY and settings.ANGEL_CLIENT_ID)

    def _ensure_session(self) -> Any:
        """Lazily authenticate and return SmartConnect session."""
        if self._session and (time.time() - self._last_auth) < 3600:
            return self._session

        if not self.is_available:
            raise RuntimeError("Angel One credentials not configured")

        try:
            from SmartApi import SmartConnect
            import pyotp

            obj = SmartConnect(api_key=settings.ANGEL_API_KEY)
            totp = pyotp.TOTP(settings.ANGEL_TOTP_SECRET).now()
            data = obj.generateSession(
                settings.ANGEL_CLIENT_ID,
                settings.ANGEL_CLIENT_PIN,
                totp,
            )
            if data.get("status"):
                self._session = obj
                self._auth_token = data["data"]["jwtToken"]
                self._last_auth = time.time()
                self._save_token_cache(data["data"])
                logger.info("Angel One session established")
            else:
                raise RuntimeError(f"Angel One auth failed: {data.get('message')}")
        except ImportError:
            logger.error("smartapi-python not installed")
            raise RuntimeError("smartapi-python package not installed")
        except Exception as exc:
            SOURCE_FAILURE_COUNT.labels(source="angel_one", error_type="auth").inc()
            logger.error("Angel One auth error: %s", exc)
            raise

        return self._session

    def _save_token_cache(self, auth_data: dict) -> None:
        """Persist tokens for session reuse."""
        cache_path = Path(settings.ANGEL_TOKEN_CACHE_PATH)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({
            "jwt": auth_data.get("jwtToken", ""),
            "refresh": auth_data.get("refreshToken", ""),
            "feed": auth_data.get("feedToken", ""),
            "timestamp": time.time(),
        }))

    # ── Historical data ──────────────────────────────────────────────

    def get_historical(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: str = "1d",
    ) -> list[OHLCV]:
        """Fetch historical candles from Angel One."""
        interval_map = {
            "1m": "ONE_MINUTE", "5m": "FIVE_MINUTE", "15m": "FIFTEEN_MINUTE",
            "30m": "THIRTY_MINUTE", "1h": "ONE_HOUR", "1d": "ONE_DAY",
        }
        angel_interval = interval_map.get(interval, "ONE_DAY")
        token = _nse_symbol_to_token(symbol)
        if not token:
            logger.warning("No Angel One token for %s, falling back to empty", symbol)
            return []

        try:
            session = self._ensure_session()
            params = {
                "exchange": "NSE",
                "symboltoken": token,
                "interval": angel_interval,
                "fromdate": start.strftime("%Y-%m-%d %H:%M"),
                "todate": end.strftime("%Y-%m-%d %H:%M"),
            }
            resp = session.getCandleData(params)
            if not resp or not resp.get("data"):
                return []

            bars: list[OHLCV] = []
            for row in resp["data"]:
                bars.append(OHLCV(
                    timestamp=datetime.fromisoformat(row[0]),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=int(row[5]),
                    symbol=symbol,
                ))
            return bars
        except Exception as exc:
            SOURCE_FAILURE_COUNT.labels(source="angel_one", error_type="historical").inc()
            logger.error("Angel One historical fetch for %s failed: %s", symbol, exc)
            return []

    # ── Live ticks ───────────────────────────────────────────────────

    def get_ltp(self, symbols: list[str]) -> dict[str, Tick]:
        """Get LTP for symbols from Angel One."""
        result: dict[str, Tick] = {}
        try:
            session = self._ensure_session()
            token_list = []
            sym_map: dict[str, str] = {}
            for sym in symbols:
                tk = _nse_symbol_to_token(sym)
                if tk:
                    token_list.append({"exchange": "NSE", "symboltoken": tk})
                    sym_map[tk] = sym

            if not token_list:
                return result

            resp = session.getMarketData("LTP", {"exchange": "NSE", "symbolTokens": token_list})
            if resp and resp.get("data", {}).get("fetched"):
                for item in resp["data"]["fetched"]:
                    tk = item.get("symbolToken", "")
                    sym = sym_map.get(tk, tk)
                    result[sym] = Tick(
                        symbol=sym,
                        timestamp=datetime.now(_IST),
                        price=float(item.get("ltp", 0)),
                        volume=0,
                    )
        except Exception as exc:
            SOURCE_FAILURE_COUNT.labels(source="angel_one", error_type="ltp").inc()
            logger.error("Angel One LTP fetch failed: %s", exc)
        return result

    # ── Option chain ─────────────────────────────────────────────────

    def get_option_chain(self, symbol: str, expiry: datetime | None = None) -> OptionChain | None:
        """Fetch option chain from Angel One (NSE F&O segment)."""
        try:
            session = self._ensure_session()
            # Angel One doesn't have a direct option chain API in SmartConnect
            # TODO: Implement via scraping or external source when needed
            logger.debug("Option chain not directly available via Angel One SmartConnect")
            return None
        except Exception as exc:
            SOURCE_FAILURE_COUNT.labels(source="angel_one", error_type="option_chain").inc()
            logger.error("Angel One option chain fetch failed: %s", exc)
            return None

    def connect(self) -> bool:
        try:
            self._ensure_session()
            return True
        except Exception:
            return False

    def disconnect(self) -> None:
        self._session = None
        self._auth_token = None

    def health_check(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "available": self.is_available,
            "authenticated": self._session is not None,
            "last_auth_age_s": (
                round(time.time() - self._last_auth, 1) if self._last_auth else None
            ),
        }
