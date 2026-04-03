# Model manager logic
"""Model manager â€“ singleton that holds the in-memory model and supports hot-reload."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from backend.prediction_engine.models.lightgbm_model import LightGBMModel

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = REPO_ROOT / "models" / "registry.json"
ARTIFACTS_DIR = REPO_ROOT / "models" / "artifacts"


class ModelManager:
    """Thread-safe singleton for managing the loaded prediction model."""

    _instance: "ModelManager | None" = None
    _lock = threading.Lock()

    def __new__(cls) -> "ModelManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._model = None
                    cls._instance._status = "not_loaded"
        return cls._instance

    @property
    def model(self) -> LightGBMModel | None:
        return self._model

    @property
    def status(self) -> str:
        return self._status

    def load_latest(self) -> str:
        """Load the latest model from the registry. Returns the version string."""
        return self._load_version(version=None)

    def load_version(self, version: str) -> str:
        """Load a specific model version."""
        return self._load_version(version=version)

    def _load_version(self, version: str | None) -> str:
        with self._lock:
            self._status = "loading"
            try:
                registry = self._read_registry()
                if version is None:
                    version = registry.get("latest")
                if not version:
                    raise ValueError("No model version available in registry")

                artifact_path = ARTIFACTS_DIR / version
                if not artifact_path.exists():
                    raise FileNotFoundError(f"Artifact not found: {artifact_path}")

                self._model = LightGBMModel.load(artifact_path)
                self._status = "loaded"
                logger.info("Model %s loaded successfully", version)
                return version
            except Exception:
                self._status = "error"
                raise

    def get_model_info(self) -> dict:
        """Return metadata about the currently loaded model."""
        # Auto-load latest model if none loaded yet
        if self._model is None and self._status == "not_loaded":
            try:
                self.load_latest()
            except Exception:
                pass  # no model available yet

        registry = self._read_registry()
        version = self._model.get_version() if self._model else None

        # Find metrics from registry
        metrics = {}
        if version and registry.get("models"):
            for entry in registry["models"]:
                if entry["version"] == version:
                    metrics = entry.get("metrics", {})
                    break

        return {
            "model_version": version or "none",
            "status": self._status,
            "last_trained": metrics.get("timestamp"),
            "accuracy": metrics.get("test_accuracy"),
        }

    def predict(self, ticker: str, horizon_days: int = 1) -> dict | None:
        """Run a full prediction pipeline for a ticker.

        Returns dict with keys: action, confidence, expected_return,
        model_version, calibration_score.  Returns None on failure.
        """
        # Auto-load latest model if none loaded
        if self._model is None or self._status != "loaded":
            try:
                self.load_latest()
            except Exception:
                logger.warning("predict() called but no model available")
                return None

        try:
            import pandas as pd
            from backend.prediction_engine.feature_store.feature_store import (
                get_features_for_inference,
                FEATURE_COLUMNS,
            )

            feat_dict = get_features_for_inference(ticker)
            numeric_cols = [c for c in FEATURE_COLUMNS if c not in ("ticker", "date")]
            X = pd.DataFrame([{c: feat_dict[c] for c in numeric_cols}])

            results = self._model.predict_with_expected_return(X)
            if not results:
                return None

            r = results[0]
            predicted_price = float(feat_dict["close"]) * (1 + r["expected_return"])
            return {
                "action": r["action"],
                "confidence": r["confidence"],
                "expected_return": r["expected_return"],
                "predicted_price": predicted_price,
                "model_version": self._model.get_version(),
                "calibration_score": r.get("calibration_score"),
            }
        except Exception as exc:
            logger.warning("Prediction failed for %s: %s", ticker, exc)
            return None

    @staticmethod
    def _read_registry() -> dict:
        if REGISTRY_PATH.exists():
            return json.loads(REGISTRY_PATH.read_text())
        return {"models": [], "latest": None}
