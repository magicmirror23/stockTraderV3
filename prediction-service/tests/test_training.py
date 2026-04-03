"""Tests for training pipeline — dataset building, splitting, validation."""

import numpy as np
import pandas as pd
import pytest

from app.training.dataset_builder import temporal_split, check_for_leakage
from app.training.validate import compute_metrics, compute_hit_rate


@pytest.fixture
def sample_dataset():
    """Create a sample labeled dataset."""
    np.random.seed(42)
    n = 500
    dates = pd.bdate_range("2022-01-01", periods=n)
    features = pd.DataFrame(
        np.random.randn(n, 10),
        index=dates,
        columns=[f"feat_{i}" for i in range(10)],
    )
    features["target"] = np.random.randint(0, 2, n)
    return features


def test_temporal_split(sample_dataset):
    split = temporal_split(sample_dataset)
    assert len(split.X_train) > 0
    assert len(split.X_val) > 0
    assert len(split.X_test) > 0
    # Train should come before val which comes before test
    assert split.train_dates[1] < split.val_dates[0]
    assert split.val_dates[1] < split.test_dates[0]


def test_no_leakage(sample_dataset):
    split = temporal_split(sample_dataset)
    warnings = check_for_leakage(split)
    # Should have no leakage warnings (temporal ordering)
    leakage_warnings = [w for w in warnings if "Train end" in w or "Val end" in w]
    assert len(leakage_warnings) == 0


def test_split_feature_columns(sample_dataset):
    split = temporal_split(sample_dataset)
    # Target should NOT be in features
    assert "target" not in split.feature_names
    assert "symbol" not in split.feature_names
    assert len(split.feature_names) == 10


def test_compute_metrics():
    y_true = np.array([1, 0, 1, 1, 0, 1, 0, 0])
    y_pred = np.array([1, 0, 1, 0, 0, 1, 1, 0])
    y_proba = np.array([0.9, 0.1, 0.8, 0.4, 0.2, 0.7, 0.6, 0.3])

    metrics = compute_metrics(y_true, y_pred, y_proba)
    assert "accuracy" in metrics
    assert "precision" in metrics
    assert "recall" in metrics
    assert "f1" in metrics
    assert "auc_roc" in metrics
    assert "ece" in metrics
    assert metrics["accuracy"] == 0.75


def test_compute_hit_rate():
    y_true = np.array([1, 0, 1, 1, 0])
    y_proba = np.array([0.9, 0.1, 0.7, 0.55, 0.45])

    result = compute_hit_rate(y_true, y_proba, threshold=0.55)
    assert "hit_rate" in result
    assert "trade_count" in result
    assert result["trade_count"] <= len(y_true)
