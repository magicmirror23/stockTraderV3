# Price feed service
"""Live price feed adapter with replay mode for tests.

Provides a streaming interface for real-time price data.
In replay mode, reads from CSV files and streams with configurable speed.
Supports intraday tick simulation from OHLC candles for realistic streaming.
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import AsyncIterator

import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_WATCHLIST = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"]

# â”€â”€ Symbol categories for the Indian market â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
SYMBOL_CATEGORIES: dict[str, list[str]] = {
    "Indices": ["NIFTY50", "BANKNIFTY", "SENSEX"],
    "Banking": [
        "HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK",
        "INDUSINDBK", "BANKBARODA", "PNB",
    ],
    "IT": ["TCS", "INFY", "WIPRO", "HCLTECH", "TECHM"],
    "Oil & Gas": ["RELIANCE", "ONGC", "BPCL"],
    "Pharma": ["SUNPHARMA", "DIVISLAB", "DRREDDY", "CIPLA", "APOLLOHOSP"],
    "Auto": ["MARUTI", "EICHERMOT", "HEROMOTOCO", "M_M", "TATAMOTORS"],
    "Metals & Mining": ["TATASTEEL", "HINDALCO", "JSWSTEEL", "VEDL", "COALINDIA"],
    "FMCG": ["HINDUNILVR", "ITC", "NESTLEIND", "TATACONSUM"],
    "Finance": ["BAJFINANCE", "BAJAJFINSV", "SBILIFE", "HDFCLIFE", "JIOFIN"],
    "Infrastructure": ["LT", "ULTRACEMCO", "GRASIM", "POWERGRID", "NTPC", "ADANIENT"],
    "Consumer": ["TITAN", "ASIANPAINT", "TRENT", "IRCTC"],
}

# Reverse map: symbol -> category
SYMBOL_TO_CATEGORY: dict[str, str] = {}
for _cat, _syms in SYMBOL_CATEGORIES.items():
    for _s in _syms:
        SYMBOL_TO_CATEGORY[_s] = _cat


@dataclass
class PriceTick:
    symbol: str
    timestamp: datetime
    price: float
    volume: int
    bid: float | None = None
    ask: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    prev_close: float | None = None
    change: float | None = None
    change_pct: float | None = None


class PriceFeed:
    """Unified price feed supporting live and replay modes.

    Modes:
      - replay: Stream from CSV files with intraday tick simulation.
      - auto:   Try AngelOne live feed first, fall back to replay.
      - live:   Use AngelOne live feed only (error if unavailable).

    Data is auto-downloaded via yfinance when CSV files are missing or stale.
    """

    def __init__(self, mode: str = "auto", data_dir: str | Path = "storage/raw"):
        self._mode = mode
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._live_feed = None  # lazily initialized AngelLiveFeed

    # -- Auto-download helpers ---------------------------------------------------

    def _ensure_data(self, symbol: str) -> bool:
        """Make sure CSV data exists and is fresh for *symbol*. Downloads if needed."""
        try:
            from backend.services.data_downloader import ensure_symbol_data
            return ensure_symbol_data(symbol, self._data_dir)
        except Exception as exc:
            logger.debug("Auto-download failed for %s: %s", symbol, exc)
            return False

    def _ensure_data_multi(self, symbols: list[str]) -> None:
        """Ensure CSV data for multiple symbols (best-effort)."""
        for sym in symbols:
            self._ensure_data(sym)

    # â”€â”€ Live feed integration â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _get_live_feed(self):
        """Lazily create and return the AngelLiveFeed singleton."""
        if self._live_feed is None:
            try:
                from backend.services.angel_feed import AngelLiveFeed
                self._live_feed = AngelLiveFeed()
            except Exception:
                pass
        return self._live_feed

    @property
    def feed_mode(self) -> str:
        """Current active feed mode: 'live' or 'replay'."""
        if self._mode == "replay":
            return "replay"
        lf = self._get_live_feed()
        if lf and lf.is_connected:
            return "live"
        return "replay"

    @property
    def feed_status(self) -> dict:
        """Status of the live feed (or replay fallback)."""
        lf = self._get_live_feed()
        if lf:
            return {**lf.status, "feed_mode": self.feed_mode}
        return {"feed_mode": "replay", "available": False}

    def connect_live(self, symbols: list[str] | None = None) -> dict:
        """Attempt to connect to AngelOne SmartAPI live feed."""
        lf = self._get_live_feed()
        if not lf:
            return {"status": "error", "error": "AngelLiveFeed unavailable"}
        if not lf.is_available:
            return {"status": "unavailable", "error": "AngelOne credentials not set in .env"}
        # Use all known symbols if none specified
        syms = symbols or [s for cat in SYMBOL_CATEGORIES.values() for s in cat]
        ok = lf.connect(syms)
        return {**lf.status, "feed_mode": "live" if ok else "replay"}

    def disconnect_live(self) -> dict:
        """Disconnect the live feed and fall back to replay."""
        lf = self._get_live_feed()
        if lf:
            lf.disconnect()
            self._live_feed = None  # force re-creation next time
        return {"feed_mode": "replay"}

    def available_symbols(self) -> list[str]:
        """Return list of symbols that have CSV data."""
        return sorted(
            p.stem for p in self._data_dir.glob("*.csv") if p.stem != ".gitkeep"
        )

    @staticmethod
    def _generate_intraday_ticks(
        row, prev_close: float, symbol: str, n_ticks: int = 20
    ) -> list[PriceTick]:
        """Generate realistic intraday ticks from a single OHLC candle.

        Creates a price path: Open â†’ (random walk touching High/Low) â†’ Close.
        This simulates intraday movement within a daily candle.
        """
        o, h, l, c = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])
        volume = int(row.get("Volume", 0))
        base_date = row["Date"].to_pydatetime() if hasattr(row["Date"], "to_pydatetime") else row["Date"]

        # Market hours: 9:15 to 15:30 IST = 375 minutes
        market_minutes = 375
        interval = market_minutes / max(n_ticks, 1)

        # Build a price path: Open â†’ High â†’ Low â†’ Close (with some randomness)
        prices = []
        hit_high_first = random.random() > 0.5

        if hit_high_first:
            # Open â†’ High â†’ Low â†’ Close
            seg1 = max(1, n_ticks // 3)
            seg2 = max(1, n_ticks // 3)
            seg3 = n_ticks - seg1 - seg2
            for i in range(seg1):
                t = i / max(seg1 - 1, 1)
                prices.append(o + (h - o) * t + random.uniform(-0.2, 0.2) * (h - l) * 0.05)
            for i in range(seg2):
                t = i / max(seg2 - 1, 1)
                prices.append(h + (l - h) * t + random.uniform(-0.2, 0.2) * (h - l) * 0.05)
            for i in range(seg3):
                t = i / max(seg3 - 1, 1)
                prices.append(l + (c - l) * t + random.uniform(-0.2, 0.2) * (h - l) * 0.05)
        else:
            # Open â†’ Low â†’ High â†’ Close
            seg1 = max(1, n_ticks // 3)
            seg2 = max(1, n_ticks // 3)
            seg3 = n_ticks - seg1 - seg2
            for i in range(seg1):
                t = i / max(seg1 - 1, 1)
                prices.append(o + (l - o) * t + random.uniform(-0.2, 0.2) * (h - l) * 0.05)
            for i in range(seg2):
                t = i / max(seg2 - 1, 1)
                prices.append(l + (h - l) * t + random.uniform(-0.2, 0.2) * (h - l) * 0.05)
            for i in range(seg3):
                t = i / max(seg3 - 1, 1)
                prices.append(h + (c - h) * t + random.uniform(-0.2, 0.2) * (h - l) * 0.05)

        # Ensure first = open and last = close exactly, clamp within [low, high]
        prices[0] = o
        prices[-1] = c
        prices = [max(l, min(h, p)) for p in prices]

        ticks = []
        vol_per_tick = max(1, volume // n_ticks)
        for idx, price in enumerate(prices):
            ts = base_date.replace(hour=9, minute=15) + timedelta(minutes=interval * idx)
            price = round(price, 2)
            change = round(price - prev_close, 2)
            change_pct = round((change / prev_close * 100) if prev_close else 0.0, 2)
            spread = price * 0.0005  # tighter spread for realism
            # Add random volume variation
            tick_vol = max(1, int(vol_per_tick * random.uniform(0.3, 2.5)))
            ticks.append(PriceTick(
                symbol=symbol,
                timestamp=ts,
                price=price,
                volume=tick_vol,
                bid=round(price - spread, 2),
                ask=round(price + spread, 2),
                open=o,
                high=h,
                low=l,
                close=c,
                prev_close=round(prev_close, 2),
                change=change,
                change_pct=change_pct,
            ))
        return ticks

    async def _live_stream_single(
        self, symbol: str,
    ) -> AsyncIterator[PriceTick]:
        """Yield real-time ticks from AngelOne live feed for one symbol."""
        lf = self._get_live_feed()
        if not lf:
            return
        last_price = None
        while True:
            data = lf.get_latest(symbol)
            if data and data.get("price") != last_price:
                last_price = data["price"]
                try:
                    ts = datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
                except Exception:
                    ts = datetime.now()
                yield PriceTick(
                    symbol=symbol,
                    timestamp=ts,
                    price=data["price"],
                    volume=data.get("volume", 0),
                    bid=data.get("bid"),
                    ask=data.get("ask"),
                    open=data.get("open"),
                    high=data.get("high"),
                    low=data.get("low"),
                    close=data.get("close"),
                    prev_close=data.get("prev_close"),
                    change=data.get("change"),
                    change_pct=data.get("change_pct"),
                )
            await asyncio.sleep(0.2)  # 5 updates/sec max

    async def _live_stream_multi(
        self, symbols: list[str],
    ) -> AsyncIterator[PriceTick]:
        """Yield real-time ticks from AngelOne live feed for multiple symbols."""
        lf = self._get_live_feed()
        if not lf:
            return
        last_prices: dict[str, float] = {}
        while True:
            for sym in symbols:
                data = lf.get_latest(sym)
                if data and data.get("price") != last_prices.get(sym):
                    last_prices[sym] = data["price"]
                    try:
                        ts = datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
                    except Exception:
                        ts = datetime.now()
                    yield PriceTick(
                        symbol=sym,
                        timestamp=ts,
                        price=data["price"],
                        volume=data.get("volume", 0),
                        bid=data.get("bid"),
                        ask=data.get("ask"),
                        open=data.get("open"),
                        high=data.get("high"),
                        low=data.get("low"),
                        close=data.get("close"),
                        prev_close=data.get("prev_close"),
                        change=data.get("change"),
                        change_pct=data.get("change_pct"),
                    )
            await asyncio.sleep(0.15)

    async def stream(
        self,
        symbol: str,
        speed: float = 1.0,
        recent_days: int = 30,
    ) -> AsyncIterator[PriceTick]:
        """Stream price ticks for a symbol.

        Uses AngelOne live feed when connected, otherwise replays CSV data.
        """
        if self.feed_mode == "live":
            async for tick in self._live_stream_single(symbol):
                yield tick
        else:
            async for tick in self._replay_stream(symbol, speed, recent_days):
                yield tick

    async def stream_multi(
        self,
        symbols: list[str],
        speed: float = 10.0,
        recent_days: int = 30,
    ) -> AsyncIterator[PriceTick]:
        """Stream ticks for multiple symbols.

        Uses AngelOne live feed when connected, otherwise replays CSV data.
        """
        if self.feed_mode == "live":
            async for tick in self._live_stream_multi(symbols):
                yield tick
            return

        self._ensure_data_multi(symbols)
        frames: dict[str, pd.DataFrame] = {}
        for sym in symbols:
            csv_path = self._data_dir / f"{sym}.csv"
            if csv_path.exists():
                df = pd.read_csv(csv_path, parse_dates=["Date"])
                df = df.sort_values("Date").reset_index(drop=True)
                # Only use recent data
                if recent_days > 0 and len(df) > recent_days:
                    df = df.tail(recent_days).reset_index(drop=True)
                frames[sym] = df

        if not frames:
            return

        # Build intraday ticks for all symbols, then interleave by timestamp
        all_ticks: list[PriceTick] = []
        n_intraday = 15  # ticks per candle per symbol
        for sym, df in frames.items():
            for i in range(len(df)):
                row = df.iloc[i]
                prev_close = float(df.iloc[i - 1]["Close"]) if i > 0 else float(row["Open"])
                ticks = self._generate_intraday_ticks(row, prev_close, sym, n_intraday)
                all_ticks.extend(ticks)

        # Sort by timestamp for realistic interleaving
        all_ticks.sort(key=lambda t: t.timestamp)

        delay = max(0.01, 0.05 / speed)
        for tick in all_ticks:
            yield tick
            await asyncio.sleep(delay)

    async def _replay_stream(
        self,
        symbol: str,
        speed: float = 1.0,
        recent_days: int = 30,
    ) -> AsyncIterator[PriceTick]:
        """Replay historical data with intraday tick simulation."""
        self._ensure_data(symbol)
        csv_path = self._data_dir / f"{symbol}.csv"
        if not csv_path.exists():
            logger.warning("No data file for %s", symbol)
            return

        df = pd.read_csv(csv_path, parse_dates=["Date"])
        df = df.sort_values("Date").reset_index(drop=True)

        # Only replay recent data so prices match what users see online
        if recent_days > 0 and len(df) > recent_days:
            df = df.tail(recent_days).reset_index(drop=True)

        n_intraday = 25  # more ticks per candle for single-symbol for smoother chart
        delay = max(0.01, 0.08 / speed)

        for i in range(len(df)):
            row = df.iloc[i]
            prev_close = float(df.iloc[i - 1]["Close"]) if i > 0 else float(row["Open"])
            ticks = self._generate_intraday_ticks(row, prev_close, symbol, n_intraday)
            for tick in ticks:
                yield tick
                await asyncio.sleep(delay)

    def get_latest_price(self, symbol: str) -> PriceTick | None:
        """Get the most recent price for a symbol.

        Checks live feed first, falls back to CSV data.
        """
        # If live feed is connected, use real-time data
        if self.feed_mode == "live":
            lf = self._get_live_feed()
            data = lf.get_latest(symbol) if lf else None
            if data and data.get("price"):
                try:
                    ts = datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
                except Exception:
                    ts = datetime.now()
                return PriceTick(
                    symbol=symbol,
                    timestamp=ts,
                    price=data["price"],
                    volume=data.get("volume", 0),
                    bid=data.get("bid"),
                    ask=data.get("ask"),
                    open=data.get("open"),
                    high=data.get("high"),
                    low=data.get("low"),
                    close=data.get("close"),
                    prev_close=data.get("prev_close"),
                    change=data.get("change"),
                    change_pct=data.get("change_pct"),
                )

        # Fallback: CSV data (auto-download if missing/stale)
        self._ensure_data(symbol)
        csv_path = self._data_dir / f"{symbol}.csv"
        if not csv_path.exists():
            return None
        df = pd.read_csv(csv_path, parse_dates=["Date"])
        if df.empty:
            return None
        row = df.iloc[-1]
        prev_row = df.iloc[-2] if len(df) >= 2 else df.iloc[-1]
        price = float(row["Close"])
        prev_close = float(prev_row["Close"])
        change = price - prev_close
        change_pct = (change / prev_close * 100) if prev_close else 0.0
        spread = price * 0.001
        return PriceTick(
            symbol=symbol,
            timestamp=row["Date"].to_pydatetime(),
            price=price,
            volume=int(row.get("Volume", 0)),
            bid=round(price - spread / 2, 2),
            ask=round(price + spread / 2, 2),
            open=float(row["Open"]),
            high=float(row["High"]),
            low=float(row["Low"]),
            close=price,
            prev_close=round(prev_close, 2),
            change=round(change, 2),
            change_pct=round(change_pct, 2),
        )

    def get_watchlist_snapshot(self, symbols: list[str] | None = None) -> list[dict]:
        """Get latest prices for multiple symbols at once."""
        syms = symbols or self.available_symbols() or DEFAULT_WATCHLIST
        results = []
        for sym in syms:
            tick = self.get_latest_price(sym)
            if tick:
                results.append({
                    "symbol": tick.symbol,
                    "price": tick.price,
                    "open": tick.open,
                    "high": tick.high,
                    "low": tick.low,
                    "close": tick.close,
                    "prev_close": tick.prev_close,
                    "change": tick.change,
                    "change_pct": tick.change_pct,
                    "volume": tick.volume,
                    "bid": tick.bid,
                    "ask": tick.ask,
                    "timestamp": tick.timestamp.isoformat(),
                })
        return results

    def get_market_overview(self) -> dict:
        """Compute top gainers, losers, volume leaders from available data."""
        snapshot = self.get_watchlist_snapshot()
        if not snapshot:
            return {"gainers": [], "losers": [], "volume_leaders": [],
                    "indices": [], "categories": {}, "total_symbols": 0}

        # Separate indices from stocks
        index_names = {"NIFTY50", "BANKNIFTY", "SENSEX"}
        indices = [s for s in snapshot if s["symbol"] in index_names]
        stocks = [s for s in snapshot if s["symbol"] not in index_names]

        sorted_by_change = sorted(stocks, key=lambda x: x["change_pct"], reverse=True)
        gainers = [s for s in sorted_by_change if s["change_pct"] > 0][:10]
        losers = [s for s in reversed(sorted_by_change) if s["change_pct"] < 0][:10]
        volume_leaders = sorted(stocks, key=lambda x: x["volume"], reverse=True)[:10]

        # Group by category
        categories: dict[str, list[dict]] = {}
        for item in snapshot:
            cat = SYMBOL_TO_CATEGORY.get(item["symbol"], "Other")
            categories.setdefault(cat, []).append(item)

        return {
            "gainers": gainers,
            "losers": losers,
            "volume_leaders": volume_leaders,
            "indices": indices,
            "categories": {k: v for k, v in sorted(categories.items())},
            "total_symbols": len(snapshot),
        }

    def get_categories(self) -> dict:
        """Return symbol categories with availability info."""
        available = set(self.available_symbols())
        result = {}
        for cat, syms in SYMBOL_CATEGORIES.items():
            result[cat] = [
                {"symbol": s, "available": s in available}
                for s in syms
            ]
        return result

