"""Regime-aware cross-sectional ranking engine for offline training.

This module upgrades the prediction stack from a single binary classifier into
an explicit 4-layer architecture:
1) regime detection
2) alpha/ranking prediction
3) trade filtering
4) portfolio construction

All computations are point-in-time and train/validation/test splits are
strictly time-ordered.
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)
from sklearn.base import BaseEstimator
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.frozen import FrozenEstimator
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import confusion_matrix, roc_auc_score
from sklearn.preprocessing import StandardScaler

from backend.ml_platform.universe_definitions import get_symbol_tags
from backend.prediction_engine.training.trainer import NUMERIC_FEATURES, TrainingConfig, TrainingPipelineError

try:
    from lightgbm import LGBMClassifier, LGBMRanker, LGBMRegressor
except Exception:  # pragma: no cover - optional dependency at import time
    LGBMClassifier = None  # type: ignore[assignment]
    LGBMRegressor = None  # type: ignore[assignment]
    LGBMRanker = None  # type: ignore[assignment]


REGIME_COLUMNS = [
    "regime_trending_up",
    "regime_trending_down",
    "regime_sideways",
    "regime_high_vol",
    "regime_low_vol",
    "regime_risk_on",
    "regime_risk_off",
]

ENGINEERED_COLUMNS = [
    "ret_1",
    "ret_3",
    "ret_5",
    "ret_10",
    "realized_vol_5",
    "realized_vol_20",
    "atr_pct",
    "z_ret_20",
    "z_volume_20",
    "gap_z_20",
    "trend_persistence_10",
    "mean_reversion_score",
    "stock_return_1d_minus_nifty_return_1d",
    "stock_return_5d_minus_nifty_return_5d",
    "sector_relative_strength_5d",
    "sector_relative_strength_20d",
    "benchmark_relative_momentum",
    "market_breadth_feature",
    "sector_breadth_feature",
    "beta_to_benchmark_63d",
    "rolling_corr_to_benchmark_20d",
    "benchmark_rel_strength",
    "sector_rel_strength",
    "breadth_advancers",
    "breadth_decliners",
    "breadth_momentum_5",
    "drawdown_63",
    "recovery_20",
]

TARGET_COLUMNS = [
    "target_next_day_return",
    "target_next_3d_return",
    "target_excess_return",
    "target_rank_pct",
    "target_top_bucket",
    "target_bottom_bucket",
    "target_top_bottom_label",
    "target_top_decile",
    "target_downside_aware",
    "target_opportunity_score",
]


@dataclass(frozen=True)
class RegimeRankingConfig:
    mode: str = "classification"  # classification | regression | ranker
    horizon_bars: int = 3
    max_positions: int = 8
    min_confidence: float = 0.55
    downside_penalty: float = 0.50
    risk_off_penalty: float = 0.35
    top_bucket_pct: float = 0.20
    bottom_bucket_pct: float = 0.20
    include_day_of_week: bool = False
    min_trade_alert_threshold: int = 25
    max_dominant_feature_pct: float = 0.40
    enable_sequence_model: bool = False
    random_state: int = 42

    @classmethod
    def from_env(cls, *, default_horizon: int = 3, default_seed: int = 42) -> "RegimeRankingConfig":
        mode = (os.getenv("RANKING_MODEL_MODE", "classification").strip().lower() or "classification")
        if mode not in {"classification", "regression", "ranker"}:
            mode = "classification"
        return cls(
            mode=mode,
            horizon_bars=max(1, int(os.getenv("RANKING_HORIZON_BARS", str(default_horizon)))),
            max_positions=max(1, int(os.getenv("RANKING_MAX_POSITIONS", "8"))),
            min_confidence=float(os.getenv("RANKING_MIN_CONFIDENCE", "0.55")),
            downside_penalty=float(os.getenv("RANKING_DOWNSIDE_PENALTY", "0.50")),
            risk_off_penalty=float(os.getenv("RANKING_RISK_OFF_PENALTY", "0.35")),
            top_bucket_pct=float(os.getenv("RANKING_TOP_BUCKET_PCT", "0.20")),
            bottom_bucket_pct=float(os.getenv("RANKING_BOTTOM_BUCKET_PCT", "0.20")),
            include_day_of_week=(os.getenv("RANKING_INCLUDE_DAY_OF_WEEK", "false").strip().lower() in {"1", "true", "yes", "on", "y"}),
            min_trade_alert_threshold=max(1, int(os.getenv("RANKING_MIN_TRADES_ALERT", "25"))),
            enable_sequence_model=(os.getenv("RANKING_ENABLE_SEQUENCE_MODEL", "false").strip().lower() in {"1", "true", "yes", "on", "y"}),
            random_state=int(os.getenv("RANKING_RANDOM_STATE", str(default_seed))),
        )


def _sigmoid(x: np.ndarray | float) -> np.ndarray | float:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30.0, 30.0)))


def _safe_div(n: float, d: float) -> float:
    if d == 0 or not np.isfinite(d):
        return 0.0
    return float(n / d)


def _rolling_zscore(series: pd.Series, window: int = 20) -> pd.Series:
    mean = series.rolling(window, min_periods=max(5, window // 2)).mean()
    std = series.rolling(window, min_periods=max(5, window // 2)).std()
    z = (series - mean) / std.replace(0.0, np.nan)
    return z.replace([np.inf, -np.inf], np.nan).fillna(0.0)


def _profit_factor(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    gains = returns[returns > 0].sum()
    losses = returns[returns < 0].sum()
    if losses == 0:
        return float(gains > 0) * 10.0
    return float(gains / abs(losses))


def _max_drawdown(daily_returns: pd.Series) -> float:
    if daily_returns.empty:
        return 0.0
    equity = (1.0 + daily_returns.fillna(0.0)).cumprod()
    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0
    return float(abs(drawdown.min()))


def _sharpe(daily_returns: pd.Series) -> float:
    if daily_returns.empty:
        return 0.0
    std = float(daily_returns.std())
    if std <= 0:
        return 0.0
    return float((daily_returns.mean() / std) * math.sqrt(252.0))


def _sortino(daily_returns: pd.Series) -> float:
    if daily_returns.empty:
        return 0.0
    downside = daily_returns[daily_returns < 0]
    std = float(downside.std()) if not downside.empty else 0.0
    if std <= 0:
        return 0.0
    return float((daily_returns.mean() / std) * math.sqrt(252.0))


def _risk_objective(metrics: dict[str, float]) -> float:
    # Explicitly risk-adjusted objective; accuracy is not used for selection.
    sharpe = float(metrics.get("sharpe", 0.0))
    sortino = float(metrics.get("sortino", 0.0))
    profit_factor = float(metrics.get("profit_factor", 0.0))
    max_dd = float(metrics.get("max_drawdown", 0.0))
    precision_exec = float(metrics.get("precision_executed", 0.0))
    return sharpe + 0.35 * sortino + 0.20 * profit_factor + 0.25 * precision_exec - 1.8 * max_dd


def _split_by_time(
    frame: pd.DataFrame,
    cfg: TrainingConfig,
    *,
    date_col: str = "date",
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    work = frame.copy()
    work[date_col] = pd.to_datetime(work[date_col])
    unique_dates = pd.Index(sorted(work[date_col].dropna().unique()))
    required = cfg.train_min_days + cfg.val_min_days + cfg.test_min_days + 2 * cfg.purge_gap_days

    if len(unique_dates) < required:
        raise TrainingPipelineError(
            reason="insufficient_data",
            message=f"Not enough unique dates to split safely (got {len(unique_dates)}).",
            details={"unique_dates": int(len(unique_dates)), "required_min_dates": int(required)},
        )

    train_end = int(cfg.train_min_days - 1)
    val_start = int(train_end + cfg.purge_gap_days + 1)
    val_end = int(val_start + cfg.val_min_days - 1)
    test_start = int(val_end + cfg.purge_gap_days + 1)
    test_end = int(test_start + cfg.test_min_days - 1)

    if test_end >= len(unique_dates):
        # Use tail-aligned windows while preserving embargo gaps.
        test_end = len(unique_dates) - 1
        test_start = max(0, test_end - cfg.test_min_days + 1)
        val_end = test_start - cfg.purge_gap_days - 1
        val_start = max(0, val_end - cfg.val_min_days + 1)
        train_end = val_start - cfg.purge_gap_days - 1
        if train_end + 1 < cfg.train_min_days:
            raise TrainingPipelineError(
                reason="insufficient_data",
                message="Not enough dates for configured train/val/test windows.",
                details={
                    "unique_dates": int(len(unique_dates)),
                    "required_train_days": int(cfg.train_min_days),
                    "required_val_days": int(cfg.val_min_days),
                    "required_test_days": int(cfg.test_min_days),
                },
            )

    train_dates = unique_dates[: train_end + 1]
    val_dates = unique_dates[val_start : val_end + 1]
    test_dates = unique_dates[test_start : test_end + 1]

    train_df = work[work[date_col].isin(train_dates)].copy()
    val_df = work[work[date_col].isin(val_dates)].copy()
    test_df = work[work[date_col].isin(test_dates)].copy()
    return train_df, val_df, test_df


def _build_regime_features(features: pd.DataFrame) -> pd.DataFrame:
    df = features.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)

    # Sector tags for sector-relative features + explainability.
    df["sector"] = df["ticker"].map(lambda t: get_symbol_tags(str(t)).get("sector", "Unknown"))

    # Ensure required numeric columns exist.
    defaults = {
        "return_1d": 0.0,
        "return_3d": 0.0,
        "return_5d": 0.0,
        "return_10d": 0.0,
        "volatility_20": 0.0,
        "volume_change": 0.0,
        "gap_pct": 0.0,
        "atr_14": 0.0,
        "close": 0.0,
        "distance_sma50": 0.0,
        "momentum_10": 0.0,
        "ema_crossover": 0.0,
        "rsi_14": 50.0,
    }
    for col, default in defaults.items():
        if col not in df.columns:
            df[col] = default

    g = df.groupby("ticker", sort=False)
    close = g["close"]

    df["ret_1"] = close.pct_change(1).replace([np.inf, -np.inf], np.nan)
    df["ret_3"] = close.pct_change(3).replace([np.inf, -np.inf], np.nan)
    df["ret_5"] = close.pct_change(5).replace([np.inf, -np.inf], np.nan)
    df["ret_10"] = close.pct_change(10).replace([np.inf, -np.inf], np.nan)
    df["realized_vol_5"] = g["return_1d"].transform(lambda s: s.rolling(5, min_periods=3).std())
    df["realized_vol_20"] = g["return_1d"].transform(lambda s: s.rolling(20, min_periods=10).std())
    df["atr_pct"] = df["atr_14"] / df["close"].replace(0.0, np.nan)

    df["z_ret_20"] = g["return_1d"].transform(lambda s: _rolling_zscore(s, window=20))
    df["z_volume_20"] = g["volume_change"].transform(lambda s: _rolling_zscore(s, window=20))
    df["gap_z_20"] = g["gap_pct"].transform(lambda s: _rolling_zscore(s, window=20))

    df["trend_persistence_10"] = g["return_1d"].transform(
        lambda s: np.sign(s.fillna(0.0)).rolling(10, min_periods=5).mean()
    )
    df["mean_reversion_score"] = (
        -df["distance_sma50"].fillna(0.0) * 0.6
        + (50.0 - df["rsi_14"].fillna(50.0)).clip(-20.0, 20.0) / 100.0
    )

    # Cross-sectional benchmark + breadth features.
    df["benchmark_return_1d"] = df.groupby("date")["return_1d"].transform("mean")
    df["benchmark_return_5d"] = df.groupby("date")["return_5d"].transform("mean")
    df["benchmark_rel_strength"] = df["return_5d"] - df["benchmark_return_5d"]
    df["sector_return_5d"] = df.groupby(["date", "sector"])["return_5d"].transform("mean")
    df["sector_rel_strength"] = df["return_5d"] - df["sector_return_5d"]

    df["breadth_advancers"] = df.groupby("date")["return_1d"].transform(lambda s: float((s > 0).mean()))
    df["breadth_decliners"] = df.groupby("date")["return_1d"].transform(lambda s: float((s < 0).mean()))
    breadth_daily = (
        df[["date", "breadth_advancers"]]
        .drop_duplicates("date")
        .sort_values("date")
        .set_index("date")["breadth_advancers"]
        .rolling(5, min_periods=2)
        .mean()
    )
    df["breadth_momentum_5"] = df["date"].map(breadth_daily).astype(float)

    # --- Explicit cross-sectional relative features ---
    # stock_return minus benchmark (Nifty proxy = cross-sectional mean)
    df["stock_return_1d_minus_nifty_return_1d"] = df["return_1d"] - df["benchmark_return_1d"]
    df["stock_return_5d_minus_nifty_return_5d"] = df["return_5d"] - df["benchmark_return_5d"]

    # Sector relative strength at 5d and 20d horizons
    df["sector_relative_strength_5d"] = df["return_5d"] - df["sector_return_5d"]
    # 20d sector relative strength
    ret_20d = g["close"].pct_change(20).replace([np.inf, -np.inf], np.nan)
    df["_return_20d"] = ret_20d
    sector_return_20d = df.groupby(["date", "sector"])["_return_20d"].transform("mean")
    df["sector_relative_strength_20d"] = df["_return_20d"] - sector_return_20d

    # Benchmark relative momentum (10-day momentum vs cross-sectional mean)
    if "momentum_10" in df.columns:
        benchmark_momentum = df.groupby("date")["momentum_10"].transform("mean")
        df["benchmark_relative_momentum"] = df["momentum_10"].fillna(0.0) - benchmark_momentum.fillna(0.0)
    else:
        df["benchmark_relative_momentum"] = df["return_5d"] - df["benchmark_return_5d"]

    # Market breadth feature (already computed breadth_advancers)
    df["market_breadth_feature"] = df["breadth_advancers"]

    # Sector breadth feature
    df["sector_breadth_feature"] = df.groupby(["date", "sector"])["return_1d"].transform(
        lambda s: float((s > 0).mean()) if len(s) > 1 else 0.5
    )

    # Beta to benchmark (rolling 63-day)
    def _compute_rolling_beta(group):
        ret = group["return_1d"].values
        bm = group["benchmark_return_1d"].values
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

    df["beta_to_benchmark_63d"] = df.groupby("ticker", group_keys=False).apply(_compute_rolling_beta, include_groups=False)

    # Rolling correlation to benchmark (20-day)
    def _compute_rolling_corr(group):
        ret = group["return_1d"].values
        bm = group["benchmark_return_1d"].values
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

    df["rolling_corr_to_benchmark_20d"] = df.groupby("ticker", group_keys=False).apply(_compute_rolling_corr, include_groups=False)

    # Clean up temp columns
    df.drop(columns=["_return_20d"], errors="ignore", inplace=True)

    # Drawdown / recovery state.
    rolling_max_63 = close.transform(lambda s: s.rolling(63, min_periods=20).max())
    rolling_min_20 = close.transform(lambda s: s.rolling(20, min_periods=10).min())
    df["drawdown_63"] = df["close"] / rolling_max_63.replace(0.0, np.nan) - 1.0
    df["recovery_20"] = df["close"] / rolling_min_20.replace(0.0, np.nan) - 1.0

    # Regime model.
    trend_score = (
        0.45 * df["momentum_10"].fillna(0.0)
        + 0.35 * df["distance_sma50"].fillna(0.0)
        + 0.20 * df["ema_crossover"].fillna(0.0)
    )
    df["regime_trending_up"] = (trend_score > 0.015).astype(int)
    df["regime_trending_down"] = (trend_score < -0.015).astype(int)
    df["regime_sideways"] = ((df["regime_trending_up"] == 0) & (df["regime_trending_down"] == 0)).astype(int)

    vol_ref = g["volatility_20"].transform(
        lambda s: s.rolling(126, min_periods=20).median().fillna(s.median())
    )
    df["regime_high_vol"] = (df["volatility_20"].fillna(0.0) > vol_ref.fillna(0.0)).astype(int)
    df["regime_low_vol"] = (1 - df["regime_high_vol"]).astype(int)

    risk_score = 0.6 * df["breadth_advancers"].fillna(0.5) + 0.4 * (df["benchmark_return_1d"].fillna(0.0) > 0).astype(float)
    df["regime_risk_on"] = (risk_score >= 0.52).astype(int)
    df["regime_risk_off"] = (1 - df["regime_risk_on"]).astype(int)

    trend_name = np.where(
        df["regime_trending_up"] == 1,
        "trending_up",
        np.where(df["regime_trending_down"] == 1, "trending_down", "sideways"),
    )
    vol_name = np.where(df["regime_high_vol"] == 1, "high_volatility", "low_volatility")
    risk_name = np.where(df["regime_risk_on"] == 1, "risk_on", "risk_off")
    df["regime_label"] = pd.Series(trend_name, index=df.index) + "|" + pd.Series(vol_name, index=df.index) + "|" + pd.Series(risk_name, index=df.index)

    for col in ENGINEERED_COLUMNS + REGIME_COLUMNS:
        if col in df.columns:
            df[col] = df[col].replace([np.inf, -np.inf], np.nan)
    return df


def build_targets(
    frame: pd.DataFrame,
    *,
    horizon_bars: int = 1,
    downside_penalty: float = 0.50,
    top_bucket_pct: float = 0.20,
    bottom_bucket_pct: float = 0.20,
) -> pd.DataFrame:
    df = frame.copy()
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    horizon = max(1, int(horizon_bars))
    g = df.groupby("ticker", sort=False)

    df["target_next_day_return"] = g["close"].shift(-1) / df["close"] - 1.0
    df["target_next_3d_return"] = g["close"].shift(-3) / df["close"] - 1.0
    df["target_horizon_return"] = g["close"].shift(-horizon) / df["close"] - 1.0

    # Benchmark excess return computed in point-in-time cross-section.
    benchmark_next = df.groupby("date")["target_next_day_return"].transform("mean")
    df["target_excess_return"] = df["target_next_day_return"] - benchmark_next

    # Percentile rank per date
    pct_rank = df.groupby("date")["target_horizon_return"].transform(lambda s: s.rank(pct=True))
    df["target_rank_pct"] = pct_rank

    # Top-decile opportunity classification by date.
    df["target_top_decile"] = (pct_rank >= 0.90).astype(float)

    # Cross-sectional bucket labels (Option A from config)
    df["target_top_bucket"] = (pct_rank >= (1.0 - top_bucket_pct)).astype(float)
    df["target_bottom_bucket"] = (pct_rank <= bottom_bucket_pct).astype(float)
    # Binary label: 1=top, 0=bottom, NaN=middle (to be dropped during training)
    top_bottom = pd.Series(np.nan, index=df.index)
    top_bottom[df["target_top_bucket"] == 1] = 1.0
    top_bottom[df["target_bottom_bucket"] == 1] = 0.0
    df["target_top_bottom_label"] = top_bottom

    downside_ref = (
        df.groupby("ticker")["return_1d"]
        .transform(lambda s: s.clip(upper=0.0).rolling(20, min_periods=10).std())
        .fillna(0.0)
    )
    df["target_downside_aware"] = df["target_horizon_return"] - float(downside_penalty) * downside_ref
    df["target_opportunity_score"] = (
        0.45 * df["target_excess_return"].fillna(0.0)
        + 0.35 * df["target_next_3d_return"].fillna(0.0)
        + 0.20 * df["target_downside_aware"].fillna(0.0)
    )
    return df


def build_regime_ranking_frame(
    features: pd.DataFrame,
    *,
    horizon_bars: int = 1,
    downside_penalty: float = 0.50,
    top_bucket_pct: float = 0.20,
    bottom_bucket_pct: float = 0.20,
) -> pd.DataFrame:
    enriched = _build_regime_features(features)
    targeted = build_targets(
        enriched,
        horizon_bars=horizon_bars,
        downside_penalty=downside_penalty,
        top_bucket_pct=top_bucket_pct,
        bottom_bucket_pct=bottom_bucket_pct,
    )
    return targeted

def _build_feature_matrix(frame: pd.DataFrame, *, include_day_of_week: bool = False) -> tuple[pd.DataFrame, list[str]]:
    feature_cols = list(dict.fromkeys([*NUMERIC_FEATURES, *ENGINEERED_COLUMNS, *REGIME_COLUMNS]))
    if not include_day_of_week and "day_of_week" in feature_cols:
        feature_cols.remove("day_of_week")
    available = [c for c in feature_cols if c in frame.columns]
    X = frame[available].copy()
    X = X.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return X, available


def _portfolio_from_scores(
    frame: pd.DataFrame,
    *,
    score_col: str,
    return_col: str,
    threshold: float,
    max_positions: int,
    mode: str,
) -> tuple[pd.DataFrame, pd.Series]:
    rows: list[pd.DataFrame] = []
    for _, day in frame.groupby("date", sort=True):
        day = day.copy()
        day = day[np.isfinite(day[score_col])]
        if day.empty:
            continue

        # Apply confidence threshold.
        if mode == "classification":
            day = day[day[score_col] >= threshold]
        else:
            day = day[day[score_col] >= threshold]
        if day.empty:
            continue

        # Risk filter: penalize/skip risk-off.
        if "regime_risk_off" in day.columns:
            day = day[day["regime_risk_off"] == 0]
        if day.empty:
            continue

        day = day.sort_values(score_col, ascending=False).head(max_positions)
        risk = day.get("realized_vol_20", pd.Series(np.ones(len(day)), index=day.index)).abs().clip(lower=1e-6)
        inv_vol = 1.0 / risk
        weights = inv_vol / inv_vol.sum()
        day["weight"] = weights
        day["weighted_return"] = day[return_col] * day["weight"]
        rows.append(day)

    if not rows:
        return pd.DataFrame(), pd.Series(dtype=float)
    portfolio = pd.concat(rows, ignore_index=True)
    daily = portfolio.groupby("date")["weighted_return"].sum().sort_index()
    return portfolio, daily


def _compute_exec_metrics(portfolio: pd.DataFrame, daily_returns: pd.Series, return_col: str) -> dict[str, float]:
    if portfolio.empty or daily_returns.empty:
        return {
            "sharpe": 0.0,
            "sortino": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
            "precision_executed": 0.0,
            "trade_count": 0.0,
            "avg_trade_return": 0.0,
        }
    executed = portfolio[return_col]
    precision = float((executed > 0).mean())
    return {
        "sharpe": _sharpe(daily_returns),
        "sortino": _sortino(daily_returns),
        "profit_factor": _profit_factor(executed),
        "max_drawdown": _max_drawdown(daily_returns),
        "precision_executed": precision,
        "trade_count": float(len(portfolio)),
        "avg_trade_return": float(executed.mean()),
    }


def _optimize_threshold_validation_only(
    val_frame: pd.DataFrame,
    *,
    score_col: str,
    return_col: str,
    mode: str,
    max_positions: int,
    min_trades: int = 15,
) -> tuple[float, dict[str, float], list[dict[str, float]]]:
    if mode == "classification":
        candidates = [round(x, 3) for x in np.linspace(0.50, 0.85, 15)]
    else:
        candidates = [round(x, 3) for x in np.linspace(0.65, 0.95, 13)]

    best_threshold = candidates[0]
    best_metrics = {
        "sharpe": -999.0,
        "sortino": 0.0,
        "profit_factor": 0.0,
        "max_drawdown": 1.0,
        "precision_executed": 0.0,
        "trade_count": 0.0,
        "avg_trade_return": 0.0,
    }
    history: list[dict[str, float]] = []

    any_valid = False
    for threshold in candidates:
        portfolio, daily = _portfolio_from_scores(
            val_frame,
            score_col=score_col,
            return_col=return_col,
            threshold=threshold,
            max_positions=max_positions,
            mode=mode,
        )
        metrics = _compute_exec_metrics(portfolio, daily, return_col=return_col)
        objective = _risk_objective(metrics)
        # Demote thresholds with too few trades to prevent small-sample overfitting
        if metrics.get("trade_count", 0) < min_trades:
            objective = float("-inf")
        else:
            any_valid = True
        history.append({"threshold": threshold, "objective": objective, **metrics})
        if objective > _risk_objective(best_metrics):
            best_threshold = threshold
            best_metrics = metrics

    # If no threshold met the minimum trade floor, mark this candidate invalid
    if not any_valid:
        best_metrics = {
            **best_metrics,
            "_invalid": True,
            "_reason": f"no threshold produced >= {min_trades} validation trades",
        }
    return float(best_threshold), best_metrics, history


def _group_metrics(portfolio: pd.DataFrame, *, group_col: str, return_col: str) -> list[dict[str, Any]]:
    if portfolio.empty or group_col not in portfolio.columns:
        return []
    out: list[dict[str, Any]] = []
    for key, grp in portfolio.groupby(group_col):
        if grp.empty:
            continue
        out.append(
            {
                group_col: str(key),
                "trade_count": int(len(grp)),
                "avg_return": float(grp[return_col].mean()),
                "win_rate": float((grp[return_col] > 0).mean()),
                "profit_factor": _profit_factor(grp[return_col]),
            }
        )
    out.sort(key=lambda row: row["trade_count"], reverse=True)
    return out


def _feature_importance(model: Any, feature_columns: list[str]) -> list[dict[str, float | str]]:
    imp: list[tuple[str, float]] = []
    if hasattr(model, "coef_"):
        coefs = np.asarray(getattr(model, "coef_"))
        if coefs.ndim == 2:
            coefs = np.mean(np.abs(coefs), axis=0)
        else:
            coefs = np.abs(coefs)
        for idx, col in enumerate(feature_columns):
            value = float(coefs[idx]) if idx < len(coefs) else 0.0
            imp.append((col, value))
    elif hasattr(model, "feature_importances_"):
        values = np.asarray(getattr(model, "feature_importances_"))
        for idx, col in enumerate(feature_columns):
            value = float(values[idx]) if idx < len(values) else 0.0
            imp.append((col, value))
    else:
        imp = [(col, 0.0) for col in feature_columns]

    total = sum(v for _, v in imp) or 1.0
    ranked = sorted(imp, key=lambda x: x[1], reverse=True)[:25]
    return [{"feature": name, "importance": float(val), "importance_pct": float(val / total)} for name, val in ranked]


class RegimeAwareRankingModel:
    """Serialized inference model for regime-aware ranking decisions."""

    def __init__(
        self,
        *,
        mode: str,
        estimator: Any,
        threshold: float,
        feature_columns: list[str],
        score_mean: float,
        score_std: float,
        target_return_col: str,
        feature_importance: list[dict[str, Any]],
    ) -> None:
        self.mode = mode
        self.estimator = estimator
        self.threshold = float(threshold)
        self.feature_columns = list(feature_columns)
        self.score_mean = float(score_mean)
        self.score_std = float(score_std if score_std > 1e-9 else 1.0)
        self.target_return_col = str(target_return_col)
        self.feature_importance = feature_importance

    def _score(self, X: pd.DataFrame) -> np.ndarray:
        if self.mode == "classification":
            if hasattr(self.estimator, "predict_proba"):
                prob = self.estimator.predict_proba(X)
                if isinstance(prob, np.ndarray) and prob.ndim == 2:
                    return prob[:, 1]
                return np.asarray(prob).reshape(-1)
            raw = np.asarray(self.estimator.predict(X), dtype=float)
            return np.asarray(_sigmoid(raw), dtype=float)
        raw = np.asarray(self.estimator.predict(X), dtype=float)
        score = _sigmoid((raw - self.score_mean) / self.score_std)
        return np.asarray(score, dtype=float)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        score = self._score(X)
        return np.column_stack([1.0 - score, score])

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        score = self._score(X)
        labels = np.ones(len(score), dtype=int)
        labels[score >= self.threshold] = 2
        labels[score <= (1.0 - self.threshold)] = 0
        return labels

    def predict_with_expected_return(
        self,
        X: pd.DataFrame,
        price: float | None = None,
        quantity: int = 1,
        min_net_edge_bps: float = 6.0,
        slippage_bps: float = 2.0,
    ) -> list[dict[str, Any]]:
        scores = self._score(X)
        min_edge = float(max(0.0, min_net_edge_bps) / 10_000.0)
        slip = float(max(0.0, slippage_bps) / 10_000.0)
        out: list[dict[str, Any]] = []
        _ = price, quantity  # kept for signature compatibility

        # Adaptive thresholds: use z-score normalization when the raw score
        # distribution is compressed (std < 0.05).  This prevents the model
        # from producing all-hold when calibrated probabilities cluster
        # tightly around 0.5.
        raw_std = float(np.nanstd(scores)) if len(scores) > 1 else self.score_std
        effective_std = max(raw_std, self.score_std)
        raw_mean = float(np.nanmean(scores)) if len(scores) > 1 else self.score_mean

        if effective_std < 0.05:
            # Score distribution is compressed — use z-score based thresholds.
            # Buy when score is >1 std above mean, sell when >1 std below.
            buy_threshold = float(np.clip(raw_mean + effective_std, 0.505, 0.90))
            sell_threshold = float(np.clip(raw_mean - effective_std, 0.10, raw_mean - 0.5 * effective_std))
        else:
            buy_threshold = self.threshold
            sell_threshold = 1.0 - self.threshold

        for i, score in enumerate(scores):
            row = X.iloc[i] if isinstance(X, pd.DataFrame) else None
            volatility = float(abs(row.get("volatility_20", 0.02)) if row is not None else 0.02)
            regime_risk_off = int(row.get("regime_risk_off", 0)) if row is not None else 0

            centered = (float(score) - 0.5) * 2.0
            vol_scale = float(np.clip(0.4 * volatility + 0.015, 0.01, 0.10))
            expected_return = float(np.clip(centered * vol_scale, -0.20, 0.20))
            net_expected = expected_return - slip * np.sign(expected_return)

            action = "hold"
            reason = None
            if regime_risk_off == 1 and score >= buy_threshold:
                reason = "risk_off_filter"
            elif score >= buy_threshold and net_expected >= min_edge:
                action = "buy"
            elif score <= sell_threshold and abs(net_expected) >= min_edge:
                action = "sell"
            elif abs(net_expected) < min_edge:
                reason = "net_edge_below_costs"
            else:
                reason = "confidence_below_threshold"

            confidence = float(max(score, 1.0 - score))
            out.append(
                {
                    "action": action,
                    "confidence": round(confidence, 4),
                    "expected_return": round(expected_return, 6),
                    "net_expected_return": round(net_expected, 6),
                    "ranking_score": round(float(score), 6),
                    "buy_threshold": round(buy_threshold, 4),
                    "sell_threshold": round(sell_threshold, 4),
                    "no_trade_reason": reason,
                }
            )
        return out

def train_regime_aware_ranking(
    features: pd.DataFrame,
    *,
    cfg: RegimeRankingConfig,
    safety_cfg: TrainingConfig,
) -> dict[str, Any]:
    raw = build_regime_ranking_frame(
        features,
        horizon_bars=cfg.horizon_bars,
        downside_penalty=cfg.downside_penalty,
        top_bucket_pct=cfg.top_bucket_pct,
        bottom_bucket_pct=cfg.bottom_bucket_pct,
    )
    raw = raw.sort_values(["ticker", "date"]).reset_index(drop=True)

    # Keep rows where all main targets are available.
    train_frame = raw.dropna(
        subset=[
            "target_next_day_return",
            "target_next_3d_return",
            "target_excess_return",
            "target_downside_aware",
            "target_opportunity_score",
        ]
    ).copy()
    if train_frame.empty:
        raise TrainingPipelineError(
            reason="insufficient_data",
            message="No rows available after constructing regime-aware targets.",
            details={"rows_before": int(len(raw)), "rows_after": 0},
        )

    # For classification, use top-vs-bottom bucket label (not just top decile)
    train_frame["target_top_decile"] = train_frame["target_top_decile"].fillna(0.0).astype(int)
    train_frame["target_top_bottom_label"] = train_frame.get("target_top_bottom_label", pd.Series(np.nan, index=train_frame.index))

    # Strict time split.
    train_df, val_df, test_df = _split_by_time(train_frame, safety_cfg, date_col="date")

    X_train_raw, feature_columns = _build_feature_matrix(train_df, include_day_of_week=cfg.include_day_of_week)
    X_val_raw, _ = _build_feature_matrix(val_df, include_day_of_week=cfg.include_day_of_week)
    X_test_raw, _ = _build_feature_matrix(test_df, include_day_of_week=cfg.include_day_of_week)

    scaler = StandardScaler()
    X_train = pd.DataFrame(scaler.fit_transform(X_train_raw), columns=feature_columns, index=X_train_raw.index)
    X_val = pd.DataFrame(scaler.transform(X_val_raw), columns=feature_columns, index=X_val_raw.index)
    X_test = pd.DataFrame(scaler.transform(X_test_raw), columns=feature_columns, index=X_test_raw.index)

    # Choose target return column based on horizon
    target_return_col = f"target_next_{cfg.horizon_bars}d_return" if f"target_next_{cfg.horizon_bars}d_return" in train_df.columns else "target_horizon_return"
    if target_return_col not in train_df.columns:
        target_return_col = "target_next_day_return"

    if cfg.mode == "classification":
        # Use top-vs-bottom bucket labels for balanced classification
        use_bucket_labels = train_df["target_top_bottom_label"].notna().sum() > 100
        if use_bucket_labels:
            # Filter to only top/bottom bucket rows for training
            train_bucket_mask = train_df["target_top_bottom_label"].notna()
            val_bucket_mask = val_df["target_top_bottom_label"].notna()
            y_train = train_df.loc[train_bucket_mask, "target_top_bottom_label"].astype(int)
            y_val = val_df.loc[val_bucket_mask, "target_top_bottom_label"].astype(int)
            X_train_cls = X_train.loc[train_bucket_mask]
            X_val_cls = X_val.loc[val_bucket_mask]
            cls_label_col = "target_top_bottom_label"
        else:
            y_train = train_df["target_top_decile"].astype(int)
            y_val = val_df["target_top_decile"].astype(int)
            X_train_cls = X_train
            X_val_cls = X_val
            cls_label_col = "target_top_decile"

        candidate_specs: dict[str, Any] = {
            "baseline_logistic": LogisticRegression(max_iter=700, class_weight="balanced", random_state=cfg.random_state),
            "tree_boosting": HistGradientBoostingClassifier(max_depth=6, learning_rate=0.05, max_iter=300, random_state=cfg.random_state),
        }
        # Add LightGBM classifier if available
        if LGBMClassifier is not None:
            candidate_specs["lightgbm_classifier"] = LGBMClassifier(
                n_estimators=800,
                learning_rate=0.01,
                num_leaves=31,
                max_depth=5,
                min_child_samples=80,
                feature_fraction=0.7,
                bagging_fraction=0.7,
                bagging_freq=5,
                lambda_l1=0.3,
                lambda_l2=1.5,
                is_unbalance=True,
                random_state=cfg.random_state,
                verbose=-1,
            )
    else:
        y_train = train_df["target_opportunity_score"].astype(float)
        y_val = val_df["target_opportunity_score"].astype(float)
        X_train_cls = X_train
        X_val_cls = X_val
        candidate_specs = {
            "baseline_ridge": Ridge(alpha=2.0, random_state=cfg.random_state),
            "tree_boosting": HistGradientBoostingRegressor(max_depth=6, learning_rate=0.05, max_iter=300, random_state=cfg.random_state),
        }
        # Add LightGBM regressor if available
        if LGBMRegressor is not None:
            candidate_specs["lightgbm_regressor"] = LGBMRegressor(
                n_estimators=800,
                learning_rate=0.01,
                num_leaves=31,
                max_depth=5,
                min_child_samples=80,
                feature_fraction=0.7,
                bagging_fraction=0.7,
                bagging_freq=5,
                lambda_l1=0.3,
                lambda_l2=1.5,
                random_state=cfg.random_state,
                verbose=-1,
            )

    comparison_rows: list[dict[str, Any]] = []
    chosen: dict[str, Any] | None = None

    for model_name, estimator in candidate_specs.items():
        estimator.fit(X_train_cls, y_train)

        if cfg.mode == "classification":
            calibrated = CalibratedClassifierCV(estimator=FrozenEstimator(estimator), method="sigmoid")
            calibrated.fit(X_val_cls, y_val)
            val_scores = np.asarray(calibrated.predict_proba(X_val))[:, 1]
            test_scores = np.asarray(calibrated.predict_proba(X_test))[:, 1]
            deployed_estimator = calibrated
        else:
            val_raw = np.asarray(estimator.predict(X_val), dtype=float)
            test_raw = np.asarray(estimator.predict(X_test), dtype=float)
            mu = float(np.nanmean(val_raw)) if np.isfinite(val_raw).any() else 0.0
            sd = float(np.nanstd(val_raw)) if np.isfinite(val_raw).any() else 1.0
            sd = sd if sd > 1e-9 else 1.0
            val_scores = np.asarray(_sigmoid((val_raw - mu) / sd), dtype=float)
            test_scores = np.asarray(_sigmoid((test_raw - mu) / sd), dtype=float)
            deployed_estimator = estimator

        val_eval = val_df.copy()
        val_eval["ranking_score"] = val_scores
        threshold, val_metrics, threshold_grid = _optimize_threshold_validation_only(
            val_eval,
            score_col="ranking_score",
            return_col=target_return_col,
            mode=cfg.mode,
            max_positions=cfg.max_positions,
        )

        test_eval = test_df.copy()
        test_eval["ranking_score"] = test_scores
        test_portfolio, test_daily = _portfolio_from_scores(
            test_eval,
            score_col="ranking_score",
            return_col=target_return_col,
            threshold=threshold,
            max_positions=cfg.max_positions,
            mode=cfg.mode,
        )
        test_metrics = _compute_exec_metrics(test_portfolio, test_daily, return_col=target_return_col)

        val_objective = _risk_objective(val_metrics)
        # Demote models whose best threshold produced too few validation trades
        min_val_trades = max(15, cfg.min_trade_alert_threshold)
        val_trade_count = int(val_metrics.get("trade_count", 0))
        candidate_invalid = val_metrics.get("_invalid", False)
        if candidate_invalid or val_trade_count < min_val_trades:
            reason = val_metrics.get("_reason", f"only {val_trade_count} validation trades")
            logger.warning(
                "Model %s demoted: %s (min=%d)",
                model_name, reason, min_val_trades,
            )
            val_objective = float("-inf")
        else:
            logger.info(
                "Model %s: val_objective=%.3f, val_trades=%d, threshold=%.3f",
                model_name, val_objective, val_trade_count, threshold,
            )
        test_objective = _risk_objective(test_metrics)
        row = {
            "model_name": model_name,
            "mode": cfg.mode,
            "validation": {**val_metrics, "risk_objective": float(val_objective), "trade_count": float(val_trade_count)},
            "test": {**test_metrics, "risk_objective": float(test_objective)},
            "threshold": float(threshold),
            "threshold_source": "validation_only",
            "threshold_grid": threshold_grid,
        }
        comparison_rows.append(row)

        if chosen is None or val_objective > chosen["validation_objective"]:
            score_mean = float(np.nanmean(val_scores))
            score_std = float(np.nanstd(val_scores))
            score_std = score_std if score_std > 1e-9 else 1.0
            chosen = {
                "model_name": model_name,
                "estimator": deployed_estimator,
                "base_estimator": estimator,
                "threshold": float(threshold),
                "validation_objective": float(val_objective),
                "test_metrics": test_metrics,
                "val_metrics": val_metrics,
                "score_mean": score_mean,
                "score_std": score_std,
                "test_portfolio": test_portfolio,
                "test_eval": test_eval,
                "test_scores": test_scores,
            }

    if chosen is None:
        raise TrainingPipelineError(
            reason="training_failed",
            message="No candidate ranking model could be trained.",
            details={},
        )

    selected_model = RegimeAwareRankingModel(
        mode=cfg.mode,
        estimator=chosen["estimator"],
        threshold=chosen["threshold"],
        feature_columns=feature_columns,
        score_mean=chosen["score_mean"],
        score_std=chosen["score_std"],
        target_return_col=target_return_col,
        feature_importance=_feature_importance(chosen["base_estimator"], feature_columns),
    )

    test_portfolio = chosen["test_portfolio"]
    metrics_by_symbol = _group_metrics(test_portfolio, group_col="ticker", return_col=target_return_col)
    metrics_by_sector = _group_metrics(test_portfolio, group_col="sector", return_col=target_return_col)
    metrics_by_regime = _group_metrics(test_portfolio, group_col="regime_label", return_col=target_return_col)

    sequence_note = {
        "enabled": bool(cfg.enable_sequence_model),
        "status": "not_enabled" if not cfg.enable_sequence_model else "configured_but_not_selected",
        "message": "Sequence model scaffold is config-gated; baseline and tree models are primary for robust production deployment.",
    }

    candidate_summary = sorted(comparison_rows, key=lambda r: r["validation"]["risk_objective"], reverse=True)
    selected_row = candidate_summary[0]

    # Fallback defaults for inference when cross-sectional features are absent.
    default_feature_values = {col: float(X_train_raw[col].median()) for col in feature_columns}
    for col in REGIME_COLUMNS:
        default_feature_values.setdefault(col, 0.0)

    metadata = {
        "architecture": "regime_aware_ranking_engine",
        "target_mode": cfg.mode,
        "horizon_bars": int(cfg.horizon_bars),
        "threshold_source": "validation_only",
        "selected_model": selected_row["model_name"],
        "selected_threshold": float(selected_row["threshold"]),
        "default_feature_values": default_feature_values,
        "target_definitions": {
            "target_next_day_return": "close[t+1]/close[t]-1",
            "target_next_3d_return": "close[t+3]/close[t]-1",
            "target_excess_return": "target_next_day_return - cross_sectional_benchmark_next_day_return",
            "target_top_decile": "1 when target_horizon_return is in top 10% of symbols for same date",
            "target_downside_aware": "target_horizon_return - downside_penalty * downside_vol_20",
            "target_opportunity_score": "0.45*excess + 0.35*next_3d + 0.20*downside_aware",
        },
        "feature_groups": {
            "base_numeric": list(NUMERIC_FEATURES),
            "engineered": list(ENGINEERED_COLUMNS),
            "regime": list(REGIME_COLUMNS),
        },
        "model_comparison": {
            "selection_rule": "max_validation_risk_objective",
            "risk_objective_formula": "sharpe + 0.35*sortino + 0.20*profit_factor + 0.25*precision_executed - 1.8*max_drawdown",
            "candidates": candidate_summary,
            "sequence_model": sequence_note,
        },
        "explainability": {
            "feature_importance": selected_model.feature_importance,
            "metrics_by_symbol": metrics_by_symbol[:80],
            "metrics_by_sector": metrics_by_sector,
            "metrics_by_regime": metrics_by_regime,
        },
        "train_split": {
            "train_start": str(pd.to_datetime(train_df["date"]).min().date()),
            "train_end": str(pd.to_datetime(train_df["date"]).max().date()),
            "val_start": str(pd.to_datetime(val_df["date"]).min().date()),
            "val_end": str(pd.to_datetime(val_df["date"]).max().date()),
            "test_start": str(pd.to_datetime(test_df["date"]).min().date()),
            "test_end": str(pd.to_datetime(test_df["date"]).max().date()),
        },
    }

    metrics = {
        "selected_model": selected_row["model_name"],
        "selected_threshold": float(selected_row["threshold"]),
        "validation_risk_objective": float(selected_row["validation"]["risk_objective"]),
        "validation_trade_count": int(selected_row["validation"].get("trade_count", 0)),
        "test_risk_objective": float(selected_row["test"]["risk_objective"]),
        "test_sharpe": float(selected_row["test"]["sharpe"]),
        "test_sortino": float(selected_row["test"]["sortino"]),
        "test_profit_factor": float(selected_row["test"]["profit_factor"]),
        "test_max_drawdown": float(selected_row["test"]["max_drawdown"]),
        "test_precision_executed": float(selected_row["test"]["precision_executed"]),
        "test_trade_count": float(selected_row["test"]["trade_count"]),
        "executed_trade_win_rate": float(selected_row["test"]["precision_executed"]),
    }

    # Compute full-test-set classification accuracy (not just executed trades)
    _test_scores = chosen.get("test_scores")
    if cfg.mode == "classification" and _test_scores is not None:
        _label_col = cls_label_col if "cls_label_col" in dir() else "target_top_decile"
        if _label_col in test_df.columns:
            _y_test = test_df[_label_col]
            _mask = _y_test.notna()
            if _mask.sum() > 0:
                _y_true = _y_test[_mask].astype(int).values
                _y_pred = (_test_scores[_mask.values] >= 0.5).astype(int)
                _cls_acc = float((_y_true == _y_pred).mean())
                metrics["classification_accuracy"] = _cls_acc
                metrics["test_accuracy"] = _cls_acc
            else:
                metrics["classification_accuracy"] = None
                metrics["test_accuracy"] = None
        else:
            metrics["classification_accuracy"] = None
            metrics["test_accuracy"] = metrics["executed_trade_win_rate"]
    else:
        # For non-classification modes, fall back to executed trade win rate
        metrics["classification_accuracy"] = None
        metrics["test_accuracy"] = metrics["executed_trade_win_rate"]

    # --- Enhanced evaluation metrics ---
    test_eval = chosen.get("test_eval", pd.DataFrame())
    if not test_eval.empty and "ranking_score" in test_eval.columns:
        eval_metrics = _compute_ranking_eval_metrics(
            test_eval,
            score_col="ranking_score",
            return_col=target_return_col,
            mode=cfg.mode,
            max_positions=cfg.max_positions,
        )
        metrics.update(eval_metrics)

    # --- Diagnostics / alerts ---
    diagnostics = _compute_diagnostics(
        metrics=metrics,
        feature_importance=selected_model.feature_importance,
        test_trade_count=int(metrics.get("test_trade_count", 0)),
        cfg=cfg,
    )
    if diagnostics:
        metrics["diagnostics"] = diagnostics

    return {
        "model": selected_model,
        "scaler": scaler,
        "feature_columns": feature_columns,
        "metrics": metrics,
        "metadata": metadata,
        "comparison": candidate_summary,
        "prepared_frame": raw,
    }


def _compute_ranking_eval_metrics(
    test_eval: pd.DataFrame,
    *,
    score_col: str,
    return_col: str,
    mode: str,
    max_positions: int,
) -> dict[str, Any]:
    """Compute comprehensive ranking evaluation metrics."""
    metrics: dict[str, Any] = {}

    scores = test_eval[score_col].values
    returns = test_eval[return_col].values if return_col in test_eval.columns else None

    # ROC AUC (for classification mode)
    if mode == "classification":
        try:
            # Use top_bottom_label or top_decile as ground truth
            if "target_top_bottom_label" in test_eval.columns:
                y_true_auc = test_eval["target_top_bottom_label"]
                mask = y_true_auc.notna()
                if mask.sum() > 10:
                    metrics["test_roc_auc"] = float(roc_auc_score(y_true_auc[mask].astype(int), scores[mask]))
            elif "target_top_decile" in test_eval.columns:
                y_true_auc = test_eval["target_top_decile"].astype(int)
                metrics["test_roc_auc"] = float(roc_auc_score(y_true_auc, scores))
        except (ValueError, Exception):
            metrics["test_roc_auc"] = 0.0

        # Confusion matrix
        try:
            threshold = 0.5
            preds = (scores >= threshold).astype(int)
            if "target_top_bottom_label" in test_eval.columns:
                y_true_cm = test_eval["target_top_bottom_label"]
                mask_cm = y_true_cm.notna()
                if mask_cm.sum() > 0:
                    metrics["confusion_matrix"] = confusion_matrix(
                        y_true_cm[mask_cm].astype(int), preds[mask_cm]
                    ).tolist()
        except Exception:
            pass

    # Prediction distribution
    metrics["prediction_distribution"] = {
        "mean_score": float(np.nanmean(scores)),
        "std_score": float(np.nanstd(scores)),
        "min_score": float(np.nanmin(scores)),
        "max_score": float(np.nanmax(scores)),
        "median_score": float(np.nanmedian(scores)),
    }

    if returns is not None and len(returns) > 0:
        # Precision@k: fraction of top-k predictions with positive returns
        for k in [5, 10, 20]:
            if len(scores) >= k:
                top_k_idx = np.argsort(scores)[-k:]
                top_k_returns = returns[top_k_idx]
                valid_mask = np.isfinite(top_k_returns)
                if valid_mask.sum() > 0:
                    metrics[f"precision_at_{k}"] = float((top_k_returns[valid_mask] > 0).mean())
                    metrics[f"avg_return_top_{k}"] = float(np.mean(top_k_returns[valid_mask]))

        # Top-decile precision
        n_decile = max(1, len(scores) // 10)
        top_decile_idx = np.argsort(scores)[-n_decile:]
        top_decile_returns = returns[top_decile_idx]
        valid_top = np.isfinite(top_decile_returns)
        if valid_top.sum() > 0:
            metrics["top_decile_precision"] = float((top_decile_returns[valid_top] > 0).mean())
            metrics["top_decile_avg_return"] = float(np.mean(top_decile_returns[valid_top]))

        # Information Coefficient (rank correlation between scores and returns)
        from scipy.stats import spearmanr
        valid_ic = np.isfinite(scores) & np.isfinite(returns)
        if valid_ic.sum() > 20:
            ic, ic_pvalue = spearmanr(scores[valid_ic], returns[valid_ic])
            metrics["information_coefficient"] = float(ic)
            metrics["ic_pvalue"] = float(ic_pvalue)

        # Per-date IC (average daily rank correlation)
        if "date" in test_eval.columns:
            daily_ics = []
            for _, day_df in test_eval.groupby("date"):
                if len(day_df) < 5:
                    continue
                day_scores = day_df[score_col].values
                day_returns = day_df[return_col].values
                valid_day = np.isfinite(day_scores) & np.isfinite(day_returns)
                if valid_day.sum() >= 5:
                    ic_day, _ = spearmanr(day_scores[valid_day], day_returns[valid_day])
                    if np.isfinite(ic_day):
                        daily_ics.append(ic_day)
            if daily_ics:
                metrics["mean_daily_ic"] = float(np.mean(daily_ics))
                metrics["std_daily_ic"] = float(np.std(daily_ics))
                metrics["ic_positive_pct"] = float((np.array(daily_ics) > 0).mean())

        # Top-N backtest summary
        top_n_summary = _compute_top_n_backtest(test_eval, score_col=score_col, return_col=return_col, top_n=max_positions)
        metrics["top_n_backtest"] = top_n_summary

    return metrics


def _compute_top_n_backtest(
    df: pd.DataFrame,
    *,
    score_col: str,
    return_col: str,
    top_n: int = 10,
) -> dict[str, Any]:
    """Compute a simplified top-N selection backtest on scored predictions."""
    if "date" not in df.columns:
        return {}

    daily_returns = []
    total_trades = 0
    winning_trades = 0

    for date, day_df in df.groupby("date", sort=True):
        if day_df.empty or len(day_df) < 3:
            continue
        valid = day_df[np.isfinite(day_df[score_col]) & np.isfinite(day_df[return_col])]
        if valid.empty:
            continue
        top = valid.nlargest(min(top_n, len(valid)), score_col)
        if top.empty:
            continue
        day_ret = float(top[return_col].mean())
        daily_returns.append(day_ret)
        total_trades += len(top)
        winning_trades += int((top[return_col] > 0).sum())

    if not daily_returns:
        return {"total_trades": 0, "message": "no valid trading days"}

    daily_series = pd.Series(daily_returns)
    equity = (1.0 + daily_series).cumprod()
    total_return = float(equity.iloc[-1] - 1.0)

    return {
        "top_n": top_n,
        "trading_days": len(daily_returns),
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "win_rate": round(winning_trades / max(total_trades, 1), 4),
        "total_return_pct": round(total_return * 100, 4),
        "sharpe": round(_sharpe(daily_series), 4),
        "sortino": round(_sortino(daily_series), 4),
        "max_drawdown": round(_max_drawdown(daily_series), 4),
        "avg_daily_return": round(float(daily_series.mean()), 6),
        "avg_selected_return": round(float(daily_series.mean()), 6),
    }


def _compute_diagnostics(
    *,
    metrics: dict[str, Any],
    feature_importance: list[dict[str, Any]],
    test_trade_count: int,
    cfg: Any,
) -> list[dict[str, str]]:
    """Generate diagnostic alerts for common issues."""
    diagnostics = []

    # Feature dominance
    if feature_importance:
        top_imp = feature_importance[0].get("importance_pct", 0.0)
        max_pct = getattr(cfg, "max_dominant_feature_pct", 0.40)
        if float(top_imp) > max_pct:
            diagnostics.append({
                "level": "warning",
                "message": f"Feature '{feature_importance[0].get('feature')}' dominates with {top_imp:.0%} importance.",
            })

    # ROC AUC check
    roc_auc = metrics.get("test_roc_auc", None)
    if roc_auc is not None and float(roc_auc) < 0.5:
        diagnostics.append({
            "level": "critical",
            "message": f"ROC AUC ({roc_auc:.3f}) is below 0.5 -- model is worse than random.",
        })

    # Prediction distribution skew
    pred_dist = metrics.get("prediction_distribution", {})
    mean_score = pred_dist.get("mean_score", 0.5)
    if mean_score is not None and (float(mean_score) > 0.95 or float(mean_score) < 0.05):
        diagnostics.append({
            "level": "warning",
            "message": f"Model predicts >95% of one class (mean score: {mean_score:.3f}).",
        })

    # Trade count
    min_trades = getattr(cfg, "min_trade_alert_threshold", 25)
    if test_trade_count < min_trades:
        diagnostics.append({
            "level": "warning",
            "message": f"Only {test_trade_count} trades in test -- too few for reliable evaluation (min: {min_trades}).",
        })

    # Validation trade count (selected model)
    val_trade_count = int(metrics.get("validation_trade_count", 0))
    if val_trade_count < 20:
        diagnostics.append({
            "level": "warning",
            "message": f"Selected model had only {val_trade_count} validation trades -- selection may be unreliable.",
        })

    for d in diagnostics:
        logger.warning("DIAGNOSTIC [%s]: %s", d["level"], d["message"])

    return diagnostics
