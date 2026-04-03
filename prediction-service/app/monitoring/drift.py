"""Drift detection — PSI, calibration drift, and hit-rate monitoring.

Compares recent prediction distributions against a reference period
to detect model degradation before it affects trading performance.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from app.core.config import settings
from app.core.metrics import FEATURE_DRIFT_SCORE, CALIBRATION_DRIFT

logger = logging.getLogger(__name__)


def population_stability_index(
    reference: np.ndarray,
    current: np.ndarray,
    n_bins: int = 10,
) -> float:
    """Compute Population Stability Index (PSI).

    PSI < 0.1  → no drift
    PSI 0.1–0.2 → moderate drift
    PSI > 0.2  → significant drift
    """
    eps = 1e-8
    ref_bins = np.histogram(reference, bins=n_bins, range=(0, 1))[0] / len(reference) + eps
    cur_bins = np.histogram(current, bins=n_bins, range=(0, 1))[0] / len(current) + eps

    psi = np.sum((cur_bins - ref_bins) * np.log(cur_bins / ref_bins))
    return float(psi)


def feature_psi(
    reference_df,
    current_df,
    feature_names: list[str] | None = None,
    n_bins: int = 10,
) -> dict[str, float]:
    """Compute PSI per feature."""
    import pandas as pd

    if feature_names is None:
        feature_names = list(reference_df.columns)

    results = {}
    for col in feature_names:
        if col in reference_df.columns and col in current_df.columns:
            ref = reference_df[col].dropna().values
            cur = current_df[col].dropna().values
            if len(ref) > 0 and len(cur) > 0:
                # Normalise to [0, 1] for PSI computation
                combined_min = min(ref.min(), cur.min())
                combined_max = max(ref.max(), cur.max())
                if combined_max > combined_min:
                    ref_norm = (ref - combined_min) / (combined_max - combined_min)
                    cur_norm = (cur - combined_min) / (combined_max - combined_min)
                    results[col] = population_stability_index(ref_norm, cur_norm, n_bins)
                else:
                    results[col] = 0.0
    return results


def calibration_drift_score(
    y_true: np.ndarray,
    y_proba: np.ndarray,
    n_bins: int = 10,
) -> float:
    """Compute calibration ECE drift score.

    Same as ECE — rising ECE indicates calibration drift.
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
    return float(ece)


async def run_drift_check(
    lookback_days: int = 30,
    reference_days: int = 90,
) -> dict[str, Any]:
    """Run a comprehensive drift check against recent predictions.

    Returns drift report with PSI scores, calibration ECE, and alert flags.
    """
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select
    from app.db.session import async_session_factory
    from app.db.models import PredictionRecord, DriftMetric

    now = datetime.now(timezone.utc)
    current_cutoff = now - timedelta(days=lookback_days)
    reference_cutoff = now - timedelta(days=reference_days)

    async with async_session_factory() as session:
        # Fetch recent predictions
        current_stmt = select(PredictionRecord).where(
            PredictionRecord.timestamp >= current_cutoff
        )
        current_result = await session.execute(current_stmt)
        current_rows = current_result.scalars().all()

        # Fetch reference predictions
        ref_stmt = select(PredictionRecord).where(
            PredictionRecord.timestamp >= reference_cutoff,
            PredictionRecord.timestamp < current_cutoff,
        )
        ref_result = await session.execute(ref_stmt)
        ref_rows = ref_result.scalars().all()

    if len(current_rows) < 10 or len(ref_rows) < 10:
        logger.info("Insufficient predictions for drift check (current=%d, ref=%d)", len(current_rows), len(ref_rows))
        return {"status": "insufficient_data", "current_count": len(current_rows), "reference_count": len(ref_rows)}

    # PSI on prediction probabilities
    ref_proba = np.array([r.direction_probability for r in ref_rows if r.direction_probability])
    cur_proba = np.array([r.direction_probability for r in current_rows if r.direction_probability])

    psi = population_stability_index(ref_proba, cur_proba) if len(ref_proba) > 0 and len(cur_proba) > 0 else 0.0

    # Confidence distribution shift
    ref_conf = np.array([r.confidence_score for r in ref_rows if r.confidence_score])
    cur_conf = np.array([r.confidence_score for r in current_rows if r.confidence_score])
    conf_psi = population_stability_index(ref_conf, cur_conf) if len(ref_conf) > 0 and len(cur_conf) > 0 else 0.0

    is_drifted = psi > 0.2 or conf_psi > 0.2

    # Update Prometheus metrics
    FEATURE_DRIFT_SCORE.set(psi)
    CALIBRATION_DRIFT.set(conf_psi)

    # Persist drift metric
    async with async_session_factory() as session:
        record = DriftMetric(
            model_version=current_rows[0].model_version if current_rows else None,
            feature_psi_scores={"prediction_psi": psi, "confidence_psi": conf_psi},
            is_drifted=is_drifted,
        )
        session.add(record)
        await session.commit()

    report = {
        "prediction_psi": round(psi, 4),
        "confidence_psi": round(conf_psi, 4),
        "is_drifted": is_drifted,
        "current_predictions": len(current_rows),
        "reference_predictions": len(ref_rows),
        "alert": "DRIFT DETECTED" if is_drifted else "OK",
    }

    if is_drifted:
        logger.warning("Drift detected: PSI=%.4f", psi)
    else:
        logger.info("Drift check passed: PSI=%.4f", psi)

    return report
