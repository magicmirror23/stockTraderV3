from __future__ import annotations

import numpy as np
import pandas as pd

from backend.ml_platform.regime_ranking import (
    RegimeRankingConfig,
    build_regime_ranking_frame,
    train_regime_aware_ranking,
)
from backend.prediction_engine.training.trainer import NUMERIC_FEATURES, TrainingConfig


def _synthetic_features(*, tickers: int = 10, days: int = 280, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-01", periods=days)
    rows: list[dict] = []

    for idx in range(tickers):
        ticker = f"SYM{idx:03d}"
        price = 100.0 + idx * 5.0
        drift = 0.0006 if idx % 2 == 0 else -0.0002
        vol = 0.012 + (idx % 4) * 0.002

        for dt in dates:
            ret = drift + float(rng.normal(0.0, vol))
            price = max(5.0, price * (1.0 + ret))

            row = {
                "ticker": ticker,
                "date": dt,
                "close": price,
                "return_1d": ret,
                "return_3d": ret * 3.0 + float(rng.normal(0, 0.01)),
                "return_5d": ret * 5.0 + float(rng.normal(0, 0.015)),
                "return_10d": ret * 10.0 + float(rng.normal(0, 0.02)),
                "volatility_20": abs(float(rng.normal(0.02, 0.007))),
                "volume_change": float(rng.normal(0.0, 0.15)),
                "gap_pct": float(rng.normal(0.0, 0.01)),
                "atr_14": abs(float(rng.normal(1.2, 0.3))),
                "distance_sma50": float(rng.normal(0.0, 0.03)),
                "momentum_10": float(rng.normal(0.0, 0.03)),
                "ema_crossover": float(rng.normal(0.0, 0.02)),
                "rsi_14": float(np.clip(rng.normal(50.0, 10.0), 5.0, 95.0)),
            }

            for col in NUMERIC_FEATURES:
                if col in row:
                    continue
                if col == "day_of_week":
                    row[col] = float(dt.weekday())
                elif "return" in col or "momentum" in col:
                    row[col] = float(rng.normal(0.0, 0.02))
                elif "vol" in col or "atr" in col:
                    row[col] = abs(float(rng.normal(0.02, 0.01)))
                elif "rsi" in col or "williams" in col or "stoch" in col or "cci" in col:
                    row[col] = float(rng.normal(0.0, 1.0))
                elif "volume" in col:
                    row[col] = float(rng.normal(1.0, 0.2))
                else:
                    row[col] = float(rng.normal(0.0, 0.05))
            rows.append(row)

    return pd.DataFrame(rows)


def _safety_cfg() -> TrainingConfig:
    return TrainingConfig(
        train_min_days=140,
        val_min_days=40,
        test_min_days=40,
        purge_gap_days=5,
        min_unique_dates=180,
        min_rows_per_symbol=100,
        min_symbols=4,
        min_samples_per_class=5,
        allow_reduced_validation=False,
    )


def test_no_leakage_target_tail_is_nan_before_drop():
    features = _synthetic_features(tickers=4, days=120, seed=7)
    framed = build_regime_ranking_frame(features, horizon_bars=1, downside_penalty=0.5)

    for _, grp in framed.groupby("ticker"):
        tail = grp.sort_values("date").tail(1)
        assert tail["target_next_day_return"].isna().all()
        assert tail["target_horizon_return"].isna().all()
        tail3 = grp.sort_values("date").tail(3)
        assert tail3["target_next_3d_return"].isna().any()


def test_ranking_training_is_reproducible():
    features = _synthetic_features(tickers=9, days=260, seed=99)
    cfg = RegimeRankingConfig(mode="classification", horizon_bars=1, max_positions=6, random_state=123)

    out1 = train_regime_aware_ranking(features, cfg=cfg, safety_cfg=_safety_cfg())
    out2 = train_regime_aware_ranking(features, cfg=cfg, safety_cfg=_safety_cfg())

    assert out1["metrics"]["selected_model"] == out2["metrics"]["selected_model"]
    assert abs(float(out1["metrics"]["selected_threshold"]) - float(out2["metrics"]["selected_threshold"])) < 1e-9
    assert abs(float(out1["metrics"]["validation_risk_objective"]) - float(out2["metrics"]["validation_risk_objective"])) < 1e-9


def test_threshold_optimization_is_validation_only():
    features = _synthetic_features(tickers=8, days=240, seed=1337)
    cfg = RegimeRankingConfig(mode="classification", horizon_bars=1, max_positions=5, random_state=11)
    out = train_regime_aware_ranking(features, cfg=cfg, safety_cfg=_safety_cfg())

    metadata = out["metadata"]
    assert metadata["threshold_source"] == "validation_only"
    candidates = metadata["model_comparison"]["candidates"]
    assert len(candidates) >= 2
    assert all(c["threshold_source"] == "validation_only" for c in candidates)

