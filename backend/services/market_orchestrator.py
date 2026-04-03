"""Market session orchestrator — upgrades market_hours into an active scheduler.

Emits events: market.opening_soon, market.opened, market.closed
Integrates with BotLifecycleManager for consent flow.
Supports dry-run testing mode for simulated market sessions.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.services.market_hours import (
    IST,
    MARKET_CLOSE,
    MARKET_OPEN,
    POST_CLOSE_END,
    PRE_OPEN_START,
    MarketPhase,
    get_market_status,
)

logger = logging.getLogger(__name__)


class MarketOrchestrator:
    """Active market session orchestrator that emits lifecycle events.

    Runs a background thread that monitors market sessions and emits events
    at key transitions. Integrates with the EventBus.
    """

    _instance: MarketOrchestrator | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._poll_interval = 5  # seconds
        self._last_phase: str | None = None
        self._opening_soon_emitted = False
        self._opened_emitted = False
        self._closed_emitted = False
        # Dry-run / testing mode
        self._dry_run = False
        self._simulated_phase: MarketPhase | None = None
        self._listeners: list[Any] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the orchestrator background loop."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="market-orchestrator")
        self._thread.start()
        logger.info("MarketOrchestrator started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("MarketOrchestrator stopped")

    def enable_dry_run(self, phase: str = "open") -> dict:
        """Enable test mode with a simulated market phase."""
        self._dry_run = True
        self._simulated_phase = MarketPhase(phase) if phase in [p.value for p in MarketPhase] else MarketPhase.OPEN
        logger.info("Dry-run mode enabled: phase=%s", self._simulated_phase.value)
        return {"dry_run": True, "simulated_phase": self._simulated_phase.value}

    def disable_dry_run(self) -> dict:
        self._dry_run = False
        self._simulated_phase = None
        return {"dry_run": False}

    def simulate_transition(self, phase: str) -> dict:
        """Force a phase transition in dry-run mode for testing."""
        if not self._dry_run:
            return {"error": "dry_run not enabled"}
        old = self._simulated_phase
        self._simulated_phase = MarketPhase(phase) if phase in [p.value for p in MarketPhase] else None
        if self._simulated_phase:
            self._emit_phase_change(old, self._simulated_phase)
            return {"old_phase": old.value if old else None, "new_phase": self._simulated_phase.value}
        return {"error": "invalid phase"}

    def get_session_info(self) -> dict:
        """Return enriched session info with orchestrator state."""
        ms = get_market_status()
        now = datetime.now(IST)
        today_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
        today_close = now.replace(hour=15, minute=30, second=0, microsecond=0)

        return {
            "phase": self._simulated_phase.value if self._dry_run and self._simulated_phase else ms.phase.value,
            "message": ms.message,
            "ist_now": ms.ist_now,
            "next_event": ms.next_event,
            "next_event_time": ms.next_event_time,
            "seconds_to_next": ms.seconds_to_next,
            "is_trading_day": ms.is_trading_day,
            "session_open": today_open.strftime("%H:%M IST"),
            "session_close": today_close.strftime("%H:%M IST"),
            "dry_run": self._dry_run,
            "orchestrator_running": self._thread is not None and self._thread.is_alive(),
        }

    def is_market_open(self) -> bool:
        """Check if market is currently open (respects dry-run)."""
        if self._dry_run and self._simulated_phase:
            return self._simulated_phase in (MarketPhase.OPEN, MarketPhase.PRE_OPEN)
        ms = get_market_status()
        return ms.phase in (MarketPhase.OPEN, MarketPhase.PRE_OPEN)

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as exc:
                logger.exception("MarketOrchestrator tick error: %s", exc)
            self._stop_event.wait(self._poll_interval)

    def _tick(self) -> None:
        ms = get_market_status()
        current_phase = self._simulated_phase.value if (self._dry_run and self._simulated_phase) else ms.phase.value

        # Detect phase change
        if self._last_phase and self._last_phase != current_phase:
            old_p = MarketPhase(self._last_phase)
            new_p = MarketPhase(current_phase)
            self._emit_phase_change(old_p, new_p)
            # Reset flags on phase transitions
            if current_phase == "open":
                self._closed_emitted = False
            elif current_phase in ("closed", "weekend", "holiday", "post_close"):
                self._opened_emitted = False
                self._opening_soon_emitted = False

        # Emit opening_soon (5 min before pre-open, i.e., 8:55 IST)
        if not self._opening_soon_emitted and ms.is_trading_day and current_phase == "closed":
            if 0 < ms.seconds_to_next <= 600:  # within 10 minutes of next event
                self._emit_event("market.opening_soon", {
                    "seconds_to_open": ms.seconds_to_next,
                    "next_event": ms.next_event,
                })
                self._opening_soon_emitted = True

        # Emit market.opened
        if not self._opened_emitted and current_phase == "open":
            self._emit_event("market.opened", {"phase": "open"})
            self._opened_emitted = True

        # Emit market.closed
        if not self._closed_emitted and current_phase in ("post_close", "closed") and self._last_phase == "open":
            self._emit_event("market.closed", {"phase": current_phase})
            self._closed_emitted = True

        self._last_phase = current_phase

    def _emit_phase_change(self, old_phase: MarketPhase | None, new_phase: MarketPhase) -> None:
        payload = {
            "from_phase": old_phase.value if old_phase else None,
            "to_phase": new_phase.value,
        }
        if new_phase == MarketPhase.OPEN:
            self._emit_event("market.opened", payload)
        elif new_phase in (MarketPhase.CLOSED, MarketPhase.POST_CLOSE, MarketPhase.WEEKEND, MarketPhase.HOLIDAY):
            self._emit_event("market.closed", payload)

    def _emit_event(self, event_type: str, payload: dict) -> None:
        try:
            from backend.services.event_bus import Event, get_event_bus
            bus = get_event_bus()
            bus.publish(Event(event_type, payload, source="market_orchestrator"))
        except Exception as exc:
            logger.debug("Event emission failed: %s", exc)


def get_market_orchestrator() -> MarketOrchestrator:
    """Singleton accessor."""
    if MarketOrchestrator._instance is None:
        with MarketOrchestrator._lock:
            if MarketOrchestrator._instance is None:
                MarketOrchestrator._instance = MarketOrchestrator()
    return MarketOrchestrator._instance
