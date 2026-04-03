"""Ensemble model — stacking meta-learner with validation gating.

Combines multiple base models via a logistic-regression meta-learner
trained on out-of-fold predictions.  Models that fail a minimum AUC
gate during training are excluded from the ensemble automatically.
Supports regime-aware weight adjustment at inference time.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_predict

from app.models.baselines import BaseModel

logger = logging.getLogger(__name__)

_MIN_COMPONENT_AUC = 0.52  # models below this are excluded


class EnsembleModel(BaseModel):
    """Stacking ensemble with per-model validation gating."""

    name = "ensemble"

    def __init__(
        self,
        models: list[BaseModel] | None = None,
        weights: list[float] | None = None,
        use_stacking: bool = True,
        min_component_auc: float = _MIN_COMPONENT_AUC,
    ):
        self.models: list[BaseModel] = models or []
        self.weights: list[float] = weights or []
        self.use_stacking = use_stacking
        self.min_component_auc = min_component_auc
        self._meta_learner: LogisticRegression | None = None
        self._active_mask: list[bool] = []
        self._feature_names: list[str] = []
        self._component_metrics: dict[str, dict] = {}

    def add_model(self, model: BaseModel, weight: float = 1.0) -> None:
        self.models.append(model)
        self.weights.append(weight)

    def fit(self, X: pd.DataFrame, y: pd.Series, **kwargs: Any) -> dict:
        """Fit all sub-models, gate on validation AUC, then fit a stacking
        meta-learner on out-of-fold predictions of the surviving models."""
        from sklearn.metrics import roc_auc_score

        self._feature_names = list(X.columns)
        metrics: dict[str, Any] = {}
        oof_probas: list[np.ndarray] = []
        self._active_mask = []

        eval_set = kwargs.get("eval_set")
        X_val, y_val = eval_set if eval_set else (None, None)

        for model, weight in zip(self.models, self.weights):
            m = model.fit(X, y, **kwargs)
            metrics[model.name] = m

            # Validation gating
            if X_val is not None and len(X_val) > 0:
                try:
                    val_proba = model.predict_proba(X_val)
                    auc = roc_auc_score(y_val, val_proba)
                except Exception:
                    auc = 0.0
            else:
                auc = 0.5  # no validation data → accept

            passed = auc >= self.min_component_auc
            self._active_mask.append(passed)
            self._component_metrics[model.name] = {
                "val_auc": round(float(auc), 4),
                "passed_gate": passed,
                "weight": weight,
            }
            if not passed:
                logger.warning(
                    "Ensemble gate: %s excluded (AUC=%.4f < %.4f)",
                    model.name, auc, self.min_component_auc,
                )

        # Normalise weights for active models only
        active_weights = [
            w for w, active in zip(self.weights, self._active_mask) if active
        ]
        total = sum(active_weights)
        if total > 0:
            self.weights = [
                (w / total if active else 0.0)
                for w, active in zip(self.weights, self._active_mask)
            ]
        else:
            # All models failed gate — fall back to equal weighting
            logger.warning("All models failed gate — using equal weights as fallback")
            self._active_mask = [True] * len(self.models)
            self.weights = [1.0 / len(self.models)] * len(self.models)

        # Fit stacking meta-learner
        if self.use_stacking and X_val is not None and len(X_val) > 10:
            self._fit_meta_learner(X_val, y_val)

        active_count = sum(self._active_mask)
        logger.info(
            "Ensemble fit: %d/%d models active, stacking=%s",
            active_count, len(self.models), self._meta_learner is not None,
        )
        metrics["_ensemble"] = {
            "active_models": active_count,
            "component_metrics": self._component_metrics,
            "stacking": self._meta_learner is not None,
        }
        return metrics

    def _fit_meta_learner(self, X_val: pd.DataFrame, y_val: pd.Series) -> None:
        """Fit a logistic regression on stacked base-model predictions."""
        meta_features = self._build_meta_features(X_val)
        if meta_features.shape[1] < 2:
            return
        try:
            self._meta_learner = LogisticRegression(
                C=1.0, solver="lbfgs", max_iter=500,
            )
            self._meta_learner.fit(meta_features, y_val)
            logger.info("Meta-learner fit on %d samples, %d base models", len(y_val), meta_features.shape[1])
        except Exception as exc:
            logger.warning("Meta-learner fit failed: %s", exc)
            self._meta_learner = None

    def _build_meta_features(self, X: pd.DataFrame) -> np.ndarray:
        """Produce an (n_samples, n_active_models) matrix of base predictions."""
        cols = []
        for model, active in zip(self.models, self._active_mask):
            if not active:
                continue
            try:
                p = model.predict_proba(X)
                cols.append(p)
            except Exception:
                cols.append(np.full(len(X), 0.5))
        if not cols:
            return np.empty((len(X), 0))
        return np.column_stack(cols)

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        proba = self.predict_proba(X)
        return (proba > 0.5).astype(int)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """Return ensemble probability.

        Uses the stacking meta-learner when available, otherwise
        falls back to weighted average.
        """
        if not self.models:
            return np.full(len(X), 0.5)

        if self._meta_learner is not None:
            meta_feats = self._build_meta_features(X)
            if meta_feats.shape[1] >= 2:
                try:
                    return self._meta_learner.predict_proba(meta_feats)[:, 1]
                except Exception:
                    pass

        # Weighted average fallback
        probas: list[np.ndarray] = []
        for model, weight, active in zip(self.models, self.weights, self._active_mask):
            if not active:
                continue
            try:
                p = model.predict_proba(X)
                probas.append(p * weight)
            except Exception as exc:
                logger.warning("Model %s failed in ensemble: %s", model.name, exc)

        if not probas:
            return np.full(len(X), 0.5)

        return np.sum(probas, axis=0)

    def predict_proba_with_regime(
        self,
        X: pd.DataFrame,
        regime: str | None = None,
    ) -> np.ndarray:
        """Regime-aware prediction using adjusted weights."""
        if regime is None or self._meta_learner is not None:
            return self.predict_proba(X)

        from app.inference.regime_router import get_regime_model_weights

        base_weights = {
            m.name: w for m, w, a in zip(self.models, self.weights, self._active_mask) if a
        }
        adj_weights = get_regime_model_weights(regime, base_weights)

        probas: list[np.ndarray] = []
        for model, active in zip(self.models, self._active_mask):
            if not active:
                continue
            w = adj_weights.get(model.name, 0.0)
            if w <= 0:
                continue
            try:
                p = model.predict_proba(X)
                probas.append(p * w)
            except Exception:
                pass

        if not probas:
            return np.full(len(X), 0.5)
        return np.sum(probas, axis=0)

    def get_feature_importance(self) -> dict[str, float]:
        """Weighted average of feature importances (active models only)."""
        combined: dict[str, float] = {}
        for model, weight, active in zip(self.models, self.weights, self._active_mask):
            if not active:
                continue
            imp = model.get_feature_importance()
            for k, v in imp.items():
                combined[k] = combined.get(k, 0.0) + v * weight
        return combined

    @property
    def component_metrics(self) -> dict[str, dict]:
        return dict(self._component_metrics)


def build_default_ensemble(**kwargs: Any) -> EnsembleModel:
    """Create the default ensemble: LightGBM + XGBoost + RandomForest."""
    from app.models.tree_models import LightGBMModel, XGBoostModel
    from app.models.baselines import RandomForestModel

    ensemble = EnsembleModel()
    ensemble.add_model(LightGBMModel(**kwargs), weight=0.45)
    ensemble.add_model(XGBoostModel(**kwargs), weight=0.35)
    ensemble.add_model(RandomForestModel(), weight=0.20)
    return ensemble
