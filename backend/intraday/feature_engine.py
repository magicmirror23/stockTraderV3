"""Intraday feature engine – computes rolling features from candle data
strictly without future data leakage.

Feature groups:
  returns       – ret_1m, ret_3m, ret_5m, ret_15m
  volatility    – realized_vol_5, realized_vol_15, intraday_atr
  trend         – trend_persistence, ema_slope
  volume        – volume_spike, volume_zscore, volume_ratio
  structure     – distance_from_vwap, opening_range_break, gap_from_prev_close
  context       – nifty_intraday_return, sector_intraday_strength, market_breadth
  liquidity     – spread_estimate, slippage_estimate, trade_volume_proxy
  time          – minutes_since_open, minutes_to_close
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# NSE market hours (IST)
MARKET_OPEN_MIN = 9 * 60 + 15   # 09:15
MARKET_CLOSE_MIN = 15 * 60 + 30  # 15:30
TRADING_DAY_MINUTES = MARKET_CLOSE_MIN - MARKET_OPEN_MIN  # 375


def compute_intraday_features(
    df: pd.DataFrame,
    *,
    nifty_df: pd.DataFrame | None = None,
    sector_df: pd.DataFrame | None = None,
    market_breadth_df: pd.DataFrame | None = None,
    prev_close: float | None = None,
) -> pd.DataFrame:
    """Compute a full intraday feature matrix from a candle DataFrame.

    Parameters
    ----------
    df : pd.DataFrame
        Must have columns: open, high, low, close, volume.
        Index should be a DatetimeIndex (or column ``timestamp``).
    nifty_df : optional
        Nifty index candle DataFrame for context features.
    sector_df : optional
        Sector index candle DataFrame for sector strength.
    market_breadth_df : optional
        Breadth data (advancers / decliners).
    prev_close : optional
        Previous day's closing price for gap calculation.

    Returns
    -------
    pd.DataFrame with one row per candle and all intraday features.
    """
    if df.empty:
        return pd.DataFrame()

    feat = pd.DataFrame(index=df.index)

    # ── Returns ────────────────────────────────────────────────────────
    feat["ret_1m"] = df["close"].pct_change(1)
    feat["ret_3m"] = df["close"].pct_change(3)
    feat["ret_5m"] = df["close"].pct_change(5)
    feat["ret_15m"] = df["close"].pct_change(15)

    # ── Volatility ─────────────────────────────────────────────────────
    log_ret = np.log(df["close"] / df["close"].shift(1))
    feat["realized_vol_5"] = log_ret.rolling(5, min_periods=2).std() * np.sqrt(5)
    feat["realized_vol_15"] = log_ret.rolling(15, min_periods=5).std() * np.sqrt(15)

    tr = pd.DataFrame(
        {
            "hl": df["high"] - df["low"],
            "hc": (df["high"] - df["close"].shift(1)).abs(),
            "lc": (df["low"] - df["close"].shift(1)).abs(),
        }
    )
    true_range = tr.max(axis=1)
    feat["intraday_atr"] = true_range.rolling(14, min_periods=5).mean()

    # ── Trend ──────────────────────────────────────────────────────────
    # trend persistence: fraction of positive returns in last N bars
    pos_ret = (log_ret > 0).astype(float)
    feat["trend_persistence"] = pos_ret.rolling(10, min_periods=3).mean()

    ema_short = df["close"].ewm(span=8, min_periods=3).mean()
    ema_long = df["close"].ewm(span=21, min_periods=8).mean()
    feat["ema_slope"] = (ema_short - ema_long) / ema_long

    # ── Volume ─────────────────────────────────────────────────────────
    vol_mean = df["volume"].rolling(20, min_periods=5).mean()
    vol_std = df["volume"].rolling(20, min_periods=5).std()
    feat["volume_spike"] = (df["volume"] / vol_mean.clip(lower=1)).clip(upper=10)
    feat["volume_zscore"] = ((df["volume"] - vol_mean) / vol_std.clip(lower=1)).clip(-5, 5)
    feat["volume_ratio"] = df["volume"] / vol_mean.clip(lower=1)

    # ── Market structure ───────────────────────────────────────────────
    if "vwap" in df.columns and df["vwap"].notna().any():
        feat["distance_from_vwap"] = (df["close"] - df["vwap"]) / df["vwap"]
    else:
        # approximate VWAP from cumulative volume-weighted price
        cum_vol = df["volume"].cumsum()
        cum_vwap = (df["close"] * df["volume"]).cumsum() / cum_vol.clip(lower=1)
        feat["distance_from_vwap"] = (df["close"] - cum_vwap) / cum_vwap.clip(lower=0.01)

    # Opening range break (first 15 bars = first 15 minutes of 1m data)
    feat["opening_range_break"] = 0.0
    if len(df) >= 15:
        or_high = df["high"].iloc[:15].max()
        or_low = df["low"].iloc[:15].min()
        or_range = or_high - or_low if or_high > or_low else 1.0
        feat["opening_range_break"] = (
            (df["close"] - or_high) / or_range
        ).clip(-3, 3)

    if prev_close is not None and prev_close > 0:
        feat["gap_from_prev_close"] = (df["open"].iloc[0] - prev_close) / prev_close
    else:
        feat["gap_from_prev_close"] = 0.0

    # ── Market context ─────────────────────────────────────────────────
    if nifty_df is not None and not nifty_df.empty and "close" in nifty_df.columns:
        nifty_ret = nifty_df["close"].pct_change(5)
        feat["nifty_intraday_return"] = nifty_ret.reindex(feat.index, method="ffill").fillna(0)
    else:
        feat["nifty_intraday_return"] = 0.0

    if sector_df is not None and not sector_df.empty and "close" in sector_df.columns:
        sector_ret = sector_df["close"].pct_change(5)
        feat["sector_intraday_strength"] = sector_ret.reindex(feat.index, method="ffill").fillna(0)
    else:
        feat["sector_intraday_strength"] = 0.0

    if market_breadth_df is not None and not market_breadth_df.empty:
        feat["market_breadth"] = market_breadth_df.reindex(feat.index, method="ffill").fillna(0.5)
    else:
        feat["market_breadth"] = 0.5

    # ── Liquidity ──────────────────────────────────────────────────────
    # spread estimate from high-low / close
    feat["spread_estimate"] = (df["high"] - df["low"]) / df["close"].clip(lower=0.01)
    feat["slippage_estimate"] = feat["spread_estimate"] * 0.5  # half-spread
    feat["trade_volume_proxy"] = df["volume"].rolling(5, min_periods=1).mean()

    # ── Time features ──────────────────────────────────────────────────
    if hasattr(df.index, "hour"):
        bar_minutes = df.index.hour * 60 + df.index.minute
    else:
        bar_minutes = pd.Series(0, index=df.index)

    feat["minutes_since_open"] = (bar_minutes - MARKET_OPEN_MIN).clip(lower=0) / TRADING_DAY_MINUTES
    feat["minutes_to_close"] = (MARKET_CLOSE_MIN - bar_minutes).clip(lower=0) / TRADING_DAY_MINUTES

    # Fill NaN in early bars (before enough history)
    feat = feat.ffill().fillna(0.0)

    return feat


# ── Convenience: single-bar feature snapshot ──────────────────────────────


def compute_latest_features(
    df: pd.DataFrame,
    **kwargs: Any,
) -> dict[str, float]:
    """Compute features for the latest bar only. Useful for real-time inference."""
    features = compute_intraday_features(df, **kwargs)
    if features.empty:
        return {}
    return features.iloc[-1].to_dict()


# ── Feature column list (for model training) ──────────────────────────────

INTRADAY_FEATURE_COLUMNS = [
    "ret_1m", "ret_3m", "ret_5m", "ret_15m",
    "realized_vol_5", "realized_vol_15", "intraday_atr",
    "trend_persistence", "ema_slope",
    "volume_spike", "volume_zscore", "volume_ratio",
    "distance_from_vwap", "opening_range_break", "gap_from_prev_close",
    "nifty_intraday_return", "sector_intraday_strength", "market_breadth",
    "spread_estimate", "slippage_estimate", "trade_volume_proxy",
    "minutes_since_open", "minutes_to_close",
]
