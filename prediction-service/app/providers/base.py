"""Abstract base for market-data providers.

Every concrete provider (Angel One, Yahoo, mock) implements this protocol.
Business logic NEVER imports a concrete provider directly – only through
``app.providers.factory.get_provider()``.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class OHLCV:
    """Single daily / intraday bar."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    symbol: str = ""


@dataclass
class Tick:
    """Level-1 market tick."""

    symbol: str
    timestamp: datetime
    price: float
    volume: int = 0
    bid: float | None = None
    ask: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None


@dataclass
class OptionChainRow:
    """Single row from an option chain."""

    symbol: str
    expiry: datetime
    strike: float
    option_type: str  # "CE" | "PE"
    ltp: float = 0.0
    open_interest: int = 0
    change_in_oi: int = 0
    volume: int = 0
    iv: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    bid: float | None = None
    ask: float | None = None


@dataclass
class OptionChain:
    """Complete option chain for an underlying."""

    underlying: str
    underlying_price: float
    timestamp: datetime
    rows: list[OptionChainRow] = field(default_factory=list)
    expiries: list[datetime] = field(default_factory=list)


class MarketDataProvider(abc.ABC):
    """Protocol that all data providers must implement."""

    # ── Identity ─────────────────────────────────────────────────────
    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Human-readable provider name."""

    @property
    @abc.abstractmethod
    def is_available(self) -> bool:
        """True if credentials are configured and provider is reachable."""

    # ── Historical data ──────────────────────────────────────────────
    @abc.abstractmethod
    def get_historical(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: str = "1d",
    ) -> list[OHLCV]:
        """Fetch historical bars.  *interval* can be 1d, 1h, 5m etc."""

    # ── Live / real-time ─────────────────────────────────────────────
    @abc.abstractmethod
    def get_ltp(self, symbols: list[str]) -> dict[str, Tick]:
        """Get latest traded price / tick for one or more symbols."""

    # ── Option chains ────────────────────────────────────────────────
    @abc.abstractmethod
    def get_option_chain(self, symbol: str, expiry: datetime | None = None) -> OptionChain | None:
        """Fetch the full option chain for an underlying."""

    # ── Macro / cross-asset ──────────────────────────────────────────
    def get_index_value(self, index_symbol: str) -> Tick | None:
        """Return the latest value for an index like ^NSEI, ^VIX."""
        ticks = self.get_ltp([index_symbol])
        return ticks.get(index_symbol)

    # ── Connection lifecycle ─────────────────────────────────────────
    def connect(self) -> bool:
        """Establish live connection (e.g. WebSocket).  Returns success."""
        return True

    def disconnect(self) -> None:
        """Tear down live connections."""

    def health_check(self) -> dict[str, Any]:
        """Return provider health / status dict."""
        return {"provider": self.name, "available": self.is_available}
