"""Dataset builder — time-series safe train/val/test splitting.

CRITICAL: All splits are temporal (no future data leakage).
Implements purge + embargo to handle label overlap and rolling features.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.core.config import settings

logger = logging.getLogger(__name__)

# Features that are known to use forward-looking information if mis-computed.
# Any column matching these patterns will be flagged during leakage audit.
_FORWARD_LOOKING_PATTERNS: list[re.Pattern] = [
    re.compile(r"future_", re.IGNORECASE),
    re.compile(r"_forward", re.IGNORECASE),
    re.compile(r"target_", re.IGNORECASE),
    re.compile(r"next_day", re.IGNORECASE),
    re.compile(r"_lead_?\d", re.IGNORECASE),
]


@dataclass
class SplitResult:
    """Result of a train/val/test split."""
    X_train: pd.DataFrame
    y_train: pd.Series
    X_val: pd.DataFrame
    y_val: pd.Series
    X_test: pd.DataFrame
    y_test: pd.Series
    feature_names: list[str]
    train_dates: tuple[str, str]
    val_dates: tuple[str, str]
    test_dates: tuple[str, str]
    purged_train_count: int = 0
    leakage_audit: dict = field(default_factory=dict)


def temporal_split(
    df: pd.DataFrame,
    target_col: str = "target",
    train_ratio: float = 0.7,
    val_ratio: float = 0.15,
    embargo_days: int | None = None,
    purge_days: int | None = None,
    label_horizon: int | None = None,
) -> SplitResult:
    """Split data temporally: train → purge+embargo → val → purge+embargo → test.

    The purge window removes training rows whose labels overlap with the
    test start.  The embargo adds an extra gap on top of the purge.
    """
    embargo_days = embargo_days if embargo_days is not None else settings.TRAIN_EMBARGO_DAYS
    purge_days = purge_days if purge_days is not None else settings.TRAIN_PURGE_DAYS
    label_horizon = label_horizon if label_horizon is not None else settings.LABEL_HORIZON_DAYS

    if target_col not in df.columns:
        raise ValueError(f"Target column '{target_col}' not found")

    df = df.sort_index()
    n = len(df)
    train_end = int(n * train_ratio)
    val_end = int(n * (train_ratio + val_ratio))

    # Total gap = purge (label overlap) + embargo (safety margin)
    total_gap = purge_days + embargo_days

    train_df = df.iloc[:train_end]
    val_df = df.iloc[train_end + total_gap:val_end]
    test_df = df.iloc[val_end + total_gap:]

    if val_df.empty or test_df.empty:
        raise ValueError(
            f"Purge+embargo ({total_gap}d) consumed val or test set. "
            f"Reduce purge_days/embargo_days or add more data."
        )

    # Purge: remove training rows whose label window overlaps val/test start
    train_df = _purge_overlapping_labels(train_df, val_df.index.min(), label_horizon, purge_days)
    purged_count = train_end - len(train_df)

    exclude = {target_col, "symbol"}
    feature_cols = [c for c in df.columns if c not in exclude]

    # Audit features for leakage signals
    audit = _audit_features(feature_cols, train_df[feature_cols], train_df[target_col])

    split = SplitResult(
        X_train=train_df[feature_cols],
        y_train=train_df[target_col],
        X_val=val_df[feature_cols],
        y_val=val_df[target_col],
        X_test=test_df[feature_cols],
        y_test=test_df[target_col],
        feature_names=feature_cols,
        train_dates=(str(train_df.index.min()), str(train_df.index.max())),
        val_dates=(str(val_df.index.min()), str(val_df.index.max())),
        test_dates=(str(test_df.index.min()), str(test_df.index.max())),
        purged_train_count=purged_count,
        leakage_audit=audit,
    )

    logger.info(
        "Temporal split: train=%d [%s..%s] (purged %d), val=%d [%s..%s], "
        "test=%d [%s..%s], purge=%dd, embargo=%dd",
        len(train_df), *split.train_dates, purged_count,
        len(val_df), *split.val_dates,
        len(test_df), *split.test_dates,
        purge_days, embargo_days,
    )
    return split


def _purge_overlapping_labels(
    train_df: pd.DataFrame,
    boundary: pd.Timestamp,
    label_horizon: int,
    purge_days: int,
) -> pd.DataFrame:
    """Remove training rows whose label window reaches past *boundary*.

    For a label that uses t+label_horizon return, any training row within
    label_horizon + purge_days of the boundary must be removed.
    """
    cutoff = boundary - pd.Timedelta(days=label_horizon + purge_days)
    return train_df[train_df.index <= cutoff]


def purge_overlap(
    train_idx: pd.DatetimeIndex,
    test_idx: pd.DatetimeIndex,
    embargo_days: int = 5,
    label_horizon: int = 1,
) -> pd.DatetimeIndex:
    """Remove training samples whose label window overlaps the test set.

    Returns filtered train index.
    """
    if len(test_idx) == 0:
        return train_idx

    test_start = test_idx.min()
    cutoff = test_start - pd.Timedelta(days=embargo_days + label_horizon)
    return train_idx[train_idx <= cutoff]


def _audit_features(
    feature_cols: list[str],
    X_train: pd.DataFrame,
    y_train: pd.Series,
) -> dict:
    """Detect features that look suspiciously leaky.

    Checks:
      1. Column names matching forward-looking patterns.
      2. Features with unrealistically high point-biserial correlation
         to the target (|r| > 0.95 strongly suggests label leakage).
      3. Features that are constant (zero-variance).
    """
    flagged_names: list[str] = []
    high_corr: list[dict] = []
    zero_var: list[str] = []

    for col in feature_cols:
        for pat in _FORWARD_LOOKING_PATTERNS:
            if pat.search(col):
                flagged_names.append(col)
                break

    # Point-biserial correlation (fast: Pearson on binary target)
    try:
        y_arr = y_train.values.astype(float)
        if y_arr.std() > 0:
            for col in feature_cols:
                series = X_train[col]
                if series.std() == 0:
                    zero_var.append(col)
                    continue
                r = np.corrcoef(series.fillna(0).values, y_arr)[0, 1]
                if abs(r) > 0.95:
                    high_corr.append({"feature": col, "correlation": round(float(r), 4)})
    except Exception:
        pass

    audit = {}
    if flagged_names:
        audit["suspect_column_names"] = flagged_names
        logger.warning("Leakage audit: suspect column names: %s", flagged_names)
    if high_corr:
        audit["high_target_correlation"] = high_corr
        logger.warning("Leakage audit: features with |r| > 0.95: %s", high_corr)
    if zero_var:
        audit["zero_variance_features"] = zero_var
        logger.info("Leakage audit: %d zero-variance features", len(zero_var))

    if not audit:
        logger.info("Leakage audit passed — no suspicious features found")
    return audit


def check_for_leakage(split: SplitResult) -> list[str]:
    """Validate that no future information leaks into training data.

    Returns a list of warnings (empty if clean).
    """
    warnings = []

    # Check temporal ordering
    if split.train_dates[1] >= split.val_dates[0]:
        warnings.append(f"Train end ({split.train_dates[1]}) >= Val start ({split.val_dates[0]})")
    if split.val_dates[1] >= split.test_dates[0]:
        warnings.append(f"Val end ({split.val_dates[1]}) >= Test start ({split.test_dates[0]})")

    # Check for NaN target
    if split.y_train.isna().any():
        warnings.append(f"Train target has {split.y_train.isna().sum()} NaN values")
    if split.y_test.isna().any():
        warnings.append(f"Test target has {split.y_test.isna().sum()} NaN values")

    # Check class balance
    for name, y in [("train", split.y_train), ("val", split.y_val), ("test", split.y_test)]:
        if len(y) > 0:
            pos_ratio = y.mean()
            if pos_ratio < 0.3 or pos_ratio > 0.7:
                warnings.append(f"{name} set imbalanced: {pos_ratio:.2%} positive")

    # Surface leakage audit results as warnings
    audit = split.leakage_audit
    if audit.get("suspect_column_names"):
        warnings.append(f"Suspect column names: {audit['suspect_column_names']}")
    if audit.get("high_target_correlation"):
        warnings.append(f"High-correlation features: {audit['high_target_correlation']}")

    if warnings:
        for w in warnings:
            logger.warning("Leakage check: %s", w)
    else:
        logger.info("Leakage check passed")

    return warnings
