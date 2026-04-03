"""Gradient-boosted tree models — LightGBM and XGBoost.

These are the primary production models for direction prediction.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from app.models.baselines import BaseModel

logger = logging.getLogger(__name__)


class LightGBMModel(BaseModel):
    """LightGBM gradient boosted classifier."""

    name = "lightgbm"

    def __init__(self, **params: Any):
        self.params = {
            "objective": "binary",
            "metric": "binary_logloss",
            "boosting_type": "gbdt",
            "num_leaves": 31,
            "learning_rate": 0.05,
            "feature_fraction": 0.8,
            "bagging_fraction": 0.8,
            "bagging_freq": 5,
            "verbose": -1,
            "n_estimators": 500,
            "max_depth": -1,
            "random_state": 42,
        }
        self.params.update(params)
        self.model: Any = None
        self._feature_names: list[str] = []

    def fit(self, X: pd.DataFrame, y: pd.Series, **kwargs: Any) -> dict:
        import lightgbm as lgb

        self._feature_names = list(X.columns)
        X_clean = X.fillna(0)

        eval_set = kwargs.get("eval_set")
        callbacks = [lgb.log_evaluation(period=100)]
        if kwargs.get("early_stopping_rounds"):
            callbacks.append(lgb.early_stopping(kwargs["early_stopping_rounds"]))

        self.model = lgb.LGBMClassifier(**self.params)
        fit_kwargs: dict[str, Any] = {"callbacks": callbacks}
        if eval_set:
            X_val, y_val = eval_set
            fit_kwargs["eval_set"] = [(X_val.fillna(0), y_val)]
        self.model.fit(X_clean, y, **fit_kwargs)

        train_acc = self.model.score(X_clean, y)
        logger.info("LightGBM fit: train_acc=%.4f", train_acc)
        return {"train_accuracy": train_acc, "best_iteration": getattr(self.model, "best_iteration_", -1)}

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.model.predict(X.fillna(0))

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        return self.model.predict_proba(X.fillna(0))[:, 1]

    def get_feature_importance(self) -> dict[str, float]:
        if self.model is not None:
            imp = self.model.feature_importances_
            return dict(zip(self._feature_names, imp.tolist()))
        return {}


class XGBoostModel(BaseModel):
    """XGBoost gradient boosted classifier."""

    name = "xgboost"

    def __init__(self, **params: Any):
        self.params = {
            "objective": "binary:logistic",
            "eval_metric": "logloss",
            "max_depth": 6,
            "learning_rate": 0.05,
            "n_estimators": 500,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "random_state": 42,
            "use_label_encoder": False,
            "verbosity": 0,
        }
        self.params.update(params)
        self.model: Any = None
        self._feature_names: list[str] = []

    def fit(self, X: pd.DataFrame, y: pd.Series, **kwargs: Any) -> dict:
        from xgboost import XGBClassifier

        self._feature_names = list(X.columns)
        X_clean = X.fillna(0)

        self.model = XGBClassifier(**self.params)
        fit_kwargs: dict[str, Any] = {}
        eval_set = kwargs.get("eval_set")
        if eval_set:
            X_val, y_val = eval_set
            fit_kwargs["eval_set"] = [(X_val.fillna(0), y_val)]
        if kwargs.get("early_stopping_rounds"):
            fit_kwargs["early_stopping_rounds"] = kwargs["early_stopping_rounds"]
            fit_kwargs["verbose"] = False

        self.model.fit(X_clean, y, **fit_kwargs)
        train_acc = self.model.score(X_clean, y)
        logger.info("XGBoost fit: train_acc=%.4f", train_acc)
        return {"train_accuracy": train_acc}

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.model.predict(X.fillna(0))

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        return self.model.predict_proba(X.fillna(0))[:, 1]

    def get_feature_importance(self) -> dict[str, float]:
        if self.model is not None:
            imp = self.model.feature_importances_
            return dict(zip(self._feature_names, imp.tolist()))
        return {}
