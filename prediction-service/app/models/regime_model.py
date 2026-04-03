"""Regime classifier — identifies market regimes (trending, mean-reverting, volatile).

The regime label is used by the ensemble to weight models differently
depending on the current market state.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

from app.models.baselines import BaseModel

logger = logging.getLogger(__name__)


class MarketRegime(str, Enum):
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    MEAN_REVERTING = "mean_reverting"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"


def compute_regime_features(df: pd.DataFrame) -> pd.DataFrame:
    """Extract features used for regime classification.

    Expects a DataFrame with 'close' column at minimum.
    """
    close = df["close"]
    log_ret = np.log(close / close.shift(1))

    features = pd.DataFrame(index=df.index)
    features["ret_mean_21d"] = log_ret.rolling(21).mean()
    features["ret_std_21d"] = log_ret.rolling(21).std()
    features["ret_skew_21d"] = log_ret.rolling(21).skew()
    features["ret_kurt_21d"] = log_ret.rolling(21).apply(
        lambda x: x.kurtosis() if len(x) > 3 else 0, raw=False
    )
    features["hurst"] = log_ret.rolling(63).apply(_hurst_exponent, raw=True)

    # Trend strength: ADX-like measure
    if "high" in df.columns and "low" in df.columns:
        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - close.shift(1)).abs(),
            (df["low"] - close.shift(1)).abs(),
        ], axis=1).max(axis=1)
        features["atr_ratio"] = tr.rolling(14).mean() / close

    return features.dropna()


def _hurst_exponent(series: np.ndarray) -> float:
    """Simplified Hurst exponent estimation."""
    if len(series) < 20:
        return 0.5
    lags = range(2, min(20, len(series) // 2))
    tau = []
    for lag in lags:
        diffs = series[lag:] - series[:-lag]
        std = np.std(diffs)
        if std > 0:
            tau.append(std)
        else:
            tau.append(1e-10)
    if len(tau) < 2:
        return 0.5
    log_lags = np.log(list(lags[: len(tau)]))
    log_tau = np.log(tau)
    try:
        poly = np.polyfit(log_lags, log_tau, 1)
        return float(poly[0])
    except Exception:
        return 0.5


class RegimeModel(BaseModel):
    """KMeans-based regime classifier."""

    name = "regime_classifier"

    def __init__(self, n_regimes: int = 4):
        self.n_regimes = n_regimes
        self.scaler = StandardScaler()
        self.model = KMeans(n_clusters=n_regimes, random_state=42, n_init=10)
        self._regime_map: dict[int, str] = {}
        self._feature_names: list[str] = []

    def fit(self, X: pd.DataFrame, y: pd.Series | None = None, **kwargs: Any) -> dict:
        """Fit the regime model. y is ignored (unsupervised)."""
        self._feature_names = list(X.columns)
        X_scaled = self.scaler.fit_transform(X.fillna(0))
        self.model.fit(X_scaled)

        # Label clusters based on centroid characteristics
        self._label_clusters(X)

        logger.info("Regime model fit: %d clusters, inertia=%.2f", self.n_regimes, self.model.inertia_)
        return {"inertia": self.model.inertia_, "n_regimes": self.n_regimes}

    def _label_clusters(self, X: pd.DataFrame) -> None:
        """Assign human-readable labels to clusters based on centroid features."""
        centroids = self.scaler.inverse_transform(self.model.cluster_centers_)
        ret_idx = self._feature_names.index("ret_mean_21d") if "ret_mean_21d" in self._feature_names else 0
        vol_idx = self._feature_names.index("ret_std_21d") if "ret_std_21d" in self._feature_names else 1

        for i, c in enumerate(centroids):
            ret_mean = c[ret_idx]
            vol_level = c[vol_idx]

            if vol_level > np.median([row[vol_idx] for row in centroids]):
                self._regime_map[i] = MarketRegime.HIGH_VOLATILITY.value
            elif ret_mean > 0.001:
                self._regime_map[i] = MarketRegime.TRENDING_UP.value
            elif ret_mean < -0.001:
                self._regime_map[i] = MarketRegime.TRENDING_DOWN.value
            else:
                self._regime_map[i] = MarketRegime.MEAN_REVERTING.value

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        X_scaled = self.scaler.transform(X.fillna(0))
        labels = self.model.predict(X_scaled)
        return np.array([self._regime_map.get(l, "unknown") for l in labels])

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """Return distance-based confidence (inverse of distance to centroid)."""
        X_scaled = self.scaler.transform(X.fillna(0))
        distances = self.model.transform(X_scaled)
        # Convert to probabilities (softmax of negative distances)
        neg_dist = -distances
        exp_dist = np.exp(neg_dist - neg_dist.max(axis=1, keepdims=True))
        return exp_dist / exp_dist.sum(axis=1, keepdims=True)

    def get_current_regime(self, X: pd.DataFrame) -> str:
        """Return the regime for the most recent observation."""
        regimes = self.predict(X.tail(1))
        return regimes[0] if len(regimes) > 0 else "unknown"
