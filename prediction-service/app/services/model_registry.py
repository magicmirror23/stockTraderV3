"""Model registry — version management for trained models.

Tracks active model, supports promotion/retirement,
and auto-loads the latest model at startup.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


class ModelRegistry:
    """File-based model registry backed by a JSON manifest."""

    def __init__(self, artifacts_dir: str | None = None):
        self.artifacts_dir = Path(artifacts_dir or settings.MODEL_ARTIFACTS_DIR)
        self._manifest_path = self.artifacts_dir / "registry.json"
        self._manifest: dict[str, Any] = self._load_manifest()

    def _load_manifest(self) -> dict[str, Any]:
        if self._manifest_path.exists():
            try:
                data = json.loads(self._manifest_path.read_text())
                if "models" not in data:
                    data["models"] = {}
                return data
            except Exception:
                pass
        return {"active_version": None, "models": {}}

    def _save_manifest(self) -> None:
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._manifest_path.write_text(json.dumps(self._manifest, indent=2, default=str))

    @property
    def active_version(self) -> str | None:
        return self._manifest.get("active_version")

    def list_versions(self) -> list[dict[str, Any]]:
        """List all registered model versions."""
        models = self._manifest.get("models", {})
        return [
            {"version": v, **info}
            for v, info in sorted(models.items(), reverse=True)
        ]

    def register(
        self,
        version: str,
        model_type: str,
        metrics: dict | None = None,
        artifact_path: str | None = None,
    ) -> None:
        """Register a new model version."""
        self._manifest.setdefault("models", {})[version] = {
            "model_type": model_type,
            "registered_at": datetime.now(timezone.utc).isoformat(),
            "status": "trained",
            "metrics": metrics or {},
            "artifact_path": artifact_path or str(self.artifacts_dir / version / "model.joblib"),
        }
        self._save_manifest()
        logger.info("Registered model %s (%s)", version, model_type)

    def promote(self, version: str) -> bool:
        """Promote a model to active status."""
        models = self._manifest.get("models", {})
        if version not in models:
            logger.error("Version %s not found in registry", version)
            return False

        # Retire current active
        current = self._manifest.get("active_version")
        if current and current in models:
            models[current]["status"] = "retired"

        models[version]["status"] = "active"
        self._manifest["active_version"] = version
        self._save_manifest()
        logger.info("Promoted model %s to active", version)
        return True

    def retire(self, version: str) -> bool:
        """Retire a model version."""
        models = self._manifest.get("models", {})
        if version not in models:
            return False
        models[version]["status"] = "retired"
        if self._manifest.get("active_version") == version:
            self._manifest["active_version"] = None
        self._save_manifest()
        return True

    def get_latest_version(self) -> str | None:
        """Get the most recently registered version."""
        models = self._manifest.get("models", {})
        if not models:
            # Fallback: scan directories
            if self.artifacts_dir.exists():
                versions = sorted(
                    [d.name for d in self.artifacts_dir.iterdir()
                     if d.is_dir() and d.name.startswith("v")],
                    reverse=True,
                )
                return versions[0] if versions else None
            return None
        return max(models.keys())

    def get_model_path(self, version: str | None = None) -> str | None:
        """Get the artifact path for a version."""
        version = version or self.active_version or self.get_latest_version()
        if not version:
            return None
        models = self._manifest.get("models", {})
        info = models.get(version, {})
        return info.get("artifact_path", str(self.artifacts_dir / version / "model.joblib"))


# Singleton instance
_registry: ModelRegistry | None = None


def get_registry() -> ModelRegistry:
    global _registry
    if _registry is None:
        _registry = ModelRegistry()
    return _registry
