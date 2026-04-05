"""NSE enrichment provider (metadata, market status, symbol search scaffolding)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from backend.services.market_hours import get_market_status, MarketPhase

from ..errors import ProviderFailure, ERROR_PROVIDER_UNAVAILABLE
from ..symbols import SymbolResolver
from .base import MarketDataProvider


class NSEEnrichmentProvider(MarketDataProvider):
    name = "nse_enrichment"

    def __init__(self, resolver: SymbolResolver | None = None) -> None:
        self._resolver = resolver or SymbolResolver()

    def supports_historical(self) -> bool:
        # Enrichment provider is metadata-first; no OHLC bootstrap yet.
        return False

    def get_historical_bars(
        self,
        symbol: str,
        start_date: str | datetime,
        end_date: str | datetime,
        interval: str,
    ) -> pd.DataFrame:
        raise ProviderFailure(
            "NSE enrichment provider does not supply OHLC historical bars.",
            code=ERROR_PROVIDER_UNAVAILABLE,
            provider=self.name,
            retryable=False,
        )

    def get_latest_quote(self, symbol: str) -> dict[str, Any]:
        raise ProviderFailure(
            "NSE enrichment provider quote endpoint not enabled.",
            code=ERROR_PROVIDER_UNAVAILABLE,
            provider=self.name,
            retryable=False,
        )

    def get_market_status(self, exchange: str) -> dict[str, Any]:
        status = get_market_status()
        phase_to_status = {
            MarketPhase.OPEN: "open",
            MarketPhase.PRE_OPEN: "pre_open",
            MarketPhase.CLOSED: "closed",
        }
        return {
            "exchange": exchange,
            "status": phase_to_status.get(status.phase, "closed"),
            "phase": status.phase.value,
            "message": status.message,
            "next_event": status.next_event,
            "next_event_time": status.next_event_time,
            "seconds_to_next": status.seconds_to_next,
            "provider": self.name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def search_symbol(self, symbol: str) -> dict[str, Any]:
        resolved = self._resolver.resolve(symbol)
        return {
            "input_symbol": symbol,
            "canonical_symbol": resolved.canonical_symbol,
            "exchange": resolved.exchange,
            "provider": self.name,
            "metadata": {
                "supports_options_enrichment": True,
                "supports_market_breadth": True,
                "supports_index_metadata": True,
            },
        }

    def index_metadata(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        return {
            "provider": self.name,
            "timestamp": now,
            "indices": [
                {"symbol": "NIFTY50", "name": "NIFTY 50", "exchange": "NSE"},
                {"symbol": "BANKNIFTY", "name": "NIFTY BANK", "exchange": "NSE"},
                {"symbol": "SENSEX", "name": "SENSEX", "exchange": "BSE"},
            ],
            "market_breadth": {
                "advances": None,
                "declines": None,
                "unchanged": None,
                "note": "Wire NSE breadth feed for live values.",
            },
        }
