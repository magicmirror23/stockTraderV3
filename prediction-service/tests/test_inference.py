"""Tests for inference pipeline."""

import numpy as np
import pandas as pd
import pytest

from app.inference.confidence import apply_confidence_threshold, calibrate_probability
from app.inference.regime_router import adjust_for_regime


def test_confidence_threshold_long():
    assert apply_confidence_threshold(0.7, threshold=0.55) == "long"


def test_confidence_threshold_short():
    assert apply_confidence_threshold(0.3, threshold=0.55) == "short"


def test_confidence_threshold_no_trade():
    assert apply_confidence_threshold(0.52, threshold=0.55) == "no_trade"


def test_calibrate_probability():
    # Identity calibration
    p = calibrate_probability(0.7, calibration_factor=1.0)
    assert abs(p - 0.7) < 0.01

    # Sharpening
    p_sharp = calibrate_probability(0.7, calibration_factor=2.0)
    assert p_sharp > 0.7  # More confident


def test_regime_adjustment():
    result = adjust_for_regime(0.65, 0.8, "trending_up")
    assert result["adjusted_probability"] > 0.65  # Bullish bias
    assert "regime" in result

    result_vol = adjust_for_regime(0.65, 0.8, "high_volatility")
    assert result_vol["adjusted_confidence"] < 0.8  # Reduced confidence


def test_regime_unknown():
    result = adjust_for_regime(0.5, 0.5, "nonexistent_regime")
    # Should fallback to mean-reverting defaults
    assert "adjusted_probability" in result
