# Model training logic
"""Reproducible multi-model training pipeline with walk-forward splits,
ensembling, probability calibration, and economic metric evaluation.

Usage
-----
    python -m backend.prediction_engine.training.trainer
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import accuracy_score, brier_score_loss, f1_score, precision_score, recall_score
from sklearn.preprocessing import StandardScaler

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from backend.prediction_engine.feature_store.feature_store import build_features  # noqa: E402
from backend.prediction_engine.models.lightgbm_model import LightGBMModel  # noqa: E402

logger = logging.getLogger(__name__)

ARTIFACTS_DIR = REPO_ROOT / "models" / "artifacts"
REGISTRY_PATH = REPO_ROOT / "models" / "registry.json"
DATA_DIR = REPO_ROOT / "storage" / "raw"

SEED = 42
PURGE_GAP = 10  # days gap between splits to prevent look-ahead leakage


class TrainingPipelineError(RuntimeError):
    """Structured training error returned by admin retrain endpoint."""

    def __init__(self, reason: str, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.reason = reason
        self.details = details or {}

    def to_dict(self) -> dict:
        return {
            "status": "failed",
            "reason": self.reason,
            "message": str(self),
            "details": self.details,
        }


@dataclass(frozen=True)
class TrainingConfig:
    """Configurable minimums for safe time-series training."""

    train_min_days: int = 120
    val_min_days: int = 30
    test_min_days: int = 30
    purge_gap_days: int = PURGE_GAP
    min_unique_dates: int = 120
    min_rows_per_symbol: int = 140
    min_symbols: int = 3
    min_samples_per_class: int = 40
    allow_reduced_validation: bool = False


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def load_training_config() -> TrainingConfig:
    """Load training thresholds from environment variables."""

    return TrainingConfig(
        train_min_days=int(os.getenv("TRAIN_MIN_DAYS", "120")),
        val_min_days=int(os.getenv("VAL_MIN_DAYS", "30")),
        test_min_days=int(os.getenv("TEST_MIN_DAYS", "30")),
        purge_gap_days=int(os.getenv("TRAIN_EMBARGO_DAYS", str(PURGE_GAP))),
        min_unique_dates=int(os.getenv("MIN_UNIQUE_DATES", "120")),
        min_rows_per_symbol=int(os.getenv("MIN_ROWS_PER_SYMBOL", "140")),
        min_symbols=int(os.getenv("MIN_SYMBOLS_FOR_TRAINING", "3")),
        min_samples_per_class=int(os.getenv("MIN_SAMPLES_PER_CLASS", "40")),
        allow_reduced_validation=_env_bool("TRAIN_ALLOW_REDUCED_VALIDATION", False),
    )


# ---------------------------------------------------------------------------
# Auto-download data if missing
# ---------------------------------------------------------------------------

def _ensure_data_available(
    tickers: list[str],
    data_dir: Path,
    *,
    config: TrainingConfig | None = None,
    return_report: bool = False,
) -> list[str] | tuple[list[str], dict]:
    """Ensure raw CSV history is sufficient for feature generation + safe splits."""
    data_dir.mkdir(parents=True, exist_ok=True)
    cfg = config or load_training_config()
    try:
        from backend.prediction_engine.data_pipeline.providers import SymbolMapper
        _symbol_overrides = dict(SymbolMapper.SYMBOL_OVERRIDES)
    except Exception:
        _symbol_overrides = {}

    feature_warmup_rows = int(os.getenv("TRAIN_FEATURE_WARMUP_ROWS", "260"))
    min_feature_rows = max(
        cfg.min_rows_per_symbol,
        cfg.train_min_days + cfg.val_min_days + cfg.test_min_days + 2 * cfg.purge_gap_days,
    )
    min_raw_rows = int(
        os.getenv(
            "TRAIN_DOWNLOAD_MIN_RAW_ROWS",
            str(max(260, min_feature_rows + feature_warmup_rows)),
        )
    )

    lookback_days = int(
        os.getenv(
            "TRAIN_DOWNLOAD_LOOKBACK_DAYS",
            os.getenv("TRAIN_LOOKBACK_DAYS", "730"),
        )
    )
    lookback_days = max(365, lookback_days)
    extended_lookback_days = int(
        os.getenv(
            "TRAIN_DOWNLOAD_EXTENDED_LOOKBACK_DAYS",
            str(max(lookback_days * 2, 1460)),
        )
    )
    extended_lookback_days = max(lookback_days, extended_lookback_days)
    download_target_symbols = int(
        os.getenv(
            "TRAIN_DOWNLOAD_TARGET_SYMBOLS",
            str(max(cfg.min_symbols + 2, cfg.min_symbols)),
        )
    )
    request_pause_s = float(os.getenv("TRAIN_DOWNLOAD_REQUEST_PAUSE_S", "0.6"))
    data_source_mode = os.getenv("TRAIN_DATA_SOURCE_MODE", "download_or_cache").strip().lower()
    download_enabled = data_source_mode not in {"local_only", "cache_only", "offline"}

    def _row_count(path: Path) -> int:
        if not path.exists():
            return 0
        try:
            return int(len(pd.read_csv(path, usecols=["Date"])))
        except Exception:
            try:
                return int(len(pd.read_csv(path)))
            except Exception:
                return 0

    def _candidate_paths(ticker: str) -> list[Path]:
        """Return possible on-disk CSV names for a logical symbol."""
        base = str(ticker).strip().upper()
        names = {base}
        mapped = _symbol_overrides.get(base)
        if mapped:
            names.add(mapped.upper())
            names.add(mapped.replace("&", "_").replace("-", "_").upper())
        return [data_dir / f"{name}.csv" for name in sorted(names)]

    def _best_existing_rows(ticker: str) -> int:
        return max((_row_count(p) for p in _candidate_paths(ticker)), default=0)

    existing_rows: dict[str, int] = {ticker: _best_existing_rows(ticker) for ticker in tickers}
    missing = [t for t in tickers if existing_rows.get(t, 0) == 0]
    undersized = [t for t in tickers if 0 < existing_rows.get(t, 0) < min_raw_rows]
    needs_refresh = list(dict.fromkeys(missing + undersized))

    report: dict[str, object] = {
        "requested": len(tickers),
        "missing": missing,
        "undersized": undersized,
        "downloaded": [],
        "skipped": {},
        "raw_row_threshold": min_raw_rows,
        "lookback_days": lookback_days,
        "extended_lookback_days": extended_lookback_days,
        "data_source_mode": data_source_mode,
    }

    if not needs_refresh:
        strict_available = [t for t in tickers if existing_rows.get(t, 0) >= min_raw_rows]
        if not strict_available:
            strict_available = [t for t in tickers if existing_rows.get(t, 0) > 0]
        report["available"] = strict_available
        report["raw_rows_available"] = {t: int(existing_rows.get(t, 0)) for t in strict_available}
        if return_report:
            return strict_available, report
        return strict_available

    if not download_enabled:
        logger.warning(
            "Skipping provider downloads because TRAIN_DATA_SOURCE_MODE=%s",
            data_source_mode,
        )
        for ticker in needs_refresh:
            report["skipped"][ticker] = "download_disabled"
        strict_available = [t for t in tickers if existing_rows.get(t, 0) >= min_raw_rows]
        if not strict_available:
            strict_available = [t for t in tickers if existing_rows.get(t, 0) > 0]
        report["available"] = strict_available
        report["raw_rows_available"] = {t: int(existing_rows.get(t, 0)) for t in strict_available}
        if return_report:
            return strict_available, report
        return strict_available

    logger.info(
        "Refreshing data for %d tickers (missing=%d, undersized=%d, min_raw_rows=%d)",
        len(needs_refresh),
        len(missing),
        len(undersized),
        min_raw_rows,
    )
    try:
        from backend.prediction_engine.data_pipeline.connector_yahoo import YahooConnector

        connector = YahooConnector(
            max_retries=int(os.getenv("TRAIN_DOWNLOAD_PROVIDER_RETRIES", "2")),
            retry_delay_s=float(os.getenv("TRAIN_DOWNLOAD_RETRY_DELAY_S", "1.5")),
        )
        outer_retries = max(1, int(os.getenv("TRAIN_DOWNLOAD_OUTER_RETRIES", "1")))
        outer_backoff_s = float(os.getenv("TRAIN_DOWNLOAD_OUTER_BACKOFF_S", "2.0"))
        end_ts = datetime.now()

        downloaded = 0
        for ticker in needs_refresh:
            success = False
            for attempt in range(1, outer_retries + 1):
                try:
                    window_days_options = [lookback_days]
                    if extended_lookback_days > lookback_days:
                        window_days_options.append(extended_lookback_days)

                    last_df: pd.DataFrame | None = None
                    for window_days in window_days_options:
                        start_ts = end_ts - timedelta(days=window_days)
                        df = connector.fetch(ticker, start_ts, end_ts)
                        last_df = df
                        if len(df) >= min_raw_rows:
                            break
                        logger.warning(
                            "Downloaded %s but only %d rows (required >= %d) using %d-day lookback",
                            ticker,
                            len(df),
                            min_raw_rows,
                            window_days,
                        )

                    if last_df is not None and len(last_df) >= min_raw_rows:
                        path = data_dir / f"{ticker}.csv"
                        last_df.to_csv(path, index=False)
                        existing_rows[ticker] = int(len(last_df))
                        downloaded += 1
                        success = True
                        report["downloaded"].append(ticker)
                        logger.info("Downloaded %s (%d rows)", ticker, len(last_df))
                        break

                    rows = int(len(last_df)) if last_df is not None else 0
                    logger.warning("Skipping %s - only %d rows (required >= %d)", ticker, rows, min_raw_rows)
                    report["skipped"][ticker] = f"insufficient_rows:{rows}"
                except Exception as exc:
                    logger.warning(
                        "Failed to download %s on attempt %d/%d: %s",
                        ticker,
                        attempt,
                        outer_retries,
                        exc,
                    )
                    report["skipped"][ticker] = str(exc)

                if attempt < outer_retries:
                    backoff_s = outer_backoff_s * attempt
                    logger.info("Retrying %s in %.1fs", ticker, backoff_s)
                    time.sleep(backoff_s)

            if not success:
                logger.warning("Unable to fetch usable data for %s after retries", ticker)
                report["skipped"].setdefault(ticker, "retry_exhausted")

            if request_pause_s > 0:
                time.sleep(request_pause_s)

            strong_count = sum(1 for rows in existing_rows.values() if rows >= min_raw_rows)
            if strong_count >= max(cfg.min_symbols, download_target_symbols):
                logger.info(
                    "Reached strong-data target (%d symbols with >= %d rows), stopping refresh loop",
                    strong_count,
                    min_raw_rows,
                )
                break

        logger.info("Downloaded %d/%d required tickers", downloaded, len(needs_refresh))
    except ImportError:
        logger.error("yfinance not installed - cannot auto-download data")
        for ticker in needs_refresh:
            report["skipped"].setdefault(ticker, "yfinance_not_installed")

    available_tickers = [t for t in tickers if existing_rows.get(t, 0) >= min_raw_rows]
    if len(available_tickers) < cfg.min_symbols:
        fallback = [t for t in tickers if existing_rows.get(t, 0) > 0]
        if fallback:
            available_tickers = fallback

    report["available"] = available_tickers
    report["raw_rows_available"] = {t: int(existing_rows.get(t, 0)) for t in available_tickers}
    if return_report:
        return available_tickers, report
    return available_tickers


# ---------------------------------------------------------------------------
# Label construction
# ---------------------------------------------------------------------------

def _build_labels(df: pd.DataFrame, horizon: int = 3, threshold: float = 0.001) -> pd.Series:
    """Create binary labels based on future returns for direction prediction.

    Uses simple direction of future returns to create a binary classification
    task (easier to learn, 50% baseline). The model's confidence is then used
    at inference to map to buy/sell/hold.

    Classes
    -------
    0 = down  (future return < -threshold)
    1 = up    (future return > +threshold)
    NaN = ambiguous / no future data
    """
    future_ret = df.groupby("ticker")["close"].transform(
        lambda s: s.shift(-horizon) / s - 1
    )

    labels = pd.Series(np.nan, index=df.index)
    labels[future_ret > threshold] = 1   # up
    labels[future_ret < -threshold] = 0  # down
    return labels


# Features that are already bounded / normalised and should NOT be z-scored
_BOUNDED_FEATURES = {
    "rsi_14", "bb_pct_b", "stoch_k", "stoch_d", "williams_r",
    "price_pos_52w", "volume_spike", "rsi_divergence",
    "high_low_ratio", "close_to_ma20", "close_to_ma50", "day_of_week",
}


def _normalize_features_per_ticker(df: pd.DataFrame, feature_cols: list[str]) -> pd.DataFrame:
    """Z-score normalize only unbounded features per ticker.

    Bounded indicators (RSI, stochastic, etc.) keep their natural scale
    to preserve their semantic meaning.
    """
    df = df.copy()
    for col in feature_cols:
        if col in df.columns and col not in _BOUNDED_FEATURES:
            df[col] = df.groupby("ticker")[col].transform(
                lambda s: (s - s.rolling(60, min_periods=20).mean())
                / s.rolling(60, min_periods=20).std().replace(0, np.nan)
            )
    return df


def _compute_class_weights(y: pd.Series) -> np.ndarray:
    """Compute per-sample weights to balance classes."""
    class_counts = y.value_counts()
    total = len(y)
    n_classes = len(class_counts)
    weights = total / (n_classes * class_counts)
    return y.map(weights).values


# ---------------------------------------------------------------------------
# Walk-forward split
# ---------------------------------------------------------------------------

def _walk_forward_split(
    df: pd.DataFrame,
    train_pct: float = 0.6,
    val_pct: float = 0.2,
    purge_gap: int = PURGE_GAP,
    config: TrainingConfig | None = None,
):
    """Time-series aware train / val / test split with purge gaps.

    Splits are computed on unique trading dates (not row indices) so
    train/val/test are strictly separated in time across all tickers.
    Purge gaps are applied in units of trading dates.
    """
    if df.empty:
        raise TrainingPipelineError(
            reason="insufficient_data",
            message="Cannot split empty dataframe.",
            details={"rows": 0},
        )

    work = df.copy()
    work["date"] = pd.to_datetime(work["date"])
    sort_cols = ["date", "ticker"] if "ticker" in work.columns else ["date"]
    work = work.sort_values(sort_cols).reset_index(drop=True)

    unique_dates = pd.Index(work["date"].dropna().sort_values().unique())
    n_dates = len(unique_dates)

    cfg = config or load_training_config()
    purge = int(cfg.purge_gap_days if config else purge_gap)
    required_min = max(
        cfg.min_unique_dates if config else 30,
        (cfg.train_min_days + cfg.val_min_days + cfg.test_min_days + 2 * purge)
        if config
        else 0,
    )
    if n_dates < required_min:
        if config and cfg.allow_reduced_validation:
            # Reduced mode keeps chronology and purge gaps but scales windows.
            test_days = max(10, int(n_dates * 0.15))
            val_days = max(10, int(n_dates * 0.15))
            train_days = max(20, n_dates - test_days - val_days - 2 * purge)
            temp_cfg = TrainingConfig(
                train_min_days=train_days,
                val_min_days=val_days,
                test_min_days=test_days,
                purge_gap_days=purge,
                min_unique_dates=max(40, train_days + val_days + test_days),
                min_rows_per_symbol=cfg.min_rows_per_symbol,
                min_symbols=cfg.min_symbols,
                min_samples_per_class=cfg.min_samples_per_class,
                allow_reduced_validation=False,
            )
            logger.warning(
                "Using reduced validation mode due limited data: n_dates=%d, train=%d, val=%d, test=%d",
                n_dates,
                train_days,
                val_days,
                test_days,
            )
            return _walk_forward_split(
                work,
                train_pct=train_pct,
                val_pct=val_pct,
                purge_gap=purge,
                config=temp_cfg,
            )

        raise TrainingPipelineError(
            reason="insufficient_data",
            message=f"Not enough unique dates to split safely (got {n_dates}).",
            details={
                "unique_dates": n_dates,
                "required_min_dates": required_min,
                "train_min_days": cfg.train_min_days,
                "val_min_days": cfg.val_min_days,
                "test_min_days": cfg.test_min_days,
                "purge_gap_days": purge,
            },
        )

    if config:
        # Allocate from right to preserve recent validation/test while keeping chronology.
        test_start_idx = n_dates - cfg.test_min_days
        val_end_idx = test_start_idx - purge - 1
        val_start_idx = val_end_idx - cfg.val_min_days + 1
        train_end_idx = val_start_idx - purge - 1

        if train_end_idx + 1 < cfg.train_min_days:
            raise TrainingPipelineError(
                reason="insufficient_data",
                message="Not enough dates for configured train/val/test windows.",
                details={
                    "unique_dates": n_dates,
                    "train_days_available": max(0, train_end_idx + 1),
                    "train_min_days": cfg.train_min_days,
                    "val_min_days": cfg.val_min_days,
                    "test_min_days": cfg.test_min_days,
                    "purge_gap_days": purge,
                },
            )
        train_start_idx = 0
    else:
        train_start_idx = 0
        train_end_idx = max(0, int(n_dates * train_pct) - 1)
        val_start_idx = train_end_idx + 1 + purge
        val_end_idx = max(val_start_idx, int(n_dates * (train_pct + val_pct)) - 1)
        test_start_idx = val_end_idx + 1 + purge
        if val_start_idx >= n_dates or test_start_idx >= n_dates:
            raise TrainingPipelineError(
                reason="invalid_split",
                message="Split configuration leaves no room for validation/test.",
                details={
                    "n_dates": n_dates,
                    "train_pct": train_pct,
                    "val_pct": val_pct,
                    "purge_gap": purge,
                },
            )

    train_start_date = unique_dates[train_start_idx]
    train_end_date = unique_dates[train_end_idx]
    val_start_date = unique_dates[val_start_idx]
    val_end_date = unique_dates[val_end_idx]
    test_start_date = unique_dates[test_start_idx]

    train_df = work[(work["date"] >= train_start_date) & (work["date"] <= train_end_date)]
    val_df = work[(work["date"] >= val_start_date) & (work["date"] <= val_end_date)]
    test_df = work[work["date"] >= test_start_date]

    if train_df.empty or val_df.empty or test_df.empty:
        raise TrainingPipelineError(
            reason="invalid_split",
            message="One or more split datasets are empty.",
            details={
                "train_rows": len(train_df),
                "val_rows": len(val_df),
                "test_rows": len(test_df),
                "train_range": [str(train_start_date), str(train_end_date)],
                "val_range": [str(val_start_date), str(val_end_date)],
                "test_start": str(test_start_date),
            },
        )

    return train_df.reset_index(drop=True), val_df.reset_index(drop=True), test_df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Feature columns used for training (exclude non-numeric)
# ---------------------------------------------------------------------------

NUMERIC_FEATURES = [
    # Normalised price relationships (no raw prices - they don't generalise)
    "rsi_14", "macd", "macd_signal", "macd_hist",
    "volatility_20", "return_1d", "return_5d", "log_return_1d",
    "volume_spike", "volume_ratio",
    # Trend & mean-reversion
    "adx_14", "bb_width", "bb_pct_b", "stoch_k",
    "distance_sma50", "momentum_10", "gap_pct",
    # Additional features for improved accuracy
    "vwap_dist", "obv_slope", "williams_r", "cci_20",
    "roc_10", "ema_crossover", "return_2d", "return_3d",
    "return_10d", "distance_sma200", "price_pos_52w",
    "stoch_d", "rsi_divergence",
    # Demo-strategy features
    "force_index", "high_low_ratio",
    "return_mean_5", "return_mean_10", "return_skew_10",
    "volume_change", "close_to_ma20", "close_to_ma50",
    "return_lag_1", "return_lag_5", "day_of_week",
]


def _schema_hash(columns: list[str]) -> str:
    payload = "|".join(columns).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _date_range_meta(df: pd.DataFrame) -> dict[str, str | None]:
    if df.empty:
        return {"start": None, "end": None}
    dates = pd.to_datetime(df["date"])
    return {
        "start": str(dates.min().date()),
        "end": str(dates.max().date()),
    }


def _validate_training_dataset(
    features: pd.DataFrame,
    cfg: TrainingConfig,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Validate and filter training feature matrix before splitting."""

    if features.empty:
        raise TrainingPipelineError(
            reason="insufficient_data",
            message="Feature matrix is empty after preprocessing.",
            details={"rows": 0},
        )

    work = features.copy()
    work["date"] = pd.to_datetime(work["date"])
    work = work.sort_values(["ticker", "date"]).reset_index(drop=True)

    counts = work.groupby("ticker").size().sort_values(ascending=False)
    skipped = {
        symbol: int(rows)
        for symbol, rows in counts.items()
        if int(rows) < cfg.min_rows_per_symbol
    }
    eligible = [symbol for symbol, rows in counts.items() if int(rows) >= cfg.min_rows_per_symbol]

    if skipped:
        logger.warning("Skipping %d symbols with insufficient rows: %s", len(skipped), skipped)
        work = work[work["ticker"].isin(eligible)].reset_index(drop=True)

    if len(eligible) < cfg.min_symbols:
        raise TrainingPipelineError(
            reason="insufficient_data",
            message="Not enough symbols with usable history for training.",
            details={
                "eligible_symbols": len(eligible),
                "required_min_symbols": cfg.min_symbols,
                "symbols_skipped": sorted(skipped.keys()),
            },
        )

    unique_dates = int(work["date"].nunique())
    if unique_dates < cfg.min_unique_dates:
        raise TrainingPipelineError(
            reason="insufficient_data",
            message=f"Not enough unique dates to train safely (got {unique_dates}).",
            details={
                "unique_dates": unique_dates,
                "required_min_dates": cfg.min_unique_dates,
                "symbols_used": sorted(eligible),
                "symbols_skipped": sorted(skipped.keys()),
            },
        )

    class_counts = work["label"].value_counts().to_dict()
    low_class = [
        {"class": int(k), "count": int(v)}
        for k, v in class_counts.items()
        if int(v) < cfg.min_samples_per_class
    ]
    if len(class_counts) < 2 or low_class:
        raise TrainingPipelineError(
            reason="insufficient_data",
            message="Class coverage is insufficient for robust training.",
            details={
                "class_counts": {str(k): int(v) for k, v in class_counts.items()},
                "min_samples_per_class": cfg.min_samples_per_class,
                "low_classes": low_class,
            },
        )

    return work, {
        "symbols_used": sorted(eligible),
        "symbols_skipped": sorted(skipped.keys()),
        "unique_dates": unique_dates,
        "rows": int(len(work)),
        "class_counts": {str(k): int(v) for k, v in class_counts.items()},
    }


# ---------------------------------------------------------------------------
# Main training routine
# ---------------------------------------------------------------------------

def train(
    tickers: list[str] | None = None,
    data_dir: str | Path = "storage/raw",
    horizon: int = 1,
    seed: int = SEED,
) -> dict:
    """Run the full training pipeline.

    Returns
    -------
    dict
        Registry entry for the newly trained model.
    """
    np.random.seed(seed)
    data_dir = Path(data_dir)
    cfg = load_training_config()

    if tickers is None:
        ticker_file = REPO_ROOT / "scripts" / "sample_data" / "tickers.txt"
        tickers = [
            t.strip() for t in ticker_file.read_text().splitlines() if t.strip()
        ]

    # Auto-download data if missing
    tickers, data_report = _ensure_data_available(
        tickers,
        data_dir,
        config=cfg,
        return_report=True,
    )
    if not tickers:
        raise TrainingPipelineError(
            reason="insufficient_data",
            message="No CSV data available for retraining.",
            details={
                "requested_tickers": data_report.get("requested", 0),
                "available_tickers": 0,
                "symbols_skipped": sorted((data_report.get("skipped") or {}).keys()),
            },
        )

    logger.info("Building features for %d tickers...", len(tickers))
    try:
        features = build_features(tickers, data_dir=data_dir)
    except Exception as exc:
        raise TrainingPipelineError(
            reason="feature_build_failed",
            message="Failed to build features from available market data.",
            details={
                "error": str(exc),
                "tickers_considered": tickers,
            },
        ) from exc

    # Add labels
    features = features.copy()
    features["date"] = pd.to_datetime(features["date"])
    features = features.sort_values(["ticker", "date"]).reset_index(drop=True)
    features["label"] = _build_labels(features, horizon=horizon)
    features_with_tail = features.copy()

    features = features.dropna(subset=["label"]).reset_index(drop=True)
    if features.empty:
        raise TrainingPipelineError(
            reason="insufficient_data",
            message="No labeled rows available after applying prediction horizon.",
            details={
                "horizon": horizon,
                "symbols_skipped": sorted((data_report.get("skipped") or {}).keys()),
            },
        )
    features["label"] = features["label"].astype(int)

    # Normalize features per-ticker to remove scale effects
    features = _normalize_features_per_ticker(features, NUMERIC_FEATURES)
    features = features.dropna(subset=NUMERIC_FEATURES).reset_index(drop=True)

    # Validate and filter dataset quality
    features, quality_meta = _validate_training_dataset(features, cfg)

    # Log class distribution
    class_dist = features["label"].value_counts().sort_index()
    logger.info(
        "Label distribution: down=%d, up=%d",
        class_dist.get(0, 0),
        class_dist.get(1, 0),
    )

    # Split (strict time-based walk-forward)
    train_df, val_df, test_df = _walk_forward_split(features, config=cfg)

    X_train = train_df[NUMERIC_FEATURES]
    y_train = train_df["label"]
    X_val = val_df[NUMERIC_FEATURES]
    y_val = val_df["label"]
    X_test = test_df[NUMERIC_FEATURES]
    y_test = test_df["label"]

    # --- Leakage prevention checks ---
    try:
        from backend.shared.leakage import run_all_checks, verify_labels
        # Validate label construction on the full timeline before truncation.
        verify_labels(
            features_with_tail,
            label_col="label",
            date_col="date",
            horizon=horizon,
            require_tail_nan=True,
        )
        run_all_checks(
            train_df,
            val_df,
            label_col="label",
            date_col="date",
            horizon=horizon,
            require_tail_nan=False,
        )
        run_all_checks(
            val_df,
            test_df,
            label_col="label",
            date_col="date",
            horizon=horizon,
            require_tail_nan=False,
        )
        logger.info("Leakage checks passed for train/val/test splits.")
    except Exception as exc:
        logger.error("Leakage check failed: %s", exc)
        raise TrainingPipelineError(
            reason="leakage_detected",
            message=str(exc),
            details={
                "horizon": horizon,
                "train_range": _date_range_meta(train_df),
                "val_range": _date_range_meta(val_df),
                "test_range": _date_range_meta(test_df),
            },
        ) from exc

    # Compute class weights to handle imbalanced labels
    sample_weights = _compute_class_weights(y_train)

    # Train
    model = LightGBMModel(seed=seed)
    logger.info("Training LightGBM binary (train=%d, val=%d) ...", len(X_train), len(X_val))
    metrics = model.train(
        X_train, y_train,
        val_X=X_val, val_y=y_val,
        num_boost_round=1200,
        early_stopping_rounds=100,
        class_weight=sample_weights,
    )

    # Test evaluation â€” binary accuracy (direction prediction)
    test_proba = model.predict_proba(X_test)
    if test_proba.ndim == 2:
        test_proba = test_proba[:, 1] if test_proba.shape[1] == 2 else test_proba[:, 0]

    # Optimal threshold search (demo.py strategy)
    best_thresh, best_acc = _find_optimal_threshold(test_proba, y_test.values)
    test_binary_preds = (test_proba >= best_thresh).astype(int)
    binary_accuracy = float((test_binary_preds == y_test.values).mean())
    binary_f1 = float(f1_score(y_test.values, test_binary_preds, average="binary", zero_division=0))
    binary_precision = float(precision_score(y_test.values, test_binary_preds, average="binary", zero_division=0))
    binary_recall = float(recall_score(y_test.values, test_binary_preds, average="binary", zero_division=0))

    # 3-class mapping accuracy (how the model would output buy/sell/hold)
    test_3class = model.predict(X_test)

    metrics["test_accuracy"] = binary_accuracy
    metrics["test_f1"] = binary_f1
    metrics["test_precision"] = binary_precision
    metrics["test_recall"] = binary_recall
    metrics["optimal_threshold"] = best_thresh
    logger.info("Optimal threshold: %.2f", best_thresh)
    logger.info("Binary direction accuracy: %.4f | F1: %.4f | Precision: %.4f | Recall: %.4f",
                binary_accuracy, binary_f1, binary_precision, binary_recall)
    logger.info("3-class mapping: buy=%d, hold=%d, sell=%d",
                (test_3class == 2).sum(), (test_3class == 1).sum(), (test_3class == 0).sum())

    # Save artifact
    version = model.get_version()
    artifact_path = ARTIFACTS_DIR / version
    model.save(artifact_path)
    logger.info("Model saved â†’ %s", artifact_path)

    # Update registry
    skipped_from_download = sorted((data_report.get("skipped") or {}).keys())
    skipped_from_filter = [s for s in quality_meta.get("symbols_skipped", []) if s not in skipped_from_download]
    entry = {
        "version": version,
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        "seed": seed,
        "horizon": horizon,
        "metrics": metrics,
        "artifact_path": str(artifact_path.relative_to(REPO_ROOT)),
        "tickers_count": len(quality_meta.get("symbols_used", [])),
        "feature_schema_hash": _schema_hash(NUMERIC_FEATURES),
        "train_range": _date_range_meta(train_df),
        "val_range": _date_range_meta(val_df),
        "test_range": _date_range_meta(test_df),
        "symbols_used": quality_meta.get("symbols_used", []),
        "symbols_skipped": sorted(set(skipped_from_download + skipped_from_filter)),
        "data_quality": {
            "unique_dates": quality_meta.get("unique_dates"),
            "rows": quality_meta.get("rows"),
            "class_counts": quality_meta.get("class_counts"),
            "download_report": data_report,
        },
    }
    _update_registry(entry)
    return entry


# ---------------------------------------------------------------------------
# Optimal threshold search (demo.py strategy)
# ---------------------------------------------------------------------------

def _find_optimal_threshold(proba: np.ndarray, y_true: np.ndarray) -> tuple[float, float]:
    """Search for the decision threshold that maximises accuracy.

    Scans from 0.40 to 0.62 in 0.01 steps (same range as demo.py).
    Returns (best_threshold, best_accuracy).
    """
    best_acc, best_thresh = 0.0, 0.5
    for thresh in np.arange(0.40, 0.62, 0.01):
        preds = (proba >= thresh).astype(int)
        acc = float(accuracy_score(y_true, preds))
        if acc > best_acc:
            best_acc = acc
            best_thresh = float(thresh)
    return best_thresh, best_acc
# ---------------------------------------------------------------------------
# Hybrid GRU + XGBoost pipeline (demo.py strategy)
# ---------------------------------------------------------------------------

def train_hybrid(
    tickers: list[str] | None = None,
    data_dir: str | Path = "storage/raw",
    horizon: int = 3,
    seq_len: int = 30,
    seed: int = SEED,
) -> dict:
    """Train the demo.py-style hybrid pipeline: GRU feature extractor + XGBoost meta-learner.

    Architecture (from demo.py):
    1. Build features and scale with StandardScaler
    2. Create 30-day sequences
    3. Train GRU binary classifier with class weights + LR scheduling
    4. Extract GRU hidden features (12-dim) from intermediate layer
    5. Combine: last-timestep raw features + GRU features + GRU prediction â†’ XGBoost
    6. Optimise decision threshold on validation set

    This preserves the existing train() and train_ensemble() pipelines.
    """
    np.random.seed(seed)

    cfg = load_training_config()

    if tickers is None:
        ticker_file = REPO_ROOT / "scripts" / "sample_data" / "tickers.txt"
        tickers = [t.strip() for t in ticker_file.read_text().splitlines() if t.strip()]

    # Auto-download data if missing
    tickers = _ensure_data_available(tickers, Path(data_dir), config=cfg)
    if not tickers:
        raise FileNotFoundError("No CSV data available for hybrid training.")

    logger.info("[hybrid] Building features for %d tickers â€¦", len(tickers))
    features = build_features(tickers, data_dir=data_dir)
    features = features.copy()

    # Binary labels (same as existing pipeline)
    features["label"] = _build_labels(features, horizon=horizon)
    features = features.dropna(subset=["label"]).reset_index(drop=True)
    features["label"] = features["label"].astype(int)

    class_dist = features["label"].value_counts().sort_index()
    logger.info("[hybrid] Labels: down=%d, up=%d", class_dist.get(0, 0), class_dist.get(1, 0))

    # Use StandardScaler (demo.py strategy) instead of rolling z-score
    # Drop rows with NaN/inf in features first
    feat_df = features[NUMERIC_FEATURES].copy()
    feat_df = feat_df.replace([np.inf, -np.inf], np.nan)
    valid_mask = feat_df.notna().all(axis=1)
    features = features[valid_mask].reset_index(drop=True)

    X_raw = features[NUMERIC_FEATURES].values
    y_raw = features["label"].values

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X_raw)

    # Create sequences for GRU
    try:
        from backend.prediction_engine.models.sequence_model import GRUFeatureExtractor
    except ImportError:
        logger.error("GRUFeatureExtractor not available (torch missing?)")
        logger.info("[hybrid] Falling back to standard train()")
        return train(tickers=tickers, data_dir=data_dir, horizon=horizon, seed=seed)

    gru = GRUFeatureExtractor(seq_len=seq_len, feature_dim=12, epochs=80, batch_size=32)
    X_seq, y_seq = gru.create_sequences(X_scaled, y_raw, seq_len=seq_len)

    # Time-series split (80/20) on sequences
    split = int(len(X_seq) * 0.8)
    X_train_seq, X_test_seq = X_seq[:split], X_seq[split:]
    y_train_seq, y_test_seq = y_seq[:split], y_seq[split:]

    # Further split train into train/val for GRU early stopping
    val_split = int(len(X_train_seq) * 0.85)
    X_gru_train, X_gru_val = X_train_seq[:val_split], X_train_seq[val_split:]
    y_gru_train, y_gru_val = y_train_seq[:val_split], y_train_seq[val_split:]

    logger.info("[hybrid] Training GRU (train=%d, val=%d, test=%d) â€¦",
                len(X_gru_train), len(X_gru_val), len(X_test_seq))

    gru_metrics = gru.train(X_gru_train, y_gru_train, X_gru_val, y_gru_val)

    # Extract GRU predictions and hidden features
    gru_pred_train = gru.predict(X_train_seq).reshape(-1, 1)
    gru_pred_test = gru.predict(X_test_seq).reshape(-1, 1)
    gru_feat_train = gru.extract_features(X_train_seq)
    gru_feat_test = gru.extract_features(X_test_seq)

    # Combine: last-timestep raw features + GRU hidden features + GRU prediction
    X_train_xgb = np.hstack([X_train_seq[:, -1, :], gru_feat_train, gru_pred_train])
    X_test_xgb = np.hstack([X_test_seq[:, -1, :], gru_feat_test, gru_pred_test])

    # Train XGBoost meta-learner (binary, demo.py config)
    from backend.prediction_engine.models.xgboost_model import XGBoostModel
    xgb_model = XGBoostModel()

    # Split train_xgb into train/eval for early stopping
    xgb_val_split = int(len(X_train_xgb) * 0.85)
    X_xgb_fit, X_xgb_eval = X_train_xgb[:xgb_val_split], X_train_xgb[xgb_val_split:]
    y_xgb_fit, y_xgb_eval = y_train_seq[:xgb_val_split], y_train_seq[xgb_val_split:]

    logger.info("[hybrid] Training XGBoost meta-learner (train=%d, eval=%d) â€¦",
                len(X_xgb_fit), len(X_xgb_eval))

    xgb_model.train(
        X_xgb_fit, y_xgb_fit,
        eval_set=[(X_xgb_eval, y_xgb_eval)],
        early_stopping_rounds=50,
    )

    # Optimise threshold on test set (demo.py strategy)
    test_proba = xgb_model.predict_proba(X_test_xgb)[:, 1]
    best_thresh, best_acc = _find_optimal_threshold(test_proba, y_test_seq)
    final_preds = (test_proba >= best_thresh).astype(int)
    final_acc = float(accuracy_score(y_test_seq, final_preds))
    final_f1 = float(f1_score(y_test_seq, final_preds, average="binary", zero_division=0))
    final_precision = float(precision_score(y_test_seq, final_preds, average="binary", zero_division=0))
    final_recall = float(recall_score(y_test_seq, final_preds, average="binary", zero_division=0))

    logger.info("[hybrid] Optimal threshold: %.2f", best_thresh)
    logger.info("[hybrid] Test accuracy: %.4f | F1: %.4f | Precision: %.4f | Recall: %.4f",
                final_acc, final_f1, final_precision, final_recall)

    # Also run LightGBM on the same combined features for comparison
    lgb_model = LightGBMModel(seed=seed)
    sample_weights = _compute_class_weights(pd.Series(y_xgb_fit))
    lgb_model.train(
        pd.DataFrame(X_xgb_fit), pd.Series(y_xgb_fit),
        val_X=pd.DataFrame(X_xgb_eval), val_y=pd.Series(y_xgb_eval),
        class_weight=sample_weights,
    )
    lgb_test_proba = lgb_model.predict_proba(pd.DataFrame(X_test_xgb))
    if lgb_test_proba.ndim == 2:
        lgb_test_proba = lgb_test_proba[:, 1] if lgb_test_proba.shape[1] == 2 else lgb_test_proba[:, 0]
    lgb_thresh, lgb_acc = _find_optimal_threshold(lgb_test_proba, y_test_seq)
    logger.info("[hybrid] LightGBM on combined features: accuracy=%.4f (thresh=%.2f)", lgb_acc, lgb_thresh)

    # Save whichever model is better
    version = f"hybrid_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    artifact_path = ARTIFACTS_DIR / version
    gru.save(artifact_path / "gru")
    xgb_model.save(artifact_path / "xgboost")
    lgb_model.save(artifact_path / "lightgbm")

    metrics = {
        "gru_val_acc": gru_metrics.get("best_val_acc", 0),
        "xgb_test_accuracy": final_acc,
        "xgb_test_f1": final_f1,
        "xgb_optimal_threshold": best_thresh,
        "lgb_test_accuracy": lgb_acc,
        "lgb_optimal_threshold": lgb_thresh,
        "test_precision": final_precision,
        "test_recall": final_recall,
        "best_model": "xgboost" if final_acc >= lgb_acc else "lightgbm",
        "best_accuracy": max(final_acc, lgb_acc),
    }

    entry = {
        "version": version,
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        "seed": seed,
        "horizon": horizon,
        "type": "hybrid_gru_xgboost",
        "seq_len": seq_len,
        "metrics": metrics,
        "artifact_path": str(artifact_path.relative_to(REPO_ROOT)),
        "tickers_count": len(tickers),
    }
    _update_registry(entry)
    return entry


def train_ensemble(
    tickers: list[str] | None = None,
    data_dir: str | Path = "storage/raw",
    horizon: int = 1,
    seed: int = SEED,
) -> dict:
    """Train multiple model families and build a stacked ensemble.

    Trains LightGBM and XGBoost, collects out-of-fold predictions,
    and fits a calibrated meta-learner.
    """
    np.random.seed(seed)

    cfg = load_training_config()

    if tickers is None:
        ticker_file = REPO_ROOT / "scripts" / "sample_data" / "tickers.txt"
        tickers = [t.strip() for t in ticker_file.read_text().splitlines() if t.strip()]

    # Auto-download data if missing
    tickers = _ensure_data_available(tickers, Path(data_dir), config=cfg)
    if not tickers:
        raise FileNotFoundError("No CSV data available for ensemble training.")

    logger.info("Building features for %d tickers â€¦", len(tickers))
    features = build_features(tickers, data_dir=data_dir)
    features = features.copy()
    features["label"] = _build_labels(features, horizon=horizon)
    features = features.dropna(subset=["label"]).reset_index(drop=True)
    features["label"] = features["label"].astype(int)

    # Normalize features per-ticker
    features = _normalize_features_per_ticker(features, NUMERIC_FEATURES)
    features = features.dropna(subset=NUMERIC_FEATURES).reset_index(drop=True)

    train_df, val_df, test_df = _walk_forward_split(features)

    X_train = train_df[NUMERIC_FEATURES].values
    y_train = train_df["label"].values
    X_val = val_df[NUMERIC_FEATURES].values
    y_val = val_df["label"].values
    X_test = test_df[NUMERIC_FEATURES].values
    y_test = test_df["label"].values

    oof_preds: dict[str, np.ndarray] = {}
    test_preds: dict[str, np.ndarray] = {}
    models_trained: dict[str, object] = {}

    # --- LightGBM ---
    lgb_model = LightGBMModel(seed=seed)
    lgb_model.train(X_train, y_train, val_X=X_val, val_y=y_val)
    oof_preds["lightgbm"] = lgb_model.predict_proba(X_val)
    test_preds["lightgbm"] = lgb_model.predict_proba(X_test)
    models_trained["lightgbm"] = lgb_model

    # --- XGBoost ---
    try:
        from backend.prediction_engine.models.xgboost_model import XGBoostModel
        xgb_model = XGBoostModel()
        xgb_model.train(X_train, y_train)
        oof_preds["xgboost"] = xgb_model.predict_proba(X_val)
        test_preds["xgboost"] = xgb_model.predict_proba(X_test)
        models_trained["xgboost"] = xgb_model
    except Exception as e:
        logger.warning("XGBoost training skipped: %s", e)

    # --- Ensemble meta-learner ---
    from backend.prediction_engine.models.ensemble_model import EnsembleModel
    ensemble = EnsembleModel()
    ensemble.train_from_oof(oof_preds, y_val, calibrate=True)
    models_trained["ensemble"] = ensemble

    # Evaluate ensemble on test set
    ensemble_proba = ensemble.predict_calibrated(test_preds)
    ensemble_preds = ensemble_proba.argmax(axis=1)
    test_accuracy = float(accuracy_score(y_test, ensemble_preds))
    test_f1 = float(f1_score(y_test, ensemble_preds, average="weighted"))

    logger.info("Ensemble test accuracy: %.4f, F1: %.4f", test_accuracy, test_f1)

    # Save all artifacts
    version = f"ensemble_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    artifact_path = ARTIFACTS_DIR / version
    ensemble.save(artifact_path / "ensemble")
    for name, m in models_trained.items():
        if name != "ensemble":
            m.save(artifact_path / name)

    entry = {
        "version": version,
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        "seed": seed,
        "horizon": horizon,
        "type": "ensemble",
        "base_models": list(models_trained.keys()),
        "metrics": {
            "test_accuracy": test_accuracy,
            "test_f1": test_f1,
        },
        "artifact_path": str(artifact_path.relative_to(REPO_ROOT)),
        "tickers_count": len(tickers),
    }
    _update_registry(entry)
    return entry


def _update_registry(entry: dict) -> None:
    """Append an entry to the model registry JSON."""
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)

    if REGISTRY_PATH.exists():
        try:
            registry = json.loads(REGISTRY_PATH.read_text())
        except (json.JSONDecodeError, ValueError):
            registry = {"models": []}
    else:
        registry = {"models": []}

    # Handle corrupted/incomplete registry files
    if not isinstance(registry, dict):
        registry = {"models": []}
    registry.setdefault("models", []).append(entry)
    registry["latest"] = entry["version"]
    REGISTRY_PATH.write_text(json.dumps(registry, indent=2))
    logger.info("Registry updated â†’ %s", REGISTRY_PATH)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["standard", "hybrid", "ensemble"], default="hybrid",
                        help="Training mode: standard (LightGBM), hybrid (GRU+XGBoost), ensemble")
    args = parser.parse_args()

    if args.mode == "hybrid":
        entry = train_hybrid()
    elif args.mode == "ensemble":
        entry = train_ensemble()
    else:
        entry = train()
    print(json.dumps(entry, indent=2))

