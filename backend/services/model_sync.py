"""Model artifact sync helpers for microservice deployments.

Admin service trains models, then ships artifacts to prediction service so
inference can load the exact same version without shared filesystem mounts.
"""

from __future__ import annotations

import base64
import io
import json
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS_DIR = REPO_ROOT / "models" / "artifacts"
REGISTRY_PATH = REPO_ROOT / "models" / "registry.json"


def _read_registry() -> dict[str, Any]:
    if REGISTRY_PATH.exists():
        try:
            data = json.loads(REGISTRY_PATH.read_text())
            if isinstance(data, dict):
                data.setdefault("models", [])
                data.setdefault("latest", None)
                return data
        except (json.JSONDecodeError, ValueError):
            pass
    return {"models": [], "latest": None}


def _write_registry(registry: dict[str, Any]) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(registry, indent=2))


def _upsert_registry_entry(version: str, entry: dict[str, Any] | None, set_latest: bool) -> None:
    registry = _read_registry()
    rows = list(registry.get("models", []))

    merged = {
        "version": version,
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        "artifact_path": f"models/artifacts/{version}",
    }
    if isinstance(entry, dict):
        merged.update(entry)
        merged["version"] = version

    replaced = False
    for idx, row in enumerate(rows):
        if row.get("version") == version:
            rows[idx] = merged
            replaced = True
            break
    if not replaced:
        rows.append(merged)

    registry["models"] = rows
    if set_latest:
        registry["latest"] = version
    _write_registry(registry)


def _safe_extract_tar(tar: tarfile.TarFile, destination: Path) -> None:
    destination = destination.resolve()
    for member in tar.getmembers():
        target = (destination / member.name).resolve()
        if not str(target).startswith(str(destination)):
            raise ValueError(f"Unsafe archive path detected: {member.name}")
    tar.extractall(destination)


def build_model_sync_payload(version: str, registry_entry: dict[str, Any] | None = None) -> dict[str, Any]:
    """Pack model artifact directory into a JSON-safe payload."""
    artifact_dir = ARTIFACTS_DIR / version
    if not artifact_dir.exists() or not artifact_dir.is_dir():
        raise FileNotFoundError(f"Model artifact path not found: {artifact_dir}")

    payload_bytes = io.BytesIO()
    with tarfile.open(fileobj=payload_bytes, mode="w:gz") as archive:
        archive.add(artifact_dir, arcname=version)

    blob = base64.b64encode(payload_bytes.getvalue()).decode("ascii")
    return {
        "version": version,
        "artifact_tgz_b64": blob,
        "registry_entry": registry_entry or {},
    }


def apply_model_sync_payload(payload: dict[str, Any], *, set_latest: bool = True) -> dict[str, Any]:
    """Unpack synced artifact payload into local models directory."""
    if not isinstance(payload, dict):
        raise ValueError("Sync payload must be an object")

    version = str(payload.get("version", "")).strip()
    bundle_b64 = payload.get("artifact_tgz_b64")
    if not version:
        raise ValueError("Missing version in sync payload")
    if not bundle_b64:
        raise ValueError("Missing artifact_tgz_b64 in sync payload")

    raw = base64.b64decode(bundle_b64)
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        _safe_extract_tar(archive, ARTIFACTS_DIR)

    artifact_dir = ARTIFACTS_DIR / version
    if not artifact_dir.exists():
        raise FileNotFoundError(f"Synced artifact directory missing after extraction: {artifact_dir}")

    entry = payload.get("registry_entry")
    _upsert_registry_entry(version, entry if isinstance(entry, dict) else None, set_latest=set_latest)

    return {
        "status": "synced",
        "version": version,
        "artifact_path": str(artifact_dir),
        "registry_path": str(REGISTRY_PATH),
    }
