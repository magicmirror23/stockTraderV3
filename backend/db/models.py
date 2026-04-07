# SQLAlchemy models

"""SQLAlchemy ORM models for persisting orders, fills, backtest jobs,
bot state, risk snapshots, trade journal, and system events."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
)

from backend.db.session import Base


def _uuid():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Original tables
# ---------------------------------------------------------------------------

class Order(Base):
    __tablename__ = "orders"

    id = Column(String(36), primary_key=True, default=_uuid)
    intent_id = Column(String(36), nullable=False, index=True)
    ticker = Column(String(10), nullable=False)
    side = Column(String(4), nullable=False)  # buy / sell
    quantity = Column(Integer, nullable=False)
    order_type = Column(String(6), nullable=False)  # market / limit
    limit_price = Column(Float, nullable=True)
    status = Column(String(20), default="pending")
    # Option fields
    option_type = Column(String(2), nullable=True)    # CE / PE
    strike = Column(Float, nullable=True)
    expiry = Column(String(10), nullable=True)
    strategy = Column(String(30), nullable=True)
    # Risk approval
    risk_score = Column(Float, nullable=True)
    risk_reason = Column(Text, nullable=True)
    # Execution quality
    execution_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Fill(Base):
    __tablename__ = "fills"

    id = Column(String(36), primary_key=True, default=_uuid)
    order_id = Column(String(36), nullable=False, index=True)
    ticker = Column(String(10), nullable=False)
    side = Column(String(4), nullable=False)
    quantity = Column(Integer, nullable=False)
    filled_price = Column(Float, nullable=False)
    slippage = Column(Float, default=0.0)
    latency_ms = Column(Float, default=0.0)
    commission = Column(Float, default=0.0)
    fill_quality = Column(Float, nullable=True)  # 0-1 quality score
    partial = Column(Boolean, default=False)
    # Option fields
    option_type = Column(String(2), nullable=True)
    strike = Column(Float, nullable=True)
    expiry = Column(String(10), nullable=True)
    strategy = Column(String(30), nullable=True)
    executed_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class BacktestJob(Base):
    __tablename__ = "backtest_jobs"

    id = Column(String(36), primary_key=True, default=_uuid)
    tickers = Column(Text, nullable=False)  # JSON list
    start_date = Column(String(10), nullable=False)
    end_date = Column(String(10), nullable=False)
    initial_capital = Column(Float, default=100_000.0)
    strategy = Column(String(50), default="momentum")
    status = Column(String(20), default="pending")
    result_json = Column(Text, nullable=True)
    submitted_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(String(36), primary_key=True, default=_uuid)
    event = Column(String(80), nullable=False)
    entity_type = Column(String(50), nullable=True)
    entity_id = Column(String(36), nullable=True)
    data = Column(Text, nullable=True)  # JSON blob
    correlation_id = Column(String(36), nullable=True, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Bot Lifecycle State (persistent across restarts)
# ---------------------------------------------------------------------------

class BotState(Base):
    """Persistent bot state machine — survives process restarts."""
    __tablename__ = "bot_state"

    id = Column(String(36), primary_key=True, default=_uuid)
    state = Column(String(30), nullable=False, default="STOPPED")
    # STOPPED | WAITING_FOR_MARKET | WAITING_FOR_CONSENT | ACTIVE
    # PAUSED | SAFE_MODE | ERROR
    previous_state = Column(String(30), nullable=True)
    config_json = Column(Text, nullable=True)  # JSON bot config
    error_message = Column(Text, nullable=True)
    consent_requested_at = Column(DateTime, nullable=True)
    consent_timeout_seconds = Column(Integer, default=300)  # 5 min
    last_heartbeat = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class BotStateTransition(Base):
    """Immutable log of every bot state change for audit."""
    __tablename__ = "bot_state_transitions"

    id = Column(String(36), primary_key=True, default=_uuid)
    from_state = Column(String(30), nullable=True)
    to_state = Column(String(30), nullable=False)
    reason = Column(String(200), nullable=True)
    data_json = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (Index("ix_bst_timestamp", "timestamp"),)


# ---------------------------------------------------------------------------
# Risk Snapshots
# ---------------------------------------------------------------------------

class RiskSnapshot(Base):
    """Pre-trade and post-trade risk state snapshots."""
    __tablename__ = "risk_snapshots"

    id = Column(String(36), primary_key=True, default=_uuid)
    snapshot_type = Column(String(20), nullable=False)  # pre_trade / post_trade / eod
    order_id = Column(String(36), nullable=True, index=True)
    total_exposure = Column(Float, default=0.0)
    sector_exposure_json = Column(Text, nullable=True)
    greeks_json = Column(Text, nullable=True)  # portfolio Greeks
    daily_pnl = Column(Float, default=0.0)
    max_drawdown = Column(Float, default=0.0)
    risk_score = Column(Float, default=0.0)  # 0-100
    data_json = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Trade Journal
# ---------------------------------------------------------------------------

class TradeJournal(Base):
    """Automatic trade journal with mistake tagging."""
    __tablename__ = "trade_journal"

    id = Column(String(36), primary_key=True, default=_uuid)
    order_id = Column(String(36), nullable=True, index=True)
    ticker = Column(String(10), nullable=False)
    side = Column(String(4), nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=True)
    quantity = Column(Integer, nullable=False)
    gross_pnl = Column(Float, nullable=True)
    net_pnl = Column(Float, nullable=True)
    strategy_used = Column(String(50), nullable=True)
    regime = Column(String(30), nullable=True)
    confidence = Column(Float, nullable=True)
    # Explanation
    entry_reason = Column(Text, nullable=True)
    exit_reason = Column(String(50), nullable=True)
    skip_reason = Column(Text, nullable=True)  # "why not trade"
    # Mistake tagging
    mistake_tags = Column(Text, nullable=True)  # JSON list
    # Timestamps
    entered_at = Column(DateTime, nullable=True)
    exited_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# System Events (event bus persistence)
# ---------------------------------------------------------------------------

class SystemEvent(Base):
    """Persisted event bus messages for replay, DLQ, and audit."""
    __tablename__ = "system_events"

    id = Column(String(36), primary_key=True, default=_uuid)
    event_type = Column(String(80), nullable=False, index=True)
    payload_json = Column(Text, nullable=True)
    correlation_id = Column(String(36), nullable=True, index=True)
    source = Column(String(50), nullable=True)
    status = Column(String(20), default="published")  # published / consumed / dlq
    retry_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    consumed_at = Column(DateTime, nullable=True)

    __table_args__ = (Index("ix_se_type_status", "event_type", "status"),)


# ---------------------------------------------------------------------------
# Model Leaderboard
# ---------------------------------------------------------------------------

class ModelLeaderboard(Base):
    """Track model performance for champion/challenger evaluation."""
    __tablename__ = "model_leaderboard"

    id = Column(String(36), primary_key=True, default=_uuid)
    model_version = Column(String(50), nullable=False, index=True)
    model_type = Column(String(30), nullable=True)  # lgbm / xgb / ensemble / lstm
    accuracy = Column(Float, nullable=True)
    sharpe = Column(Float, nullable=True)
    win_rate = Column(Float, nullable=True)
    total_predictions = Column(Integer, default=0)
    correct_predictions = Column(Integer, default=0)
    regime = Column(String(30), nullable=True)
    symbol = Column(String(10), nullable=True)
    is_champion = Column(Boolean, default=False)
    promoted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Market Data Service
# ---------------------------------------------------------------------------

class MarketBar(Base):
    """Canonical normalized OHLCV bars shared across all services."""

    __tablename__ = "market_bars"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(24), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    interval = Column(String(16), nullable=False, default="1d", index=True)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False, default=0.0)
    source = Column(String(40), nullable=False, default="unknown")
    ingested_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    __table_args__ = (
        Index("ux_market_bars_sym_ts_int", "symbol", "timestamp", "interval", unique=True),
        Index("ix_market_bars_sym_int_ts", "symbol", "interval", "timestamp"),
    )


class MarketDataFailure(Base):
    """Tracks symbol/provider failures for retry and cooldown jobs."""

    __tablename__ = "market_data_failures"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(24), nullable=False, index=True)
    interval = Column(String(16), nullable=False, default="1d", index=True)
    provider = Column(String(40), nullable=False)
    error_code = Column(String(40), nullable=False, index=True)
    last_error = Column(Text, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    last_attempt_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    cooldown_until = Column(DateTime, nullable=True, index=True)

    __table_args__ = (
        Index("ux_market_data_fail_sym_int", "symbol", "interval", unique=True),
    )

