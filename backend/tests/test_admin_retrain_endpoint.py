# Admin retrain endpoint tests
"""Tests that retrain endpoint fails gracefully with structured payloads."""

from __future__ import annotations

from backend.api.routers import admin
from backend.prediction_engine.training.trainer import TrainingPipelineError


def _reset_retrain_state() -> None:
    with admin._retrain_lock:
        admin._retrain_status.update(
            running=False,
            progress=None,
            error=None,
            reason=None,
            details=None,
            correlation_id=None,
        )


def test_retrain_returns_structured_insufficient_data(client, monkeypatch):
    _reset_retrain_state()

    def _raise_training_error():
        raise TrainingPipelineError(
            reason="insufficient_data",
            message="Not enough unique dates to split safely (got 27).",
            details={
                "unique_dates": 27,
                "required_min_dates": 120,
                "symbols_skipped": ["TATAMOTORS"],
            },
        )

    monkeypatch.setattr(admin, "_run_train_sync", _raise_training_error)

    res = client.post("/api/v1/retrain")
    body = res.json()

    assert res.status_code == 200
    assert body["status"] == "failed"
    assert body["reason"] == "insufficient_data"
    assert body["details"]["unique_dates"] == 27
    assert "correlation_id" in body
    assert body["correlation_id"]


def test_retrain_success_payload_shape(client, monkeypatch):
    _reset_retrain_state()

    def _ok():
        return {
            "version": "v_test_001",
            "metrics": {"test_accuracy": 0.61},
        }

    monkeypatch.setattr(admin, "_run_train_sync", _ok)
    monkeypatch.setattr(admin.ModelManager, "load_latest", lambda self: None)

    res = client.post("/api/v1/retrain")
    body = res.json()

    assert res.status_code == 200
    assert body["status"] == "success"
    assert body["model_version"] == "v_test_001"
    assert body["metrics"]["test_accuracy"] == 0.61
    assert "correlation_id" in body
    assert body["correlation_id"]


def test_retrain_disabled_in_production_by_default(client, monkeypatch):
    _reset_retrain_state()
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("INFERENCE_ONLY", "true")
    monkeypatch.setenv("ALLOW_PROD_RETRAIN", "false")

    res = client.post("/api/v1/retrain")
    body = res.json()

    assert res.status_code == 403
    assert body["status"] == "failed"
    assert body["reason"] == "retrain_disabled"
    assert body["details"]["disabled_reason"] in {
        "inference_only_mode",
        "prod_retrain_disabled",
    }


def test_retrain_maps_invalid_feature_valueerror_to_structured_failure(client, monkeypatch):
    _reset_retrain_state()

    def _raise_value_error():
        raise ValueError("Input X contains infinity or a value too large for dtype('float64').")

    monkeypatch.setattr(admin, "_run_train_sync", _raise_value_error)

    res = client.post("/api/v1/retrain")
    body = res.json()

    assert res.status_code == 200
    assert body["status"] == "failed"
    assert body["reason"] == "invalid_feature_values"
    assert "correlation_id" in body
