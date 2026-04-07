"""Trade supervisor – centralized risk engine for all automated intraday
and F&O trading.  Enforces hard safety limits and detects system failures.

Every trade must pass through ``approve_trade()`` before execution.
The supervisor can pause trading automatically when safety conditions
are breached.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)


class SupervisorState(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    HALTED = "halted"         # hard stop – manual restart required
    COOLDOWN = "cooldown"


class PauseReason(str, Enum):
    DAILY_LOSS = "daily_loss_limit"
    DRAWDOWN = "max_drawdown"
    RATE_LIMIT = "trade_rate_limit"
    DATA_FAILURE = "data_feed_failure"
    BROKER_FAILURE = "broker_api_failure"
    VOLATILITY = "abnormal_volatility"
    MANUAL = "manual_pause"
    WEBSOCKET = "websocket_disconnection"


@dataclass
class SupervisorConfig:
    """Hard safety rules for the trade supervisor."""

    # Loss limits
    daily_loss_limit: float = 5000.0        # ₹5,000
    max_drawdown_pct: float = 0.05          # 5% peak-to-trough
    max_drawdown_amount: float = 10000.0    # ₹10,000 absolute

    # Rate limits
    max_trades_per_minute: int = 10
    max_trades_per_symbol_per_minute: int = 3
    max_open_positions: int = 15
    max_open_per_symbol: int = 3

    # Cooldowns
    symbol_cooldown_after_stopout_s: int = 300  # 5 min cooldown after stop-out
    global_cooldown_on_drawdown_s: int = 600    # 10 min global cooldown

    # Anomaly detection
    volatility_spike_threshold: float = 3.0  # 3x normal vol
    max_spread_pct: float = 0.005            # 0.5% spread limit
    min_liquidity_volume: int = 1000

    # System health
    data_feed_timeout_s: int = 30
    broker_health_timeout_s: int = 15


@dataclass
class TradeApproval:
    """Result of a trade approval request."""

    approved: bool
    trade_id: str = ""
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    risk_score: float = 0.0        # 0-100 (higher = riskier)
    adjusted_quantity: int = 0     # may be reduced by supervisor


class TradeSupervisor:
    """Centralized risk supervisor for all automated trading."""

    def __init__(self, config: SupervisorConfig | None = None):
        self.config = config or SupervisorConfig()
        self._state = SupervisorState.ACTIVE
        self._pause_reason: PauseReason | None = None
        self._lock = Lock()

        # Tracking
        self._daily_pnl: float = 0.0
        self._peak_equity: float = 0.0
        self._current_equity: float = 0.0
        self._trade_timestamps: list[float] = []
        self._symbol_trade_timestamps: dict[str, list[float]] = defaultdict(list)
        self._open_positions: dict[str, int] = defaultdict(int)  # symbol → count
        self._cooldown_until: dict[str, float] = {}  # symbol → epoch
        self._global_cooldown_until: float = 0.0
        self._last_data_feed: float = time.monotonic()
        self._last_broker_health: float = time.monotonic()
        self._pause_history: list[dict] = []

    @property
    def state(self) -> SupervisorState:
        return self._state

    @property
    def is_trading_allowed(self) -> bool:
        return self._state == SupervisorState.ACTIVE

    def approve_trade(
        self,
        symbol: str,
        side: str,
        price: float,
        quantity: int,
        confidence: float = 0.5,
        spread_pct: float = 0.0,
        volume: int = 0,
        volatility: float = 0.0,
    ) -> TradeApproval:
        """Evaluate a proposed trade against all risk rules.

        This is the single gate every trade must pass through.
        """
        with self._lock:
            reasons: list[str] = []
            warnings: list[str] = []
            risk_score = 0.0
            adjusted_qty = quantity

            # ── State check ───────────────────────────────
            if self._state != SupervisorState.ACTIVE:
                return TradeApproval(
                    approved=False, reasons=[f"supervisor_{self._state.value}"],
                    risk_score=100, adjusted_quantity=0,
                )

            # ── Global cooldown ───────────────────────────
            now = time.monotonic()
            if now < self._global_cooldown_until:
                remaining = int(self._global_cooldown_until - now)
                return TradeApproval(
                    approved=False, reasons=[f"global_cooldown ({remaining}s remaining)"],
                    risk_score=80, adjusted_quantity=0,
                )

            # ── Symbol cooldown ───────────────────────────
            if symbol in self._cooldown_until and now < self._cooldown_until[symbol]:
                remaining = int(self._cooldown_until[symbol] - now)
                return TradeApproval(
                    approved=False,
                    reasons=[f"symbol_cooldown: {symbol} ({remaining}s remaining)"],
                    risk_score=70, adjusted_quantity=0,
                )

            # ── Daily loss limit ──────────────────────────
            if self._daily_pnl <= -self.config.daily_loss_limit:
                self._pause(PauseReason.DAILY_LOSS)
                return TradeApproval(
                    approved=False,
                    reasons=[f"daily_loss_limit: pnl={self._daily_pnl:.0f} <= -{self.config.daily_loss_limit:.0f}"],
                    risk_score=100, adjusted_quantity=0,
                )
            if self._daily_pnl <= -self.config.daily_loss_limit * 0.8:
                warnings.append(f"approaching daily loss limit: {self._daily_pnl:.0f}")
                risk_score += 30

            # ── Drawdown check ────────────────────────────
            if self._peak_equity > 0:
                dd = (self._peak_equity - self._current_equity) / self._peak_equity
                if dd >= self.config.max_drawdown_pct:
                    self._pause(PauseReason.DRAWDOWN)
                    return TradeApproval(
                        approved=False,
                        reasons=[f"max_drawdown: {dd:.1%} >= {self.config.max_drawdown_pct:.1%}"],
                        risk_score=100, adjusted_quantity=0,
                    )
                if dd >= self.config.max_drawdown_pct * 0.7:
                    warnings.append(f"drawdown at {dd:.1%}")
                    risk_score += 20

            # ── Trade rate limit ──────────────────────────
            cutoff = now - 60
            recent = [t for t in self._trade_timestamps if t > cutoff]
            if len(recent) >= self.config.max_trades_per_minute:
                return TradeApproval(
                    approved=False,
                    reasons=[f"rate_limit: {len(recent)} trades in last minute"],
                    risk_score=90, adjusted_quantity=0,
                )

            sym_recent = [t for t in self._symbol_trade_timestamps[symbol] if t > cutoff]
            if len(sym_recent) >= self.config.max_trades_per_symbol_per_minute:
                return TradeApproval(
                    approved=False,
                    reasons=[f"symbol_rate_limit: {symbol} has {len(sym_recent)} trades in last minute"],
                    risk_score=80, adjusted_quantity=0,
                )

            # ── Position limits ───────────────────────────
            total_open = sum(self._open_positions.values())
            if total_open >= self.config.max_open_positions:
                return TradeApproval(
                    approved=False,
                    reasons=[f"max_open_positions: {total_open} >= {self.config.max_open_positions}"],
                    risk_score=85, adjusted_quantity=0,
                )

            sym_open = self._open_positions.get(symbol, 0)
            if sym_open >= self.config.max_open_per_symbol:
                return TradeApproval(
                    approved=False,
                    reasons=[f"max_open_per_symbol: {symbol} has {sym_open}"],
                    risk_score=75, adjusted_quantity=0,
                )

            # ── Spread / liquidity check ──────────────────
            if spread_pct > self.config.max_spread_pct:
                reasons.append(f"spread_too_wide: {spread_pct:.3%}")
                risk_score += 40

            if 0 < volume < self.config.min_liquidity_volume:
                reasons.append(f"low_liquidity: volume={volume}")
                risk_score += 30

            # ── Volatility anomaly ────────────────────────
            if volatility > 0 and volatility > self.config.volatility_spike_threshold:
                warnings.append(f"high_volatility: {volatility:.1f}x normal")
                risk_score += 25
                adjusted_qty = max(1, int(quantity * 0.5))  # reduce size

            # ── Data feed freshness ───────────────────────
            data_age = now - self._last_data_feed
            if data_age > self.config.data_feed_timeout_s:
                self._pause(PauseReason.DATA_FAILURE)
                return TradeApproval(
                    approved=False,
                    reasons=[f"data_feed_stale: {data_age:.0f}s"],
                    risk_score=100, adjusted_quantity=0,
                )

            # ── Broker health ─────────────────────────────
            broker_age = now - self._last_broker_health
            if broker_age > self.config.broker_health_timeout_s:
                self._pause(PauseReason.BROKER_FAILURE)
                return TradeApproval(
                    approved=False,
                    reasons=[f"broker_health_stale: {broker_age:.0f}s"],
                    risk_score=100, adjusted_quantity=0,
                )

            # ── Approved ──────────────────────────────────
            if reasons:
                return TradeApproval(
                    approved=False, reasons=reasons, warnings=warnings,
                    risk_score=min(risk_score, 100), adjusted_quantity=0,
                )

            return TradeApproval(
                approved=True, warnings=warnings,
                risk_score=min(risk_score, 100),
                adjusted_quantity=adjusted_qty,
            )

    def record_trade(self, symbol: str, pnl: float = 0.0, is_open: bool = True) -> None:
        """Record a trade execution for rate-limiting and position tracking."""
        with self._lock:
            now = time.monotonic()
            self._trade_timestamps.append(now)
            self._symbol_trade_timestamps[symbol].append(now)

            if is_open:
                self._open_positions[symbol] = self._open_positions.get(symbol, 0) + 1
            else:
                self._open_positions[symbol] = max(0, self._open_positions.get(symbol, 0) - 1)
                self._daily_pnl += pnl

    def record_stopout(self, symbol: str) -> None:
        """Record a stop-out and apply symbol cooldown."""
        with self._lock:
            self._cooldown_until[symbol] = (
                time.monotonic() + self.config.symbol_cooldown_after_stopout_s
            )
            logger.warning("COOLDOWN: %s for %ds after stopout",
                          symbol, self.config.symbol_cooldown_after_stopout_s)

    def update_equity(self, equity: float) -> None:
        """Update current equity for drawdown tracking."""
        with self._lock:
            self._current_equity = equity
            self._peak_equity = max(self._peak_equity, equity)

    def heartbeat_data_feed(self) -> None:
        """Call periodically to indicate data feed is alive."""
        self._last_data_feed = time.monotonic()

    def heartbeat_broker(self) -> None:
        """Call periodically to indicate broker API is responsive."""
        self._last_broker_health = time.monotonic()

    def _pause(self, reason: PauseReason) -> None:
        """Pause trading with a reason."""
        prev = self._state
        self._state = SupervisorState.PAUSED
        self._pause_reason = reason
        self._pause_history.append({
            "reason": reason.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "daily_pnl": self._daily_pnl,
        })

        if reason == PauseReason.DRAWDOWN:
            self._global_cooldown_until = (
                time.monotonic() + self.config.global_cooldown_on_drawdown_s
            )

        logger.warning("SUPERVISOR PAUSED: %s → %s (reason=%s, pnl=%.0f)",
                       prev.value, self._state.value, reason.value, self._daily_pnl)

    def resume(self, force: bool = False) -> bool:
        """Resume trading. Returns True if successful."""
        with self._lock:
            if self._state == SupervisorState.HALTED and not force:
                logger.warning("Cannot resume from HALTED state without force=True")
                return False
            self._state = SupervisorState.ACTIVE
            self._pause_reason = None
            logger.info("SUPERVISOR RESUMED")
            return True

    def halt(self, reason: str = "manual") -> None:
        """Hard halt – requires manual restart."""
        with self._lock:
            self._state = SupervisorState.HALTED
            logger.critical("SUPERVISOR HALTED: %s", reason)

    def reset_daily(self, initial_equity: float = 0.0) -> None:
        """Reset all daily counters (call at start of each trading day)."""
        with self._lock:
            self._daily_pnl = 0.0
            self._trade_timestamps.clear()
            self._symbol_trade_timestamps.clear()
            self._open_positions.clear()
            self._cooldown_until.clear()
            self._global_cooldown_until = 0.0
            self._pause_history.clear()
            if initial_equity > 0:
                self._peak_equity = initial_equity
                self._current_equity = initial_equity
            if self._state == SupervisorState.PAUSED:
                self._state = SupervisorState.ACTIVE
                self._pause_reason = None
            logger.info("SUPERVISOR: daily reset (equity=%.0f)", initial_equity)

    def get_status(self) -> dict:
        """Return supervisor status snapshot."""
        with self._lock:
            return {
                "state": self._state.value,
                "pause_reason": self._pause_reason.value if self._pause_reason else None,
                "daily_pnl": round(self._daily_pnl, 2),
                "peak_equity": round(self._peak_equity, 2),
                "current_equity": round(self._current_equity, 2),
                "drawdown_pct": round(
                    (self._peak_equity - self._current_equity) / max(self._peak_equity, 1) * 100, 2
                ),
                "open_positions": dict(self._open_positions),
                "total_open": sum(self._open_positions.values()),
                "cooldowns": {
                    sym: max(0, int(until - time.monotonic()))
                    for sym, until in self._cooldown_until.items()
                },
                "trades_last_minute": len([
                    t for t in self._trade_timestamps
                    if t > time.monotonic() - 60
                ]),
                "pause_history": self._pause_history[-10:],
            }
