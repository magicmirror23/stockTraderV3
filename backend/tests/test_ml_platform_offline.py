# Offline training / inference bundle tests
"""Tests for local-only training and inference artifact safety."""

from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.preprocessing import StandardScaler

from backend.ml_platform.inference_pipeline import InferencePipeline, SchemaMismatchError
from backend.ml_platform.training_pipeline import TrainingRunConfig, run_local_training
from backend.prediction_engine.training import trainer
from backend.prediction_engine.training.trainer import NUMERIC_FEATURES, TrainingPipelineError


class _DummyBinaryModel:
    def predict_proba(self, X):
        return np.array([[0.2, 0.8] for _ in range(len(X))], dtype=float)


def _write_bundle(base: Path) -> Path:
    version = "model_v001"
    model_dir = base / version
    model_dir.mkdir(parents=True, exist_ok=True)

    scaler = StandardScaler()
    scaler.fit(np.array([[1.0, 2.0, 100.0], [2.0, 3.0, 101.0]], dtype=float))

    with open(model_dir / "model.pkl", "wb") as f:
        pickle.dump(_DummyBinaryModel(), f)
    with open(model_dir / "scaler.pkl", "wb") as f:
        pickle.dump(scaler, f)

    (model_dir / "feature_columns.json").write_text(json.dumps(["f1", "f2", "close"]))
    (model_dir / "metadata.json").write_text(
        json.dumps({"model_version": version, "artifact_format": "bundle_v1"})
    )
    (model_dir / "metrics.json").write_text(json.dumps({"test_accuracy": 0.75}))

    (base / "index.json").write_text(
        json.dumps(
            {
                "active_version": version,
                "models": [{"version": version, "path": str(model_dir)}],
            }
        )
    )
    return model_dir


def test_inference_pipeline_loads_bundle_and_predicts(tmp_path):
    _write_bundle(tmp_path)

    pipeline = InferencePipeline(registry_dir=tmp_path)
    loaded = pipeline.load()
    assert loaded.version == "model_v001"
    assert pipeline.status()["loaded"] is True

    result = pipeline.predict_from_features({"f1": 1.5, "f2": 2.5, "close": 100.0})
    assert result["model_version"] == "model_v001"
    assert result["action"] in {"buy", "hold", "sell"}
    assert 0.0 <= result["confidence"] <= 1.0


def test_inference_pipeline_rejects_schema_mismatch(tmp_path):
    _write_bundle(tmp_path)
    pipeline = InferencePipeline(registry_dir=tmp_path)
    pipeline.load()

    with pytest.raises(SchemaMismatchError):
        pipeline.predict_from_features({"f1": 1.0, "close": 100.0})


def test_local_training_returns_structured_insufficient_data(monkeypatch, tmp_path):
    monkeypatch.setenv("TRAIN_DATA_SOURCE_MODE", "local_store_only")

    def _empty(*args, **kwargs):
        return [], {"requested": 1, "skipped": {"AAA": "missing"}}

    monkeypatch.setattr("backend.ml_platform.training_pipeline._ensure_data_available", _empty)

    with pytest.raises(TrainingPipelineError) as exc_info:
        run_local_training(
            tickers=["AAA"],
            run_config=TrainingRunConfig(
                data_dir=tmp_path / "raw",
                model_registry_dir=tmp_path / "models",
            ),
        )

    assert exc_info.value.reason == "insufficient_data"
    assert "symbols_skipped" in exc_info.value.details


def test_local_training_surfaces_leakage_as_structured_error(monkeypatch, tmp_path):
    monkeypatch.setenv("TRAIN_DATA_SOURCE_MODE", "local_store_only")

    dates = pd.date_range("2025-01-01", periods=50, freq="B")
    rows: list[dict] = []
    for i, dt in enumerate(dates):
        row = {"ticker": "AAA", "date": dt, "close": 100 + i}
        for idx, feature in enumerate(NUMERIC_FEATURES):
            row[feature] = float(i + idx + 1)
        rows.append(row)
    feature_df = pd.DataFrame(rows)

    def _ensure(*args, **kwargs):
        return ["AAA"], {"requested": 1, "skipped": {}, "available": ["AAA"]}

    def _build(*args, **kwargs):
        return feature_df.copy()

    def _validate(df, cfg):
        return df, {
            "symbols_used": ["AAA"],
            "symbols_skipped": [],
            "rows": int(len(df)),
            "unique_dates": int(df["date"].nunique()),
            "class_counts": {"0": 10, "1": 10},
        }

    def _split(df, config=None):
        train_df = df.iloc[:20].copy()
        val_df = df.iloc[20:35].copy()
        test_df = df.iloc[35:].copy()
        return train_df, val_df, test_df

    def _raise_leakage(*args, **kwargs):
        raise ValueError("leakage_detected_for_test")

    monkeypatch.setattr("backend.ml_platform.training_pipeline._ensure_data_available", _ensure)
    monkeypatch.setattr("backend.ml_platform.training_pipeline.build_features", _build)
    monkeypatch.setattr("backend.ml_platform.training_pipeline._validate_training_dataset", _validate)
    monkeypatch.setattr("backend.ml_platform.training_pipeline._walk_forward_split", _split)
    monkeypatch.setattr(trainer, "_normalize_features_per_ticker", lambda df, cols: df)
    monkeypatch.setattr("backend.shared.leakage.verify_labels", _raise_leakage)

    with pytest.raises(TrainingPipelineError) as exc_info:
        run_local_training(
            tickers=["AAA"],
            run_config=TrainingRunConfig(
                data_dir=tmp_path / "raw",
                model_registry_dir=tmp_path / "models",
            ),
        )

    assert exc_info.value.reason == "leakage_detected"
    assert "train_range" in exc_info.value.details


def test_local_training_rejects_all_invalid_features_with_structured_error(monkeypatch, tmp_path):
    monkeypatch.setenv("TRAIN_DATA_SOURCE_MODE", "local_store_only")

    dates = pd.date_range("2025-01-01", periods=60, freq="B")
    rows: list[dict] = []
    for i, dt in enumerate(dates):
        row = {"ticker": "AAA", "date": dt, "close": 100 + i}
        for idx, feature in enumerate(NUMERIC_FEATURES):
            row[feature] = float(i + idx + 1)
        rows.append(row)
    # Poison every row so sanitization drops all rows and returns structured failure.
    for row in rows:
        row[NUMERIC_FEATURES[0]] = float("inf")
    feature_df = pd.DataFrame(rows)

    def _ensure(*args, **kwargs):
        return ["AAA"], {"requested": 1, "skipped": {}, "available": ["AAA"]}

    def _build(*args, **kwargs):
        return feature_df.copy()

    def _validate(df, cfg):
        return df, {
            "symbols_used": ["AAA"],
            "symbols_skipped": [],
            "rows": int(len(df)),
            "unique_dates": int(df["date"].nunique()),
            "class_counts": {"0": 20, "1": 20},
        }

    def _split(df, config=None):
        train_df = df.iloc[:30].copy()
        val_df = df.iloc[30:45].copy()
        test_df = df.iloc[45:].copy()
        return train_df, val_df, test_df

    monkeypatch.setattr("backend.ml_platform.training_pipeline._ensure_data_available", _ensure)
    monkeypatch.setattr("backend.ml_platform.training_pipeline.build_features", _build)
    monkeypatch.setattr("backend.ml_platform.training_pipeline._validate_training_dataset", _validate)
    monkeypatch.setattr("backend.ml_platform.training_pipeline._walk_forward_split", _split)
    monkeypatch.setattr(trainer, "_normalize_features_per_ticker", lambda df, cols: df)
    monkeypatch.setattr("backend.shared.leakage.verify_labels", lambda *a, **k: None)
    monkeypatch.setattr("backend.shared.leakage.run_all_checks", lambda *a, **k: None)

    with pytest.raises(TrainingPipelineError) as exc_info:
        run_local_training(
            tickers=["AAA"],
            run_config=TrainingRunConfig(
                data_dir=tmp_path / "raw",
                model_registry_dir=tmp_path / "models",
            ),
        )

    assert exc_info.value.reason == "invalid_feature_values"
    assert exc_info.value.details["inf_values_found"] >= 1
    assert exc_info.value.details["invalid_rows_dropped"] >= 1
