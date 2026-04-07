"""Intraday ML training pipeline – walk-forward time-split training
for short-horizon intraday prediction models.

Trains LightGBM / HistGradientBoosting / Logistic Regression models
on intraday feature data.  Evaluation metrics focus on trading quality:
precision_executed, profit_factor, Sharpe ratio, trades_per_day.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, precision_score, recall_score

logger = logging.getLogger(__name__)

MODELS_DIR = Path("models/intraday")
MODELS_DIR.mkdir(parents=True, exist_ok=True)


# ── Configuration ──────────────────────────────────────────────────────────


@dataclass
class IntradayTrainConfig:
    """Training configuration for intraday models."""

    # Target
    horizon_bars: int = 3                   # predict N bars ahead
    target_return_threshold: float = 0.002  # 0.2% minimum return for positive label
    target_type: str = "breakout"           # breakout | momentum | mean_reversion | return

    # Walk-forward
    train_days: int = 60                    # days in training window
    val_days: int = 15                      # days in validation window
    n_splits: int = 5                       # number of walk-forward splits
    purge_bars: int = 10                    # bars between train/val to prevent leakage

    # Models
    models_to_train: list[str] = field(
        default_factory=lambda: ["logistic", "lightgbm", "histgb"]
    )

    # Risk
    min_trades_per_split: int = 20
    min_precision: float = 0.50

    # Output
    model_dir: str = str(MODELS_DIR)


# ── Target builders ────────────────────────────────────────────────────────


def build_intraday_target(
    df: pd.DataFrame,
    horizon: int = 3,
    threshold: float = 0.002,
    target_type: str = "breakout",
) -> pd.Series:
    """Build binary classification target from price data.

    Labels are computed using only forward-looking data, which will be
    stripped during training to prevent leakage.
    """
    future_ret = df["close"].shift(-horizon) / df["close"] - 1

    if target_type == "breakout":
        # High exceeds close + threshold within horizon
        future_high = df["high"].rolling(horizon).max().shift(-horizon)
        target = ((future_high / df["close"] - 1) >= threshold).astype(int)
    elif target_type == "momentum":
        target = (future_ret >= threshold).astype(int)
    elif target_type == "mean_reversion":
        # Price reverts toward VWAP
        if "vwap" in df.columns:
            dist = (df["close"] - df["vwap"]).abs()
            future_dist = (df["close"].shift(-horizon) - df["vwap"]).abs()
            target = (future_dist < dist * 0.5).astype(int)
        else:
            target = (future_ret.abs() < threshold).astype(int)
    else:  # raw return
        target = (future_ret >= threshold).astype(int)

    return target


# ── Walk-forward splitter ──────────────────────────────────────────────────


def walk_forward_splits(
    df: pd.DataFrame,
    train_days: int = 60,
    val_days: int = 15,
    n_splits: int = 5,
    purge_bars: int = 10,
) -> list[tuple[pd.DataFrame, pd.DataFrame]]:
    """Generate time-ordered train/val splits. Never shuffles."""
    dates = df.index.normalize().unique().sort_values()
    total_needed = train_days + val_days
    step = max(1, (len(dates) - total_needed) // max(n_splits - 1, 1))

    splits = []
    for i in range(n_splits):
        start_idx = i * step
        train_end_idx = start_idx + train_days
        val_end_idx = train_end_idx + val_days

        if val_end_idx > len(dates):
            break

        train_dates = dates[start_idx:train_end_idx]
        val_dates = dates[train_end_idx:val_end_idx]

        train_mask = df.index.normalize().isin(train_dates)
        val_mask = df.index.normalize().isin(val_dates)

        train_df = df[train_mask].iloc[:-purge_bars] if purge_bars else df[train_mask]
        val_df = df[val_mask]

        if len(train_df) > 50 and len(val_df) > 20:
            splits.append((train_df, val_df))

    return splits


# ── Model training ─────────────────────────────────────────────────────────


def _train_logistic(X_train: np.ndarray, y_train: np.ndarray) -> Any:
    model = LogisticRegression(
        max_iter=1000, C=0.1, class_weight="balanced", solver="lbfgs"
    )
    model.fit(X_train, y_train)
    return model


def _train_lightgbm(X_train: np.ndarray, y_train: np.ndarray) -> Any:
    try:
        import lightgbm as lgb
    except ImportError:
        logger.warning("lightgbm not installed, skipping")
        return None

    model = lgb.LGBMClassifier(
        n_estimators=300,
        max_depth=6,
        learning_rate=0.05,
        num_leaves=31,
        min_child_samples=20,
        subsample=0.8,
        colsample_bytree=0.8,
        class_weight="balanced",
        verbose=-1,
    )
    model.fit(X_train, y_train)
    return model


def _train_histgb(X_train: np.ndarray, y_train: np.ndarray) -> Any:
    from sklearn.ensemble import HistGradientBoostingClassifier

    model = HistGradientBoostingClassifier(
        max_iter=300,
        max_depth=6,
        learning_rate=0.05,
        min_samples_leaf=20,
        max_bins=255,
    )
    model.fit(X_train, y_train)
    return model


TRAINERS = {
    "logistic": _train_logistic,
    "lightgbm": _train_lightgbm,
    "histgb": _train_histgb,
}


# ── Evaluation ─────────────────────────────────────────────────────────────


@dataclass
class IntradayEvalMetrics:
    accuracy: float = 0.0
    precision_executed: float = 0.0
    recall: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    avg_trade_return: float = 0.0
    trades_per_day: float = 0.0
    total_trades: int = 0
    win_rate: float = 0.0


def evaluate_intraday_model(
    model: Any,
    X_val: np.ndarray,
    y_val: np.ndarray,
    prices: pd.Series,
    horizon: int = 3,
    threshold: float = 0.55,
) -> IntradayEvalMetrics:
    """Evaluate model with trading-centric metrics."""
    proba = model.predict_proba(X_val)[:, 1]
    preds = (proba >= threshold).astype(int)

    # Classification metrics
    acc = accuracy_score(y_val, preds) if len(y_val) > 0 else 0
    prec = precision_score(y_val, preds, zero_division=0)
    rec = recall_score(y_val, preds, zero_division=0)

    # Trading simulation
    trade_mask = preds == 1
    n_trades = trade_mask.sum()

    if n_trades == 0:
        return IntradayEvalMetrics(accuracy=acc, precision_executed=prec, recall=rec)

    # Compute returns for executed trades
    price_arr = prices.values if isinstance(prices, pd.Series) else prices
    trade_returns = []
    for i in np.where(trade_mask)[0]:
        if i + horizon < len(price_arr):
            ret = (price_arr[i + horizon] / price_arr[i]) - 1
            trade_returns.append(ret)

    if not trade_returns:
        return IntradayEvalMetrics(
            accuracy=acc, precision_executed=prec, recall=rec, total_trades=n_trades
        )

    tr = np.array(trade_returns)
    wins = tr[tr > 0]
    losses = tr[tr <= 0]

    gross_profit = wins.sum() if len(wins) > 0 else 0
    gross_loss = abs(losses.sum()) if len(losses) > 0 else 1e-9
    profit_factor = gross_profit / max(gross_loss, 1e-9)

    # Sharpe (annualized assuming ~75 trades/day × 250 days)
    if tr.std() > 0:
        sharpe = (tr.mean() / tr.std()) * np.sqrt(250 * 75)
    else:
        sharpe = 0.0

    # Drawdown
    cum = np.cumsum(tr)
    running_max = np.maximum.accumulate(cum)
    dd = running_max - cum
    max_dd = dd.max() if len(dd) > 0 else 0.0

    # Trades per day estimate
    n_days = max(1, len(set(prices.index.date)) if hasattr(prices.index, "date") else 1)
    tpd = n_trades / n_days

    return IntradayEvalMetrics(
        accuracy=acc,
        precision_executed=prec,
        recall=rec,
        profit_factor=profit_factor,
        sharpe_ratio=sharpe,
        max_drawdown=max_dd,
        avg_trade_return=float(tr.mean()),
        trades_per_day=tpd,
        total_trades=int(n_trades),
        win_rate=float(len(wins) / len(tr)) if len(tr) > 0 else 0.0,
    )


# ── Full training run ─────────────────────────────────────────────────────


def train_intraday_model(
    feature_df: pd.DataFrame,
    price_df: pd.DataFrame,
    config: IntradayTrainConfig | None = None,
) -> dict[str, Any]:
    """Run full intraday model training pipeline.

    Returns dict with best model, metrics, and metadata.
    """
    cfg = config or IntradayTrainConfig()
    from backend.intraday.feature_engine import INTRADAY_FEATURE_COLUMNS

    logger.info("Starting intraday model training: target=%s, horizon=%d", cfg.target_type, cfg.horizon_bars)

    # Build target
    target = build_intraday_target(
        price_df, horizon=cfg.horizon_bars,
        threshold=cfg.target_return_threshold,
        target_type=cfg.target_type,
    )

    # Align features and target
    common_idx = feature_df.index.intersection(target.dropna().index)
    available_cols = [c for c in INTRADAY_FEATURE_COLUMNS if c in feature_df.columns]
    X = feature_df.loc[common_idx, available_cols].values
    y = target.loc[common_idx].values
    prices = price_df["close"].loc[common_idx]

    logger.info("Training data: %d samples, %d features, %.1f%% positive",
                len(X), len(available_cols), y.mean() * 100)

    # Walk-forward splits
    combined = pd.DataFrame(X, index=common_idx, columns=available_cols)
    combined["_target"] = y
    combined["_price"] = prices.values

    splits = walk_forward_splits(combined, cfg.train_days, cfg.val_days, cfg.n_splits, cfg.purge_bars)

    if not splits:
        logger.warning("No valid walk-forward splits could be created")
        return {"error": "insufficient_data", "model": None}

    # Train each model type across all splits
    results: list[dict] = []

    for model_name in cfg.models_to_train:
        trainer = TRAINERS.get(model_name)
        if trainer is None:
            continue

        split_metrics = []
        best_model_obj = None
        best_sharpe = -999

        for si, (train_split, val_split) in enumerate(splits):
            feat_cols = [c for c in available_cols if c in train_split.columns]
            X_tr = train_split[feat_cols].values
            y_tr = train_split["_target"].values
            X_vl = val_split[feat_cols].values
            y_vl = val_split["_target"].values
            p_vl = val_split["_price"]

            try:
                model_obj = trainer(X_tr, y_tr)
            except Exception as exc:
                logger.warning("Failed training %s split %d: %s", model_name, si, exc)
                continue

            if model_obj is None:
                continue

            metrics = evaluate_intraday_model(model_obj, X_vl, y_vl, p_vl, cfg.horizon_bars)

            if metrics.total_trades < cfg.min_trades_per_split:
                logger.info("  %s split %d: only %d trades (min=%d), skipping",
                            model_name, si, metrics.total_trades, cfg.min_trades_per_split)
                continue

            split_metrics.append(metrics)
            if metrics.sharpe_ratio > best_sharpe:
                best_sharpe = metrics.sharpe_ratio
                best_model_obj = model_obj

        if not split_metrics or best_model_obj is None:
            logger.info("  %s: no valid splits", model_name)
            continue

        avg_metrics = IntradayEvalMetrics(
            accuracy=np.mean([m.accuracy for m in split_metrics]),
            precision_executed=np.mean([m.precision_executed for m in split_metrics]),
            recall=np.mean([m.recall for m in split_metrics]),
            profit_factor=np.mean([m.profit_factor for m in split_metrics]),
            sharpe_ratio=np.mean([m.sharpe_ratio for m in split_metrics]),
            max_drawdown=np.mean([m.max_drawdown for m in split_metrics]),
            avg_trade_return=np.mean([m.avg_trade_return for m in split_metrics]),
            trades_per_day=np.mean([m.trades_per_day for m in split_metrics]),
            total_trades=sum(m.total_trades for m in split_metrics),
            win_rate=np.mean([m.win_rate for m in split_metrics]),
        )

        results.append({
            "model_name": model_name,
            "model": best_model_obj,
            "metrics": avg_metrics,
            "n_splits_valid": len(split_metrics),
        })

        logger.info("  %s: sharpe=%.2f, pf=%.2f, prec=%.2f, trades=%d, wr=%.1f%%",
                     model_name, avg_metrics.sharpe_ratio, avg_metrics.profit_factor,
                     avg_metrics.precision_executed, avg_metrics.total_trades,
                     avg_metrics.win_rate * 100)

    if not results:
        return {"error": "no_valid_models", "model": None}

    # Select best by Sharpe (with min precision floor)
    valid = [r for r in results if r["metrics"].precision_executed >= cfg.min_precision]
    if not valid:
        valid = results  # fallback to best available

    best = max(valid, key=lambda r: r["metrics"].sharpe_ratio)

    # Persist
    version_id = f"intraday_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    model_path = Path(cfg.model_dir) / version_id
    model_path.mkdir(parents=True, exist_ok=True)

    import joblib
    joblib.dump(best["model"], model_path / "model.joblib")

    meta = {
        "version": version_id,
        "model_name": best["model_name"],
        "target_type": cfg.target_type,
        "horizon_bars": cfg.horizon_bars,
        "target_threshold": cfg.target_return_threshold,
        "feature_columns": available_cols,
        "n_features": len(available_cols),
        "n_splits_valid": best["n_splits_valid"],
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "metrics": {
            "sharpe_ratio": best["metrics"].sharpe_ratio,
            "profit_factor": best["metrics"].profit_factor,
            "precision_executed": best["metrics"].precision_executed,
            "accuracy": best["metrics"].accuracy,
            "win_rate": best["metrics"].win_rate,
            "trades_per_day": best["metrics"].trades_per_day,
            "avg_trade_return": best["metrics"].avg_trade_return,
            "max_drawdown": best["metrics"].max_drawdown,
            "total_trades": best["metrics"].total_trades,
        },
    }
    with open(model_path / "meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    logger.info("Intraday model saved: %s (%s) sharpe=%.2f",
                version_id, best["model_name"], best["metrics"].sharpe_ratio)

    return {
        "version": version_id,
        "model": best["model"],
        "model_name": best["model_name"],
        "metrics": best["metrics"],
        "meta": meta,
        "feature_columns": available_cols,
    }
