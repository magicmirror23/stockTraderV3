"""TwelveData provider for historical fallback and quotes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
import pandas as pd

from ..errors import (
    ProviderFailure,
    ERROR_EMPTY_DATA,
    ERROR_INVALID_RESPONSE,
    ERROR_PROVIDER_UNAVAILABLE,
    ERROR_RATE_LIMITED,
    ERROR_SYMBOL_NOT_FOUND,
)
from ..symbols import SymbolResolver
from .base import MarketDataProvider


class TwelveDataProvider(MarketDataProvider):
    name = "twelve_data"

    _BASE_URL = "https://api.twelvedata.com"

    def __init__(
        self,
        api_key: str | None,
        resolver: SymbolResolver | None = None,
        timeout_s: float = 20.0,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._resolver = resolver or SymbolResolver()
        self._timeout_s = timeout_s

    def _request(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._api_key:
            raise ProviderFailure(
                "TWELVE_DATA_API_KEY is not configured",
                code=ERROR_PROVIDER_UNAVAILABLE,
                provider=self.name,
                retryable=False,
            )

        req_params = {**params, "apikey": self._api_key}
        try:
            with httpx.Client(timeout=self._timeout_s) as client:
                resp = client.get(f"{self._BASE_URL}{path}", params=req_params)
            data = resp.json()
        except Exception as exc:
            raise ProviderFailure(
                "TwelveData request failed",
                code=ERROR_PROVIDER_UNAVAILABLE,
                provider=self.name,
                details={"path": path},
                retryable=True,
            ) from exc

        status = str(data.get("status", "")).lower()
        if status == "error":
            code_text = str(data.get("code", ""))
            message = str(data.get("message", "TwelveData returned error"))
            lowered = message.lower()
            if "rate" in lowered or code_text in {"429", "5"}:
                code = ERROR_RATE_LIMITED
                retryable = True
            elif "symbol" in lowered and "not found" in lowered:
                code = ERROR_SYMBOL_NOT_FOUND
                retryable = False
            else:
                code = ERROR_PROVIDER_UNAVAILABLE
                retryable = True
            raise ProviderFailure(
                message,
                code=code,
                provider=self.name,
                details={"provider_code": code_text, "raw": data},
                retryable=retryable,
            )

        return data

    def get_historical_bars(
        self,
        symbol: str,
        start_date: str | datetime,
        end_date: str | datetime,
        interval: str,
    ) -> pd.DataFrame:
        resolved = self._resolver.resolve(symbol)

        interval_map = {
            "1d": "1day",
            "1h": "1h",
            "15m": "15min",
            "5m": "5min",
            "1m": "1min",
        }
        td_interval = interval_map.get(interval, "1day")

        start = pd.Timestamp(start_date).strftime("%Y-%m-%d")
        end = pd.Timestamp(end_date).strftime("%Y-%m-%d")

        data = self._request(
            "/time_series",
            {
                "symbol": resolved.twelve_data_symbol,
                "interval": td_interval,
                "start_date": start,
                "end_date": end,
                "order": "ASC",
                "outputsize": 5000,
                "timezone": "Asia/Kolkata",
                "format": "JSON",
            },
        )

        rows = data.get("values")
        if not isinstance(rows, list) or not rows:
            raise ProviderFailure(
                f"No data returned for {resolved.canonical_symbol}",
                code=ERROR_EMPTY_DATA,
                provider=self.name,
                details={"symbol": resolved.canonical_symbol},
                retryable=True,
            )

        frame = pd.DataFrame(rows)
        needed = {"datetime", "open", "high", "low", "close", "volume"}
        if not needed.issubset(set(frame.columns)):
            raise ProviderFailure(
                "TwelveData response missing required columns",
                code=ERROR_INVALID_RESPONSE,
                provider=self.name,
                details={"columns": list(frame.columns)},
                retryable=False,
            )

        frame = frame.rename(columns={"datetime": "Date"})
        return frame

    def get_latest_quote(self, symbol: str) -> dict[str, Any]:
        resolved = self._resolver.resolve(symbol)
        data = self._request("/quote", {"symbol": resolved.twelve_data_symbol})

        price = float(data.get("close") or data.get("price") or 0.0)
        prev_close = float(data.get("previous_close") or data.get("close") or 0.0)
        change = price - prev_close
        change_pct = (change / prev_close * 100.0) if prev_close else 0.0

        return {
            "symbol": resolved.canonical_symbol,
            "price": round(price, 4),
            "prev_close": round(prev_close, 4),
            "change": round(change, 4),
            "change_pct": round(change_pct, 4),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "provider": self.name,
        }

    def get_market_status(self, exchange: str) -> dict[str, Any]:
        data = self._request("/market_state", {})
        markets = data.get("markets") if isinstance(data, dict) else None
        status = "unknown"
        if isinstance(markets, list):
            for m in markets:
                if str(m.get("exchange", "")).upper() == str(exchange).upper():
                    status = str(m.get("status", "unknown")).lower()
                    break

        return {
            "exchange": exchange,
            "status": status,
            "provider": self.name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def search_symbol(self, symbol: str) -> dict[str, Any]:
        resolved = self._resolver.resolve(symbol)
        data = self._request("/symbol_search", {"symbol": resolved.canonical_symbol})
        payload = data.get("data") if isinstance(data, dict) else None
        first = payload[0] if isinstance(payload, list) and payload else {}
        return {
            "input_symbol": symbol,
            "canonical_symbol": resolved.canonical_symbol,
            "provider_symbol": resolved.twelve_data_symbol,
            "provider": self.name,
            "match": first,
        }
