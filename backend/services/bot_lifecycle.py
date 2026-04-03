"""Persistent bot lifecycle manager with state machine, crash recovery,
consent flow, and market-aware orchestration.

States:
    STOPPED → WAITING_FOR_MARKET → WAITING_FOR_CONSENT → ACTIVE → PAUSED → ...
    Any state can transition to ERROR or SAFE_MODE.
    Only explicit user action transitions to STOPPED.

This replaces the old TradingBot class in market.py with a production-grade
implementation that persists state across restarts.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class BotLifecycleState(str, Enum):
    STOPPED = "STOPPED"
    WAITING_FOR_MARKET = "WAITING_FOR_MARKET"
    WAITING_FOR_CONSENT = "WAITING_FOR_CONSENT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    SAFE_MODE = "SAFE_MODE"
    ERROR = "ERROR"


# Valid transitions
_TRANSITIONS: dict[BotLifecycleState, set[BotLifecycleState]] = {
    BotLifecycleState.STOPPED: {
        BotLifecycleState.WAITING_FOR_MARKET,
    },
    BotLifecycleState.WAITING_FOR_MARKET: {
        BotLifecycleState.WAITING_FOR_CONSENT,
        BotLifecycleState.ACTIVE,  # if market already open
        BotLifecycleState.STOPPED,
        BotLifecycleState.ERROR,
    },
    BotLifecycleState.WAITING_FOR_CONSENT: {
        BotLifecycleState.ACTIVE,
        BotLifecycleState.STOPPED,
        BotLifecycleState.WAITING_FOR_MARKET,
        BotLifecycleState.ERROR,
    },
    BotLifecycleState.ACTIVE: {
        BotLifecycleState.PAUSED,
        BotLifecycleState.WAITING_FOR_MARKET,
        BotLifecycleState.SAFE_MODE,
        BotLifecycleState.STOPPED,
        BotLifecycleState.ERROR,
    },
    BotLifecycleState.PAUSED: {
        BotLifecycleState.ACTIVE,
        BotLifecycleState.WAITING_FOR_MARKET,
        BotLifecycleState.STOPPED,
        BotLifecycleState.ERROR,
    },
    BotLifecycleState.SAFE_MODE: {
        BotLifecycleState.ACTIVE,
        BotLifecycleState.STOPPED,
        BotLifecycleState.ERROR,
    },
    BotLifecycleState.ERROR: {
        BotLifecycleState.WAITING_FOR_MARKET,
        BotLifecycleState.STOPPED,
    },
}


class BotConfig:
    """Bot trading configuration."""

    def __init__(self, **kwargs):
        self.watchlist: list[str] = kwargs.get(
            "watchlist", ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"]
        )
        self.min_confidence: float = kwargs.get("min_confidence", 0.7)
        self.max_positions: int = kwargs.get("max_positions", 5)
        self.position_size_pct: float = kwargs.get("position_size_pct", 0.10)
        self.stop_loss_pct: float = kwargs.get("stop_loss_pct", 0.02)
        self.take_profit_pct: float = kwargs.get("take_profit_pct", 0.05)
        self.cycle_interval: int = kwargs.get("cycle_interval", 60)
        self.consent_timeout: int = kwargs.get("consent_timeout", 300)  # 5 min
        self.auto_resume: bool = kwargs.get("auto_resume", True)
        self.strategy_mode: str = kwargs.get("strategy_mode", "auto")  # auto/equity/options/both
        self.kill_switches: dict[str, bool] = kwargs.get("kill_switches", {})

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d: dict) -> BotConfig:
        return cls(**d)


class BotLifecycleManager:
    """Persistent, crash-recoverable bot lifecycle manager.

    - Persists state in DB (survives restarts)
    - Emits events via EventBus
    - Manages market-aware consent flow
    - Delegates trading to the existing TradingBot logic
    """

    _instance: BotLifecycleManager | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._state = BotLifecycleState.STOPPED
        self._config = BotConfig()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._error_message: str | None = None
        self._consent_requested_at: float | None = None
        self._heartbeat_interval = 10  # seconds
        self._last_heartbeat: float = 0
        # Trading state (delegated)
        self._trading_engine: Any = None
        self.trades_today: list[dict] = []
        self.positions: dict[str, dict] = {}
        self.total_pnl: float = 0.0
        self.total_charges: float = 0.0
        self.cycle_count: int = 0
        self.last_cycle: str | None = None
        self.errors: list[str] = []
        self._available_balance: float = 0.0
        self._total_equity: float = 0.0
        self._risk_mgr: Any = None
        self._adapter: Any = None
        # Try to recover state from DB
        self._recover_state()

    def _recover_state(self) -> None:
        """Recover bot state from DB on startup (crash recovery)."""
        try:
            from backend.db.session import SessionLocal
            from backend.db.models import BotState

            db = SessionLocal()
            try:
                row = db.query(BotState).first()
                if row and row.state != "STOPPED":
                    prev = row.state
                    # If we were ACTIVE/WAITING, transition to WAITING_FOR_MARKET
                    if prev in ("ACTIVE", "WAITING_FOR_CONSENT", "PAUSED"):
                        self._state = BotLifecycleState.WAITING_FOR_MARKET
                        logger.info("Bot crash recovery: %s → WAITING_FOR_MARKET", prev)
                    elif prev == "WAITING_FOR_MARKET":
                        self._state = BotLifecycleState.WAITING_FOR_MARKET
                    else:
                        self._state = BotLifecycleState.STOPPED

                    if row.config_json:
                        self._config = BotConfig.from_dict(json.loads(row.config_json))

                    # Auto-restart the lifecycle loop
                    if self._state == BotLifecycleState.WAITING_FOR_MARKET:
                        self._start_loop()
                        self._log_transition(
                            BotLifecycleState(prev),
                            self._state,
                            "crash_recovery",
                        )
            finally:
                db.close()
        except Exception as exc:
            logger.debug("Bot state recovery skipped: %s", exc)

    def _persist_state(self) -> None:
        """Save current state to DB."""
        try:
            from backend.db.session import SessionLocal
            from backend.db.models import BotState

            db = SessionLocal()
            try:
                row = db.query(BotState).first()
                if not row:
                    row = BotState(state=self._state.value)
                    db.add(row)
                else:
                    row.previous_state = row.state
                    row.state = self._state.value

                row.config_json = json.dumps(self._config.to_dict())
                row.error_message = self._error_message
                row.consent_requested_at = (
                    datetime.fromtimestamp(self._consent_requested_at, tz=timezone.utc)
                    if self._consent_requested_at
                    else None
                )
                row.consent_timeout_seconds = self._config.consent_timeout
                row.last_heartbeat = datetime.now(timezone.utc)
                row.updated_at = datetime.now(timezone.utc)

                if self._state == BotLifecycleState.ACTIVE and not row.started_at:
                    row.started_at = datetime.now(timezone.utc)
                if self._state == BotLifecycleState.STOPPED:
                    row.started_at = None

                db.commit()
            finally:
                db.close()
        except Exception as exc:
            logger.debug("Bot state persistence failed: %s", exc)

    def _log_transition(
        self,
        from_state: BotLifecycleState | None,
        to_state: BotLifecycleState,
        reason: str,
        data: dict | None = None,
    ) -> None:
        """Persist state transition and emit event."""
        try:
            from backend.db.session import SessionLocal
            from backend.db.models import BotStateTransition

            db = SessionLocal()
            try:
                t = BotStateTransition(
                    from_state=from_state.value if from_state else None,
                    to_state=to_state.value,
                    reason=reason,
                    data_json=json.dumps(data) if data else None,
                )
                db.add(t)
                db.commit()
            finally:
                db.close()
        except Exception:
            pass

        # Emit event
        try:
            from backend.services.event_bus import get_event_bus, Event, EventType
            bus = get_event_bus()
            bus.publish(Event(
                EventType.BOT_STATE_CHANGED,
                {
                    "from": from_state.value if from_state else None,
                    "to": to_state.value,
                    "reason": reason,
                },
                source="bot_lifecycle",
            ))
        except Exception:
            pass

    def _transition(self, new_state: BotLifecycleState, reason: str) -> bool:
        """Attempt a state transition. Returns True if successful."""
        if new_state == self._state:
            return True

        allowed = _TRANSITIONS.get(self._state, set())
        if new_state not in allowed:
            logger.warning(
                "Invalid bot transition: %s → %s (reason: %s)",
                self._state.value, new_state.value, reason,
            )
            return False

        old = self._state
        self._state = new_state
        self._persist_state()
        self._log_transition(old, new_state, reason)
        logger.info("Bot: %s → %s (%s)", old.value, new_state.value, reason)
        return True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def state(self) -> BotLifecycleState:
        return self._state

    @property
    def config(self) -> BotConfig:
        return self._config

    def start(self, config: dict | None = None) -> dict:
        """Start the bot. Transitions STOPPED → WAITING_FOR_MARKET."""
        if self._state not in (BotLifecycleState.STOPPED, BotLifecycleState.ERROR):
            return {
                "status": "already_running",
                "state": self._state.value,
                "message": f"Bot is in {self._state.value} state",
            }

        if config:
            self._config = BotConfig(**{**self._config.to_dict(), **config})

        # Reset trading state
        self.trades_today = []
        self.positions = {}
        self.total_pnl = 0.0
        self.total_charges = 0.0
        self.cycle_count = 0
        self.errors = []
        self._error_message = None
        self._risk_mgr = None
        self._adapter = None

        # Initialize balance
        self._refresh_balance()

        # Check if market is currently open
        from backend.services.market_hours import get_market_status
        market = get_market_status()
        is_open = market.phase.value in ("open", "pre_open")

        if is_open:
            # Market open — go to consent first
            self._transition(BotLifecycleState.WAITING_FOR_MARKET, "start_requested")
            self._transition(BotLifecycleState.WAITING_FOR_CONSENT, "market_already_open")
            self._consent_requested_at = time.time()
        else:
            self._transition(BotLifecycleState.WAITING_FOR_MARKET, "start_requested")

        self._start_loop()

        return {
            "status": "started",
            "state": self._state.value,
            "config": self._config.to_dict(),
        }

    def stop(self) -> dict:
        """Explicitly stop the bot. Only way to reach STOPPED."""
        old = self._state
        self._stop_event.set()
        self._state = BotLifecycleState.STOPPED
        self._consent_requested_at = None
        self._persist_state()
        self._log_transition(old, BotLifecycleState.STOPPED, "user_stopped")

        return {
            "status": "stopped",
            "state": "STOPPED",
            "cycles": self.cycle_count,
            "total_pnl": round(self.total_pnl, 2),
            "trades": len(self.trades_today),
        }

    def pause(self) -> dict:
        """Pause trading (positions kept, no new trades)."""
        if self._state != BotLifecycleState.ACTIVE:
            return {"status": "error", "message": f"Cannot pause from {self._state.value}"}
        self._transition(BotLifecycleState.PAUSED, "user_paused")
        return {"status": "paused", "state": "PAUSED"}

    def resume(self) -> dict:
        """Resume from PAUSED state."""
        if self._state != BotLifecycleState.PAUSED:
            return {"status": "error", "message": f"Cannot resume from {self._state.value}"}
        self._transition(BotLifecycleState.ACTIVE, "user_resumed")
        return {"status": "resumed", "state": "ACTIVE"}

    def grant_consent(self) -> dict:
        """User grants consent to start trading."""
        if self._state != BotLifecycleState.WAITING_FOR_CONSENT:
            return {"status": "no_consent_needed", "state": self._state.value}

        self._consent_requested_at = None
        self._transition(BotLifecycleState.ACTIVE, "user_consent_granted")
        return {"status": "active", "state": "ACTIVE", "message": "Trading started with user consent"}

    def decline_consent(self) -> dict:
        """User declines consent — stop the bot."""
        if self._state != BotLifecycleState.WAITING_FOR_CONSENT:
            return {"status": "no_consent_needed", "state": self._state.value}
        self._consent_requested_at = None
        return self.stop()

    def enter_safe_mode(self, reason: str) -> None:
        """Enter safe mode on downstream failure."""
        if self._state in (BotLifecycleState.ACTIVE, BotLifecycleState.PAUSED):
            self._transition(BotLifecycleState.SAFE_MODE, f"safe_mode: {reason}")
            self._error_message = reason

    def update_config(self, config: dict) -> dict:
        """Update config without restart."""
        for key, val in config.items():
            if hasattr(self._config, key):
                setattr(self._config, key, val)
        self._persist_state()
        return {"status": "updated", "config": self._config.to_dict()}

    @property
    def status(self) -> dict:
        risk = self._risk_mgr.status if self._risk_mgr else {}
        consent_countdown = None
        if (
            self._state == BotLifecycleState.WAITING_FOR_CONSENT
            and self._consent_requested_at
        ):
            elapsed = time.time() - self._consent_requested_at
            consent_countdown = max(0, int(self._config.consent_timeout - elapsed))

        return {
            "state": self._state.value,
            "config": self._config.to_dict(),
            "consent_countdown": consent_countdown,
            "cycle_count": self.cycle_count,
            "last_cycle": self.last_cycle,
            "available_balance": round(self._available_balance, 2),
            "total_equity": round(self._total_equity, 2),
            "active_positions": len(self.positions),
            "positions": self.positions,
            "trades_today": self.trades_today[-30:],
            "total_pnl": round(self.total_pnl, 2),
            "total_charges": round(self.total_charges, 2),
            "net_pnl": round(self.total_pnl - self.total_charges, 2),
            "risk": risk,
            "errors": self.errors[-10:],
            "error_message": self._error_message,
        }

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    def _start_loop(self) -> None:
        """Start the background lifecycle loop."""
        self._stop_event.clear()
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._lifecycle_loop, daemon=True)
        self._thread.start()

    def _lifecycle_loop(self) -> None:
        """Main lifecycle loop — never exits unless STOPPED."""
        while not self._stop_event.is_set():
            try:
                self._heartbeat()

                if self._state == BotLifecycleState.STOPPED:
                    break

                if self._state == BotLifecycleState.WAITING_FOR_MARKET:
                    self._handle_waiting_for_market()

                elif self._state == BotLifecycleState.WAITING_FOR_CONSENT:
                    self._handle_waiting_for_consent()

                elif self._state == BotLifecycleState.ACTIVE:
                    self._run_trading_cycle()

                elif self._state == BotLifecycleState.PAUSED:
                    # Check if market closed while paused
                    self._check_market_close()

                elif self._state == BotLifecycleState.SAFE_MODE:
                    self._handle_safe_mode()

                elif self._state == BotLifecycleState.ERROR:
                    # Wait for user intervention or auto-recover
                    self._stop_event.wait(30)
                    continue

            except Exception as exc:
                msg = f"Lifecycle error: {exc}"
                logger.exception(msg)
                self.errors.append(msg)
                self._error_message = str(exc)
                self._transition(BotLifecycleState.ERROR, f"exception: {exc}")

            # Sleep based on state
            if self._state == BotLifecycleState.ACTIVE:
                self._stop_event.wait(self._config.cycle_interval)
            elif self._state in (
                BotLifecycleState.WAITING_FOR_MARKET,
                BotLifecycleState.WAITING_FOR_CONSENT,
            ):
                self._stop_event.wait(5)
            else:
                self._stop_event.wait(15)

    def _heartbeat(self) -> None:
        """Periodic heartbeat for liveness detection."""
        now = time.time()
        if now - self._last_heartbeat > self._heartbeat_interval:
            self._last_heartbeat = now
            self._persist_state()

    def _handle_waiting_for_market(self) -> None:
        """Wait until market opens, then request consent."""
        from backend.services.market_hours import get_market_status
        market = get_market_status()
        is_open = market.phase.value in ("open", "pre_open")

        if is_open:
            self._consent_requested_at = time.time()
            self._transition(
                BotLifecycleState.WAITING_FOR_CONSENT, "market_opened"
            )
            # Emit consent request event
            try:
                from backend.services.event_bus import get_event_bus, Event, EventType
                bus = get_event_bus()
                bus.publish(Event(
                    EventType.BOT_CONSENT_REQUESTED,
                    {"timeout_seconds": self._config.consent_timeout},
                    source="bot_lifecycle",
                ))
            except Exception:
                pass

    def _handle_waiting_for_consent(self) -> None:
        """Wait for user consent or auto-resume after timeout."""
        if not self._consent_requested_at:
            self._consent_requested_at = time.time()

        elapsed = time.time() - self._consent_requested_at
        if elapsed >= self._config.consent_timeout and self._config.auto_resume:
            logger.info(
                "Auto-resuming bot after %d seconds (no user response)",
                self._config.consent_timeout,
            )
            self._consent_requested_at = None
            self._transition(BotLifecycleState.ACTIVE, "consent_timeout_auto_resume")
            # Emit event
            try:
                from backend.services.event_bus import get_event_bus, Event, EventType
                bus = get_event_bus()
                bus.publish(Event(
                    EventType.BOT_CONSENT_TIMEOUT,
                    {"action": "auto_resume"},
                    source="bot_lifecycle",
                ))
            except Exception:
                pass

    def _check_market_close(self) -> None:
        """Check if market has closed — transition to WAITING_FOR_MARKET."""
        from backend.services.market_hours import get_market_status
        market = get_market_status()
        is_open = market.phase.value in ("open", "pre_open")
        if not is_open and self._state in (
            BotLifecycleState.ACTIVE,
            BotLifecycleState.PAUSED,
        ):
            # Reset daily P&L for risk manager
            if self._risk_mgr:
                self._risk_mgr.reset_daily()
            self._transition(BotLifecycleState.WAITING_FOR_MARKET, "market_closed")

    def _handle_safe_mode(self) -> None:
        """In safe mode: no trading, just monitor. Auto-recover if dependency restored."""
        # Check if we can exit safe mode
        try:
            adapter = self._get_adapter()
            adapter.get_balance()
            # If balance fetch works, dependencies are back
            self._transition(BotLifecycleState.ACTIVE, "safe_mode_auto_recovery")
            self._error_message = None
        except Exception:
            pass  # Stay in safe mode

    def _run_trading_cycle(self) -> None:
        """Single trading cycle: predict → risk → trade → manage exits."""
        from backend.services.market_hours import get_market_status

        # Check market close first
        market = get_market_status()
        is_open = market.phase.value in ("open", "pre_open")
        if not is_open:
            self._check_market_close()
            return

        self.cycle_count += 1
        self.last_cycle = datetime.now(timezone.utc).isoformat()

        try:
            from backend.services.model_manager import ModelManager
            from backend.services.brokerage_calculator import (
                estimate_breakeven_move, net_pnl_after_charges, TradeType,
            )

            adapter = self._get_adapter()
            mgr = ModelManager()
            risk = self._get_risk_manager()
            risk.tick_cycle()
            self._refresh_balance()

            # --- Check exits on existing positions ---
            for ticker in list(self.positions.keys()):
                self._check_exit(ticker, adapter)

            # --- New entries ---
            for ticker in self._config.watchlist:
                # Kill switch check
                if self._config.kill_switches.get(ticker, False):
                    continue

                if len(self.positions) >= self._config.max_positions:
                    break
                if ticker in self.positions:
                    continue

                try:
                    prediction = mgr.predict(ticker, horizon_days=1)
                    if prediction is None:
                        continue

                    action = prediction.get("action", "hold")
                    confidence = prediction.get("confidence", 0)

                    if action == "hold" or confidence < self._config.min_confidence:
                        # Log skip reason for "why not trade"
                        self._log_skip(ticker, action, confidence,
                                       "low_confidence" if confidence < self._config.min_confidence else "hold_signal")
                        continue

                    price = prediction.get("predicted_price", 100)
                    if price <= 0:
                        continue

                    max_trade_value = self._available_balance * self._config.position_size_pct
                    if max_trade_value < price:
                        self._log_skip(ticker, action, confidence, "insufficient_balance")
                        continue
                    qty = max(1, int(max_trade_value / price))

                    breakeven_move = estimate_breakeven_move(price, qty, TradeType.INTRADAY)
                    expected_profit = price * prediction.get("expected_return", 0.02)
                    if expected_profit < breakeven_move:
                        self._log_skip(ticker, action, confidence, "below_breakeven")
                        continue

                    allowed, reason = risk.can_open_position(ticker, price, qty)
                    if not allowed:
                        self._log_skip(ticker, action, confidence, f"risk_blocked: {reason}")
                        continue

                    side = "buy" if action == "buy" else "sell"
                    intent = {
                        "ticker": ticker,
                        "side": side,
                        "quantity": qty,
                        "order_type": "market",
                        "current_price": price,
                    }

                    result = adapter.place_order(intent)
                    filled_price = result.get("filled_price", price)

                    risk.register_entry(ticker, side, filled_price, qty)

                    self.positions[ticker] = {
                        "side": side,
                        "quantity": qty,
                        "entry_price": filled_price,
                        "current_price": filled_price,
                        "pnl": 0.0,
                        "net_pnl": 0.0,
                        "confidence": confidence,
                        "strategy": prediction.get("strategy", "momentum"),
                        "regime": prediction.get("regime", "unknown"),
                        "entered_at": datetime.now(timezone.utc).isoformat(),
                    }

                    trade_record = {
                        "ticker": ticker,
                        "action": "ENTRY",
                        "side": side,
                        "quantity": qty,
                        "price": filled_price,
                        "confidence": confidence,
                        "reason": f"signal={action}, conf={confidence:.2f}",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    self.trades_today.append(trade_record)

                    # Emit event
                    self._emit_trade_event("ENTRY", trade_record)

                except Exception as exc:
                    self.errors.append(f"Predict/trade {ticker}: {exc}")

        except Exception as exc:
            self.errors.append(f"Cycle error: {exc}")
            logger.exception("Trading cycle error")
            # If repeated failures, enter safe mode
            recent_errors = [e for e in self.errors[-5:] if "Cycle error" in e]
            if len(recent_errors) >= 3:
                self.enter_safe_mode("repeated_cycle_failures")

    def _check_exit(self, ticker: str, adapter: Any) -> None:
        """Check exit conditions for a position."""
        from backend.services.brokerage_calculator import net_pnl_after_charges, TradeType

        pos = self.positions.get(ticker)
        if not pos:
            return

        try:
            ltp_data = adapter.get_ltp(ticker)
            current = ltp_data.get("ltp", pos["entry_price"])
        except Exception:
            current = pos.get("current_price", pos["entry_price"])

        pos["current_price"] = round(current, 2)
        entry = pos["entry_price"]
        qty = pos["quantity"]

        if pos["side"] == "buy":
            gross_pnl = (current - entry) * qty
            pnl_pct = (current - entry) / entry if entry else 0
        else:
            gross_pnl = (entry - current) * qty
            pnl_pct = (entry - current) / entry if entry else 0

        if pos["side"] == "buy":
            net_pnl = net_pnl_after_charges(entry, current, qty, TradeType.INTRADAY)
        else:
            net_pnl = net_pnl_after_charges(current, entry, qty, TradeType.INTRADAY)

        pos["pnl"] = round(gross_pnl, 2)
        pos["net_pnl"] = round(net_pnl, 2)

        risk = self._get_risk_manager()
        exit_reason = None

        should_trail, trail_reason = risk.check_exit(ticker, current)
        if should_trail:
            exit_reason = trail_reason
        if exit_reason is None and pnl_pct <= -self._config.stop_loss_pct:
            exit_reason = "STOP_LOSS"
        if exit_reason is None and pnl_pct >= self._config.take_profit_pct:
            exit_reason = "TAKE_PROFIT"

        if exit_reason:
            exit_side = "sell" if pos["side"] == "buy" else "buy"
            adapter.place_order({
                "ticker": ticker,
                "side": exit_side,
                "quantity": qty,
                "order_type": "market",
                "current_price": current,
            })

            charges = gross_pnl - net_pnl
            self.total_pnl += gross_pnl
            self.total_charges += charges
            risk.register_exit(ticker, net_pnl, exit_reason)

            trade_record = {
                "ticker": ticker,
                "action": exit_reason,
                "side": exit_side,
                "quantity": qty,
                "price": round(current, 2),
                "gross_pnl": round(gross_pnl, 2),
                "charges": round(charges, 2),
                "net_pnl": round(net_pnl, 2),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self.trades_today.append(trade_record)
            self._emit_trade_event(exit_reason, trade_record)

            # Journal the trade
            self._journal_trade(pos, exit_reason, current, gross_pnl, net_pnl)

            del self.positions[ticker]

    def _log_skip(self, ticker: str, action: str, confidence: float, reason: str) -> None:
        """Log why a signal was skipped (for 'why not trade' explanations)."""
        try:
            from backend.db.session import SessionLocal
            from backend.db.models import TradeJournal

            db = SessionLocal()
            try:
                j = TradeJournal(
                    ticker=ticker,
                    side=action,
                    entry_price=0,
                    quantity=0,
                    confidence=confidence,
                    skip_reason=reason,
                )
                db.add(j)
                db.commit()
            finally:
                db.close()
        except Exception:
            pass

    def _journal_trade(
        self, pos: dict, exit_reason: str, exit_price: float,
        gross_pnl: float, net_pnl: float,
    ) -> None:
        """Record completed trade in the journal with mistake tagging."""
        try:
            from backend.db.session import SessionLocal
            from backend.db.models import TradeJournal

            mistakes = []
            if exit_reason == "STOP_LOSS" and pos.get("confidence", 0) > 0.8:
                mistakes.append("high_confidence_loss")
            if abs(net_pnl) < 50 and exit_reason == "TAKE_PROFIT":
                mistakes.append("tiny_profit_exit")

            db = SessionLocal()
            try:
                j = TradeJournal(
                    ticker=pos.get("ticker", pos.get("side", "")),
                    side=pos["side"],
                    entry_price=pos["entry_price"],
                    exit_price=exit_price,
                    quantity=pos["quantity"],
                    gross_pnl=gross_pnl,
                    net_pnl=net_pnl,
                    strategy_used=pos.get("strategy"),
                    regime=pos.get("regime"),
                    confidence=pos.get("confidence"),
                    exit_reason=exit_reason,
                    mistake_tags=json.dumps(mistakes) if mistakes else None,
                    entered_at=datetime.fromisoformat(pos["entered_at"]) if pos.get("entered_at") else None,
                    exited_at=datetime.now(timezone.utc),
                )
                db.add(j)
                db.commit()
            finally:
                db.close()
        except Exception as exc:
            logger.debug("Journal write failed: %s", exc)

    def _emit_trade_event(self, action: str, trade: dict) -> None:
        """Emit trade event via EventBus."""
        try:
            from backend.services.event_bus import get_event_bus, Event, EventType
            bus = get_event_bus()
            et = EventType.TRADE_EXECUTED if action == "ENTRY" else EventType.TRADE_EXITED
            bus.publish(Event(et, trade, source="bot_lifecycle"))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Helpers (same as old TradingBot)
    # ------------------------------------------------------------------

    def _get_risk_manager(self):
        if self._risk_mgr is None:
            from backend.services.risk_manager import RiskManager, RiskConfig
            config = RiskConfig(
                max_position_pct=self._config.position_size_pct,
                max_daily_loss=5_000.0,
                max_daily_loss_pct=0.02,
                trailing_stop_pct=0.015,
                min_risk_reward_ratio=2.0,
                max_open_positions=self._config.max_positions,
                cooldown_after_loss=2,
            )
            capital = self._available_balance or 100_000.0
            self._risk_mgr = RiskManager(capital, config)
        return self._risk_mgr

    def _get_adapter(self):
        if self._adapter is None:
            from backend.trading_engine.angel_adapter import get_adapter
            self._adapter = get_adapter()
        return self._adapter

    def _refresh_balance(self) -> None:
        try:
            adapter = self._get_adapter()
            bal = adapter.get_balance()
            self._available_balance = bal.get("available_cash", 0)
            self._total_equity = bal.get("total_equity", self._available_balance)
            if self._risk_mgr:
                self._risk_mgr.update_capital(self._available_balance)
        except Exception as exc:
            logger.warning("Balance refresh failed: %s", exc)


def get_bot_manager() -> BotLifecycleManager:
    """Singleton accessor for the bot lifecycle manager."""
    if BotLifecycleManager._instance is None:
        with BotLifecycleManager._lock:
            if BotLifecycleManager._instance is None:
                BotLifecycleManager._instance = BotLifecycleManager()
    return BotLifecycleManager._instance
