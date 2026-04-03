"""In-process event bus with Redis pub/sub backend and DB persistence.

Provides decoupled event-driven communication between services.
Falls back to in-memory dispatch when Redis is unavailable.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------

class EventType:
    # Market
    MARKET_OPENING_SOON = "market.opening_soon"
    MARKET_OPENED = "market.opened"
    MARKET_CLOSED = "market.closed"
    MARKET_TICK = "market.tick"

    # Bot lifecycle
    BOT_STATE_CHANGED = "bot.state.changed"
    BOT_CONSENT_REQUESTED = "bot.consent.requested"
    BOT_CONSENT_GRANTED = "bot.consent.granted"
    BOT_CONSENT_TIMEOUT = "bot.consent.timeout"
    BOT_ERROR = "bot.error"

    # Prediction pipeline
    FEATURE_READY = "feature.ready"
    PREDICTION_READY = "prediction.ready"
    PREDICTION_EXPLANATION = "prediction.explanation"

    # Risk
    RISK_CHECKED = "risk.checked"
    RISK_BREACH = "risk.breach"
    RISK_CIRCUIT_BREAKER = "risk.circuit_breaker"

    # Trading
    TRADE_INTENT_CREATED = "trade.intent.created"
    TRADE_EXECUTED = "trade.executed"
    TRADE_REJECTED = "trade.rejected"
    TRADE_EXITED = "trade.exited"

    # Model
    MODEL_PROMOTED = "model.promoted"
    MODEL_DRIFT_DETECTED = "model.drift.detected"
    MODEL_RETRAIN_STARTED = "model.retrain.started"
    MODEL_RETRAIN_COMPLETED = "model.retrain.completed"

    # Anomaly / Sentiment
    ANOMALY_DETECTED = "anomaly.detected"
    SENTIMENT_UPDATE = "sentiment.update"

    # Strategy
    STRATEGY_SELECTED = "strategy.selected"
    STRATEGY_SKIP = "strategy.skip"


class Event:
    """Immutable event envelope."""

    __slots__ = ("event_type", "payload", "correlation_id", "source", "timestamp", "event_id")

    def __init__(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        source: str | None = None,
    ):
        self.event_id = str(uuid.uuid4())
        self.event_type = event_type
        self.payload = payload or {}
        self.correlation_id = correlation_id or str(uuid.uuid4())
        self.source = source or "unknown"
        self.timestamp = datetime.utcnow().isoformat()

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "payload": self.payload,
            "correlation_id": self.correlation_id,
            "source": self.source,
            "timestamp": self.timestamp,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, d: dict) -> Event:
        e = cls(
            event_type=d["event_type"],
            payload=d.get("payload", {}),
            correlation_id=d.get("correlation_id"),
            source=d.get("source"),
        )
        e.event_id = d.get("event_id", e.event_id)
        e.timestamp = d.get("timestamp", e.timestamp)
        return e


# ---------------------------------------------------------------------------
# Subscriber = Callable[[Event], None]
# ---------------------------------------------------------------------------
Subscriber = Callable[[Event], None]


class EventBus:
    """Thread-safe event bus with optional Redis backend.

    Usage:
        bus = get_event_bus()
        bus.subscribe("market.opened", my_handler)
        bus.publish(Event("market.opened", {"phase": "open"}))
    """

    _instance: EventBus | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Subscriber]] = {}
        self._wildcard_subscribers: list[Subscriber] = []
        self._redis = None
        self._redis_thread: threading.Thread | None = None
        self._persist = True  # persist events to DB
        self._lock_local = threading.Lock()
        self._init_redis()

    def _init_redis(self) -> None:
        """Try to connect to Redis for cross-process pub/sub."""
        try:
            import redis as redis_lib
            import os
            url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            self._redis = redis_lib.Redis.from_url(url, decode_responses=True)
            self._redis.ping()
            logger.info("EventBus connected to Redis at %s", url)
            # Start listener thread
            self._redis_thread = threading.Thread(
                target=self._redis_listener, daemon=True
            )
            self._redis_thread.start()
        except Exception:
            self._redis = None
            logger.info("EventBus using in-memory mode (Redis unavailable)")

    def _redis_listener(self) -> None:
        """Background thread that listens for Redis pub/sub messages."""
        if not self._redis:
            return
        try:
            pubsub = self._redis.pubsub()
            pubsub.psubscribe("stocktrader:events:*")
            for message in pubsub.listen():
                if message["type"] == "pmessage":
                    try:
                        data = json.loads(message["data"])
                        event = Event.from_dict(data)
                        self._dispatch_local(event, from_redis=True)
                    except Exception as exc:
                        logger.warning("Redis event parse error: %s", exc)
        except Exception as exc:
            logger.warning("Redis listener stopped: %s", exc)

    def subscribe(self, event_type: str, handler: Subscriber) -> None:
        """Subscribe to a specific event type."""
        with self._lock_local:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            self._subscribers[event_type].append(handler)

    def subscribe_all(self, handler: Subscriber) -> None:
        """Subscribe to all events (wildcard)."""
        with self._lock_local:
            self._wildcard_subscribers.append(handler)

    def publish(self, event: Event) -> None:
        """Publish an event to all subscribers and optionally to Redis + DB."""
        # Persist to DB (fire-and-forget)
        if self._persist:
            self._persist_event(event)

        # Publish to Redis if available
        if self._redis:
            try:
                channel = f"stocktrader:events:{event.event_type}"
                self._redis.publish(channel, event.to_json())
                return  # Redis listener will dispatch locally
            except Exception:
                pass  # Fall through to local dispatch

        # Local dispatch
        self._dispatch_local(event, from_redis=False)

    def _dispatch_local(self, event: Event, from_redis: bool = False) -> None:
        """Dispatch event to local subscribers with error isolation."""
        with self._lock_local:
            handlers = list(self._subscribers.get(event.event_type, []))
            wildcards = list(self._wildcard_subscribers)

        for handler in handlers + wildcards:
            try:
                handler(event)
            except Exception as exc:
                logger.error(
                    "Event handler error [%s -> %s]: %s",
                    event.event_type, handler.__name__, exc,
                )

    def _persist_event(self, event: Event) -> None:
        """Persist event to DB for audit trail / DLQ replay."""
        try:
            from backend.db.session import SessionLocal
            from backend.db.models import SystemEvent

            db = SessionLocal()
            try:
                db_event = SystemEvent(
                    event_type=event.event_type,
                    payload_json=json.dumps(event.payload),
                    correlation_id=event.correlation_id,
                    source=event.source,
                    status="published",
                )
                db.add(db_event)
                db.commit()
            finally:
                db.close()
        except Exception as exc:
            logger.debug("Event persistence failed (non-critical): %s", exc)

    def get_recent_events(
        self, event_type: str | None = None, limit: int = 50
    ) -> list[dict]:
        """Fetch recent events from DB."""
        try:
            from backend.db.session import SessionLocal
            from backend.db.models import SystemEvent

            db = SessionLocal()
            try:
                q = db.query(SystemEvent).order_by(SystemEvent.created_at.desc())
                if event_type:
                    q = q.filter(SystemEvent.event_type == event_type)
                rows = q.limit(limit).all()
                return [
                    {
                        "id": r.id,
                        "event_type": r.event_type,
                        "payload": json.loads(r.payload_json) if r.payload_json else {},
                        "correlation_id": r.correlation_id,
                        "source": r.source,
                        "status": r.status,
                        "created_at": r.created_at.isoformat() if r.created_at else None,
                    }
                    for r in rows
                ]
            finally:
                db.close()
        except Exception:
            return []


def get_event_bus() -> EventBus:
    """Singleton accessor."""
    if EventBus._instance is None:
        with EventBus._lock:
            if EventBus._instance is None:
                EventBus._instance = EventBus()
    return EventBus._instance
