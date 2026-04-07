# LightGBM model implementation
"""LightGBM classification model for stock action prediction."""

from __future__ import annotations

import json
import os
import pickle
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backend.prediction_engine.models.base_model import BaseModel

try:
    import lightgbm as lgb
except ImportError:
    lgb = None


class LightGBMModel(BaseModel):
    """LightGBM-based classifier: sell(0), hold(1), buy(2)."""

    CLASS_NAMES = ["sell", "hold", "buy"]

    def __init__(
        self,
        version: str | None = None,
        seed: int = 42,
        params: dict | None = None,
    ) -> None:
        self._seed = seed
        self._version = version or datetime.now(timezone.utc).strftime("v%Y%m%d.%H%M%S")
        self._model: lgb.Booster | None = None  # type: ignore[name-defined]
        self._params = params or self._default_params()
        self._metrics: dict = {}

    def _default_params(self) -> dict:
        return {
            "objective": "binary",
            "metric": "binary_logloss",
            "learning_rate": 0.01,
            "num_leaves": 31,
            "max_depth": 5,
            "min_child_samples": 80,
            "feature_fraction": 0.7,
            "feature_fraction_bynode": 0.5,
            "bagging_fraction": 0.7,
            "bagging_freq": 5,
            "lambda_l1": 0.3,
            "lambda_l2": 1.5,
            "min_gain_to_split": 0.02,
            "path_smooth": 5,
            "max_bin": 255,
            "is_unbalance": True,
            "seed": self._seed,
            "verbose": -1,
        }

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(self, X: pd.DataFrame, y: pd.Series, **kwargs: Any) -> dict:
        if lgb is None:
            raise RuntimeError("lightgbm is not installed")

        num_boost_round = kwargs.get("num_boost_round", 800)
        early_stopping_rounds = kwargs.get("early_stopping_rounds", 80)
        val_X = kwargs.get("val_X")
        val_y = kwargs.get("val_y")
        class_weight = kwargs.get("class_weight")  # optional per-sample weights

        dtrain = lgb.Dataset(X, label=y, weight=class_weight)
        valid_sets = [dtrain]
        valid_names = ["train"]
        callbacks = [lgb.log_evaluation(period=50)]

        if val_X is not None and val_y is not None:
            dval = lgb.Dataset(val_X, label=val_y, reference=dtrain)
            valid_sets.append(dval)
            valid_names.append("val")
            callbacks.append(lgb.early_stopping(early_stopping_rounds))

        self._model = lgb.train(
            self._params,
            dtrain,
            num_boost_round=num_boost_round,
            valid_sets=valid_sets,
            valid_names=valid_names,
            callbacks=callbacks,
        )

        # Compute accuracy on training data
        raw_preds = self._model.predict(X)
        if isinstance(raw_preds, np.ndarray) and raw_preds.ndim == 1:
            binary_preds = (raw_preds > 0.5).astype(int)
        else:
            binary_preds = np.argmax(raw_preds, axis=1)
        accuracy = float((binary_preds == y.values if hasattr(y, 'values') else binary_preds == y).mean())
        self._metrics = {
            "accuracy": accuracy,
            "best_iteration": self._model.best_iteration,
        }
        return self._metrics

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def _resolve_base_threshold(self) -> float:
        """Decision threshold anchor from training metrics/params."""
        raw = (
            self._metrics.get("optimal_threshold")
            if isinstance(self._metrics, dict)
            else None
        )
        if raw is None and isinstance(self._params, dict):
            raw = self._params.get("optimal_threshold")

        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = 0.52
        return float(np.clip(value, 0.50, 0.70))

    @staticmethod
    def _env_float(name: str, default: float) -> float:
        raw = os.getenv(name)
        if raw is None:
            return default
        try:
            return float(raw)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_row_value(
        X: pd.DataFrame,
        row_idx: int,
        col: str,
        default: float = 0.0,
    ) -> float:
        if not isinstance(X, pd.DataFrame) or col not in X.columns:
            return default
        try:
            value = float(X.iloc[row_idx][col])
        except (TypeError, ValueError):
            return default
        if not np.isfinite(value):
            return default
        return value

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Return 3-class labels: 0=sell, 1=hold, 2=buy.

        Binary model predicts P(up). Map to 3 classes using confidence:
        - Dynamic threshold around 0.5, widened by volatility
        - Costs / volatility increase abstention band
        - otherwise → hold (1)
        """
        proba_up = self.predict_proba(X)
        if proba_up.ndim == 2:
            proba_up = proba_up[:, 1] if proba_up.shape[1] == 2 else proba_up[:, 0]

        base_threshold = self._resolve_base_threshold()
        base_half_band = max(0.02, abs(base_threshold - 0.5))
        band_scale = float(
            np.clip(
                self._env_float("PREDICTION_NO_TRADE_BAND_SCALE", 1.0),
                0.25,
                2.5,
            )
        )

        labels = np.ones(len(proba_up), dtype=int)
        for i, p_up in enumerate(proba_up):
            price = max(self._safe_row_value(X, i, "close", default=100.0), 1.0)
            volatility = abs(self._safe_row_value(X, i, "volatility_20", default=0.02))
            atr_ratio = abs(self._safe_row_value(X, i, "atr_14", default=0.0)) / price

            regime_band = float(np.clip(volatility * 0.35 + atr_ratio * 0.75, 0.0, 0.08))
            half_band = float(np.clip((base_half_band + regime_band) * band_scale, 0.01, 0.20))
            buy_threshold = min(0.90, 0.5 + half_band)
            sell_threshold = max(0.10, 0.5 - half_band)

            if p_up >= buy_threshold:
                labels[i] = 2
            elif p_up <= sell_threshold:
                labels[i] = 0
        return labels

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """Return raw model probabilities.

        For binary model, returns P(up) as 1D array.
        """
        if self._model is None:
            raise RuntimeError("Model not trained / loaded")
        raw = self._model.predict(X)
        return raw

    def predict_proba_3class(self, X: pd.DataFrame) -> np.ndarray:
        """Return 3-class probability matrix (n_samples, 3).

        Maps binary P(up) to [P(sell), P(hold), P(buy)] using
        confidence-based allocation.
        """
        proba_up = self.predict_proba(X)
        if proba_up.ndim == 2:
            proba_up = proba_up[:, 1] if proba_up.shape[1] == 2 else proba_up[:, 0]
        n = len(proba_up)
        result = np.zeros((n, 3))
        for i, p_up in enumerate(proba_up):
            p_down = 1 - p_up
            if p_up > 0.52:
                result[i] = [0.1, 0.2, 0.7 * (p_up / 0.52)]  # buy-leaning
            elif p_up < 0.48:
                result[i] = [0.7 * (p_down / 0.52), 0.2, 0.1]  # sell-leaning
            else:
                result[i] = [0.2, 0.6, 0.2]  # hold
            result[i] /= result[i].sum()  # normalize
        return result

    def predict_with_expected_return(
        self,
        X: pd.DataFrame,
        price: float | None = None,
        quantity: int = 1,
        min_net_edge_bps: float = 6.0,
        slippage_bps: float = 2.0,
    ) -> list[dict]:
        """Return action probabilities mapped to actions + expected return estimate.

        When *price* and *quantity* are provided, factors in Angel One brokerage
        charges so that only trades with a positive net-of-charges return are
        recommended.
        """
        from backend.services.brokerage_calculator import estimate_breakeven_move, TradeType

        proba_up = self.predict_proba(X)
        if proba_up.ndim == 2:
            proba_up = proba_up[:, 1] if proba_up.shape[1] == 2 else proba_up[:, 0]
        results = []
        base_threshold = self._resolve_base_threshold()
        base_half_band = max(0.02, abs(base_threshold - 0.5))
        band_scale = float(
            np.clip(
                self._env_float("PREDICTION_NO_TRADE_BAND_SCALE", 1.0),
                0.25,
                2.5,
            )
        )
        min_edge_pct = max(0.0, float(min_net_edge_bps)) / 10_000.0
        slippage_pct = max(0.0, float(slippage_bps)) / 10_000.0

        for p_up in proba_up:
            p_down = 1 - p_up

            idx = len(results)
            row_price = price if price is not None else self._safe_row_value(X, idx, "close", default=100.0)
            row_price = max(float(row_price), 1.0)
            row_volatility = abs(self._safe_row_value(X, idx, "volatility_20", default=0.02))
            row_atr = abs(self._safe_row_value(X, idx, "atr_14", default=0.0))
            atr_ratio = row_atr / row_price if row_price > 0 else 0.0

            breakeven_pct = 0.0
            if quantity > 0:
                try:
                    breakeven = estimate_breakeven_move(row_price, quantity, TradeType.INTRADAY)
                    breakeven_pct = max(0.0, breakeven / row_price)
                except Exception:
                    breakeven_pct = 0.0

            tx_cost_pct = breakeven_pct + slippage_pct

            regime_band = float(
                np.clip(
                    row_volatility * 0.30 + atr_ratio * 0.75 + tx_cost_pct * 2.5,
                    0.0,
                    0.12,
                )
            )
            half_band = float(np.clip((base_half_band + regime_band) * band_scale, 0.01, 0.22))
            buy_threshold = min(0.92, 0.5 + half_band)
            sell_threshold = max(0.08, 0.5 - half_band)

            # Translate model probability edge into expected move with volatility scaling.
            # This keeps returns conservative in low-vol regimes and bounded in high-vol.
            signal_edge = float((p_up - 0.5) * 2.0)
            volatility_scale = float(np.clip(row_volatility * 1.15 + atr_ratio * 0.5, 0.01, 0.12))
            expected_return = float(np.clip(signal_edge * volatility_scale, -0.25, 0.25))

            net_long = expected_return - tx_cost_pct
            net_short = -expected_return - tx_cost_pct
            trade_edge = float(max(net_long, net_short))

            action = "hold"
            no_trade_reason: str | None = None
            if p_up >= buy_threshold:
                if net_long > min_edge_pct:
                    action = "buy"
                else:
                    no_trade_reason = "net_edge_below_costs"
            elif p_up <= sell_threshold:
                if net_short > min_edge_pct:
                    action = "sell"
                else:
                    no_trade_reason = "net_edge_below_costs"
            else:
                no_trade_reason = "probability_in_no_trade_band"

            # Keep signed expected return for consistency with direction.
            # Positive = long bias, negative = short bias.
            if expected_return >= 0:
                net_expected_return = expected_return - tx_cost_pct
            else:
                net_expected_return = expected_return + tx_cost_pct

            confidence = float(max(p_up, p_down))

            results.append(
                {
                    "action": action,
                    "confidence": round(confidence, 4),
                    "expected_return": round(expected_return, 6),
                    "net_expected_return": round(net_expected_return, 6),
                    "trade_edge": round(trade_edge, 6),
                    "buy_threshold": round(buy_threshold, 4),
                    "sell_threshold": round(sell_threshold, 4),
                    "breakeven_pct": round(breakeven_pct, 6),
                    "tx_cost_pct": round(tx_cost_pct, 6),
                    "no_trade_reason": no_trade_reason,
                }
            )
        return results

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)

        model_file = path / "model.pkl"
        meta_file = path / "meta.json"

        with open(model_file, "wb") as f:
            pickle.dump(self._model, f)

        meta = {
            "version": self._version,
            "seed": self._seed,
            "params": self._params,
            "metrics": self._metrics,
            "saved_at": datetime.now(timezone.utc).isoformat() + "Z",
        }
        meta_file.write_text(json.dumps(meta, indent=2))
        return path

    @classmethod
    def load(cls, path: str | Path) -> "LightGBMModel":
        path = Path(path)
        meta = json.loads((path / "meta.json").read_text())

        instance = cls(
            version=meta["version"],
            seed=meta.get("seed", 42),
            params=meta.get("params"),
        )
        with open(path / "model.pkl", "rb") as f:
            instance._model = pickle.load(f)  # noqa: S301
        instance._metrics = meta.get("metrics", {})
        return instance

    def get_version(self) -> str:
        return self._version

