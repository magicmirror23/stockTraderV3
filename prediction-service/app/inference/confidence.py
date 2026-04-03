"""Confidence scoring, calibration, and threshold application.

Maps raw model probabilities through a fitted calibrator, then to
actionable recommendations:  long / short / neutral / no_trade.

The calibrator is fitted on the validation set during training and
saved alongside the model artifact.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from app.core.config import settings

logger = logging.getLogger(__name__)

# Module-level calibrator (loaded once, shared across requests)
_calibrator: Any = None
_calibrator_version: str | None = None


def load_calibrator(version: str | None = None) -> bool:
    """Load a persisted calibrator from the model artifacts directory.

    Returns True if a calibrator was loaded successfully.
    """
    global _calibrator, _calibrator_version
    import joblib

    artifact_base = Path(settings.MODEL_ARTIFACTS_DIR)
    if version:
        cal_path = artifact_base / version / "calibrator.joblib"
    else:
        versions = sorted(
            [d for d in artifact_base.iterdir() if d.is_dir() and d.name.startswith("v")],
            key=lambda d: d.name,
            reverse=True,
        )
        cal_path = None
        for v in versions:
            candidate = v / "calibrator.joblib"
            if candidate.exists():
                cal_path = candidate
                break

    if cal_path is None or not cal_path.exists():
        logger.info("No calibrator found — using raw probabilities")
        return False

    try:
        _calibrator = joblib.load(str(cal_path))
        _calibrator_version = cal_path.parent.name
        logger.info("Loaded calibrator %s from %s", _calibrator_version, cal_path)
        return True
    except Exception as exc:
        logger.warning("Failed to load calibrator: %s", exc)
        return False


def calibrate_probability(raw_proba: float) -> float:
    """Calibrate a raw model probability via the fitted calibrator.

    Falls back to Platt-style logit scaling if no calibrator is loaded.
    """
    if _calibrator is not None:
        try:
            # sklearn calibrators expect 2-class probability array
            arr = np.array([[1 - raw_proba, raw_proba]])
            calibrated = _calibrator.predict_proba(arr)[0, 1]
            return float(np.clip(calibrated, 0.01, 0.99))
        except Exception:
            pass

    # Fallback: identity (no distortion when no calibrator)
    return float(np.clip(raw_proba, 0.01, 0.99))


def apply_confidence_threshold(
    probability: float,
    threshold: float | None = None,
    regime_threshold_shift: float = 0.0,
) -> str:
    """Convert probability to a trading recommendation.

    Args:
        probability: P(up) from the model (0-1).
        threshold: Confidence threshold. Defaults to settings value.
        regime_threshold_shift: Additional shift to the no-trade zone
            (positive = wider zone = fewer trades).

    Returns:
        One of: "long", "short", "neutral", "no_trade"
    """
    threshold = threshold or settings.PREDICTION_CONFIDENCE_THRESHOLD
    effective_threshold = threshold + regime_threshold_shift

    # Distance from 0.5 = confidence
    confidence = abs(probability - 0.5)

    if confidence < (effective_threshold - 0.5):
        return "no_trade"

    if probability >= effective_threshold:
        return "long"
    elif probability <= (1 - effective_threshold):
        return "short"
    else:
        return "neutral"


def fit_calibrator(
    y_val: np.ndarray,
    val_proba: np.ndarray,
    method: str = "isotonic",
) -> Any:
    """Fit a calibrator on validation predictions and return it.

    Args:
        y_val: True binary labels.
        val_proba: Raw model P(class=1) on validation set.
        method: 'isotonic' or 'sigmoid' (Platt scaling).

    Returns:
        A fitted sklearn CalibratedClassifierCV-compatible object.
    """
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.base import BaseEstimator, ClassifierMixin

    class _PrecomputedClassifier(BaseEstimator, ClassifierMixin):
        """Shim that behaves like a fitted classifier for CalibratedClassifierCV."""
        classes_ = np.array([0, 1])

        def __init__(self, probas: np.ndarray):
            self._probas = probas
            self._idx = 0

        def fit(self, X, y):
            return self

        def predict_proba(self, X):
            # Return the pre-computed probabilities row-by-row
            n = len(X)
            p = self._probas[self._idx:self._idx + n]
            self._idx += n
            return np.column_stack([1 - p, p])

        def decision_function(self, X):
            return self.predict_proba(X)[:, 1]

    # Use sklearn's isotonic/sigmoid calibration fitted on the val set
    from sklearn.isotonic import IsotonicRegression
    from sklearn.linear_model import LogisticRegression as PlattLR

    if method == "isotonic":
        ir = IsotonicRegression(out_of_bounds="clip", y_min=0.01, y_max=0.99)
        ir.fit(val_proba, y_val)

        class _IsotonicCalibrator:
            """Lightweight wrapper matching sklearn calibrator interface."""
            def __init__(self, ir):
                self._ir = ir

            def predict_proba(self, X):
                p1 = self._ir.predict(X[:, 1])
                return np.column_stack([1 - p1, p1])

        return _IsotonicCalibrator(ir)

    else:
        # Platt scaling (logistic regression on logits)
        eps = 1e-7
        logits = np.log(np.clip(val_proba, eps, 1 - eps) / (1 - np.clip(val_proba, eps, 1 - eps)))
        lr = PlattLR(C=1e10, solver="lbfgs", max_iter=1000)
        lr.fit(logits.reshape(-1, 1), y_val)

        class _PlattCalibrator:
            def __init__(self, lr):
                self._lr = lr

            def predict_proba(self, X):
                eps = 1e-7
                raw = X[:, 1]
                logits = np.log(np.clip(raw, eps, 1 - eps) / (1 - np.clip(raw, eps, 1 - eps)))
                return self._lr.predict_proba(logits.reshape(-1, 1))

        return _PlattCalibrator(lr)


def save_calibrator(calibrator: Any, version: str) -> str:
    """Persist a calibrator alongside model artifacts."""
    import joblib

    artifact_dir = Path(settings.MODEL_ARTIFACTS_DIR) / version
    artifact_dir.mkdir(parents=True, exist_ok=True)
    path = str(artifact_dir / "calibrator.joblib")
    joblib.dump(calibrator, path)
    logger.info("Saved calibrator to %s", path)
    return path
