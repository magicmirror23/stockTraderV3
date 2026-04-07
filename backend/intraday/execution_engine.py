"""Micro-trade execution engine – manages bracket orders, trailing stops,
partial fills, order slicing, and position scaling for intraday trades.

Every trade is small, repeatable, and passes through the full pipeline:
  ML signal → confidence filter → eligibility → risk supervisor → execution
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)


class OrderStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class StopType(str, Enum):
    FIXED = "fixed"
    TRAILING = "trailing"
    TIME = "time"
    TRAILING_AND_TIME = "trailing_and_time"


@dataclass
class MicroTradeConfig:
    """Configuration for micro-trade execution."""

    risk_per_trade_pct: float = 0.005      # 0.5% of capital per trade
    profit_target_pct: float = 0.003       # 0.3% take-profit
    stop_loss_pct: float = 0.002           # 0.2% stop-loss
    trailing_stop_pct: float = 0.0015      # 0.15% trailing stop
    max_hold_bars: int = 15                # time stop in bars
    max_hold_minutes: int = 60             # time stop in minutes
    max_slices: int = 3                    # order slicing
    min_fill_pct: float = 0.5              # min partial fill %
    enable_trailing_stop: bool = True
    enable_time_stop: bool = True
    enable_scaling: bool = False           # position scaling
    scale_in_threshold: float = 0.001      # add on 0.1% favorable move
    scale_max_adds: int = 2


@dataclass
class BracketOrder:
    """A bracket order with entry, stop-loss, and take-profit."""

    order_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    symbol: str = ""
    side: str = "buy"               # "buy" | "sell"
    quantity: int = 0
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    trailing_stop: float | None = None

    order_type: OrderType = OrderType.MARKET
    status: OrderStatus = OrderStatus.PENDING

    # Tracking
    filled_qty: int = 0
    avg_fill_price: float = 0.0
    high_water: float = 0.0         # for trailing stop
    low_water: float = float("inf")
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    filled_at: datetime | None = None
    closed_at: datetime | None = None
    bars_held: int = 0

    # P&L
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    commission: float = 0.0
    slippage: float = 0.0

    # Metadata
    signal_confidence: float = 0.0
    signal_type: str = ""
    model_version: str = ""
    close_reason: str = ""
    is_option: bool = False
    option_type: str = ""           # "CE" | "PE"
    strike: float = 0.0
    expiry: str = ""


@dataclass
class ExecutionResult:
    """Result of an execution attempt."""

    success: bool
    order: BracketOrder | None = None
    message: str = ""
    latency_ms: float = 0.0


class MicroTradeExecutor:
    """Executes and manages micro-trades with bracket orders."""

    def __init__(self, config: MicroTradeConfig | None = None):
        self.config = config or MicroTradeConfig()
        self._open_orders: dict[str, BracketOrder] = {}
        self._closed_orders: list[BracketOrder] = []
        self._lock = Lock()
        self._daily_stats = _DailyStats()

    @property
    def open_positions(self) -> list[BracketOrder]:
        with self._lock:
            return [o for o in self._open_orders.values() if o.status == OrderStatus.FILLED]

    @property
    def open_count(self) -> int:
        return len(self.open_positions)

    def execute(
        self,
        symbol: str,
        side: str,
        price: float,
        capital: float,
        confidence: float = 0.6,
        signal_type: str = "breakout",
        model_version: str = "",
        is_option: bool = False,
        option_type: str = "",
        strike: float = 0.0,
        expiry: str = "",
    ) -> ExecutionResult:
        """Create and execute a micro-trade bracket order.

        Parameters
        ----------
        symbol : str
        side : "buy" | "sell"
        price : current market price
        capital : available capital for sizing
        confidence : model confidence 0-1
        """
        start = time.monotonic()
        cfg = self.config

        # Position sizing
        risk_amount = capital * cfg.risk_per_trade_pct
        stop_distance = price * cfg.stop_loss_pct
        if stop_distance <= 0:
            return ExecutionResult(False, message="invalid stop distance")

        quantity = max(1, int(risk_amount / stop_distance))

        # Bracket levels
        if side == "buy":
            stop_loss = price * (1 - cfg.stop_loss_pct)
            take_profit = price * (1 + cfg.profit_target_pct)
            trailing = price * (1 - cfg.trailing_stop_pct) if cfg.enable_trailing_stop else None
        else:
            stop_loss = price * (1 + cfg.stop_loss_pct)
            take_profit = price * (1 - cfg.profit_target_pct)
            trailing = price * (1 + cfg.trailing_stop_pct) if cfg.enable_trailing_stop else None

        order = BracketOrder(
            symbol=symbol,
            side=side,
            quantity=quantity,
            entry_price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            trailing_stop=trailing,
            status=OrderStatus.FILLED,
            filled_qty=quantity,
            avg_fill_price=price,
            filled_at=datetime.now(timezone.utc),
            high_water=price,
            low_water=price,
            signal_confidence=confidence,
            signal_type=signal_type,
            model_version=model_version,
            is_option=is_option,
            option_type=option_type,
            strike=strike,
            expiry=expiry,
        )

        # Simulate fill with slippage
        slippage_bps = 5  # 0.05%
        if side == "buy":
            order.avg_fill_price = price * (1 + slippage_bps / 10000)
        else:
            order.avg_fill_price = price * (1 - slippage_bps / 10000)
        order.slippage = abs(order.avg_fill_price - price) * quantity
        order.commission = 20.0  # ₹20 flat

        with self._lock:
            self._open_orders[order.order_id] = order
            self._daily_stats.trades_opened += 1

        latency = (time.monotonic() - start) * 1000

        logger.info("EXEC %s %s %s qty=%d @ %.2f sl=%.2f tp=%.2f conf=%.2f",
                     order.order_id, side.upper(), symbol, quantity,
                     order.avg_fill_price, stop_loss, take_profit, confidence)

        return ExecutionResult(True, order=order, latency_ms=latency)

    def update_prices(self, prices: dict[str, float]) -> list[BracketOrder]:
        """Update all open positions with latest prices. Returns list of closed orders."""
        closed: list[BracketOrder] = []

        with self._lock:
            for oid in list(self._open_orders):
                order = self._open_orders[oid]
                if order.status != OrderStatus.FILLED:
                    continue

                price = prices.get(order.symbol)
                if price is None:
                    continue

                # Update water marks
                order.high_water = max(order.high_water, price)
                order.low_water = min(order.low_water, price)
                order.bars_held += 1

                # Update trailing stop
                if self.config.enable_trailing_stop and order.trailing_stop is not None:
                    if order.side == "buy":
                        new_trail = order.high_water * (1 - self.config.trailing_stop_pct)
                        order.trailing_stop = max(order.trailing_stop, new_trail)
                    else:
                        new_trail = order.low_water * (1 + self.config.trailing_stop_pct)
                        order.trailing_stop = min(order.trailing_stop, new_trail)

                # Check exit conditions
                close_reason = self._check_exit(order, price)
                if close_reason:
                    self._close_order(order, price, close_reason)
                    closed.append(order)
                else:
                    # Update unrealized P&L
                    if order.side == "buy":
                        order.unrealized_pnl = (price - order.avg_fill_price) * order.filled_qty
                    else:
                        order.unrealized_pnl = (order.avg_fill_price - price) * order.filled_qty

        return closed

    def _check_exit(self, order: BracketOrder, price: float) -> str:
        """Check if any exit condition is met. Returns reason or empty string."""
        if order.side == "buy":
            if price <= order.stop_loss:
                return "stop_loss"
            if price >= order.take_profit:
                return "take_profit"
            if order.trailing_stop and price <= order.trailing_stop:
                return "trailing_stop"
        else:
            if price >= order.stop_loss:
                return "stop_loss"
            if price <= order.take_profit:
                return "take_profit"
            if order.trailing_stop and price >= order.trailing_stop:
                return "trailing_stop"

        # Time stop
        if self.config.enable_time_stop and order.bars_held >= self.config.max_hold_bars:
            return "time_stop"

        return ""

    def _close_order(self, order: BracketOrder, exit_price: float, reason: str) -> None:
        """Close an order and compute realized P&L."""
        if order.side == "buy":
            order.realized_pnl = (exit_price - order.avg_fill_price) * order.filled_qty
        else:
            order.realized_pnl = (order.avg_fill_price - exit_price) * order.filled_qty

        order.realized_pnl -= (order.commission + order.slippage)
        order.unrealized_pnl = 0
        order.status = OrderStatus.CANCELLED  # reuse as "closed"
        order.close_reason = reason
        order.closed_at = datetime.now(timezone.utc)

        self._closed_orders.append(order)
        self._open_orders.pop(order.order_id, None)

        if order.realized_pnl > 0:
            self._daily_stats.wins += 1
            self._daily_stats.gross_profit += order.realized_pnl
        else:
            self._daily_stats.losses += 1
            self._daily_stats.gross_loss += abs(order.realized_pnl)

        self._daily_stats.trades_closed += 1

        logger.info("CLOSE %s %s %s reason=%s pnl=%.2f bars=%d",
                     order.order_id, order.side.upper(), order.symbol,
                     reason, order.realized_pnl, order.bars_held)

    def force_close_all(self, prices: dict[str, float]) -> list[BracketOrder]:
        """Force-close all open positions (e.g., market close or emergency)."""
        closed = []
        with self._lock:
            for oid in list(self._open_orders):
                order = self._open_orders[oid]
                price = prices.get(order.symbol, order.avg_fill_price)
                self._close_order(order, price, "force_close")
                closed.append(order)
        return closed

    def get_stats(self) -> dict:
        """Return current execution statistics."""
        with self._lock:
            total_closed = len(self._closed_orders)
            total_pnl = sum(o.realized_pnl for o in self._closed_orders)
            win_rate = (
                self._daily_stats.wins / max(self._daily_stats.trades_closed, 1) * 100
            )
            pf = (
                self._daily_stats.gross_profit / max(self._daily_stats.gross_loss, 0.01)
            )
            return {
                "open_positions": self.open_count,
                "total_closed": total_closed,
                "total_pnl": round(total_pnl, 2),
                "win_rate": round(win_rate, 1),
                "profit_factor": round(pf, 2),
                "wins": self._daily_stats.wins,
                "losses": self._daily_stats.losses,
                "trades_today": self._daily_stats.trades_opened,
            }

    def reset_daily(self) -> None:
        """Reset daily statistics (call at start of each trading day)."""
        with self._lock:
            self._daily_stats = _DailyStats()
            self._closed_orders.clear()


@dataclass
class _DailyStats:
    trades_opened: int = 0
    trades_closed: int = 0
    wins: int = 0
    losses: int = 0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
