"""Macro features — VIX, crude oil, gold, USD/INR, global indices.

Fetches cross-asset data and computes features that capture
macro regime and inter-market correlations.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from app.core.config import settings

logger = logging.getLogger(__name__)

# Macro symbol → yfinance ticker mapping
MACRO_YF_MAP = {
    "^NSEI": "^NSEI",
    "^NSEBANK": "^NSEBANK",
    "^INDIAVIX": "^INDIAVIX",
    "CL=F": "CL=F",      # Crude oil
    "GC=F": "GC=F",      # Gold
    "USDINR=X": "USDINR=X",
    "^GSPC": "^GSPC",    # S&P 500
    "^DJI": "^DJI",      # Dow Jones
}


def load_macro_data(
    start: datetime | None = None,
    end: datetime | None = None,
) -> pd.DataFrame:
    """Load macro/cross-asset price data using yfinance.

    Returns a DataFrame with columns for each macro symbol's close,
    indexed by date.
    """
    if start is None:
        start = datetime.now(timezone.utc) - timedelta(days=settings.TRAIN_LOOKBACK_DAYS)
    if end is None:
        end = datetime.now(timezone.utc)

    try:
        import yfinance as yf

        symbols = settings.MACRO_SYMBOLS
        tickers_str = " ".join(symbols)
        data = yf.download(
            tickers_str,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            auto_adjust=True,
            progress=False,
        )

        if data.empty:
            return pd.DataFrame()

        # Extract close prices
        if isinstance(data.columns, pd.MultiIndex):
            closes = data["Close"]
        else:
            closes = data[["Close"]].rename(columns={"Close": symbols[0]})

        # Clean column names
        closes.columns = [f"macro_{c.replace('^', '').replace('=', '_')}" for c in closes.columns]
        return closes

    except Exception as exc:
        logger.error("Failed to load macro data: %s", exc)
        return pd.DataFrame()


def add_macro_features(df: pd.DataFrame, macro_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Merge macro features into the main DataFrame.

    Computes returns and rolling correlations for macro variables.
    """
    if macro_df is None:
        macro_df = load_macro_data()

    if macro_df.empty:
        logger.warning("No macro data available, skipping macro features")
        return df

    # Align indices
    macro_df = macro_df.reindex(df.index, method="ffill")

    # Add raw macro levels
    for col in macro_df.columns:
        df[col] = macro_df[col]

    # Add macro returns
    for col in macro_df.columns:
        df[f"{col}_ret_1d"] = np.log(macro_df[col] / macro_df[col].shift(1))
        df[f"{col}_ret_5d"] = np.log(macro_df[col] / macro_df[col].shift(5))

    # VIX-specific features (if available)
    vix_col = [c for c in macro_df.columns if "vix" in c.lower() or "INDIAVIX" in c]
    if vix_col:
        vc = vix_col[0]
        df["vix_level"] = macro_df[vc]
        df["vix_change_1d"] = macro_df[vc].diff()
        df["vix_percentile_63d"] = macro_df[vc].rolling(63).apply(
            lambda x: (x.iloc[-1] - x.min()) / (x.max() - x.min() + 1e-8) if len(x) > 0 else 0.5,
            raw=False,
        )

    # Rolling correlation between Nifty returns and macro returns
    if "close" in df.columns:
        nifty_ret = np.log(df["close"] / df["close"].shift(1))
        for col in macro_df.columns:
            macro_ret = np.log(macro_df[col] / macro_df[col].shift(1))
            df[f"corr_nifty_{col}_21d"] = nifty_ret.rolling(21).corr(macro_ret)

    return df
