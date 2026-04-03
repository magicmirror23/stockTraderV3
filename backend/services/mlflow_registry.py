# MLflow registry integration
"""MLflow integration for model artifact storage and metric tracking."""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "")

_MLFLOW_AVAILABLE = False
if MLFLOW_TRACKING_URI:
    try:
        import mlflow
        mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
        _MLFLOW_AVAILABLE = True
    except ImportError:
        logger.info("mlflow not installed — model registry disabled")
else:
    logger.info("MLFLOW_TRACKING_URI not set — using local JSON registry")


def log_model_training(
    experiment_name: str,
    model_version: str,
    params: dict,
    metrics: dict,
    artifact_path: str | None = None,
    tags: dict | None = None,
) -> str | None:
    """Log a training run to MLflow.

    Returns the MLflow run ID, or None if MLflow is unavailable.
    """
    if not _MLFLOW_AVAILABLE:
        logger.info("MLflow unavailable â€“ skipping log for %s", model_version)
        return None

    mlflow.set_experiment(experiment_name)
    with mlflow.start_run(run_name=model_version) as run:
        mlflow.log_params(params)
        mlflow.log_metrics(metrics)
        if tags:
            mlflow.set_tags(tags)
        if artifact_path and os.path.exists(artifact_path):
            mlflow.log_artifact(artifact_path)
        logger.info("MLflow run %s logged for %s", run.info.run_id, model_version)
        return run.info.run_id


def register_model(
    run_id: str,
    model_name: str = "stocktrader_ensemble",
    artifact_path: str = "model",
) -> str | None:
    """Register a model version in the MLflow Model Registry."""
    if not _MLFLOW_AVAILABLE:
        return None

    model_uri = f"runs:/{run_id}/{artifact_path}"
    result = mlflow.register_model(model_uri, model_name)
    logger.info("Registered model %s version %s", model_name, result.version)
    return result.version


def get_latest_model_version(
    model_name: str = "stocktrader_ensemble",
) -> dict | None:
    """Return metadata for the latest registered model version."""
    if not _MLFLOW_AVAILABLE:
        return None

    client = mlflow.tracking.MlflowClient()
    versions = client.search_model_versions(f"name='{model_name}'")
    if not versions:
        return None

    latest = max(versions, key=lambda v: int(v.version))
    return {
        "name": latest.name,
        "version": latest.version,
        "stage": latest.current_stage,
        "run_id": latest.run_id,
        "status": latest.status,
    }
