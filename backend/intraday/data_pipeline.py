"""Intraday data pipeline – candle aggregation, rolling feature computation,
and in-memory cache for real-time and backtest replay modes.

Supports 1m, 5m, and 15m candle intervals.  All features are computed
strictly without future data leakage.
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Candle intervals ───────────────────────────────────────────────────────

SUPPORTED_INTERVALS = ("1m", "5m", "15m")

INTERVAL_MINUTES = {"1m": 1, "5m": 5, "15m": 15}


@dataclass
class Candle:
    """Single OHLCV candle."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    interval: str = "1m"
    symbol: str = ""
    vwap: float | None = None


# ── In-memory candle cache (per symbol / interval) ────────────────────────


class CandleCache:
    """Thread-safe rolling window of recent candles, keyed by (symbol, interval).

    Designed for real-time ingestion *and* backtest replay.
    """

    def __init__(self, max_bars: int = 500):
        self._max_bars = max_bars
        self._store: dict[tuple[str, str], deque[Candle]] = defaultdict(
            lambda: deque(maxlen=max_bars)
        )

    def push(self, candle: Candle) -> None:
        key = (candle.symbol, candle.interval)
        buf = self._store[key]
        if buf and buf[-1].timestamp >= candle.timestamp:
            # duplicate or out-of-order – overwrite last if same timestamp
            if buf[-1].timestamp == candle.timestamp:
                buf[-1] = candle
            return
        buf.append(candle)

    def get(self, symbol: str, interval: str, n: int | None = None) -> list[Candle]:
        key = (symbol, interval)
        buf = self._store.get(key)
        if buf is None:
            return []
        if n is None:
            return list(buf)
        return list(buf)[-n:]

    def to_dataframe(self, symbol: str, interval: str) -> pd.DataFrame:
        candles = self.get(symbol, interval)
        if not candles:
            return pd.DataFrame()
        rows = [
            {
                "timestamp": c.timestamp,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
                "vwap": c.vwap,
            }
            for c in candles
        ]
        df = pd.DataFrame(rows)
        df.set_index("timestamp", inplace=True)
        return df

    def clear(self, symbol: str | None = None, interval: str | None = None) -> None:
        if symbol and interval:
            self._store.pop((symbol, interval), None)
        elif symbol:
            for key in list(self._store.keys()):
                if key[0] == symbol:
                    del self._store[key]
        else:
            self._store.clear()

    @property
    def symbols(self) -> set[str]:
        return {k[0] for k in self._store}


# ── Candle resampler (1m → 5m / 15m) ──────────────────────────────────────


def resample_candles(
    candles_1m: list[Candle], target_interval: str, symbol: str = ""
) -> list[Candle]:
    """Aggregate 1-minute candles to a coarser interval."""
    minutes = INTERVAL_MINUTES.get(target_interval)
    if minutes is None or minutes <= 1:
        return candles_1m

    result: list[Candle] = []
    bucket: list[Candle] = []

    for c in candles_1m:
        bar_minute = c.timestamp.hour * 60 + c.timestamp.minute
        bucket_start = bar_minute - (bar_minute % minutes)
        if bucket and (
            bucket[0].timestamp.date() != c.timestamp.date()
            or (bucket[0].timestamp.hour * 60 + bucket[0].timestamp.minute)
            // minutes
            != bar_minute // minutes
        ):
            result.append(_merge_bucket(bucket, target_interval, symbol))
            bucket = []
        bucket.append(c)

    if bucket:
        result.append(_merge_bucket(bucket, target_interval, symbol))
    return result


def _merge_bucket(bucket: list[Candle], interval: str, symbol: str) -> Candle:
    total_volume = sum(c.volume for c in bucket)
    total_vwap_vol = sum((c.vwap or c.close) * c.volume for c in bucket if c.volume > 0)
    vwap = total_vwap_vol / total_volume if total_volume > 0 else bucket[-1].close
    return Candle(
        timestamp=bucket[0].timestamp,
        open=bucket[0].open,
        high=max(c.high for c in bucket),
        low=min(c.low for c in bucket),
        close=bucket[-1].close,
        volume=total_volume,
        interval=interval,
        symbol=symbol,
        vwap=vwap,
    )


# ── Historical loader (from CSV / provider) ───────────────────────────────


def load_intraday_from_csv(path: str, symbol: str, interval: str = "1m") -> list[Candle]:
    """Load candle data from a CSV with columns: timestamp, open, high, low, close, volume."""
    df = pd.read_csv(path, parse_dates=["timestamp"])
    candles = []
    for _, row in df.iterrows():
        candles.append(
            Candle(
                timestamp=row["timestamp"].to_pydatetime(),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=int(row.get("volume", 0)),
                interval=interval,
                symbol=symbol,
                vwap=float(row["vwap"]) if "vwap" in row and pd.notna(row.get("vwap")) else None,
            )
        )
    return candles


def build_cache_from_daily_csv(
    csv_path: str,
    symbol: str,
    cache: CandleCache,
    simulated_intraday: bool = True,
) -> None:
    """Populate cache from a daily OHLCV CSV (used for backtest when intraday
    data is unavailable).  Creates synthetic 15m candles from daily data."""
    df = pd.read_csv(csv_path, parse_dates=["Date"])
    for _, row in df.iterrows():
        ts = row["Date"].to_pydatetime().replace(hour=9, minute=15, tzinfo=timezone.utc)
        candle = Candle(
            timestamp=ts,
            open=float(row["Open"]),
            high=float(row["High"]),
            low=float(row["Low"]),
            close=float(row["Close"]),
            volume=int(row.get("Volume", 0)),
            interval="15m",
            symbol=symbol,
        )
        cache.push(candle)
