"""Validation metrics — classification metrics + calibration analysis.

All metrics are designed for binary direction prediction (up/down).
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def compute_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    y_proba: np.ndarray | None = None,
) -> dict[str, Any]:
    """Compute comprehensive classification metrics.

    Returns a dict with accuracy, precision, recall, F1, AUC, log_loss, etc.
    """
    from sklearn.metrics import (
        accuracy_score,
        precision_score,
        recall_score,
        f1_score,
        roc_auc_score,
        log_loss,
        confusion_matrix,
    )

    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)

    n = len(y_true)
    if n == 0:
        return {"error": "empty dataset"}

    metrics: dict[str, Any] = {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "samples": n,
        "positive_ratio": float(y_true.mean()),
    }

    # Confusion matrix
    cm = confusion_matrix(y_true, y_pred)
    metrics["confusion_matrix"] = cm.tolist()

    if y_proba is not None:
        y_proba = np.asarray(y_proba)
        try:
            metrics["auc_roc"] = float(roc_auc_score(y_true, y_proba))
        except ValueError:
            metrics["auc_roc"] = 0.5

        try:
            metrics["log_loss"] = float(log_loss(y_true, y_proba))
        except Exception:
            metrics["log_loss"] = None

        # Expected Calibration Error
        metrics["ece"] = float(_expected_calibration_error(y_true, y_proba))

        # Brier score
        metrics["brier_score"] = float(np.mean((y_proba - y_true) ** 2))

    return metrics


def _expected_calibration_error(
    y_true: np.ndarray,
    y_proba: np.ndarray,
    n_bins: int = 10,
) -> float:
    """Compute Expected Calibration Error (ECE).

    Lower is better — measures how well predicted probabilities
    match actual frequencies.
    """
    bin_edges = np.linspace(0, 1, n_bins + 1)
    ece = 0.0
    for i in range(n_bins):
        mask = (y_proba >= bin_edges[i]) & (y_proba < bin_edges[i + 1])
        if mask.sum() == 0:
            continue
        bin_acc = y_true[mask].mean()
        bin_conf = y_proba[mask].mean()
        ece += mask.sum() / len(y_true) * abs(bin_acc - bin_conf)
    return ece


def compute_hit_rate(
    y_true: np.ndarray,
    y_proba: np.ndarray,
    threshold: float = 0.55,
) -> dict[str, float]:
    """Compute hit rate for trades above confidence threshold.

    Returns accuracy and count of trades that would be taken.
    """
    y_true = np.asarray(y_true)
    y_proba = np.asarray(y_proba)

    # Only consider predictions above threshold
    confident_mask = (y_proba >= threshold) | (y_proba <= (1 - threshold))
    if confident_mask.sum() == 0:
        return {"hit_rate": 0.0, "trade_count": 0, "coverage": 0.0}

    confident_preds = (y_proba[confident_mask] > 0.5).astype(int)
    confident_true = y_true[confident_mask]
    hit_rate = float((confident_preds == confident_true).mean())

    return {
        "hit_rate": hit_rate,
        "trade_count": int(confident_mask.sum()),
        "coverage": float(confident_mask.mean()),
    }
