"""Tests for feature engineering modules."""

import numpy as np
import pandas as pd
import pytest

from app.features.market_features import (
    add_returns,
    add_volatility,
    add_atr,
    add_momentum,
    add_moving_averages,
    add_volume_features,
    add_bollinger_bands,
    add_all_market_features,
)


@pytest.fixture
def sample_ohlcv():
    """Generate sample OHLCV data."""
    np.random.seed(42)
    dates = pd.bdate_range("2023-01-01", periods=300)
    price = 1000.0
    records = []
    for d in dates:
        change = np.random.normal(0, 15)
        o = price
        c = price + change
        h = max(o, c) + abs(np.random.normal(0, 5))
        l = min(o, c) - abs(np.random.normal(0, 5))
        vol = np.random.randint(100_000, 5_000_000)
        records.append({"open": o, "high": h, "low": l, "close": c, "volume": vol})
        price = c
    return pd.DataFrame(records, index=dates)


def test_add_returns(sample_ohlcv):
    df = add_returns(sample_ohlcv)
    assert "return_1d" in df.columns
    assert "return_5d" in df.columns
    assert "return_21d" in df.columns
    assert not df["return_1d"].iloc[5:].isna().all()


def test_add_volatility(sample_ohlcv):
    df = add_volatility(sample_ohlcv)
    assert "volatility_5d" in df.columns
    assert "volatility_21d" in df.columns
    # Volatility should be positive
    valid = df["volatility_21d"].dropna()
    assert (valid >= 0).all()


def test_add_atr(sample_ohlcv):
    df = add_atr(sample_ohlcv)
    assert "atr_14" in df.columns
    valid = df["atr_14"].dropna()
    assert (valid >= 0).all()


def test_add_momentum(sample_ohlcv):
    df = add_momentum(sample_ohlcv)
    assert "rsi_14" in df.columns
    assert "macd" in df.columns
    assert "macd_signal" in df.columns
    # RSI should be [0, 100]
    valid_rsi = df["rsi_14"].dropna()
    assert (valid_rsi >= 0).all() and (valid_rsi <= 100).all()


def test_add_moving_averages(sample_ohlcv):
    df = add_moving_averages(sample_ohlcv)
    assert "sma_20" in df.columns
    assert "ema_50" in df.columns
    assert "close_vs_sma200" in df.columns


def test_add_volume_features(sample_ohlcv):
    df = add_volume_features(sample_ohlcv)
    assert "volume_ratio_20" in df.columns
    assert "obv" in df.columns


def test_add_bollinger_bands(sample_ohlcv):
    df = add_bollinger_bands(sample_ohlcv)
    assert "bb_upper_20" in df.columns
    assert "bb_lower_20" in df.columns
    assert "bb_pct_b_20" in df.columns


def test_all_market_features(sample_ohlcv):
    df = add_all_market_features(sample_ohlcv)
    # Should have many derived columns
    assert len(df.columns) > 30
    # Original columns preserved
    assert "close" in df.columns
