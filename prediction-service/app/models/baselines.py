"""Baseline models — Logistic Regression and Random Forest.

Simple classifiers for benchmarking against advanced models.
All models follow a unified fit / predict / predict_proba interface.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)


class BaseModel:
    """Common interface for all prediction models."""

    name: str = "base"

    def fit(self, X: pd.DataFrame, y: pd.Series, **kwargs: Any) -> dict:
        raise NotImplementedError

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        raise NotImplementedError

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        raise NotImplementedError

    def get_feature_importance(self) -> dict[str, float]:
        return {}

    def save(self, path: str) -> None:
        import joblib
        joblib.dump(self, path)

    @classmethod
    def load(cls, path: str) -> "BaseModel":
        import joblib
        return joblib.load(path)


class LogisticRegressionModel(BaseModel):
    """L2-regularised logistic regression with scaling."""

    name = "logistic_regression"

    def __init__(self, C: float = 1.0, max_iter: int = 1000):
        self.scaler = StandardScaler()
        self.model = LogisticRegression(C=C, max_iter=max_iter, solver="lbfgs")
        self._feature_names: list[str] = []

    def fit(self, X: pd.DataFrame, y: pd.Series, **kwargs: Any) -> dict:
        self._feature_names = list(X.columns)
        X_scaled = self.scaler.fit_transform(X.fillna(0))
        self.model.fit(X_scaled, y)
        train_acc = self.model.score(X_scaled, y)
        logger.info("LogisticRegression fit: train_acc=%.4f", train_acc)
        return {"train_accuracy": train_acc}

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        X_scaled = self.scaler.transform(X.fillna(0))
        return self.model.predict(X_scaled)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        X_scaled = self.scaler.transform(X.fillna(0))
        return self.model.predict_proba(X_scaled)[:, 1]

    def get_feature_importance(self) -> dict[str, float]:
        if hasattr(self.model, "coef_"):
            coefs = np.abs(self.model.coef_[0])
            return dict(zip(self._feature_names, coefs.tolist()))
        return {}


class RandomForestModel(BaseModel):
    """Random Forest classifier."""

    name = "random_forest"

    def __init__(self, n_estimators: int = 200, max_depth: int | None = 10):
        self.model = RandomForestClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            random_state=42,
            n_jobs=-1,
        )
        self._feature_names: list[str] = []

    def fit(self, X: pd.DataFrame, y: pd.Series, **kwargs: Any) -> dict:
        self._feature_names = list(X.columns)
        self.model.fit(X.fillna(0), y)
        train_acc = self.model.score(X.fillna(0), y)
        logger.info("RandomForest fit: train_acc=%.4f", train_acc)
        return {"train_accuracy": train_acc}

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.model.predict(X.fillna(0))

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        return self.model.predict_proba(X.fillna(0))[:, 1]

    def get_feature_importance(self) -> dict[str, float]:
        if hasattr(self.model, "feature_importances_"):
            return dict(zip(self._feature_names, self.model.feature_importances_.tolist()))
        return {}
