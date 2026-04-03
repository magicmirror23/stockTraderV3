"""Historical data loader — bulk-loads OHLCV from CSV / provider API.

Used during training-data preparation and nightly refreshes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from app.core.config import settings

logger = logging.getLogger(__name__)


def load_ohlcv_from_csv(
    symbol: str,
    start: datetime | None = None,
    end: datetime | None = None,
    data_dir: str | None = None,
) -> pd.DataFrame:
    """Load OHLCV from a local CSV file.

    Expected CSV columns: Date, Open, High, Low, Close, Volume
    Returns a DataFrame indexed by datetime with lowercase columns.
    """
    base = Path(data_dir or "storage/raw")
    candidates = [
        base / f"{symbol}.csv",
        base / f"{symbol}.NS.csv",
    ]
    csv_path = next((p for p in candidates if p.exists()), None)
    if csv_path is None:
        logger.warning("No CSV found for %s in %s", symbol, base)
        return pd.DataFrame()

    df = pd.read_csv(csv_path, parse_dates=["Date"])
    df.rename(columns=str.lower, inplace=True)
    df.set_index("date", inplace=True)
    df.sort_index(inplace=True)

    if start:
        df = df[df.index >= pd.Timestamp(start)]
    if end:
        df = df[df.index <= pd.Timestamp(end)]

    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        logger.warning("CSV for %s missing columns: %s", symbol, missing)

    return df


def load_ohlcv_from_provider(
    symbol: str,
    start: datetime,
    end: datetime,
    interval: str = "1d",
) -> pd.DataFrame:
    """Fetch OHLCV via the configured market-data provider."""
    from app.providers.factory import get_provider

    provider = get_provider()
    bars = provider.get_historical(symbol, start, end, interval)
    if not bars:
        return pd.DataFrame()

    records = [
        {
            "date": b.timestamp,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": b.volume,
        }
        for b in bars
    ]
    df = pd.DataFrame(records).set_index("date").sort_index()
    return df


def load_multi_ticker(
    tickers: list[str] | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    prefer_csv: bool = True,
) -> dict[str, pd.DataFrame]:
    """Load OHLCV for multiple tickers. Returns {symbol: DataFrame}."""
    tickers = tickers or settings.DEFAULT_TICKERS
    if start is None:
        start = datetime.now(timezone.utc) - timedelta(days=settings.TRAIN_LOOKBACK_DAYS)
    if end is None:
        end = datetime.now(timezone.utc)

    result: dict[str, pd.DataFrame] = {}
    for sym in tickers:
        df = pd.DataFrame()
        if prefer_csv:
            df = load_ohlcv_from_csv(sym, start, end)
        if df.empty:
            df = load_ohlcv_from_provider(sym, start, end)
        if not df.empty:
            result[sym] = df
        else:
            logger.warning("No data for %s", sym)

    logger.info("Loaded %d / %d tickers", len(result), len(tickers))
    return result
