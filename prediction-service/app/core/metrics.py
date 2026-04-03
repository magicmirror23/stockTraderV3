"""Prometheus metrics instrumentation.

Provides pre-defined counters, histograms, and gauges for the prediction
service.  The ``/metrics`` endpoint is mounted by the main app.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, Info

# ── Service info ─────────────────────────────────────────────────────
SERVICE_INFO = Info("prediction_service", "Prediction service build information")

# ── Predictions ──────────────────────────────────────────────────────
PREDICTION_LATENCY = Histogram(
    "prediction_latency_seconds",
    "Time to produce a single prediction",
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
PREDICTION_COUNT = Counter(
    "predictions_total",
    "Number of predictions generated",
    ["instrument", "recommendation"],
)
PREDICTION_CONFIDENCE = Histogram(
    "prediction_confidence",
    "Confidence score distribution",
    buckets=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.55, 0.6, 0.65, 0.7, 0.8, 0.9, 1.0),
)
NO_TRADE_COUNT = Counter(
    "predictions_no_trade_total",
    "Number of times no-trade was returned",
)

# ── Training ─────────────────────────────────────────────────────────
TRAINING_DURATION = Histogram(
    "training_duration_seconds",
    "Model training wall-clock time",
    buckets=(10, 30, 60, 120, 300, 600, 1800, 3600),
)
TRAINING_COUNT = Counter(
    "training_runs_total",
    "Number of training runs",
    ["status"],
)

# ── Data freshness ───────────────────────────────────────────────────
DATA_FRESHNESS_SECONDS = Gauge(
    "data_freshness_seconds",
    "Seconds since last market data update",
    ["source"],
)
STALE_DATA_COUNT = Counter(
    "stale_data_events_total",
    "Number of stale data detections",
    ["source"],
)

# ── Feature drift ────────────────────────────────────────────────────
FEATURE_DRIFT_SCORE = Gauge(
    "feature_drift_score",
    "Feature drift PSI score",
    ["feature"],
)
CALIBRATION_DRIFT = Gauge(
    "calibration_drift",
    "ECE calibration error",
)

# ── Regime ───────────────────────────────────────────────────────────
CURRENT_REGIME = Gauge(
    "current_regime_id",
    "Current detected market regime",
)

# ── Source / health ──────────────────────────────────────────────────
SOURCE_FAILURE_COUNT = Counter(
    "source_failure_total",
    "Provider / source failure events",
    ["source", "error_type"],
)
HEALTH_STATUS = Gauge(
    "health_status",
    "1 = healthy, 0 = degraded",
)
