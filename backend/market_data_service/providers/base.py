"""Provider contracts for market-data-service."""

from __future__ import annotations

import abc
from datetime import datetime
from typing import Any

import pandas as pd


class MarketDataProvider(abc.ABC):
    name = "base"

    @abc.abstractmethod
    def get_historical_bars(
        self,
        symbol: str,
        start_date: str | datetime,
        end_date: str | datetime,
        interval: str,
    ) -> pd.DataFrame:
        raise NotImplementedError

    @abc.abstractmethod
    def get_latest_quote(self, symbol: str) -> dict[str, Any]:
        raise NotImplementedError

    @abc.abstractmethod
    def get_market_status(self, exchange: str) -> dict[str, Any]:
        raise NotImplementedError

    @abc.abstractmethod
    def search_symbol(self, symbol: str) -> dict[str, Any]:
        raise NotImplementedError

    def supports_historical(self) -> bool:
        return True
