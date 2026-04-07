"""Options trading scaffold interfaces.

This module intentionally provides architecture-only interfaces so
options workflows can plug into the same strategy/risk engine later
without shipping incomplete options execution logic to production.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Protocol


class OptionRight(str, Enum):
    CALL = "call"
    PUT = "put"


class OptionStrategyTemplate(str, Enum):
    LONG_CALL = "long_call"
    LONG_PUT = "long_put"
    BULL_CALL_SPREAD = "bull_call_spread"
    BEAR_PUT_SPREAD = "bear_put_spread"
    COVERED_CALL = "covered_call"
    CASH_SECURED_PUT = "cash_secured_put"


@dataclass
class OptionContract:
    symbol: str
    underlying: str
    expiry: date
    strike: float
    right: OptionRight
    lot_size: int = 1
    ltp: float | None = None
    bid: float | None = None
    ask: float | None = None
    iv: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    open_interest: int | None = None
    volume: int | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class OptionChainSnapshot:
    underlying: str
    timestamp: datetime
    spot_price: float
    contracts: list[OptionContract]


class OptionChainProvider(Protocol):
    def get_option_chain(self, underlying: str) -> OptionChainSnapshot:
        ...


class ExpirySelector(Protocol):
    def choose_expiry(self, chain: OptionChainSnapshot, min_dte: int = 3, max_dte: int = 45) -> date:
        ...


class GreeksEstimator(Protocol):
    def enrich_contracts(self, chain: OptionChainSnapshot) -> OptionChainSnapshot:
        ...


@dataclass
class OptionStrategyRequest:
    template: OptionStrategyTemplate
    underlying: str
    risk_budget: float
    target_dte: int = 14
    direction_score: float = 0.0
    volatility_regime: str = "unknown"


@dataclass
class OptionStrategyPlan:
    template: OptionStrategyTemplate
    legs: list[OptionContract]
    rationale: str
    estimated_max_loss: float
    estimated_max_profit: float | None = None
    metadata: dict[str, object] = field(default_factory=dict)


class OptionStrategyPlanner(Protocol):
    def build_plan(self, request: OptionStrategyRequest) -> OptionStrategyPlan:
        ...
