# Data downloader service
"""Auto-download and keep NSE stock CSV data up-to-date via yfinance."""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from backend.prediction_engine.data_pipeline.connector_yahoo import YahooConnector
from backend.prediction_engine.data_pipeline.providers import SymbolMapper, ProviderError

logger = logging.getLogger(__name__)

# NSE symbols need .NS suffix for yfinance (indices use different tickers)
_YF_INDEX_MAP: dict[str, str] = {
    "NIFTY50": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "SENSEX": "^BSESN",
}

# Symbols that use .BO (BSE) instead of .NS
_YF_BSE_SYMBOLS: set[str] = {"SENSEX"}
_YF_SYMBOL_OVERRIDES: dict[str, str] = {
    "BAJAJ_AUTO": "BAJAJ-AUTO",
    "M_M": "M&M",
}

STORAGE_DIR = Path(__file__).resolve().parents[2] / "storage" / "raw"
HISTORY_YEARS = 2  # download 2 years of daily data
STALE_HOURS = 18   # re-download if CSV is older than 18 hours


def _yf_ticker(symbol: str) -> str:
    """Convert internal symbol name to yfinance ticker."""
    mapper = SymbolMapper()
    return mapper.to_yahoo(symbol)


def _is_stale(csv_path: Path, max_age_hours: float = STALE_HOURS) -> bool:
    """Check if a CSV file is missing or older than max_age_hours."""
    if not csv_path.exists():
        return True
    mtime = datetime.fromtimestamp(csv_path.stat().st_mtime)
    return (datetime.now() - mtime) > timedelta(hours=max_age_hours)


def download_symbol(symbol: str, data_dir: Path = STORAGE_DIR, period_years: int = HISTORY_YEARS) -> bool:
    """Download daily OHLCV data for a single symbol and save as CSV.

    Returns True if data was saved successfully.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    csv_path = data_dir / f"{symbol}.csv"

    ticker_str = _yf_ticker(symbol)
    try:
        end = datetime.now()
        start = end - timedelta(days=period_years * 365)
        connector = YahooConnector(
            max_retries=int(os.getenv("YF_DOWNLOAD_MAX_RETRIES", "2")),
            retry_delay_s=float(os.getenv("YF_DOWNLOAD_RETRY_DELAY_S", "1.5")),
        )
        df = connector.fetch(
            symbol,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
        )

        if df is None or df.empty:
            logger.warning("No data returned for %s (%s)", symbol, ticker_str)
            return False

        # Strip timezone info for consistency
        df["Date"] = pd.to_datetime(df["Date"]).dt.tz_localize(None)

        # Keep only the columns we need
        keep_cols = ["Date", "Open", "High", "Low", "Close", "Volume"]
        available = [c for c in keep_cols if c in df.columns]
        df = df[available]

        # Drop rows with NaN prices
        df = df.dropna(subset=["Close"])

        if df.empty:
            logger.warning("Empty dataframe after cleanup for %s", symbol)
            return False

        df.to_csv(csv_path, index=False)
        logger.info("Downloaded %d rows for %s -> %s", len(df), symbol, csv_path)
        return True

    except ProviderError as e:
        logger.error("Provider error downloading %s (%s): %s | details=%s", symbol, ticker_str, e, e.details)
        return False
    except Exception as e:
        logger.error("Failed to download %s (%s): %s", symbol, ticker_str, e)
        return False


def ensure_symbol_data(symbol: str, data_dir: Path = STORAGE_DIR) -> bool:
    """Download data for a symbol if missing or stale. Returns True if data is available."""
    csv_path = data_dir / f"{symbol}.csv"
    if not _is_stale(csv_path):
        return True
    return download_symbol(symbol, data_dir)


def refresh_all_symbols(
    symbols: list[str],
    data_dir: Path = STORAGE_DIR,
    force: bool = False,
) -> dict[str, bool]:
    """Download/refresh data for all given symbols.

    Only downloads if CSV is missing or stale (unless force=True).
    Returns dict of {symbol: success_bool}.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, bool] = {}
    consecutive_failures = 0
    max_consecutive_failures = int(os.getenv("DATA_REFRESH_MAX_CONSEC_FAILS", "8"))
    request_pause_s = float(os.getenv("DATA_REFRESH_REQUEST_PAUSE_S", "0.8"))
    fail_pause_s = float(os.getenv("DATA_REFRESH_FAIL_PAUSE_S", "2.0"))

    for idx, symbol in enumerate(symbols):
        if max_consecutive_failures > 0 and consecutive_failures >= max_consecutive_failures:
            logger.warning(
                "Stopping batch refresh after %d consecutive failures to avoid provider hammering",
                consecutive_failures,
            )
            # Mark remaining symbols as failed (not attempted) so callers can inspect.
            for leftover in symbols[idx:]:
                results[leftover] = False
            break

        csv_path = data_dir / f"{symbol}.csv"
        if not force and not _is_stale(csv_path):
            results[symbol] = True
            logger.debug("Skipping %s — CSV is fresh", symbol)
            consecutive_failures = 0
            continue
        ok = download_symbol(symbol, data_dir)
        results[symbol] = ok
        if ok:
            consecutive_failures = 0
            time.sleep(max(0.0, request_pause_s))
        else:
            consecutive_failures += 1
            time.sleep(max(0.0, fail_pause_s))

    ok = sum(1 for v in results.values() if v)
    logger.info("Refreshed %d/%d symbols successfully", ok, len(results))
    return results


def get_all_symbols() -> list[str]:
    """Return all tracked symbols: predefined categories + any user-added CSVs."""
    from backend.services.price_feed import SYMBOL_CATEGORIES
    all_syms: list[str] = []
    for syms in SYMBOL_CATEGORIES.values():
        all_syms.extend(syms)

    # Also include any user-added symbols that have CSV data on disk
    try:
        for csv_path in STORAGE_DIR.glob("*.csv"):
            sym = csv_path.stem
            if sym and sym != ".gitkeep":
                all_syms.append(sym)
    except OSError:
        pass

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for s in all_syms:
        if s not in seen:
            seen.add(s)
            unique.append(s)
    return unique


# ---------- Background refresh thread ----------

_bg_thread: threading.Thread | None = None
_bg_stop = threading.Event()


def start_background_refresh(
    interval_hours: float = 6.0,
    data_dir: Path = STORAGE_DIR,
) -> None:
    """Start a daemon thread that refreshes all symbol data periodically."""
    global _bg_thread

    if _bg_thread is not None and _bg_thread.is_alive():
        logger.info("Background refresh already running")
        return

    _bg_stop.clear()
    interval_sec = interval_hours * 3600

    def _worker():
        logger.info("Background data refresh thread started (interval=%.1fh)", interval_hours)
        while not _bg_stop.is_set():
            try:
                symbols = get_all_symbols()
                refresh_all_symbols(symbols, data_dir)
            except Exception as e:
                logger.error("Background refresh error: %s", e)
            _bg_stop.wait(timeout=interval_sec)
        logger.info("Background data refresh thread stopped")

    _bg_thread = threading.Thread(target=_worker, name="data-refresh", daemon=True)
    _bg_thread.start()


def stop_background_refresh() -> None:
    """Signal the background refresh thread to stop."""
    _bg_stop.set()
