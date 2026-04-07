"""Inference-only model loading and schema-safe prediction."""

from __future__ import annotations

import json
import logging
import os
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY_DIR = REPO_ROOT / "models"
LEGACY_ARTIFACTS_DIR = REPO_ROOT / "models" / "artifacts"
LEGACY_REGISTRY_PATH = REPO_ROOT / "models" / "registry.json"


class SchemaMismatchError(ValueError):
    """Raised when inference features do not match the trained schema."""


class IdentityScaler:
    """No-op scaler used for legacy artifacts without serialized scaler."""

    def transform(self, X):
        return X


@dataclass(frozen=True)
class LoadedArtifact:
    version: str
    path: Path
    feature_columns: list[str]
    metadata: dict[str, Any]
    metrics: dict[str, Any]


class InferencePipeline:
    """Loads approved model artifacts and enforces feature-schema checks."""

    def __init__(
        self,
        *,
        active_model_dir: str | Path | None = None,
        registry_dir: str | Path | None = None,
    ) -> None:
        env_registry = os.getenv("MODEL_REGISTRY_DIR", "").strip()
        env_active = os.getenv("ACTIVE_MODEL_DIR", "").strip()

        self.registry_dir = Path(registry_dir or env_registry or DEFAULT_REGISTRY_DIR)
        self.active_model_dir = Path(active_model_dir or env_active) if (active_model_dir or env_active) else None
        self.index_path = self.registry_dir / "index.json"

        self.model = None
        self.scaler = IdentityScaler()
        self.feature_columns: list[str] = []
        self.metadata: dict[str, Any] = {}
        self.metrics: dict[str, Any] = {}
        self.version: str | None = None
        self.loaded_path: Path | None = None

    @staticmethod
    def _is_new_bundle(path: Path) -> bool:
        required = [
            path / "model.pkl",
            path / "scaler.pkl",
            path / "feature_columns.json",
            path / "metadata.json",
            path / "metrics.json",
        ]
        return all(p.exists() for p in required)

    @staticmethod
    def _is_legacy_bundle(path: Path) -> bool:
        return (path / "model.pkl").exists() and (path / "meta.json").exists()

    def _read_index(self) -> dict[str, Any]:
        if self.index_path.exists():
            try:
                data = json.loads(self.index_path.read_text())
                if isinstance(data, dict):
                    data.setdefault("active_version", None)
                    data.setdefault("models", [])
                    return data
            except Exception:
                pass
        return {"active_version": None, "models": []}

    def _write_index(self, payload: dict[str, Any]) -> None:
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(json.dumps(payload, indent=2))

    def _resolve_active_path(self) -> tuple[Path, str] | None:
        # Explicit active model dir has first priority.
        if self.active_model_dir and self.active_model_dir.exists():
            return self.active_model_dir, self.active_model_dir.name

        # New registry index.
        index = self._read_index()
        active_version = str(index.get("active_version") or "").strip()
        if active_version:
            path = self.registry_dir / active_version
            if path.exists():
                return path, active_version

        # Legacy registry fallback.
        if LEGACY_REGISTRY_PATH.exists():
            try:
                reg = json.loads(LEGACY_REGISTRY_PATH.read_text())
                latest = str(reg.get("latest") or "").strip()
                if latest:
                    legacy_path = LEGACY_ARTIFACTS_DIR / latest
                    if legacy_path.exists():
                        return legacy_path, latest
            except Exception:
                pass

        return None

    def _load_new_bundle(self, path: Path, version: str) -> LoadedArtifact:
        with open(path / "model.pkl", "rb") as f:
            model = pickle.load(f)  # noqa: S301
        with open(path / "scaler.pkl", "rb") as f:
            scaler = pickle.load(f)  # noqa: S301

        feature_columns = json.loads((path / "feature_columns.json").read_text())
        metadata = json.loads((path / "metadata.json").read_text())
        metrics = json.loads((path / "metrics.json").read_text())

        if not isinstance(feature_columns, list) or not feature_columns:
            raise ValueError(f"Invalid feature_columns.json at {path}")

        self.model = model
        self.scaler = scaler
        self.feature_columns = [str(col) for col in feature_columns]
        self.metadata = metadata if isinstance(metadata, dict) else {}
        self.metrics = metrics if isinstance(metrics, dict) else {}
        self.version = str(metadata.get("model_version") or version)
        self.loaded_path = path

        return LoadedArtifact(
            version=self.version,
            path=path,
            feature_columns=self.feature_columns,
            metadata=self.metadata,
            metrics=self.metrics,
        )

    def _load_legacy_bundle(self, path: Path, version: str) -> LoadedArtifact:
        from backend.prediction_engine.models.lightgbm_model import LightGBMModel
        from backend.prediction_engine.training.trainer import NUMERIC_FEATURES

        model = LightGBMModel.load(path)
        meta = json.loads((path / "meta.json").read_text())

        self.model = model
        self.scaler = IdentityScaler()
        self.feature_columns = [str(col) for col in meta.get("feature_columns", NUMERIC_FEATURES)]
        self.metadata = {
            "model_version": version,
            "artifact_format": "legacy",
            "loaded_from": str(path),
            **(meta if isinstance(meta, dict) else {}),
        }
        self.metrics = meta.get("metrics", {}) if isinstance(meta, dict) else {}
        self.version = version
        self.loaded_path = path

        return LoadedArtifact(
            version=version,
            path=path,
            feature_columns=self.feature_columns,
            metadata=self.metadata,
            metrics=self.metrics,
        )

    def load(self, version: str | None = None) -> LoadedArtifact:
        if version:
            candidate = self.registry_dir / version
            if self._is_new_bundle(candidate):
                return self._load_new_bundle(candidate, version)

            legacy_candidate = LEGACY_ARTIFACTS_DIR / version
            if self._is_legacy_bundle(legacy_candidate):
                return self._load_legacy_bundle(legacy_candidate, version)

            raise FileNotFoundError(f"Model version not found: {version}")

        resolved = self._resolve_active_path()
        if not resolved:
            raise FileNotFoundError("No active model artifact found.")
        path, resolved_version = resolved

        if self._is_new_bundle(path):
            return self._load_new_bundle(path, resolved_version)
        if self._is_legacy_bundle(path):
            return self._load_legacy_bundle(path, resolved_version)

        raise FileNotFoundError(f"Unsupported artifact format at {path}")

    def activate_version(self, version: str) -> LoadedArtifact:
        target = self.registry_dir / version
        if not target.exists():
            raise FileNotFoundError(f"Version directory missing: {target}")

        index = self._read_index()
        models = list(index.get("models", []))
        if not any(str(row.get("version")) == version for row in models):
            models.append(
                {
                    "version": version,
                    "path": str(target),
                }
            )
        index["models"] = models
        index["active_version"] = version
        self._write_index(index)

        return self.load(version)

    def ensure_loaded(self) -> None:
        if self.model is None or not self.feature_columns:
            self.load()

    def validate_features(self, features: dict[str, Any]) -> pd.DataFrame:
        self.ensure_loaded()
        defaults = self.metadata.get("default_feature_values", {}) if isinstance(self.metadata, dict) else {}
        if not isinstance(defaults, dict):
            defaults = {}

        missing = [col for col in self.feature_columns if col not in features]
        unresolved = [col for col in missing if col not in defaults]
        if unresolved:
            raise SchemaMismatchError(
                f"Missing required features: {', '.join(unresolved[:12])}" +
                (" ..." if len(unresolved) > 12 else "")
            )

        row = {col: features.get(col, defaults.get(col)) for col in self.feature_columns}
        frame = pd.DataFrame([row])
        for col in self.feature_columns:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
        if frame[self.feature_columns].isna().any(axis=None):
            bad_cols = [c for c in self.feature_columns if frame[c].isna().any()]
            raise SchemaMismatchError(
                f"Non-numeric or null feature values for: {', '.join(bad_cols[:12])}" +
                (" ..." if len(bad_cols) > 12 else "")
            )

        transformed = self.scaler.transform(frame[self.feature_columns])
        transformed_df = pd.DataFrame(transformed, columns=self.feature_columns)
        return transformed_df

    def predict_from_features(
        self,
        features: dict[str, Any],
        *,
        quantity: int = 1,
        min_net_edge_bps: float | None = None,
        slippage_bps: float | None = None,
    ) -> dict[str, Any]:
        self.ensure_loaded()
        X = self.validate_features(features)

        price = float(features.get("close", 100.0) or 100.0)
        min_edge = float(min_net_edge_bps if min_net_edge_bps is not None else os.getenv("PREDICTION_MIN_EDGE_BPS", "6"))
        slip = float(slippage_bps if slippage_bps is not None else os.getenv("PREDICTION_SLIPPAGE_BPS", "2"))

        if hasattr(self.model, "predict_with_expected_return"):
            rows = self.model.predict_with_expected_return(
                X,
                price=price,
                quantity=max(1, int(quantity)),
                min_net_edge_bps=min_edge,
                slippage_bps=slip,
            )
            row = rows[0]
            return {
                "action": row.get("action", "hold"),
                "confidence": float(row.get("confidence", 0.0)),
                "expected_return": float(row.get("expected_return", 0.0)),
                "net_expected_return": float(row.get("net_expected_return", 0.0)),
                "model_version": self.version or "unknown",
                "details": row,
            }

        # Generic fallback
        proba = self.model.predict_proba(X)
        if hasattr(proba, "ndim") and proba.ndim == 2:
            p_up = float(proba[0][1] if proba.shape[1] > 1 else proba[0][0])
        else:
            p_up = float(proba[0])
        action = "buy" if p_up >= 0.55 else "sell" if p_up <= 0.45 else "hold"
        return {
            "action": action,
            "confidence": float(max(p_up, 1.0 - p_up)),
            "expected_return": 0.0,
            "model_version": self.version or "unknown",
            "details": {"p_up": p_up},
        }

    def status(self) -> dict[str, Any]:
        return {
            "loaded": self.model is not None,
            "model_version": self.version,
            "active_model_dir": str(self.loaded_path) if self.loaded_path else None,
            "feature_count": len(self.feature_columns),
            "artifact_format": self.metadata.get("artifact_format", "bundle"),
        }

    def model_metadata(self) -> dict[str, Any]:
        self.ensure_loaded()
        return {
            "model_version": self.version,
            "feature_columns": self.feature_columns,
            "metadata": self.metadata,
            "metrics": self.metrics,
            "active_model_dir": str(self.loaded_path) if self.loaded_path else None,
        }
