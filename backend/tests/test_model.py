# Model tests
"""Tests for model predict output shape and probability mapping."""

import numpy as np
import pandas as pd
import pytest

from backend.prediction_engine.models.lightgbm_model import LightGBMModel

# Skip all tests if lightgbm is not installed
lgb = pytest.importorskip("lightgbm")


class _DummyBooster:
    def __init__(self, probs):
        self._probs = np.asarray(probs, dtype=float)

    def predict(self, X):
        n = len(X)
        if n <= len(self._probs):
            return self._probs[:n]
        return np.pad(self._probs, (0, n - len(self._probs)), mode="edge")


@pytest.fixture()
def trained_model(tmp_path):
    """Train a tiny model on synthetic data."""
    np.random.seed(42)
    n = 200
    X = pd.DataFrame({
        "f1": np.random.randn(n),
        "f2": np.random.randn(n),
        "f3": np.random.randn(n),
    })
    y = pd.Series(np.random.choice([0, 1, 2], size=n))

    model = LightGBMModel(seed=42)
    model.train(X, y, num_boost_round=10)
    return model, X


def test_predict_shape(trained_model):
    model, X = trained_model
    preds = model.predict(X)
    assert preds.shape == (len(X),)
    assert set(np.unique(preds)).issubset({0, 1, 2})


def test_predict_proba_shape(trained_model):
    model, X = trained_model
    proba = model.predict_proba(X)
    # Binary model returns 1D P(up) array
    assert proba.shape == (len(X),)
    assert proba.min() >= 0.0
    assert proba.max() <= 1.0


def test_predict_proba_3class_shape(trained_model):
    model, X = trained_model
    proba = model.predict_proba_3class(X)
    assert proba.shape == (len(X), 3)
    np.testing.assert_allclose(proba.sum(axis=1), 1.0, atol=1e-6)


def test_predict_with_expected_return(trained_model):
    model, X = trained_model
    results = model.predict_with_expected_return(X)
    assert len(results) == len(X)
    for r in results:
        assert r["action"] in ("buy", "sell", "hold")
        assert 0.0 <= r["confidence"] <= 1.0
        assert "trade_edge" in r
        assert "no_trade_reason" in r


def test_predict_with_expected_return_holds_when_edge_too_small():
    model = LightGBMModel(seed=42)
    model._model = _DummyBooster([0.56])
    model._metrics = {"optimal_threshold": 0.52}

    X = pd.DataFrame(
        {
            "close": [100.0],
            "volatility_20": [0.02],
            "atr_14": [0.8],
        }
    )
    results = model.predict_with_expected_return(
        X,
        price=100.0,
        quantity=1,
        min_net_edge_bps=40,
        slippage_bps=5,
    )
    assert results[0]["action"] == "hold"
    assert results[0]["trade_edge"] >= 0
    assert results[0]["no_trade_reason"] in {
        "net_edge_below_costs",
        "probability_in_no_trade_band",
    }


def test_predict_with_expected_return_allows_strong_short_edge():
    model = LightGBMModel(seed=42)
    model._model = _DummyBooster([0.10])
    model._metrics = {"optimal_threshold": 0.52}

    X = pd.DataFrame(
        {
            "close": [100.0],
            "volatility_20": [0.03],
            "atr_14": [1.0],
        }
    )
    results = model.predict_with_expected_return(
        X,
        price=100.0,
        quantity=1,
        min_net_edge_bps=2,
        slippage_bps=0,
    )
    assert results[0]["action"] in {"sell", "hold"}
    if results[0]["action"] == "sell":
        assert results[0]["trade_edge"] > 0


def test_save_load_roundtrip(trained_model, tmp_path):
    model, X = trained_model
    original_preds = model.predict(X)

    model.save(tmp_path / "test_model")
    loaded = LightGBMModel.load(tmp_path / "test_model")

    np.testing.assert_array_equal(loaded.predict(X), original_preds)
    assert loaded.get_version() == model.get_version()
