# Model manager logic
"""Model manager singleton for inference-only serving of approved artifacts."""

from __future__ import annotations

import logging
import os
import threading

from backend.ml_platform.inference_pipeline import InferencePipeline, SchemaMismatchError

logger = logging.getLogger(__name__)


class ModelManager:
    """Thread-safe singleton for managing the loaded prediction model."""

    _instance: "ModelManager | None" = None
    _lock = threading.Lock()

    def __new__(cls) -> "ModelManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._pipeline = InferencePipeline()
                    cls._instance._status = "not_loaded"
                    cls._instance._active_version = None
        return cls._instance

    @property
    def model(self):
        return self._pipeline.model

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
                loaded = self._pipeline.load(version)
                self._status = "loaded"
                self._active_version = loaded.version
                logger.info("Model %s loaded successfully", loaded.version)
                return loaded.version
            except Exception:
                self._status = "error"
                raise

    def activate_version(self, version: str) -> str:
        with self._lock:
            self._status = "loading"
            try:
                loaded = self._pipeline.activate_version(version)
                self._status = "loaded"
                self._active_version = loaded.version
                logger.info("Model %s activated", loaded.version)
                return loaded.version
            except Exception:
                self._status = "error"
                raise

    def get_model_info(self) -> dict:
        """Return metadata about the currently loaded model."""
        # Auto-load latest model if none loaded yet
        if self.model is None and self._status == "not_loaded":
            try:
                self.load_latest()
            except Exception:
                pass  # no model available yet

        status_payload = self._pipeline.status()
        metrics = self._pipeline.metrics if isinstance(self._pipeline.metrics, dict) else {}
        metadata = self._pipeline.metadata if isinstance(self._pipeline.metadata, dict) else {}
        version = self._active_version or status_payload.get("model_version")

        return {
            "model_version": version or "none",
            "status": self._status,
            "last_trained": metadata.get("created_at") or metrics.get("timestamp"),
            "accuracy": metrics.get("classification_accuracy") or metrics.get("test_accuracy"),
            "executed_trade_win_rate": metrics.get("executed_trade_win_rate") or metrics.get("test_precision_executed"),
            "feature_count": status_payload.get("feature_count", 0),
            "artifact_format": status_payload.get("artifact_format"),
            "inference_only": _env_bool("INFERENCE_ONLY", _is_production()),
        }

    def get_model_metadata(self) -> dict:
        if self.model is None and self._status in {"not_loaded", "error"}:
            self.load_latest()
        return self._pipeline.model_metadata()

    def predict_from_features(
        self,
        features: dict,
        quantity: int = 1,
        min_net_edge_bps: float | None = None,
        slippage_bps: float | None = None,
    ) -> dict:
        """Run inference from explicit feature payload with strict schema checks."""
        if self.model is None or self._status != "loaded":
            self.load_latest()

        return self._pipeline.predict_from_features(
            features,
            quantity=quantity,
            min_net_edge_bps=(
                float(min_net_edge_bps)
                if min_net_edge_bps is not None
                else float(os.getenv("PREDICTION_MIN_EDGE_BPS", "6"))
            ),
            slippage_bps=(
                float(slippage_bps)
                if slippage_bps is not None
                else float(os.getenv("PREDICTION_SLIPPAGE_BPS", "2"))
            ),
        )

    def predict(self, ticker: str, horizon_days: int = 1) -> dict | None:
        """Run a full prediction pipeline for a ticker.

        Returns dict with keys: action, confidence, expected_return,
        model_version, calibration_score.  Returns None on failure.
        """
        # Auto-load latest model if none loaded
        if self.model is None or self._status != "loaded":
            try:
                self.load_latest()
            except Exception:
                logger.warning("predict() called but no model available")
                return None

        try:
            from backend.prediction_engine.feature_store.feature_store import get_features_for_inference

            feat_dict = get_features_for_inference(ticker)

            close_price = float(feat_dict.get("close", 0.0) or 0.0)
            if close_price <= 0:
                close_price = 100.0

            reference_capital = float(os.getenv("PREDICTION_REFERENCE_CAPITAL", "100000"))
            reference_position_pct = float(os.getenv("PREDICTION_REFERENCE_POSITION_PCT", "0.10"))
            reference_qty = max(1, int((reference_capital * reference_position_pct) / close_price))

            r = self.predict_from_features(feat_dict, quantity=reference_qty)
            details = r.get("details") if isinstance(r.get("details"), dict) else {}
            predicted_price = close_price * (1 + r["expected_return"])
            return {
                "action": r["action"],
                "confidence": r["confidence"],
                "expected_return": r["expected_return"],
                "net_expected_return": r.get("net_expected_return"),
                "trade_edge": details.get("trade_edge"),
                "buy_threshold": details.get("buy_threshold"),
                "sell_threshold": details.get("sell_threshold"),
                "no_trade_reason": details.get("no_trade_reason"),
                "predicted_price": predicted_price,
                "reference_price": close_price,
                "reference_quantity": reference_qty,
                "atr_14": float(feat_dict.get("atr_14", 0.0) or 0.0),
                "volatility_20": float(feat_dict.get("volatility_20", 0.0) or 0.0),
                "model_version": r.get("model_version") or self._active_version,
                "calibration_score": details.get("calibration_score"),
            }
        except SchemaMismatchError as exc:
            logger.warning("Schema mismatch for %s: %s", ticker, exc)
            return None
        except Exception as exc:
            logger.warning("Prediction failed for %s: %s", ticker, exc)
            return None


def _is_production() -> bool:
    return os.getenv("APP_ENV", "").strip().lower() in {"production", "prod"}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}
