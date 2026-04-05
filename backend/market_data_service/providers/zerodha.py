"""Zerodha Kite provider interface stub for future live integration."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from ..errors import ProviderFailure, ERROR_PROVIDER_UNAVAILABLE
from .base import MarketDataProvider


class ZerodhaKiteProvider(MarketDataProvider):
    name = "zerodha_kite"

    def _not_ready(self, method: str) -> ProviderFailure:
        return ProviderFailure(
            f"ZerodhaKiteProvider.{method} is not implemented yet.",
            code=ERROR_PROVIDER_UNAVAILABLE,
            provider=self.name,
            retryable=False,
            details={"method": method, "action": "implement_kite_adapter"},
        )

    def get_historical_bars(
        self,
        symbol: str,
        start_date: str | datetime,
        end_date: str | datetime,
        interval: str,
    ) -> pd.DataFrame:
        raise self._not_ready("get_historical_bars")

    def get_latest_quote(self, symbol: str) -> dict[str, Any]:
        raise self._not_ready("get_latest_quote")

    def get_market_status(self, exchange: str) -> dict[str, Any]:
        raise self._not_ready("get_market_status")

    def search_symbol(self, symbol: str) -> dict[str, Any]:
        raise self._not_ready("search_symbol")
