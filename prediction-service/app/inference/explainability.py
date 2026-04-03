"""Explainability — feature importance for individual predictions.

Uses model feature importances (and SHAP when available).
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def get_top_features(
    model: Any,
    X: pd.DataFrame,
    top_k: int = 10,
) -> dict[str, float]:
    """Return top-K most important features for this prediction.

    Uses model-level feature importance. For tree models this is split-based.
    """
    try:
        importance = model.get_feature_importance()
        if importance:
            sorted_imp = sorted(importance.items(), key=lambda x: abs(x[1]), reverse=True)
            return dict(sorted_imp[:top_k])
    except Exception:
        pass

    # Fallback: use feature values' magnitude
    if not X.empty:
        row = X.iloc[0]
        sorted_vals = row.abs().sort_values(ascending=False)
        return {k: float(v) for k, v in sorted_vals.head(top_k).items()}

    return {}


def get_shap_explanation(
    model: Any,
    X: pd.DataFrame,
    top_k: int = 10,
) -> dict[str, Any] | None:
    """Compute SHAP values for a prediction (if shap is installed)."""
    try:
        import shap

        # Try tree explainer first (fast for tree models)
        inner_model = getattr(model, "model", model)
        try:
            explainer = shap.TreeExplainer(inner_model)
        except Exception:
            explainer = shap.Explainer(inner_model)

        shap_values = explainer.shap_values(X.fillna(0))

        if isinstance(shap_values, list):
            shap_values = shap_values[1]  # class 1 for binary

        feature_effects = dict(zip(X.columns, shap_values[0]))
        sorted_effects = sorted(feature_effects.items(), key=lambda x: abs(x[1]), reverse=True)

        return {
            "top_features": dict(sorted_effects[:top_k]),
            "base_value": float(explainer.expected_value if np.isscalar(explainer.expected_value)
                                else explainer.expected_value[1]),
            "method": "shap_tree",
        }
    except ImportError:
        logger.debug("shap not installed, skipping SHAP explanation")
        return None
    except Exception as exc:
        logger.debug("SHAP computation failed: %s", exc)
        return None
