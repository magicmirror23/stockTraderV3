"""Market features — OHLCV-derived technical indicators.

All functions accept a DataFrame with lowercase columns
(open, high, low, close, volume) indexed by date.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def add_returns(df: pd.DataFrame, periods: list[int] | None = None) -> pd.DataFrame:
    """Log returns over multiple horizons."""
    periods = periods or [1, 2, 3, 5, 10, 21]
    for p in periods:
        df[f"return_{p}d"] = np.log(df["close"] / df["close"].shift(p))
    return df


def add_volatility(df: pd.DataFrame, windows: list[int] | None = None) -> pd.DataFrame:
    """Rolling realised volatility (std of log returns)."""
    windows = windows or [5, 10, 21, 63]
    log_ret = np.log(df["close"] / df["close"].shift(1))
    for w in windows:
        df[f"volatility_{w}d"] = log_ret.rolling(w).std() * np.sqrt(252)
    return df


def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Average True Range."""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df[f"atr_{period}"] = tr.rolling(period).mean()
    return df


def add_momentum(df: pd.DataFrame) -> pd.DataFrame:
    """RSI, MACD, rate-of-change, momentum indicators."""
    close = df["close"]

    # RSI
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi_14"] = 100 - (100 / (1 + rs))

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    # Rate of change
    for p in [5, 10, 21]:
        df[f"roc_{p}"] = close.pct_change(p)

    # Williams %R
    h14 = df["high"].rolling(14).max()
    l14 = df["low"].rolling(14).min()
    df["williams_r"] = (h14 - close) / (h14 - l14).replace(0, np.nan) * -100

    return df


def add_moving_averages(df: pd.DataFrame) -> pd.DataFrame:
    """SMA and EMA crossover features."""
    for w in [5, 10, 20, 50, 200]:
        df[f"sma_{w}"] = df["close"].rolling(w).mean()
        df[f"ema_{w}"] = df["close"].ewm(span=w, adjust=False).mean()

    # Price vs SMA ratios
    for w in [20, 50, 200]:
        df[f"close_vs_sma{w}"] = df["close"] / df[f"sma_{w}"] - 1

    # Golden/death cross signals
    df["sma_50_200_ratio"] = df["sma_50"] / df["sma_200"].replace(0, np.nan)
    return df


def add_volume_features(df: pd.DataFrame) -> pd.DataFrame:
    """Volume-based features: VWAP, OBV, volume ratios."""
    # Volume SMA ratio
    vol_sma = df["volume"].rolling(20).mean()
    df["volume_ratio_20"] = df["volume"] / vol_sma.replace(0, np.nan)

    # On-Balance Volume
    direction = np.sign(df["close"].diff())
    df["obv"] = (direction * df["volume"]).cumsum()
    df["obv_sma_10"] = df["obv"].rolling(10).mean()

    # Intraday VWAP proxy (daily: typical price * volume / cumulative volume)
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    df["vwap_proxy"] = typical_price  # simplified for daily

    return df


def add_bollinger_bands(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """Bollinger Bands and %B indicator."""
    sma = df["close"].rolling(period).mean()
    std = df["close"].rolling(period).std()
    df[f"bb_upper_{period}"] = sma + 2 * std
    df[f"bb_lower_{period}"] = sma - 2 * std
    df[f"bb_pct_b_{period}"] = (df["close"] - df[f"bb_lower_{period}"]) / (
        (df[f"bb_upper_{period}"] - df[f"bb_lower_{period}"]).replace(0, np.nan)
    )
    df[f"bb_width_{period}"] = (df[f"bb_upper_{period}"] - df[f"bb_lower_{period}"]) / sma
    return df


def add_all_market_features(df: pd.DataFrame) -> pd.DataFrame:
    """Apply all market feature transformations."""
    df = add_returns(df)
    df = add_volatility(df)
    df = add_atr(df)
    df = add_momentum(df)
    df = add_moving_averages(df)
    df = add_volume_features(df)
    df = add_bollinger_bands(df)
    return df
