"""Regime router — routes predictions through regime-specific model weights
and adjusts thresholds based on the detected market regime.

In trending markets, momentum-sensitive models get higher weight.
In mean-reverting markets, mean-reversion signals dominate.
In volatile markets, widen the no-trade zone and cut position sizing.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from app.models.regime_model import MarketRegime

logger = logging.getLogger(__name__)

# Per-regime tuning: ensemble weight overrides, threshold shifts, sizing.
# model_weight_overrides maps model-name → multiplier (applied on top of
# base ensemble weights).
REGIME_CONFIG: dict[str, dict[str, Any]] = {
    MarketRegime.TRENDING_UP.value: {
        "confidence_multiplier": 1.10,
        "no_trade_zone_shift": -0.02,
        "bias": 0.0,
        "max_position_pct": 1.0,
        "model_weight_overrides": {
            "lightgbm": 1.20,
            "xgboost": 1.10,
            "random_forest": 0.70,
        },
    },
    MarketRegime.TRENDING_DOWN.value: {
        "confidence_multiplier": 1.10,
        "no_trade_zone_shift": -0.02,
        "bias": 0.0,
        "max_position_pct": 0.80,
        "model_weight_overrides": {
            "lightgbm": 1.20,
            "xgboost": 1.10,
            "random_forest": 0.70,
        },
    },
    MarketRegime.MEAN_REVERTING.value: {
        "confidence_multiplier": 0.95,
        "no_trade_zone_shift": 0.02,
        "bias": 0.0,
        "max_position_pct": 0.90,
        "model_weight_overrides": {
            "lightgbm": 0.90,
            "xgboost": 0.90,
            "random_forest": 1.20,
        },
    },
    MarketRegime.HIGH_VOLATILITY.value: {
        "confidence_multiplier": 0.65,
        "no_trade_zone_shift": 0.07,
        "bias": 0.0,
        "max_position_pct": 0.50,
        "model_weight_overrides": {
            "lightgbm": 0.80,
            "xgboost": 0.80,
            "random_forest": 1.00,
        },
    },
    MarketRegime.LOW_VOLATILITY.value: {
        "confidence_multiplier": 1.0,
        "no_trade_zone_shift": 0.0,
        "bias": 0.0,
        "max_position_pct": 1.0,
        "model_weight_overrides": {},
    },
}

_DEFAULT_CONFIG = REGIME_CONFIG[MarketRegime.MEAN_REVERTING.value]


def adjust_for_regime(
    probability: float,
    confidence: float,
    regime: str,
) -> dict[str, Any]:
    """Adjust prediction based on current market regime.

    Returns adjusted probability, confidence, position sizing cap,
    and regime metadata.
    """
    config = REGIME_CONFIG.get(regime, _DEFAULT_CONFIG)

    adj_prob = float(np.clip(probability + config["bias"], 0.01, 0.99))
    adj_confidence = confidence * config["confidence_multiplier"]
    threshold_shift = config["no_trade_zone_shift"]

    return {
        "adjusted_probability": round(adj_prob, 4),
        "adjusted_confidence": round(adj_confidence, 4),
        "regime": regime,
        "threshold_shift": threshold_shift,
        "max_position_pct": config["max_position_pct"],
        "model_weight_overrides": config["model_weight_overrides"],
        "regime_config": config,
    }


def get_regime_model_weights(
    regime: str,
    base_weights: dict[str, float],
) -> dict[str, float]:
    """Return regime-adjusted ensemble weights.

    Applies per-model multipliers from the regime config on top of the
    base training-time weights, then re-normalises so they sum to 1.
    """
    config = REGIME_CONFIG.get(regime, _DEFAULT_CONFIG)
    overrides = config.get("model_weight_overrides", {})

    adjusted: dict[str, float] = {}
    for name, w in base_weights.items():
        mult = overrides.get(name, 1.0)
        adjusted[name] = w * mult

    total = sum(adjusted.values())
    if total > 0:
        adjusted = {k: v / total for k, v in adjusted.items()}

    return adjusted
