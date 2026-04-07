"""Versioned Feature Store.

Builds a feature matrix from raw OHLCV data using the transforms defined in
``transforms.py``. Supports both bulk build (for training) and single-row
inference lookups.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from backend.prediction_engine.feature_store import transforms as T

_DEFAULT_RAW_DIR = Path(__file__).resolve().parents[3] / "storage" / "raw"

logger = logging.getLogger(__name__)

MANIFEST_PATH = Path(__file__).parent / "manifest.json"

FEATURE_COLUMNS: list[str] = [
    "ticker",
    "date",
    "close",
    "sma_10",
    "sma_20",
    "sma_50",
    "ema_10",
    "ema_20",
    "rsi_14",
    "macd",
    "macd_signal",
    "macd_hist",
    "atr_14",
    "volatility_20",
    "return_1d",
    "return_5d",
    "log_return_1d",
    "volume_spike",
    "volume_ratio",
    "adx_14",
    "bb_width",
    "bb_pct_b",
    "stoch_k",
    "distance_sma50",
    "momentum_10",
    "gap_pct",
    "vwap_dist",
    "obv_slope",
    "williams_r",
    "cci_20",
    "roc_10",
    "ema_crossover",
    "return_2d",
    "return_3d",
    "return_10d",
    "distance_sma200",
    "price_pos_52w",
    "stoch_d",
    "rsi_divergence",
    "force_index",
    "high_low_ratio",
    "return_mean_5",
    "return_mean_10",
    "return_skew_10",
    "volume_change",
    "close_to_ma20",
    "close_to_ma50",
    "return_lag_1",
    "return_lag_5",
    "day_of_week",
]

# Cross-sectional features computed after concat (require multiple tickers on same dates)
CROSS_SECTIONAL_FEATURE_COLUMNS: list[str] = [
    "stock_return_1d_minus_benchmark_1d",
    "stock_return_5d_minus_benchmark_5d",
    "sector_relative_strength_5d",
    "sector_relative_strength_20d",
    "benchmark_relative_momentum",
    "market_breadth_feature",
    "sector_breadth_feature",
    "beta_to_benchmark",
    "rolling_corr_to_benchmark",
]


def _load_ticker_csv(ticker: str, data_dir: Path) -> pd.DataFrame:
    base = str(ticker).strip().upper()
    candidate_names: list[str] = [base, base.replace("_", "-"), base.replace("_", "&")]

    try:
        from backend.prediction_engine.data_pipeline.providers import SymbolMapper

        mapped = SymbolMapper.SYMBOL_OVERRIDES.get(base)
        if mapped:
            mapped_upper = mapped.upper()
            candidate_names.extend(
                [
                    mapped_upper,
                    mapped_upper.replace("&", "_").replace("-", "_"),
                    mapped_upper.replace("_", "-"),
                    mapped_upper.replace("_", "&"),
                ]
            )
    except Exception:
        # Keep file loading resilient even if provider module is unavailable.
        pass

    seen: set[str] = set()
    for name in candidate_names:
        if name in seen:
            continue
        seen.add(name)
        path = data_dir / f"{name}.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path, parse_dates=["Date"])
        return df.sort_values("Date").reset_index(drop=True)

    # Optional hydration path: materialize CSV from canonical local DB store.
    hydrate_enabled = os.getenv("FEATURE_AUTO_HYDRATE_FROM_DB", "true").strip().lower() in {
        "1", "true", "yes", "on", "y"
    }
    if hydrate_enabled:
        try:
            from backend.market_data_service.local_access import LocalMarketDataAccess

            access = LocalMarketDataAccess()
            end_date = datetime.now(timezone.utc).date().isoformat()
            start_date = (
                pd.Timestamp(datetime.now(timezone.utc).date()) - pd.DateOffset(days=365 * 5)
            ).date().isoformat()
            result = access.export_symbol_to_csv(
                symbol=ticker,
                data_dir=data_dir,
                start_date=start_date,
                end_date=end_date,
                interval="1d",
                min_rows=20,
            )
            if result.status == "ok" and result.csv_path:
                path = Path(result.csv_path)
                if path.exists():
                    df = pd.read_csv(path, parse_dates=["Date"])
                    return df.sort_values("Date").reset_index(drop=True)
        except Exception as exc:
            logger.debug("DB hydration skipped for %s: %s", ticker, exc)

    raise FileNotFoundError(
        f"No data file for {ticker}. Tried: {', '.join(f'{n}.csv' for n in seen)}"
    )


def _compute_features(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Compute all feature columns for a single-ticker DataFrame."""
    close = df["Close"]
    feat = pd.DataFrame()

    feat["date"] = df["Date"].values
    feat["close"] = close.values
    feat["ticker"] = ticker

    feat["sma_10"] = T.sma(close, 10).values
    feat["sma_20"] = T.sma(close, 20).values
    feat["sma_50"] = T.sma(close, 50).values
    feat["ema_10"] = T.ema(close, 10).values
    feat["ema_20"] = T.ema(close, 20).values

    feat["rsi_14"] = T.rsi(close, 14).values
    macd_df = T.macd(close)
    feat["macd"] = macd_df["macd"].values
    feat["macd_signal"] = macd_df["macd_signal"].values
    feat["macd_hist"] = macd_df["macd_hist"].values

    feat["atr_14"] = T.atr(df, 14).values
    feat["volatility_20"] = T.volatility(close, 20).values

    feat["return_1d"] = T.returns(close, 1).values
    feat["return_5d"] = T.returns(close, 5).values
    feat["log_return_1d"] = T.log_returns(close, 1).values

    feat["volume_spike"] = T.volume_spike(df["Volume"]).values
    feat["volume_ratio"] = T.volume_ratio(df["Volume"]).values

    feat["adx_14"] = T.adx(df, 14).values
    feat["bb_width"] = T.bollinger_band_width(close, 20).values
    feat["bb_pct_b"] = T.bollinger_pct_b(close, 20).values
    feat["stoch_k"] = T.stochastic_k(df, 14).values
    feat["distance_sma50"] = T.price_distance_from_sma(close, 50).values
    feat["momentum_10"] = T.return_momentum(close, 10).values
    feat["gap_pct"] = T.gap_pct(df).values if "Open" in df.columns else 0.0

    feat["vwap_dist"] = T.vwap_distance(df, 20).values
    feat["obv_slope"] = T.obv_slope(df, 10).values
    feat["williams_r"] = T.williams_r(df, 14).values
    feat["cci_20"] = T.cci(df, 20).values
    feat["roc_10"] = T.roc(close, 10).values
    feat["ema_crossover"] = T.ema_crossover(close, 10, 20).values
    feat["return_2d"] = T.lagged_return(close, 2).values
    feat["return_3d"] = T.lagged_return(close, 3).values
    feat["return_10d"] = T.lagged_return(close, 10).values
    sma200 = T.sma_long(close, 200)
    feat["distance_sma200"] = ((close - sma200) / sma200.replace(0, np.nan)).values
    feat["price_pos_52w"] = T.price_position_52w(df, 252).values
    feat["stoch_d"] = T.stochastic_d(df, 14, 3).values
    feat["rsi_divergence"] = T.rsi_divergence(close, 14, 10).values

    feat["force_index"] = T.force_index(df, 13).values
    feat["high_low_ratio"] = T.high_low_ratio(df).values
    feat["return_mean_5"] = T.return_mean(close, 5).values
    feat["return_mean_10"] = T.return_mean(close, 10).values
    feat["return_skew_10"] = T.return_skew(close, 10).values
    feat["volume_change"] = T.volume_change(df["Volume"]).values
    feat["close_to_ma20"] = T.close_to_sma(close, 20).values
    feat["close_to_ma50"] = T.close_to_sma(close, 50).values
    feat["return_lag_1"] = T.lagged_return_shift(close, 1).values
    feat["return_lag_5"] = T.lagged_return_shift(close, 5).values
    feat["day_of_week"] = T.day_of_week(df).values

    return feat


def _add_cross_sectional_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add benchmark-relative and breadth features across the full universe.

    These features compare each stock's behavior to the cross-sectional
    average on the same date, providing relative context.
    """
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)

    # Ensure required columns exist
    for col, default in [("return_1d", 0.0), ("return_5d", 0.0), ("close", 0.0)]:
        if col not in df.columns:
            df[col] = default

    # Benchmark = cross-sectional mean return per date
    benchmark_1d = df.groupby("date")["return_1d"].transform("mean")
    benchmark_5d = df.groupby("date")["return_5d"].transform("mean")

    df["stock_return_1d_minus_benchmark_1d"] = df["return_1d"] - benchmark_1d
    df["stock_return_5d_minus_benchmark_5d"] = df["return_5d"] - benchmark_5d

    # Sector-relative strength
    try:
        from backend.ml_platform.universe_definitions import get_symbol_tags
        df["_sector"] = df["ticker"].map(lambda t: get_symbol_tags(str(t)).get("sector", "Unknown"))
    except Exception:
        df["_sector"] = "Unknown"

    sector_return_5d = df.groupby(["date", "_sector"])["return_5d"].transform("mean")
    df["sector_relative_strength_5d"] = df["return_5d"] - sector_return_5d

    # For 20d sector relative strength, use rolling returns
    g = df.groupby("ticker", sort=False)
    if "return_10d" in df.columns:
        rolling_20d = g["close"].pct_change(20).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    else:
        rolling_20d = g["close"].pct_change(20).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    df["_return_20d"] = rolling_20d
    sector_return_20d = df.groupby(["date", "_sector"])["_return_20d"].transform("mean")
    df["sector_relative_strength_20d"] = df["_return_20d"] - sector_return_20d

    # Benchmark relative momentum (stock 10d mom - benchmark 10d mom)
    benchmark_mom = df.groupby("date")["return_5d"].transform("mean")
    benchmark_mom_rolling = benchmark_mom  # already cross-sectional per date
    if "momentum_10" in df.columns:
        df["benchmark_relative_momentum"] = df["momentum_10"] - df.groupby("date")["momentum_10"].transform("mean")
    else:
        df["benchmark_relative_momentum"] = df["return_5d"] - benchmark_5d

    # Market breadth: fraction of stocks with positive 1d return
    df["market_breadth_feature"] = df.groupby("date")["return_1d"].transform(
        lambda s: float((s > 0).mean())
    )

    # Sector breadth: fraction of stocks in same sector with positive 1d return
    df["sector_breadth_feature"] = df.groupby(["date", "_sector"])["return_1d"].transform(
        lambda s: float((s > 0).mean()) if len(s) > 1 else 0.5
    )

    # Beta to benchmark (rolling 63-day covariance / variance)
    def _rolling_beta(group):
        ret = group["return_1d"].values
        bm = group["_benchmark_1d"].values
        betas = np.full(len(ret), np.nan)
        window = 63
        for i in range(window, len(ret)):
            r_slice = ret[i - window:i]
            b_slice = bm[i - window:i]
            mask = np.isfinite(r_slice) & np.isfinite(b_slice)
            if mask.sum() < 20:
                continue
            cov = np.cov(r_slice[mask], b_slice[mask])
            var_bm = cov[1, 1]
            if var_bm > 1e-12:
                betas[i] = cov[0, 1] / var_bm
        return pd.Series(betas, index=group.index)

    df["_benchmark_1d"] = benchmark_1d
    df["beta_to_benchmark"] = df.groupby("ticker", group_keys=False).apply(_rolling_beta)

    # Rolling correlation to benchmark (20-day)
    def _rolling_corr(group):
        ret = group["return_1d"].values
        bm = group["_benchmark_1d"].values
        corrs = np.full(len(ret), np.nan)
        window = 20
        for i in range(window, len(ret)):
            r_slice = ret[i - window:i]
            b_slice = bm[i - window:i]
            mask = np.isfinite(r_slice) & np.isfinite(b_slice)
            if mask.sum() < 10:
                continue
            cc = np.corrcoef(r_slice[mask], b_slice[mask])
            if np.isfinite(cc[0, 1]):
                corrs[i] = cc[0, 1]
        return pd.Series(corrs, index=group.index)

    df["rolling_corr_to_benchmark"] = df.groupby("ticker", group_keys=False).apply(_rolling_corr)

    # Cleanup temp columns
    df.drop(columns=["_sector", "_return_20d", "_benchmark_1d"], inplace=True, errors="ignore")

    # Fill NaN in cross-sectional features
    for col in CROSS_SECTIONAL_FEATURE_COLUMNS:
        if col in df.columns:
            df[col] = df[col].replace([np.inf, -np.inf], np.nan).fillna(0.0)

    return df


def build_features(
    tickers: list[str],
    start: str | datetime | None = None,
    end: str | datetime | None = None,
    data_dir: str | Path | None = None,
) -> pd.DataFrame:
    """Build the full feature matrix for a list of tickers."""
    data_dir = Path(data_dir) if data_dir else _DEFAULT_RAW_DIR
    frames: list[pd.DataFrame] = []

    for ticker in tickers:
        try:
            df = _load_ticker_csv(ticker, data_dir)
        except FileNotFoundError:
            logger.warning("Skipping %s - CSV not found in %s", ticker, data_dir)
            continue
        frames.append(_compute_features(df, ticker))

    if not frames:
        raise FileNotFoundError("No CSV data files found for any ticker")

    result = pd.concat(frames, ignore_index=True)
    if start is not None:
        result = result[result["date"] >= pd.Timestamp(start)]
    if end is not None:
        result = result[result["date"] <= pd.Timestamp(end)]

    result = result.dropna().reset_index(drop=True)

    # Add cross-sectional / benchmark-relative features (require all tickers)
    result = _add_cross_sectional_features(result)

    _write_manifest(tickers, result)
    all_cols = [c for c in FEATURE_COLUMNS + CROSS_SECTIONAL_FEATURE_COLUMNS if c in result.columns]
    return result[all_cols]


def get_features_for_inference(
    ticker: str,
    timestamp: str | datetime | None = None,
    data_dir: str | Path | None = None,
) -> dict:
    """Return the latest feature vector for a single ticker."""
    data_dir = Path(data_dir) if data_dir else _DEFAULT_RAW_DIR
    df = _load_ticker_csv(ticker, data_dir)
    feat = _compute_features(df, ticker).dropna().reset_index(drop=True)

    if feat.empty:
        raise ValueError(f"No valid feature rows for {ticker}")

    if timestamp is not None:
        ts = pd.Timestamp(timestamp)
        feat = feat[feat["date"] <= ts]
        if feat.empty:
            raise ValueError(f"No feature rows for {ticker} on or before {timestamp}")

    row = feat.iloc[-1]
    return {col: row[col] for col in FEATURE_COLUMNS}


def _write_manifest(tickers: list[str], df: pd.DataFrame) -> None:
    manifest = {
        "version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat() + "Z",
        "tickers": tickers,
        "feature_columns": FEATURE_COLUMNS,
        "row_count": len(df),
        "date_range": {
            "start": str(df["date"].min()),
            "end": str(df["date"].max()),
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))
    logger.info("Feature manifest written to %s", MANIFEST_PATH)


OPTION_FEATURE_COLUMNS: list[str] = [
    "underlying",
    "strike",
    "expiry",
    "option_type",
    "date",
    "underlying_close",
    "iv",
    "iv_rank",
    "oi_change",
    "delta",
    "gamma",
    "theta",
    "vega",
    "moneyness",
    "days_to_expiry",
    "underlying_rsi_14",
    "underlying_atr_14",
    "underlying_volatility_20",
]


def build_option_features(
    underlying: str,
    strike: float,
    expiry: str,
    start: str | datetime | None = None,
    end: str | datetime | None = None,
    data_dir: str | Path | None = None,
) -> pd.DataFrame:
    """Build option-specific feature matrix."""
    data_dir = Path(data_dir) if data_dir else _DEFAULT_RAW_DIR
    df = _load_ticker_csv(underlying, data_dir)
    equity_feat = _compute_features(df, underlying).dropna().reset_index(drop=True)

    opt = pd.DataFrame()
    opt["underlying"] = underlying
    opt["strike"] = strike
    opt["expiry"] = expiry
    opt["option_type"] = "CE"
    opt["date"] = equity_feat["date"]
    opt["underlying_close"] = equity_feat["close"].values
    opt["moneyness"] = equity_feat["close"].values / strike

    expiry_dt = pd.Timestamp(expiry)
    opt["days_to_expiry"] = (expiry_dt - equity_feat["date"]).dt.days
    opt["underlying_rsi_14"] = equity_feat["rsi_14"].values
    opt["underlying_atr_14"] = equity_feat["atr_14"].values
    opt["underlying_volatility_20"] = equity_feat["volatility_20"].values

    for idx, row in opt.iterrows():
        dte = max(row["days_to_expiry"], 1)
        vol = row.get("underlying_volatility_20", 0.3) or 0.3
        greeks = T.greeks_estimate(row["underlying_close"], strike, dte, vol)
        opt.loc[idx, "delta"] = greeks["delta"]
        opt.loc[idx, "gamma"] = greeks["gamma"]
        opt.loc[idx, "theta"] = greeks["theta"]
        opt.loc[idx, "vega"] = greeks["vega"]

    opt["iv"] = equity_feat["volatility_20"].values
    opt["iv_rank"] = T.implied_volatility_rank(opt["iv"]).values
    opt["oi_change"] = 0

    if start is not None:
        opt = opt[opt["date"] >= pd.Timestamp(start)]
    if end is not None:
        opt = opt[opt["date"] <= pd.Timestamp(end)]

    return opt.dropna().reset_index(drop=True)
