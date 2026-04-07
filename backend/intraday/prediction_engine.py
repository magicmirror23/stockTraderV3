"""Intraday prediction / inference engine – loads a trained intraday model
and produces trade signals from real-time feature snapshots.

Every signal includes confidence, expected return, and eligibility metadata
for downstream risk / execution filters.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

MODELS_DIR = Path("models/intraday")


@dataclass
class IntradaySignal:
    """Single intraday trade signal."""

    symbol: str
    action: str                 # "buy" | "sell" | "hold"
    confidence: float           # 0-1
    expected_return: float      # estimated N-bar return
    score: float                # raw model probability
    model_version: str
    features_used: int
    signal_type: str            # "breakout" | "momentum" | "mean_reversion"
    eligible: bool = True
    rejection_reason: str = ""


class IntradayPredictor:
    """Loads an intraday model and generates signals."""

    def __init__(self, model_dir: str | Path | None = None):
        self._model: Any = None
        self._meta: dict = {}
        self._feature_cols: list[str] = []
        self._loaded = False
        self._model_dir = Path(model_dir) if model_dir else MODELS_DIR

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def model_version(self) -> str:
        return self._meta.get("version", "unknown")

    def load_latest(self) -> bool:
        """Load the most recently trained intraday model."""
        if not self._model_dir.exists():
            logger.warning("Intraday model directory does not exist: %s", self._model_dir)
            return False

        versions = sorted(
            [d for d in self._model_dir.iterdir() if d.is_dir()],
            key=lambda d: d.name,
            reverse=True,
        )
        if not versions:
            logger.warning("No intraday model versions found in %s", self._model_dir)
            return False

        return self.load(versions[0])

    def load(self, model_path: Path) -> bool:
        """Load a specific model version."""
        try:
            import joblib

            model_file = model_path / "model.joblib"
            meta_file = model_path / "meta.json"

            if not model_file.exists():
                logger.error("Model file not found: %s", model_file)
                return False

            self._model = joblib.load(model_file)

            if meta_file.exists():
                with open(meta_file) as f:
                    self._meta = json.load(f)
                self._feature_cols = self._meta.get("feature_columns", [])
            else:
                self._feature_cols = []

            self._loaded = True
            logger.info("Loaded intraday model: %s (%s)",
                        self._meta.get("version", model_path.name),
                        self._meta.get("model_name", "unknown"))
            return True

        except Exception as exc:
            logger.error("Failed to load intraday model from %s: %s", model_path, exc)
            return False

    def predict(
        self,
        features: dict[str, float],
        symbol: str = "",
        *,
        buy_threshold: float = 0.55,
        sell_threshold: float = 0.45,
    ) -> IntradaySignal:
        """Generate a single signal from a feature dict."""
        if not self._loaded or self._model is None:
            return IntradaySignal(
                symbol=symbol, action="hold", confidence=0.0,
                expected_return=0.0, score=0.5, model_version="none",
                features_used=0, signal_type="none",
                eligible=False, rejection_reason="model_not_loaded",
            )

        # Align features to model's expected columns
        if self._feature_cols:
            X = np.array([[features.get(c, 0.0) for c in self._feature_cols]])
        else:
            X = np.array([list(features.values())])

        try:
            proba = self._model.predict_proba(X)[0]
            score = float(proba[1]) if len(proba) > 1 else float(proba[0])
        except Exception as exc:
            logger.warning("Prediction failed for %s: %s", symbol, exc)
            return IntradaySignal(
                symbol=symbol, action="hold", confidence=0.0,
                expected_return=0.0, score=0.5,
                model_version=self.model_version,
                features_used=len(features),
                signal_type=self._meta.get("target_type", "unknown"),
                eligible=False, rejection_reason=f"prediction_error: {exc}",
            )

        # Determine action using adaptive thresholds
        if score >= buy_threshold:
            action = "buy"
            confidence = min((score - 0.5) * 2, 1.0)
        elif score <= sell_threshold:
            action = "sell"
            confidence = min((0.5 - score) * 2, 1.0)
        else:
            action = "hold"
            confidence = 0.0

        # Estimate expected return from score
        threshold = self._meta.get("target_threshold", 0.002)
        expected_return = (score - 0.5) * threshold * 10  # rough estimate

        return IntradaySignal(
            symbol=symbol,
            action=action,
            confidence=confidence,
            expected_return=expected_return,
            score=score,
            model_version=self.model_version,
            features_used=len(self._feature_cols) or len(features),
            signal_type=self._meta.get("target_type", "breakout"),
        )

    def predict_batch(
        self,
        feature_dicts: list[dict[str, float]],
        symbols: list[str],
        **kwargs: Any,
    ) -> list[IntradaySignal]:
        """Generate signals for multiple symbols."""
        return [
            self.predict(feat, sym, **kwargs)
            for feat, sym in zip(feature_dicts, symbols)
        ]

    def get_info(self) -> dict:
        """Return model metadata."""
        return {
            "loaded": self._loaded,
            "version": self.model_version,
            "model_name": self._meta.get("model_name", "unknown"),
            "target_type": self._meta.get("target_type", "unknown"),
            "horizon_bars": self._meta.get("horizon_bars", 0),
            "n_features": len(self._feature_cols),
            "metrics": self._meta.get("metrics", {}),
        }
