"""Walk-forward validation — purged, embargoed time-series cross-validation.

Simulates realistic production conditions by training on expanding/sliding
windows, purging label-overlapping rows, and testing on the next period.
Tracks per-fold stability and detects overfitting via train/test gaps.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from app.core.config import settings
from app.training.dataset_builder import purge_overlap
from app.training.validate import compute_metrics, compute_hit_rate

logger = logging.getLogger(__name__)


@dataclass
class WalkForwardResult:
    """Aggregated results from walk-forward validation."""
    fold_metrics: list[dict[str, Any]] = field(default_factory=list)
    aggregate_metrics: dict[str, Any] = field(default_factory=dict)
    stability_metrics: dict[str, Any] = field(default_factory=dict)
    n_folds: int = 0
    total_test_samples: int = 0
    rejected_folds: int = 0


def walk_forward_validate(
    df: pd.DataFrame,
    model_factory: callable,
    target_col: str = "target",
    n_folds: int | None = None,
    min_train_size: int = 252,
    test_size: int = 63,
    embargo_days: int | None = None,
    purge_days: int | None = None,
    label_horizon: int | None = None,
    expanding: bool = True,
    min_fold_auc: float = 0.50,
) -> WalkForwardResult:
    """Run walk-forward (anchored or sliding) cross-validation with purging.

    Args:
        df: Feature DataFrame sorted by date, with 'target' column.
        model_factory: Callable that returns a new model instance.
        n_folds: Number of folds (default from settings).
        min_train_size: Minimum training window size (rows).
        test_size: Test window size per fold.
        embargo_days: Gap between train and test (default from settings).
        purge_days: Extra rows purged for label bleed (default from settings).
        label_horizon: Forward label horizon in days (default from settings).
        expanding: If True, expanding window; else sliding.
        min_fold_auc: Minimum AUC for a fold to be accepted.

    Returns:
        WalkForwardResult with per-fold, aggregate, and stability metrics.
    """
    n_folds = n_folds or settings.TRAIN_WALK_FORWARD_FOLDS
    embargo_days = embargo_days if embargo_days is not None else settings.TRAIN_EMBARGO_DAYS
    purge_days = purge_days if purge_days is not None else settings.TRAIN_PURGE_DAYS
    label_horizon = label_horizon if label_horizon is not None else settings.LABEL_HORIZON_DAYS
    total_gap = purge_days + embargo_days

    df = df.sort_index()
    n = len(df)

    exclude = {target_col, "symbol"}
    feature_cols = [c for c in df.columns if c not in exclude]

    result = WalkForwardResult()
    all_true: list[float] = []
    all_proba: list[float] = []
    fold_aucs: list[float] = []
    fold_accs: list[float] = []

    for fold in range(n_folds):
        test_end = n - (n_folds - fold - 1) * test_size
        test_start = test_end - test_size
        if expanding:
            train_start = 0
        else:
            train_start = max(0, test_start - total_gap - min_train_size)
        train_end_raw = test_start - total_gap

        if train_end_raw - train_start < min_train_size:
            logger.warning("Fold %d: insufficient training data (%d rows), skipping", fold, train_end_raw - train_start)
            result.rejected_folds += 1
            continue

        train_df = df.iloc[train_start:train_end_raw]
        test_df = df.iloc[test_start:test_end]

        # Purge: remove training rows whose label overlaps the test window
        train_idx = purge_overlap(
            train_df.index,
            test_df.index,
            embargo_days=embargo_days,
            label_horizon=label_horizon,
        )
        train_df = train_df.loc[train_idx]
        if len(train_df) < min_train_size:
            logger.warning("Fold %d: post-purge training data too small (%d rows), skipping", fold, len(train_df))
            result.rejected_folds += 1
            continue

        X_train = train_df[feature_cols]
        y_train = train_df[target_col]
        X_test = test_df[feature_cols]
        y_test = test_df[target_col]

        # Train
        model = model_factory()
        model.fit(X_train, y_train)

        # Predict
        proba = model.predict_proba(X_test)
        preds = (proba > 0.5).astype(int)

        # Train-set predictions for overfit detection
        train_proba = model.predict_proba(X_train)
        train_preds = (train_proba > 0.5).astype(int)
        train_metrics = compute_metrics(y_train, train_preds, train_proba)

        fold_metrics = compute_metrics(y_test, preds, proba)
        hit_rate = compute_hit_rate(y_test.values, proba)
        fold_metrics.update(hit_rate)
        fold_metrics["fold"] = fold
        fold_metrics["train_size"] = len(X_train)
        fold_metrics["test_size"] = len(X_test)
        fold_metrics["purged_rows"] = train_end_raw - train_start - len(train_df)
        fold_metrics["train_period"] = f"{train_df.index.min()} to {train_df.index.max()}"
        fold_metrics["test_period"] = f"{test_df.index.min()} to {test_df.index.max()}"
        # Overfit gap: large gap means the model memorised training data
        fold_metrics["train_accuracy"] = train_metrics.get("accuracy", 0)
        fold_metrics["overfit_gap"] = train_metrics.get("accuracy", 0) - fold_metrics.get("accuracy", 0)

        result.fold_metrics.append(fold_metrics)
        fold_aucs.append(fold_metrics.get("auc_roc", 0.5))
        fold_accs.append(fold_metrics.get("accuracy", 0.5))

        all_true.extend(y_test.values)
        all_proba.extend(proba)

        logger.info(
            "Fold %d: acc=%.4f auc=%.4f hit=%.4f overfit_gap=%.4f (train=%d, test=%d, purged=%d)",
            fold, fold_metrics.get("accuracy", 0), fold_metrics.get("auc_roc", 0),
            hit_rate.get("hit_rate", 0), fold_metrics["overfit_gap"],
            len(X_train), len(X_test), fold_metrics["purged_rows"],
        )

    # Aggregate metrics
    if all_true:
        all_true_arr = np.array(all_true)
        all_proba_arr = np.array(all_proba)
        all_preds_arr = (all_proba_arr > 0.5).astype(int)
        result.aggregate_metrics = compute_metrics(all_true_arr, all_preds_arr, all_proba_arr)
        result.aggregate_metrics.update(compute_hit_rate(all_true_arr, all_proba_arr))

    result.n_folds = len(result.fold_metrics)
    result.total_test_samples = len(all_true)

    # Stability metrics across folds
    if fold_aucs:
        result.stability_metrics = {
            "auc_mean": float(np.mean(fold_aucs)),
            "auc_std": float(np.std(fold_aucs)),
            "auc_min": float(np.min(fold_aucs)),
            "auc_max": float(np.max(fold_aucs)),
            "acc_mean": float(np.mean(fold_accs)),
            "acc_std": float(np.std(fold_accs)),
            "folds_below_min_auc": int(sum(1 for a in fold_aucs if a < min_fold_auc)),
            "overfit_gap_mean": float(np.mean([m["overfit_gap"] for m in result.fold_metrics])),
            "is_stable": float(np.std(fold_aucs)) < 0.05 and all(a >= min_fold_auc for a in fold_aucs),
        }

    logger.info(
        "Walk-forward complete: %d folds (%d rejected), %d test samples, "
        "agg_acc=%.4f, auc_std=%.4f, stable=%s",
        result.n_folds, result.rejected_folds, result.total_test_samples,
        result.aggregate_metrics.get("accuracy", 0),
        result.stability_metrics.get("auc_std", 0),
        result.stability_metrics.get("is_stable", False),
    )
    return result
