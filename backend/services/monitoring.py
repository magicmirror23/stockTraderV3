# Monitoring utilities
"""Prometheus metrics, model health monitoring, and Sentry integration."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prometheus
# ---------------------------------------------------------------------------

try:
    from prometheus_client import Counter, Gauge, Histogram, generate_latest
    _PROM_AVAILABLE = True
except ImportError:
    _PROM_AVAILABLE = False
    logger.info("prometheus_client not installed â€“ metrics export disabled")


# ---------------------------------------------------------------------------
# Sentry
# ---------------------------------------------------------------------------

try:
    import sentry_sdk
    _SENTRY_DSN = os.getenv("SENTRY_DSN", "")
    if _SENTRY_DSN:
        sentry_sdk.init(dsn=_SENTRY_DSN, traces_sample_rate=0.1)
        _SENTRY_AVAILABLE = True
        logger.info("Sentry initialised")
    else:
        _SENTRY_AVAILABLE = False
except ImportError:
    _SENTRY_AVAILABLE = False
    logger.info("sentry_sdk not installed â€“ error reporting disabled")


# ---------------------------------------------------------------------------
# Metrics definitions (no-op stubs when prometheus_client is absent)
# ---------------------------------------------------------------------------

if _PROM_AVAILABLE:
    PREDICTION_REQUESTS = Counter(
        "stocktrader_prediction_requests_total",
        "Total prediction requests",
        ["endpoint"],
    )
    PREDICTION_LATENCY = Histogram(
        "stocktrader_prediction_latency_seconds",
        "Prediction endpoint latency",
        ["endpoint"],
    )
    MODEL_VERSION_GAUGE = Gauge(
        "stocktrader_model_version_info",
        "Currently loaded model version (label)",
        ["version"],
    )
    MODEL_ACCURACY_GAUGE = Gauge(
        "stocktrader_model_accuracy",
        "Current model classification accuracy on full test set",
    )
    TRADE_EXECUTIONS = Counter(
        "stocktrader_trade_executions_total",
        "Total trade executions",
        ["side", "status"],
    )
    # Option-specific metrics
    OPTION_SIGNAL_COUNT = Counter(
        "stocktrader_option_signals_total",
        "Total option signals generated",
        ["option_type", "action"],
    )
    OPTION_STRATEGY_COUNT = Counter(
        "stocktrader_option_strategy_total",
        "Total option strategy intents",
        ["strategy"],
    )
    # Replay metrics
    REPLAY_RUNS = Counter(
        "stocktrader_replay_runs_total",
        "Total paper replay runs",
    )
    REPLAY_DURATION = Histogram(
        "stocktrader_replay_duration_seconds",
        "Paper replay execution time",
    )
    # Drift metrics
    DRIFT_DETECTED = Counter(
        "stocktrader_drift_detected_total",
        "Number of drift detections",
        ["feature", "test_type"],
    )
    # Retrain metrics
    RETRAIN_RUNS = Counter(
        "stocktrader_retrain_runs_total",
        "Total retrain runs",
        ["status"],
    )

    # ── Intraday metrics ───────────────────────────────────────────
    INTRADAY_PREDICTION_REQUESTS = Counter(
        "stocktrader_intraday_prediction_requests_total",
        "Total intraday prediction requests",
        ["signal_type"],
    )
    INTRADAY_PREDICTION_LATENCY = Histogram(
        "stocktrader_intraday_prediction_latency_seconds",
        "Intraday prediction endpoint latency",
    )
    INTRADAY_TRADES = Counter(
        "stocktrader_intraday_trades_total",
        "Total intraday micro-trades",
        ["side", "outcome"],
    )
    INTRADAY_TRADE_LATENCY = Histogram(
        "stocktrader_intraday_trade_execution_latency_seconds",
        "Intraday trade execution latency",
    )
    INTRADAY_PNL = Gauge(
        "stocktrader_intraday_daily_pnl",
        "Intraday daily realised PnL",
    )
    INTRADAY_OPEN_POSITIONS = Gauge(
        "stocktrader_intraday_open_positions",
        "Number of open intraday positions",
    )
    INTRADAY_WIN_RATE = Gauge(
        "stocktrader_intraday_win_rate",
        "Intraday rolling win rate",
    )
    INTRADAY_PROFIT_FACTOR = Gauge(
        "stocktrader_intraday_profit_factor",
        "Intraday rolling profit factor",
    )
    INTRADAY_MODEL_VERSION = Gauge(
        "stocktrader_intraday_model_version_info",
        "Currently loaded intraday model version (label)",
        ["version"],
    )
    INTRADAY_SUPERVISOR_STATE = Gauge(
        "stocktrader_intraday_supervisor_state",
        "Trade supervisor state (1=ACTIVE, 2=PAUSED, 3=HALTED, 4=COOLDOWN)",
    )
    INTRADAY_SUPERVISOR_TRIGGERS = Counter(
        "stocktrader_intraday_supervisor_triggers_total",
        "Trade supervisor risk trigger activations",
        ["trigger_type"],
    )
    INTRADAY_OPTION_SIGNALS = Counter(
        "stocktrader_intraday_option_signals_total",
        "Intraday F&O option signals generated",
        ["signal_type"],
    )
    INTRADAY_DRAWDOWN = Gauge(
        "stocktrader_intraday_drawdown_pct",
        "Intraday drawdown percentage",
    )


# ---------------------------------------------------------------------------
# Recording helpers
# ---------------------------------------------------------------------------


def record_prediction(endpoint: str, latency: float) -> None:
    if _PROM_AVAILABLE:
        PREDICTION_REQUESTS.labels(endpoint=endpoint).inc()
        PREDICTION_LATENCY.labels(endpoint=endpoint).observe(latency)


def set_model_info(version: str, accuracy: float | None = None) -> None:
    if _PROM_AVAILABLE:
        MODEL_VERSION_GAUGE.labels(version=version).set(1)
        if accuracy is not None:
            MODEL_ACCURACY_GAUGE.set(accuracy)


def record_trade(side: str, status: str) -> None:
    if _PROM_AVAILABLE:
        TRADE_EXECUTIONS.labels(side=side, status=status).inc()


def record_option_signal(option_type: str, action: str) -> None:
    if _PROM_AVAILABLE:
        OPTION_SIGNAL_COUNT.labels(option_type=option_type, action=action).inc()


def record_option_strategy(strategy: str) -> None:
    if _PROM_AVAILABLE:
        OPTION_STRATEGY_COUNT.labels(strategy=strategy).inc()


def record_replay(duration: float) -> None:
    if _PROM_AVAILABLE:
        REPLAY_RUNS.inc()
        REPLAY_DURATION.observe(duration)


def record_drift(feature: str, test_type: str) -> None:
    if _PROM_AVAILABLE:
        DRIFT_DETECTED.labels(feature=feature, test_type=test_type).inc()


def record_retrain(status: str) -> None:
    if _PROM_AVAILABLE:
        RETRAIN_RUNS.labels(status=status).inc()


# ── Intraday recording helpers ────────────────────────────────────


def record_intraday_prediction(signal_type: str, latency: float) -> None:
    if _PROM_AVAILABLE:
        INTRADAY_PREDICTION_REQUESTS.labels(signal_type=signal_type).inc()
        INTRADAY_PREDICTION_LATENCY.observe(latency)


def record_intraday_trade(side: str, outcome: str, latency: float = 0.0) -> None:
    if _PROM_AVAILABLE:
        INTRADAY_TRADES.labels(side=side, outcome=outcome).inc()
        if latency > 0:
            INTRADAY_TRADE_LATENCY.observe(latency)


def set_intraday_stats(
    pnl: float,
    open_positions: int,
    win_rate: float,
    profit_factor: float,
    drawdown_pct: float = 0.0,
) -> None:
    if _PROM_AVAILABLE:
        INTRADAY_PNL.set(pnl)
        INTRADAY_OPEN_POSITIONS.set(open_positions)
        INTRADAY_WIN_RATE.set(win_rate)
        INTRADAY_PROFIT_FACTOR.set(profit_factor)
        INTRADAY_DRAWDOWN.set(drawdown_pct)


def set_intraday_model_info(version: str) -> None:
    if _PROM_AVAILABLE:
        INTRADAY_MODEL_VERSION.labels(version=version).set(1)


_SUPERVISOR_STATE_MAP = {"ACTIVE": 1, "PAUSED": 2, "HALTED": 3, "COOLDOWN": 4}


def set_supervisor_state(state: str) -> None:
    if _PROM_AVAILABLE:
        INTRADAY_SUPERVISOR_STATE.set(_SUPERVISOR_STATE_MAP.get(state, 0))


def record_supervisor_trigger(trigger_type: str) -> None:
    if _PROM_AVAILABLE:
        INTRADAY_SUPERVISOR_TRIGGERS.labels(trigger_type=trigger_type).inc()


def record_intraday_option_signal(signal_type: str) -> None:
    if _PROM_AVAILABLE:
        INTRADAY_OPTION_SIGNALS.labels(signal_type=signal_type).inc()


def capture_exception(exc: Exception) -> None:
    """Send exception to Sentry if available."""
    if _SENTRY_AVAILABLE:
        sentry_sdk.capture_exception(exc)
    logger.exception("Captured exception: %s", exc)


def get_metrics_text() -> str:
    """Return Prometheus-compatible metrics text."""
    if _PROM_AVAILABLE:
        return generate_latest().decode("utf-8")
    return "# prometheus_client not installed\n"

