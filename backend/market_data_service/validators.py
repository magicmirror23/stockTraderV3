"""OHLCV validation and normalization utilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from .errors import ProviderFailure, ERROR_EMPTY_DATA, ERROR_INVALID_RESPONSE


@dataclass(frozen=True)
class ValidationConfig:
    min_rows: int = 20


def _find_col(columns: list[str], aliases: list[str]) -> str | None:
    lowered = {c.lower(): c for c in columns}
    for alias in aliases:
        col = lowered.get(alias.lower())
        if col:
            return col
    return None


def normalize_ohlcv_frame(
    frame: pd.DataFrame,
    *,
    symbol: str,
    interval: str,
    source: str,
    min_rows: int = 20,
) -> pd.DataFrame:
    """Return normalized OHLCV dataframe with strict validation."""
    if frame is None or frame.empty:
        raise ProviderFailure(
            "Provider returned empty data.",
            code=ERROR_EMPTY_DATA,
            provider=source,
            details={"symbol": symbol},
            retryable=True,
        )

    df = frame.copy()
    cols = list(df.columns)

    ts_col = _find_col(cols, ["timestamp", "date", "datetime", "time"])
    open_col = _find_col(cols, ["open"])
    high_col = _find_col(cols, ["high"])
    low_col = _find_col(cols, ["low"])
    close_col = _find_col(cols, ["close", "adj close", "adjusted_close"])
    vol_col = _find_col(cols, ["volume", "vol"])

    if ts_col is None and len(df.columns) > 0:
        # Common yfinance shape where date is in index.
        if isinstance(df.index, pd.DatetimeIndex):
            df = df.reset_index()
            ts_col = df.columns[0]

    missing = []
    if ts_col is None:
        missing.append("timestamp")
    if open_col is None:
        missing.append("open")
    if high_col is None:
        missing.append("high")
    if low_col is None:
        missing.append("low")
    if close_col is None:
        missing.append("close")
    if vol_col is None:
        missing.append("volume")

    if missing:
        raise ProviderFailure(
            "Provider response missing required OHLCV columns.",
            code=ERROR_INVALID_RESPONSE,
            provider=source,
            details={"missing_columns": missing, "symbol": symbol},
            retryable=False,
        )

    out = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(df[ts_col], errors="coerce").dt.tz_localize(None),
            "open": pd.to_numeric(df[open_col], errors="coerce"),
            "high": pd.to_numeric(df[high_col], errors="coerce"),
            "low": pd.to_numeric(df[low_col], errors="coerce"),
            "close": pd.to_numeric(df[close_col], errors="coerce"),
            "volume": pd.to_numeric(df[vol_col], errors="coerce").fillna(0.0),
        }
    )

    out = out.dropna(subset=["timestamp", "open", "high", "low", "close"])
    out = out.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")

    # Price sanity checks.
    out = out[(out["open"] > 0) & (out["high"] > 0) & (out["low"] > 0) & (out["close"] > 0)]
    out = out[(out["high"] >= out["low"]) & (out["high"] >= out["open"]) & (out["high"] >= out["close"])]
    out = out[(out["low"] <= out["open"]) & (out["low"] <= out["close"])]

    if out.empty:
        raise ProviderFailure(
            "No valid rows after OHLCV validation.",
            code=ERROR_EMPTY_DATA,
            provider=source,
            details={"symbol": symbol},
            retryable=True,
        )

    if len(out) < max(1, int(min_rows)):
        raise ProviderFailure(
            f"Only {len(out)} rows available; minimum {min_rows} required.",
            code=ERROR_EMPTY_DATA,
            provider=source,
            details={"symbol": symbol, "rows": len(out), "min_rows": int(min_rows)},
            retryable=True,
        )

    out["symbol"] = symbol
    out["interval"] = interval
    out["source"] = source
    return out.reset_index(drop=True)


def frame_to_api_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    out = frame.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"]).dt.strftime("%Y-%m-%dT%H:%M:%S")
    return out.to_dict(orient="records")
