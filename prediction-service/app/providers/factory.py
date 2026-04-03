"""Provider factory — returns the configured MarketDataProvider.

Never import a concrete provider in business logic. Use::

    from app.providers.factory import get_provider
    provider = get_provider()
"""

from __future__ import annotations

import logging
from functools import lru_cache

from app.core.config import settings
from app.providers.base import MarketDataProvider

logger = logging.getLogger(__name__)


class YahooProvider(MarketDataProvider):
    """yfinance-backed provider for development / fallback."""

    @property
    def name(self) -> str:
        return "yahoo"

    @property
    def is_available(self) -> bool:
        try:
            import yfinance  # noqa: F401
            return True
        except ImportError:
            return False

    def get_historical(self, symbol, start, end, interval="1d"):
        import yfinance as yf
        from app.providers.base import OHLCV

        ticker_str = f"{symbol}.NS" if not symbol.startswith("^") and "=" not in symbol else symbol
        try:
            df = yf.Ticker(ticker_str).history(
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                interval=interval if interval in ("1d", "1h", "5m") else "1d",
            )
            if df is None or df.empty:
                return []
            bars = []
            for ts, row in df.iterrows():
                bars.append(OHLCV(
                    timestamp=ts.to_pydatetime(),
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=int(row.get("Volume", 0)),
                    symbol=symbol,
                ))
            return bars
        except Exception as exc:
            logger.warning("Yahoo fetch for %s failed: %s", symbol, exc)
            return []

    def get_ltp(self, symbols):
        import yfinance as yf
        from datetime import datetime, timezone
        from app.providers.base import Tick

        result = {}
        for sym in symbols:
            ticker_str = f"{sym}.NS" if not sym.startswith("^") and "=" not in sym else sym
            try:
                info = yf.Ticker(ticker_str).fast_info
                price = getattr(info, "last_price", None) or 0.0
                result[sym] = Tick(
                    symbol=sym,
                    timestamp=datetime.now(timezone.utc),
                    price=float(price),
                )
            except Exception:
                pass
        return result

    def get_option_chain(self, symbol, expiry=None):
        return None


class MockProvider(MarketDataProvider):
    """In-memory test provider with synthetic data."""

    @property
    def name(self) -> str:
        return "mock"

    @property
    def is_available(self) -> bool:
        return True

    def get_historical(self, symbol, start, end, interval="1d"):
        import random
        from datetime import timedelta
        from app.providers.base import OHLCV

        bars = []
        price = 1000.0
        current = start
        while current <= end:
            if current.weekday() < 5:
                change = random.gauss(0, price * 0.015)
                o = price
                c = price + change
                h = max(o, c) + abs(random.gauss(0, price * 0.005))
                l = min(o, c) - abs(random.gauss(0, price * 0.005))
                vol = random.randint(100_000, 5_000_000)
                bars.append(OHLCV(
                    timestamp=current, open=round(o, 2), high=round(h, 2),
                    low=round(l, 2), close=round(c, 2), volume=vol, symbol=symbol,
                ))
                price = c
            current += timedelta(days=1)
        return bars

    def get_ltp(self, symbols):
        from datetime import datetime, timezone
        from app.providers.base import Tick
        import random

        return {
            sym: Tick(symbol=sym, timestamp=datetime.now(timezone.utc),
                      price=round(random.uniform(500, 5000), 2))
            for sym in symbols
        }

    def get_option_chain(self, symbol, expiry=None):
        return None


@lru_cache(maxsize=1)
def get_provider() -> MarketDataProvider:
    """Return the configured market data provider instance."""
    name = settings.DATA_PROVIDER.lower()

    if name == "angel_one":
        from app.providers.angel_one import AngelOneProvider
        p = AngelOneProvider()
        if p.is_available:
            logger.info("Using Angel One provider")
            return p
        logger.warning("Angel One credentials missing, falling back to Yahoo")
        return YahooProvider()

    if name == "yahoo":
        return YahooProvider()

    if name == "mock":
        return MockProvider()

    logger.warning("Unknown provider '%s', using Yahoo", name)
    return YahooProvider()
