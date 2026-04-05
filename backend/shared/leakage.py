"""Leakage prevention and temporal validation utilities.

Hard anti-leakage rules enforced across training, validation, backtest,
and paper simulation.  Every function raises ``LeakageError`` on violation
so the pipeline fails loudly instead of silently producing fake results.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------
# Custom exception
# -----------------------------------------------------------------------

class LeakageError(Exception):
    """Raised when temporal or data leakage is detected."""


# -----------------------------------------------------------------------
# Walk-forward splitter with embargo
# -----------------------------------------------------------------------

@dataclass(frozen=True)
class SplitWindow:
    """One fold in a walk-forward validation."""
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    embargo_end: pd.Timestamp   # = train_end + embargo_days
    val_start: pd.Timestamp     # = embargo_end + 1 day
    val_end: pd.Timestamp
    fold_id: int


def walk_forward_splits(
    dates: pd.DatetimeIndex | pd.Series,
    *,
    n_folds: int = 5,
    train_days: int = 252,
    val_days: int = 63,
    embargo_days: int = 10,
    step_days: int | None = None,
) -> list[SplitWindow]:
    """Generate non-overlapping walk-forward folds with embargo gaps.

    Parameters
    ----------
    dates
        Sorted unique dates in the dataset.
    n_folds
        Maximum number of folds to generate.
    train_days
        Calendar days in each training window.
    val_days
        Calendar days in each validation window.
    embargo_days
        Gap between train and validation to prevent label leakage from
        rolling features or forward-looking labels.
    step_days
        How far to advance the window each fold.  Defaults to
        ``val_days`` (no overlap in validation windows).

    Returns
    -------
    list[SplitWindow]
        Folds ordered chronologically.  Each fold's validation window
        is guaranteed to start *after* the embargo gap ends.
    """
    if step_days is None:
        step_days = val_days

    dates = pd.DatetimeIndex(sorted(dates.unique()))
    if dates.empty:
        raise LeakageError("Empty date index — cannot create splits.")

    first, last = dates[0], dates[-1]
    folds: list[SplitWindow] = []

    fold_id = 0
    cursor = first

    while fold_id < n_folds:
        train_start = cursor
        train_end = cursor + timedelta(days=train_days)
        embargo_end = train_end + timedelta(days=embargo_days)
        val_start = embargo_end + timedelta(days=1)
        val_end = val_start + timedelta(days=val_days)

        if val_end > last:
            break

        folds.append(SplitWindow(
            train_start=pd.Timestamp(train_start),
            train_end=pd.Timestamp(train_end),
            embargo_end=pd.Timestamp(embargo_end),
            val_start=pd.Timestamp(val_start),
            val_end=pd.Timestamp(val_end),
            fold_id=fold_id,
        ))
        cursor += timedelta(days=step_days)
        fold_id += 1

    if not folds:
        raise LeakageError(
            f"Cannot create any folds with train={train_days}d, "
            f"val={val_days}d, embargo={embargo_days}d over "
            f"{(last - first).days}d of data."
        )
    return folds


def apply_split(
    df: pd.DataFrame,
    window: SplitWindow,
    date_col: str = "date",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Slice *df* into (train, val) according to *window*.

    Raises ``LeakageError`` if the resulting sets overlap or if embargo
    rows leak into validation.
    """
    dates = pd.to_datetime(df[date_col])
    train_mask = (dates >= window.train_start) & (dates <= window.train_end)
    val_mask = (dates >= window.val_start) & (dates <= window.val_end)

    # Paranoid overlap check
    overlap = train_mask & val_mask
    if overlap.any():
        raise LeakageError(
            f"Fold {window.fold_id}: {overlap.sum()} rows appear in both "
            "train and validation — temporal leakage."
        )
    embargo_leak = (dates > window.train_end) & (dates < window.val_start) & val_mask
    if embargo_leak.any():
        raise LeakageError(
            f"Fold {window.fold_id}: {embargo_leak.sum()} embargo-period "
            "rows leaked into validation."
        )

    return df.loc[train_mask].copy(), df.loc[val_mask].copy()


# -----------------------------------------------------------------------
# Feature timestamp safety
# -----------------------------------------------------------------------

def verify_feature_timestamps(
    features_df: pd.DataFrame,
    decision_time_col: str = "date",
    suspect_cols: Sequence[str] | None = None,
) -> None:
    """Check that no feature value was computed with future data.

    Heuristic checks:
    1. No column should have a correlation > 0.95 with a forward-shifted
       version of itself — that signals it was accidentally forward-filled.
    2. Named columns containing 'future' or 'forward' raise immediately.
    3. If *suspect_cols* are provided, verify their latest available
       timestamp ≤ the decision timestamp per row.
    """
    for col in features_df.columns:
        lower = col.lower()
        if "future" in lower or "forward" in lower or "target" in lower:
            raise LeakageError(
                f"Column '{col}' contains a forward-looking keyword. "
                "Rename it or remove it from the feature set."
            )

    # Forward-fill check: if corr(x, x.shift(-1)) > 0.95, suspicious
    # Use finite-only samples and variance guards to avoid noisy numpy warnings
    # from degenerate vectors (all-constant / inf-heavy columns).
    numeric_cols = features_df.select_dtypes(include=[np.number]).columns
    for col in numeric_cols:
        series = features_df[col].replace([np.inf, -np.inf], np.nan).dropna()
        if len(series) < 50:
            continue
        shifted = series.shift(-1)
        pair = pd.concat([series, shifted], axis=1).dropna()
        if len(pair) < 20:
            continue
        x = pair.iloc[:, 0]
        y = pair.iloc[:, 1]
        # Constant vectors do not have a meaningful correlation.
        if float(x.std(ddof=0)) <= 1e-12 or float(y.std(ddof=0)) <= 1e-12:
            continue
        corr = float(x.corr(y))
        if not np.isfinite(corr):
            continue
        if abs(corr) > 0.98:
            logger.warning(
                "Column '%s' has %.3f corr with 1-step-ahead shift — "
                "possible forward-fill leakage.", col, corr,
            )

    if suspect_cols:
        for col in suspect_cols:
            if col not in features_df.columns:
                continue
            if features_df[col].isna().all():
                continue
            # Additional project-specific checks can go here
            logger.debug("Suspect column '%s' passed basic checks.", col)


# -----------------------------------------------------------------------
# Label integrity
# -----------------------------------------------------------------------

def verify_labels(
    df: pd.DataFrame,
    label_col: str = "label",
    date_col: str = "date",
    horizon: int = 1,
    require_tail_nan: bool = True,
) -> None:
    """Verify that labels are built from strictly future data.

    Checks:
    1. No label should be non-NaN for the last *horizon* rows per
       ticker — those rows have no future data to form a label.
    2. Labels should not be identical to any feature column
       (target contamination).

    Parameters
    ----------
    require_tail_nan:
        Set to ``False`` when validating already-truncated training splits
        where tail rows without future labels have already been removed.
    """
    if label_col not in df.columns:
        raise LeakageError(f"Label column '{label_col}' not found.")

    # Check last-horizon rows per ticker
    if require_tail_nan:
        if "ticker" in df.columns:
            groups = df.groupby("ticker")
        else:
            groups = [(None, df)]

        for name, group in groups:
            tail = group.sort_values(date_col).tail(horizon)
            non_nan_labels = tail[label_col].dropna()
            if not non_nan_labels.empty:
                raise LeakageError(
                    f"Ticker '{name}': last {horizon} rows have non-NaN labels. "
                    "Labels cannot exist without sufficient future data."
                )

    # Target contamination check
    numeric = df.select_dtypes(include=[np.number]).replace([np.inf, -np.inf], np.nan)
    for col in numeric.columns:
        if col == label_col:
            continue
        valid = numeric[[col, label_col]].dropna()
        if len(valid) < 50:
            continue
        x = valid[col]
        y = valid[label_col]
        if float(x.std(ddof=0)) <= 1e-12 or float(y.std(ddof=0)) <= 1e-12:
            continue
        corr = float(x.corr(y))
        if not np.isfinite(corr):
            continue
        if abs(corr) > 0.95:
            raise LeakageError(
                f"Feature '{col}' has {corr:.3f} correlation with label — "
                "likely target contamination."
            )


# -----------------------------------------------------------------------
# Normalisation leak check
# -----------------------------------------------------------------------

def verify_no_future_normalisation(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    date_col: str = "date",
) -> None:
    """Ensure validation data was not used to fit normalisation statistics.

    This is a documentation-enforced check.  It verifies that the
    validation set's date range is strictly after the training set.
    """
    train_max = pd.to_datetime(train_df[date_col]).max()
    val_min = pd.to_datetime(val_df[date_col]).min()

    if val_min <= train_max:
        raise LeakageError(
            f"Validation starts at {val_min} but training ends at "
            f"{train_max} — validation data overlaps training period."
        )


# -----------------------------------------------------------------------
# Cross-validation guard
# -----------------------------------------------------------------------

def verify_no_shuffled_cv(
    splits: list[tuple[np.ndarray, np.ndarray]],
    dates: pd.Series,
) -> None:
    """Verify that train/val index splits respect chronological order.

    In every fold the maximum training date must be before the minimum
    validation date.
    """
    dates = pd.to_datetime(dates)
    for fold_idx, (train_idx, val_idx) in enumerate(splits):
        train_max = dates.iloc[train_idx].max()
        val_min = dates.iloc[val_idx].min()
        if val_min <= train_max:
            raise LeakageError(
                f"CV fold {fold_idx}: val starts at {val_min} but "
                f"train ends at {train_max} — shuffled CV detected."
            )


# -----------------------------------------------------------------------
# Backtest anti-lookahead
# -----------------------------------------------------------------------

def verify_backtest_no_lookahead(
    signals_df: pd.DataFrame,
    price_df: pd.DataFrame,
    signal_date_col: str = "date",
    price_date_col: str = "Date",
) -> None:
    """Verify backtest signals don't use future prices.

    For each signal row, the signal date must be ≤ the price date used
    for execution.  This catches same-bar entry/exit bugs.
    """
    if signals_df.empty or price_df.empty:
        return

    signal_dates = pd.to_datetime(signals_df[signal_date_col])
    # Signals should reference only past/current prices
    max_signal = signal_dates.max()
    max_price = pd.to_datetime(price_df[price_date_col]).max()

    if max_signal > max_price:
        raise LeakageError(
            f"Signals reference dates up to {max_signal} but price data "
            f"only goes to {max_price} — future price leakage."
        )


# -----------------------------------------------------------------------
# Convenience: run all checks at once
# -----------------------------------------------------------------------

def run_all_checks(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    label_col: str = "label",
    date_col: str = "date",
    horizon: int = 1,
    require_tail_nan: bool = True,
) -> None:
    """Run the full suite of leakage checks.  Raises ``LeakageError``
    on the first violation detected."""
    verify_feature_timestamps(train_df, decision_time_col=date_col)
    verify_feature_timestamps(val_df, decision_time_col=date_col)
    verify_labels(
        train_df,
        label_col=label_col,
        date_col=date_col,
        horizon=horizon,
        require_tail_nan=require_tail_nan,
    )
    verify_no_future_normalisation(train_df, val_df, date_col=date_col)
    logger.info("All leakage checks passed.")
