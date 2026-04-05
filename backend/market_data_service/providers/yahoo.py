"""Yahoo Finance provider implementation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from ..errors import (
    ProviderFailure,
    ERROR_EMPTY_DATA,
    ERROR_PROVIDER_UNAVAILABLE,
    ERROR_RATE_LIMITED,
    ERROR_SYMBOL_NOT_FOUND,
)
from ..symbols import SymbolResolver
from .base import MarketDataProvider

try:
    import yfinance as yf
except Exception:  # pragma: no cover
    yf = None


class YahooFinanceProvider(MarketDataProvider):
    name = "yahoo"

    def __init__(self, resolver: SymbolResolver | None = None) -> None:
        self._resolver = resolver or SymbolResolver()

    @staticmethod
    def _is_rate_limited(exc: Exception) -> bool:
        text = str(exc).lower()
        return "rate limit" in text or "too many requests" in text

    @staticmethod
    def _to_date(value: str | datetime) -> str:
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d")
        return str(value)[:10]

    def get_historical_bars(
        self,
        symbol: str,
        start_date: str | datetime,
        end_date: str | datetime,
        interval: str,
    ) -> pd.DataFrame:
        if yf is None:
            raise ProviderFailure(
                "yfinance is not installed",
                code=ERROR_PROVIDER_UNAVAILABLE,
                provider=self.name,
                retryable=False,
            )

        resolved = self._resolver.resolve(symbol)
        try:
            frame = yf.download(
                resolved.yahoo_symbol,
                start=self._to_date(start_date),
                end=self._to_date(end_date),
                interval=interval,
                auto_adjust=False,
                progress=False,
                threads=False,
            )
        except Exception as exc:
            code = ERROR_RATE_LIMITED if self._is_rate_limited(exc) else ERROR_PROVIDER_UNAVAILABLE
            raise ProviderFailure(
                f"Yahoo fetch failed for {resolved.canonical_symbol}",
                code=code,
                provider=self.name,
                details={"symbol": resolved.canonical_symbol, "provider_symbol": resolved.yahoo_symbol},
                retryable=True,
            ) from exc

        if frame is None or frame.empty:
            raise ProviderFailure(
                f"No data returned for {resolved.canonical_symbol}",
                code=ERROR_EMPTY_DATA,
                provider=self.name,
                details={"symbol": resolved.canonical_symbol, "provider_symbol": resolved.yahoo_symbol},
                retryable=True,
            )

        if isinstance(frame.columns, pd.MultiIndex):
            frame.columns = frame.columns.get_level_values(0)
        if "Date" not in frame.columns:
            frame = frame.reset_index()
        if "Date" not in frame.columns and len(frame.columns) > 0:
            frame = frame.rename(columns={frame.columns[0]: "Date"})

        if "Close" in frame.columns and frame["Close"].dropna().empty:
            raise ProviderFailure(
                f"Symbol not found or no close data for {resolved.canonical_symbol}",
                code=ERROR_SYMBOL_NOT_FOUND,
                provider=self.name,
                details={"symbol": resolved.canonical_symbol, "provider_symbol": resolved.yahoo_symbol},
                retryable=False,
            )

        return frame

    def get_latest_quote(self, symbol: str) -> dict[str, Any]:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=10)
        frame = self.get_historical_bars(symbol, start, end, interval="1d")
        if frame.empty:
            raise ProviderFailure(
                f"No quote data for {symbol}",
                code=ERROR_EMPTY_DATA,
                provider=self.name,
                details={"symbol": symbol},
            )

        date_col = "Date" if "Date" in frame.columns else frame.columns[0]
        frame = frame.sort_values(date_col).reset_index(drop=True)
        last = frame.iloc[-1]
        prev = frame.iloc[-2] if len(frame) > 1 else last
        price = float(last.get("Close", 0.0) or 0.0)
        prev_close = float(prev.get("Close", price) or price)
        change = price - prev_close
        change_pct = (change / prev_close * 100.0) if prev_close else 0.0

        resolved = self._resolver.resolve(symbol)
        return {
            "symbol": resolved.canonical_symbol,
            "price": round(price, 4),
            "prev_close": round(prev_close, 4),
            "change": round(change, 4),
            "change_pct": round(change_pct, 4),
            "timestamp": pd.to_datetime(last[date_col]).to_pydatetime().isoformat(),
            "provider": self.name,
        }

    def get_market_status(self, exchange: str) -> dict[str, Any]:
        return {
            "exchange": exchange,
            "status": "unknown",
            "provider": self.name,
            "message": "Yahoo provider does not publish exchange session state.",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def search_symbol(self, symbol: str) -> dict[str, Any]:
        resolved = self._resolver.resolve(symbol)
        return {
            "input_symbol": symbol,
            "canonical_symbol": resolved.canonical_symbol,
            "provider_symbol": resolved.yahoo_symbol,
            "exchange": resolved.exchange,
            "provider": self.name,
            "is_index": resolved.is_index,
        }
