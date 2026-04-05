"""Redis-backed cache with in-memory fallback for market-data service."""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

try:
    import redis
except Exception:  # pragma: no cover - optional dependency path
    redis = None


class CacheBackend:
    def __init__(self) -> None:
        self._prefix = os.getenv("MARKET_DATA_CACHE_PREFIX", "mds")
        self._memory: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()

        self._redis = None
        redis_url = os.getenv("REDIS_URL") or os.getenv("CELERY_BROKER_URL")
        if redis and redis_url and redis_url.startswith("redis"):
            try:
                self._redis = redis.Redis.from_url(redis_url, decode_responses=True)
                self._redis.ping()
            except Exception:
                self._redis = None

    def _key(self, raw: str) -> str:
        return f"{self._prefix}:{raw}"

    def get_json(self, key: str) -> dict[str, Any] | list[Any] | None:
        k = self._key(key)
        if self._redis is not None:
            raw = self._redis.get(k)
            if not raw:
                return None
            try:
                return json.loads(raw)
            except Exception:
                return None

        with self._lock:
            payload = self._memory.get(k)
            if not payload:
                return None
            expires_at, raw = payload
            if expires_at < time.time():
                self._memory.pop(k, None)
                return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    def set_json(self, key: str, value: Any, ttl_s: int) -> None:
        k = self._key(key)
        payload = json.dumps(value)

        if self._redis is not None:
            self._redis.setex(k, max(1, int(ttl_s)), payload)
            return

        with self._lock:
            self._memory[k] = (time.time() + max(1, int(ttl_s)), payload)

    def incr_with_ttl(self, key: str, ttl_s: int) -> int:
        k = self._key(key)

        if self._redis is not None:
            with self._redis.pipeline() as pipe:
                pipe.incr(k)
                pipe.expire(k, max(1, int(ttl_s)))
                count, _ = pipe.execute()
            return int(count)

        with self._lock:
            expires_at, raw = self._memory.get(k, (0.0, "0"))
            if expires_at < time.time():
                count = 0
            else:
                try:
                    count = int(raw)
                except Exception:
                    count = 0
            count += 1
            self._memory[k] = (time.time() + max(1, int(ttl_s)), str(count))
            return count

    def set_cooldown(self, scope: str, entity: str, seconds: int) -> None:
        key = f"cooldown:{scope}:{entity}"
        until = time.time() + max(1, int(seconds))
        self.set_json(key, {"cooldown_until": until}, ttl_s=max(1, int(seconds)))

    def cooldown_remaining(self, scope: str, entity: str) -> float:
        key = f"cooldown:{scope}:{entity}"
        data = self.get_json(key)
        if not data:
            return 0.0
        until = float(data.get("cooldown_until", 0.0))
        return max(0.0, until - time.time())
