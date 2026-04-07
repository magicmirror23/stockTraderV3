"""Central configuration for the cross-sectional ranking pipeline."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class RankingPipelineConfig:
    """All tunables for the ranking pipeline in one place."""

    # --- Model mode ---
    # "classification" = top-vs-bottom bucket binary classifier
    # "regression"     = predict forward returns, rank by score
    # "ranker"         = LightGBM LambdaRank (experimental)
    mode: str = "classification"

    # --- Prediction horizon ---
    horizon: int = 3  # days: 1, 3, or 5

    # --- Cross-sectional bucket thresholds ---
    top_bucket_pct: float = 0.20    # top X% labelled 1
    bottom_bucket_pct: float = 0.20  # bottom X% labelled 0

    # --- Trading ---
    top_n_trade: int = 10           # trade top N names per rebalance
    max_positions: int = 10
    min_confidence: float = 0.55
    holding_period: int = 3         # bars to hold (default = horizon)

    # --- Feature control ---
    include_day_of_week: bool = False
    include_benchmark_features: bool = True

    # --- Model selection ---
    use_lightgbm: bool = True       # use LightGBM (else sklearn fallback)

    # --- Penalties ---
    downside_penalty: float = 0.50
    risk_off_penalty: float = 0.35

    # --- Diagnostics ---
    min_trade_alert_threshold: int = 25
    max_dominant_feature_pct: float = 0.40  # alert if one feature > 40% importance

    random_state: int = 42

    @classmethod
    def from_env(cls, *, default_horizon: int = 3, default_seed: int = 42) -> "RankingPipelineConfig":
        mode = os.getenv("RANKING_MODEL_MODE", "classification").strip().lower()
        if mode not in {"classification", "regression", "ranker"}:
            mode = "classification"

        horizon = _env_int("RANKING_HORIZON_BARS", default_horizon)
        if horizon not in {1, 3, 5}:
            horizon = 3

        return cls(
            mode=mode,
            horizon=horizon,
            top_bucket_pct=_env_float("RANKING_TOP_BUCKET_PCT", 0.20),
            bottom_bucket_pct=_env_float("RANKING_BOTTOM_BUCKET_PCT", 0.20),
            top_n_trade=_env_int("RANKING_TOP_N_TRADE", 10),
            max_positions=_env_int("RANKING_MAX_POSITIONS", 10),
            min_confidence=_env_float("RANKING_MIN_CONFIDENCE", 0.55),
            holding_period=_env_int("RANKING_HOLDING_PERIOD", horizon),
            include_day_of_week=_env_bool("RANKING_INCLUDE_DAY_OF_WEEK", False),
            include_benchmark_features=_env_bool("RANKING_INCLUDE_BENCHMARK_FEATURES", True),
            use_lightgbm=_env_bool("RANKING_USE_LIGHTGBM", True),
            downside_penalty=_env_float("RANKING_DOWNSIDE_PENALTY", 0.50),
            risk_off_penalty=_env_float("RANKING_RISK_OFF_PENALTY", 0.35),
            min_trade_alert_threshold=_env_int("RANKING_MIN_TRADES_ALERT", 25),
            max_dominant_feature_pct=_env_float("RANKING_MAX_DOMINANT_FEATURE_PCT", 0.40),
            random_state=_env_int("RANKING_RANDOM_STATE", default_seed),
        )
