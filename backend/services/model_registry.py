# Model registry logic
"""MLflow integration for model artifacts and metrics tracking."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "")

try:
    import mlflow

    if MLFLOW_TRACKING_URI:
        mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    _MLFLOW_AVAILABLE = True
except ImportError:
    _MLFLOW_AVAILABLE = False
    logger.info("mlflow not installed â€“ registry will use local JSON fallback")


class ModelRegistry:
    """Unified interface to model registry (MLflow or local JSON)."""

    def __init__(self, registry_path: str | Path | None = None) -> None:
        self._registry_path = Path(registry_path) if registry_path else (
            Path(__file__).resolve().parents[2] / "models" / "registry.json"
        )

    def log_model(
        self,
        version: str,
        metrics: dict,
        params: dict | None = None,
        artifact_path: str | None = None,
    ) -> None:
        """Log a trained model to the registry."""
        if _MLFLOW_AVAILABLE and MLFLOW_TRACKING_URI:
            self._log_mlflow(version, metrics, params, artifact_path)
        else:
            self._log_local(version, metrics, params, artifact_path)

    def get_latest_version(self) -> str | None:
        registry = self._read_registry()
        return registry.get("latest")

    def list_versions(self) -> list[dict]:
        registry = self._read_registry()
        return registry.get("models", [])

    def get_model_metadata(self, version: str) -> dict | None:
        for entry in self.list_versions():
            if entry["version"] == version:
                return entry
        return None

    # ------------------------------------------------------------------
    # MLflow backend
    # ------------------------------------------------------------------

    @staticmethod
    def _log_mlflow(version, metrics, params, artifact_path):
        with mlflow.start_run(run_name=f"model-{version}"):
            if params:
                mlflow.log_params(params)
            mlflow.log_metrics(metrics)
            if artifact_path:
                mlflow.log_artifacts(artifact_path)
            mlflow.set_tag("model_version", version)

    # ------------------------------------------------------------------
    # Local JSON backend
    # ------------------------------------------------------------------

    def _log_local(self, version, metrics, params, artifact_path):
        registry = self._read_registry()
        entry = {
            "version": version,
            "metrics": metrics,
            "params": params,
            "artifact_path": artifact_path,
        }
        registry.setdefault("models", []).append(entry)
        registry["latest"] = version
        self._write_registry(registry)

    def _read_registry(self) -> dict:
        if self._registry_path.exists():
            try:
                data = json.loads(self._registry_path.read_text())
                if isinstance(data, dict):
                    data.setdefault("models", [])
                    data.setdefault("latest", None)
                    return data
            except (json.JSONDecodeError, ValueError):
                pass
        return {"models": [], "latest": None}

    def _write_registry(self, data: dict) -> None:
        self._registry_path.parent.mkdir(parents=True, exist_ok=True)
        self._registry_path.write_text(json.dumps(data, indent=2))
