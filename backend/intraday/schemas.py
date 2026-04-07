"""Intraday API schemas – request / response models for the intraday
trading stack endpoints.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ── Enums ──────────────────────────────────────────────────────────────────

class IntradayInterval(str, Enum):
    ONE_MIN = "1m"
    FIVE_MIN = "5m"
    FIFTEEN_MIN = "15m"


class IntradayTargetType(str, Enum):
    BREAKOUT = "breakout"
    MOMENTUM = "momentum"
    MEAN_REVERSION = "mean_reversion"
    RETURN = "return"


class OptionSignalTypeEnum(str, Enum):
    LONG_CALL_BREAKOUT = "long_call_breakout"
    LONG_PUT_BREAKDOWN = "long_put_breakdown"
    BULL_CALL_SPREAD = "bull_call_spread"
    BEAR_PUT_SPREAD = "bear_put_spread"
    NO_TRADE = "no_trade"


class SupervisorStateEnum(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    HALTED = "halted"
    COOLDOWN = "cooldown"


# ── Feature service ────────────────────────────────────────────────────────

class FeatureRequest(BaseModel):
    symbol: str
    interval: IntradayInterval = IntradayInterval.ONE_MIN
    bars: int = Field(100, ge=10, le=500)


class FeatureResponse(BaseModel):
    symbol: str
    interval: str
    features: dict[str, float]
    bars_used: int
    timestamp: str


# ── Prediction service ─────────────────────────────────────────────────────

class IntradayPredictRequest(BaseModel):
    symbol: str
    features: dict[str, float] | None = None
    interval: IntradayInterval = IntradayInterval.ONE_MIN


class IntradaySignalResponse(BaseModel):
    symbol: str
    action: str
    confidence: float
    expected_return: float
    score: float
    model_version: str
    features_used: int
    signal_type: str
    eligible: bool
    rejection_reason: str = ""


class IntradayBatchPredictRequest(BaseModel):
    symbols: list[str]
    interval: IntradayInterval = IntradayInterval.ONE_MIN


class IntradayBatchResponse(BaseModel):
    signals: list[IntradaySignalResponse]
    timestamp: str


class IntradayModelStatus(BaseModel):
    loaded: bool
    version: str
    model_name: str
    target_type: str
    horizon_bars: int
    n_features: int
    metrics: dict[str, Any] = {}


# ── Options signal service ─────────────────────────────────────────────────

class OptionSignalRequest(BaseModel):
    symbol: str
    underlying_trend: str = "neutral"
    trend_confidence: float = 0.5
    underlying_price: float = 0.0
    atm_iv: float = 0.18
    put_call_ratio: float = 1.0
    days_to_expiry: int = 7


class OptionSignalResponse(BaseModel):
    symbol: str
    signal_type: str
    direction: str
    confidence: float
    underlying_price: float
    entry_strike: float
    exit_strike: float
    option_type: str
    expiry: str
    max_loss: float
    max_profit: float
    breakeven: float
    risk_reward: float
    volatility_regime: str
    reasoning: list[str] = []
    eligible: bool
    rejection_reason: str = ""


# ── Execution engine ───────────────────────────────────────────────────────

class ExecuteTradeRequest(BaseModel):
    symbol: str
    side: str = Field(..., pattern="^(buy|sell)$")
    price: float = Field(..., gt=0)
    capital: float = Field(100000, gt=0)
    confidence: float = Field(0.6, ge=0, le=1)
    signal_type: str = "breakout"
    model_version: str = ""
    is_option: bool = False
    option_type: str = ""
    strike: float = 0.0
    expiry: str = ""


class ExecuteTradeResponse(BaseModel):
    success: bool
    order_id: str = ""
    symbol: str = ""
    side: str = ""
    quantity: int = 0
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    message: str = ""
    latency_ms: float = 0.0


class ExecutionStatsResponse(BaseModel):
    open_positions: int
    total_closed: int
    total_pnl: float
    win_rate: float
    profit_factor: float
    wins: int
    losses: int
    trades_today: int


class ForceCloseRequest(BaseModel):
    prices: dict[str, float] = {}


# ── Trade supervisor ───────────────────────────────────────────────────────

class SupervisorApprovalRequest(BaseModel):
    symbol: str
    side: str
    price: float
    quantity: int
    confidence: float = 0.5
    spread_pct: float = 0.0
    volume: int = 0
    volatility: float = 0.0


class SupervisorApprovalResponse(BaseModel):
    approved: bool
    reasons: list[str] = []
    warnings: list[str] = []
    risk_score: float = 0.0
    adjusted_quantity: int = 0


class SupervisorStatusResponse(BaseModel):
    state: str
    pause_reason: str | None = None
    daily_pnl: float
    peak_equity: float
    current_equity: float
    drawdown_pct: float
    open_positions: dict[str, int] = {}
    total_open: int
    cooldowns: dict[str, int] = {}
    trades_last_minute: int
    pause_history: list[dict] = []


class SupervisorResumeRequest(BaseModel):
    force: bool = False


# ── Training ───────────────────────────────────────────────────────────────

class IntradayTrainRequest(BaseModel):
    target_type: IntradayTargetType = IntradayTargetType.BREAKOUT
    horizon_bars: int = Field(3, ge=1, le=30)
    target_return_threshold: float = Field(0.002, ge=0.0005, le=0.05)
    train_days: int = Field(60, ge=20, le=365)
    val_days: int = Field(15, ge=5, le=60)
    n_splits: int = Field(5, ge=2, le=20)
    models_to_train: list[str] = ["logistic", "lightgbm", "histgb"]


class IntradayTrainResponse(BaseModel):
    status: str
    version: str = ""
    model_name: str = ""
    metrics: dict[str, Any] = {}
    error: str = ""
