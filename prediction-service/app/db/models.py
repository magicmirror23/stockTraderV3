"""SQLAlchemy ORM models for the prediction service.

Tables cover: predictions, features, model metadata, training runs,
drift metrics, event scores, sentiment snapshots, and audit logs.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class PredictionRecord(Base):
    """Stores every prediction output for auditing and backtesting."""

    __tablename__ = "predictions"

    id = Column(String(36), primary_key=True, default=_uuid)
    instrument = Column(String(32), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    timeframe = Column(String(16), default="1d")
    direction_probability = Column(Float)
    expected_move = Column(Float)
    expected_volatility = Column(Float)
    regime = Column(String(32))
    confidence_score = Column(Float)
    model_version = Column(String(64))
    top_features = Column(JSON)
    event_risk_score = Column(Float, default=0.0)
    sentiment_score = Column(Float, default=0.0)
    recommendation = Column(String(16))  # long/short/neutral/no-trade
    stop_loss_hint = Column(Float)
    take_profit_hint = Column(Float)
    options_strategy_hint = Column(String(128))
    raw_output = Column(JSON)

    __table_args__ = (
        Index("ix_pred_ts_instr", "timestamp", "instrument"),
    )


class FeatureSnapshot(Base):
    """Stores engineered features at the time of prediction/training."""

    __tablename__ = "feature_snapshots"

    id = Column(String(36), primary_key=True, default=_uuid)
    instrument = Column(String(32), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    feature_set_version = Column(String(32))
    features = Column(JSON, nullable=False)

    __table_args__ = (
        Index("ix_feat_ts_instr", "timestamp", "instrument"),
    )


class ModelMetadata(Base):
    """Tracks trained model versions and their metrics."""

    __tablename__ = "model_metadata"

    id = Column(String(36), primary_key=True, default=_uuid)
    version = Column(String(64), unique=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    model_type = Column(String(64))  # lightgbm / xgboost / ensemble / ...
    status = Column(String(16), default="trained")  # trained / active / retired
    params = Column(JSON)
    train_metrics = Column(JSON)
    val_metrics = Column(JSON)
    test_metrics = Column(JSON)
    feature_importance = Column(JSON)
    artifact_path = Column(String(512))
    tickers_count = Column(Integer)
    training_rows = Column(Integer)
    walk_forward_folds = Column(Integer)


class TrainingRun(Base):
    """Audit log for each training invocation."""

    __tablename__ = "training_runs"

    id = Column(String(36), primary_key=True, default=_uuid)
    started_at = Column(DateTime(timezone=True), default=_utcnow)
    finished_at = Column(DateTime(timezone=True))
    status = Column(String(16))  # running / success / failed
    model_version = Column(String(64))
    duration_seconds = Column(Float)
    error_message = Column(Text)
    config = Column(JSON)
    metrics = Column(JSON)


class DriftMetric(Base):
    """Periodic drift detection results."""

    __tablename__ = "drift_metrics"

    id = Column(String(36), primary_key=True, default=_uuid)
    timestamp = Column(DateTime(timezone=True), default=_utcnow)
    model_version = Column(String(64))
    feature_psi_scores = Column(JSON)
    label_drift_pvalue = Column(Float)
    calibration_ece = Column(Float)
    is_drifted = Column(Boolean, default=False)


class EventScore(Base):
    """Structured event scores from the event-ingestion pipeline."""

    __tablename__ = "event_scores"

    id = Column(String(36), primary_key=True, default=_uuid)
    timestamp = Column(DateTime(timezone=True), default=_utcnow)
    event_type = Column(String(64), nullable=False)
    severity = Column(Float, default=0.0)
    region = Column(String(64))
    sectors_impacted = Column(JSON)
    confidence = Column(Float, default=0.5)
    decay_weight = Column(Float, default=1.0)
    volatility_shock_score = Column(Float, default=0.0)
    sentiment_impact_score = Column(Float, default=0.0)
    gap_risk_score = Column(Float, default=0.0)
    expected_duration_hours = Column(Float)
    source = Column(String(128))
    raw_text = Column(Text)
    is_active = Column(Boolean, default=True)

    __table_args__ = (
        Index("ix_event_active", "is_active", "timestamp"),
    )


class SentimentSnapshot(Base):
    """Time-series sentiment readings."""

    __tablename__ = "sentiment_snapshots"

    id = Column(String(36), primary_key=True, default=_uuid)
    timestamp = Column(DateTime(timezone=True), default=_utcnow)
    instrument = Column(String(32), index=True)
    sector = Column(String(64))
    news_sentiment = Column(Float, default=0.0)
    sector_sentiment = Column(Float, default=0.0)
    macro_sentiment = Column(Float, default=0.0)
    event_sentiment = Column(Float, default=0.0)
    composite_score = Column(Float, default=0.0)


class AuditLog(Base):
    """General audit trail for important operations."""

    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=_uuid)
    timestamp = Column(DateTime(timezone=True), default=_utcnow)
    action = Column(String(64), nullable=False)
    actor = Column(String(64), default="system")
    details = Column(JSON)
    severity = Column(String(16), default="info")  # info / warning / error


class ErrorLog(Base):
    """Structured error storage."""

    __tablename__ = "error_logs"

    id = Column(String(36), primary_key=True, default=_uuid)
    timestamp = Column(DateTime(timezone=True), default=_utcnow)
    component = Column(String(64))
    error_type = Column(String(128))
    message = Column(Text)
    traceback = Column(Text)
    context = Column(JSON)
