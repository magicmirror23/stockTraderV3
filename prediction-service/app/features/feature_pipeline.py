"""Feature pipeline — unified feature construction for training & inference.

Combines market, options, macro, event, and sentiment features into
a single DataFrame suitable for ML model consumption.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from app.core.config import settings
from app.features.market_features import add_all_market_features
from app.features.macro_features import add_macro_features

logger = logging.getLogger(__name__)

# Feature columns that the model expects (updated by training pipeline)
FEATURE_COLUMNS: list[str] = []


def build_features_for_training(
    ohlcv_data: dict[str, pd.DataFrame],
    macro_df: pd.DataFrame | None = None,
    target_horizon: int = 1,
) -> pd.DataFrame:
    """Build a combined feature matrix from multi-ticker OHLCV data.

    Args:
        ohlcv_data: {symbol: DataFrame} with OHLCV columns.
        macro_df: Pre-loaded macro data (optional, loaded if None).
        target_horizon: days-ahead for the target label.

    Returns:
        A single DataFrame with all features plus 'target' column.
        Each row is (date, symbol) with a 'symbol' column.
    """
    all_frames = []

    for symbol, df in ohlcv_data.items():
        if df.empty:
            continue

        # Add market-level features
        df = add_all_market_features(df.copy())

        # Add macro features
        df = add_macro_features(df, macro_df)

        # Add target: next-day return direction (1 = up, 0 = down)
        future_ret = np.log(df["close"].shift(-target_horizon) / df["close"])
        df["target"] = (future_ret > 0).astype(int)

        # Mark symbol
        df["symbol"] = symbol

        all_frames.append(df)

    if not all_frames:
        logger.warning("No frames to combine for training features")
        return pd.DataFrame()

    combined = pd.concat(all_frames, axis=0)

    # Drop rows with NaN target (last rows have no future)
    combined = combined.dropna(subset=["target"])

    # List feature columns (exclude meta and target)
    exclude = {"target", "symbol", "open", "high", "low", "close", "volume"}
    feature_cols = [c for c in combined.columns if c not in exclude]
    global FEATURE_COLUMNS
    FEATURE_COLUMNS = feature_cols

    logger.info(
        "Built training features: %d rows, %d features, %d tickers",
        len(combined), len(feature_cols), len(ohlcv_data),
    )
    return combined


def build_features_for_inference(
    df: pd.DataFrame,
    macro_df: pd.DataFrame | None = None,
    event_features: dict[str, float] | None = None,
    sentiment_features: dict[str, float] | None = None,
    options_features: dict[str, float] | None = None,
) -> pd.Series:
    """Build a single feature row for real-time inference.

    Uses the latest row of the OHLCV DataFrame plus any real-time
    data (events, sentiment, options).

    Returns a Series aligned with FEATURE_COLUMNS.
    """
    # Market features from OHLCV
    df = add_all_market_features(df.copy())
    df = add_macro_features(df, macro_df)

    latest = df.iloc[-1].copy()

    # Merge real-time features
    if event_features:
        for k, v in event_features.items():
            latest[k] = v
    if sentiment_features:
        for k, v in sentiment_features.items():
            latest[k] = v
    if options_features:
        for k, v in options_features.items():
            latest[k] = v

    # Align with training feature columns
    if FEATURE_COLUMNS:
        for col in FEATURE_COLUMNS:
            if col not in latest.index:
                latest[col] = 0.0
        latest = latest.reindex(FEATURE_COLUMNS).fillna(0.0)

    return latest


def get_feature_names() -> list[str]:
    """Return the current feature column list."""
    return list(FEATURE_COLUMNS)
