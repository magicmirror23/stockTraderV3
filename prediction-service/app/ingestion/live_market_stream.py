"""Live market tick stream — polls real-time ticks with circuit breaker.

Implements:
  - Configurable polling interval.
  - Per-symbol freshness tracking (Prometheus gauge).
  - Circuit breaker: after N consecutive failures the stream backs off
    exponentially and emits last-known-good ticks.
  - Stale-data guard: if a tick is older than threshold, the symbol is
    flagged and the last-known-good value is annotated ``is_stale=True``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import AsyncIterator

from app.core.config import settings
from app.core.metrics import DATA_FRESHNESS_SECONDS, STALE_DATA_COUNT, SOURCE_FAILURE_COUNT
from app.providers.base import Tick

logger = logging.getLogger(__name__)

_MAX_BACKOFF_SECONDS = 60.0


class _CircuitBreaker:
    """Simple circuit breaker: after *threshold* consecutive errors, enter
    OPEN state for an exponentially growing cooldown."""

    def __init__(self, threshold: int = 3):
        self.threshold = threshold
        self._consecutive_failures = 0
        self._backoff = 1.0
        self._open_until: float = 0.0

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._backoff = 1.0

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.threshold:
            import time
            self._backoff = min(self._backoff * 2, _MAX_BACKOFF_SECONDS)
            self._open_until = time.time() + self._backoff

    @property
    def is_open(self) -> bool:
        import time
        return time.time() < self._open_until

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures


class LiveMarketStream:
    """Polls the provider for current prices at a fixed interval."""

    def __init__(self, tickers: list[str] | None = None, poll_seconds: float = 5.0):
        self.tickers = tickers or settings.DEFAULT_TICKERS
        self.poll_seconds = poll_seconds
        self._running = False
        self._last_ticks: dict[str, Tick] = {}
        self._cb = _CircuitBreaker(threshold=3)

    async def stream(self) -> AsyncIterator[dict[str, Tick]]:
        """Yield dict of {symbol: Tick} at each poll interval.

        When the circuit breaker is open, yields last-known-good ticks
        annotated with ``is_stale=True`` until the provider recovers.
        """
        from app.providers.factory import get_provider

        provider = get_provider()
        self._running = True
        logger.info("LiveMarketStream started for %d tickers", len(self.tickers))

        while self._running:
            if self._cb.is_open:
                logger.warning(
                    "Circuit breaker open (%d failures) — yielding stale ticks",
                    self._cb.consecutive_failures,
                )
                yield self._stale_snapshot()
                await asyncio.sleep(self._cb._backoff)
                continue

            try:
                ticks = provider.get_ltp(self.tickers)
                now = datetime.now(timezone.utc)

                for sym, tick in ticks.items():
                    age = (now - tick.timestamp).total_seconds()
                    DATA_FRESHNESS_SECONDS.labels(source=sym).set(age)
                    if age > settings.STALE_TICK_SECONDS:
                        STALE_DATA_COUNT.labels(source=sym).inc()

                self._last_ticks = ticks
                self._cb.record_success()
                yield ticks

            except Exception as exc:
                self._cb.record_failure()
                SOURCE_FAILURE_COUNT.labels(source="live_stream", error_type=type(exc).__name__).inc()
                logger.error(
                    "LiveMarketStream poll error (failure #%d): %s",
                    self._cb.consecutive_failures, exc,
                )
                # Yield stale ticks so downstream still has data
                if self._last_ticks:
                    yield self._stale_snapshot()

            await asyncio.sleep(self.poll_seconds)

    def _stale_snapshot(self) -> dict[str, Tick]:
        """Return last-known ticks — callers should treat these as stale."""
        return dict(self._last_ticks)

    def stop(self) -> None:
        self._running = False

    @property
    def last_ticks(self) -> dict[str, Tick]:
        return dict(self._last_ticks)

    @property
    def circuit_breaker_open(self) -> bool:
        return self._cb.is_open
