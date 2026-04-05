# Model manager logic
"""Model manager â€“ singleton that holds the in-memory model and supports hot-reload."""

from __future__ import annotations

import json
import logging
import os
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

            close_price = float(feat_dict.get("close", 0.0) or 0.0)
            if close_price <= 0:
                close_price = 100.0

            reference_capital = float(os.getenv("PREDICTION_REFERENCE_CAPITAL", "100000"))
            reference_position_pct = float(os.getenv("PREDICTION_REFERENCE_POSITION_PCT", "0.10"))
            reference_qty = max(1, int((reference_capital * reference_position_pct) / close_price))

            results = self._model.predict_with_expected_return(
                X,
                price=close_price,
                quantity=reference_qty,
                min_net_edge_bps=float(os.getenv("PREDICTION_MIN_EDGE_BPS", "6")),
                slippage_bps=float(os.getenv("PREDICTION_SLIPPAGE_BPS", "2")),
            )
            if not results:
                return None

            r = results[0]
            predicted_price = close_price * (1 + r["expected_return"])
            return {
                "action": r["action"],
                "confidence": r["confidence"],
                "expected_return": r["expected_return"],
                "net_expected_return": r.get("net_expected_return"),
                "trade_edge": r.get("trade_edge"),
                "buy_threshold": r.get("buy_threshold"),
                "sell_threshold": r.get("sell_threshold"),
                "no_trade_reason": r.get("no_trade_reason"),
                "predicted_price": predicted_price,
                "reference_price": close_price,
                "reference_quantity": reference_qty,
                "atr_14": float(feat_dict.get("atr_14", 0.0) or 0.0),
                "volatility_20": float(feat_dict.get("volatility_20", 0.0) or 0.0),
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
