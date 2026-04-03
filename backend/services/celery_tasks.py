# Celery task definitions
"""Celery tasks for scheduled model retraining.

Configure a Celery beat schedule to call ``retrain_nightly`` on a cron.
Requires Redis or RabbitMQ as a broker.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

CELERY_BROKER = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")

try:
    from celery import Celery
    from celery.schedules import crontab

    app = Celery("stocktrader", broker=CELERY_BROKER)
    app.conf.timezone = "UTC"
    app.conf.beat_schedule = {
        "retrain-nightly": {
            "task": "backend.services.celery_tasks.retrain_nightly",
            "schedule": crontab(hour=2, minute=0),  # 02:00 UTC
        },
    }
    _CELERY_AVAILABLE = True
except ImportError:
    app = None
    _CELERY_AVAILABLE = False
    logger.info("celery not installed â€“ scheduled retrain disabled")


def _run_retrain() -> dict:
    """Common retrain logic shared by Celery task and sync fallback."""
    from backend.prediction_engine.training.trainer import train
    from backend.services.mlflow_registry import log_model_training
    from backend.services.model_manager import ModelManager
    from backend.services.monitoring import record_retrain

    try:
        entry = train()
        try:
            log_model_training(
                experiment_name="stocktrader",
                model_version=entry["version"],
                params=entry.get("params", {}),
                metrics=entry.get("metrics", {}),
            )
        except Exception:
            logger.debug("MLflow logging skipped during retrain")

        mgr = ModelManager()
        mgr.load_latest()
        record_retrain("success")

        return {
            "status": "success",
            "model_version": entry["version"],
            "metrics": entry.get("metrics", {}),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        record_retrain("failed")
        logger.exception("Retrain task failed")
        raise


if _CELERY_AVAILABLE:
    @app.task(name="backend.services.celery_tasks.retrain_nightly", bind=True, max_retries=2)
    def retrain_nightly(self):
        """Celery task: retrain all models and register new versions."""
        try:
            return _run_retrain()
        except Exception as exc:
            self.retry(exc=exc, countdown=300)

