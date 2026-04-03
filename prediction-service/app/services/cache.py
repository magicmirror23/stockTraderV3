"""Cache service — Redis-backed caching with stale-while-revalidate.

Falls back to in-memory LRU cache when Redis is unavailable.
Session-aware TTLs: shorter during market hours, longer after close.
Supports stale-while-revalidate so callers never block on a cache miss
when a slightly-old value is available.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Callable

from app.core.config import settings

logger = logging.getLogger(__name__)

_redis_client: Any = None
# In-memory fallback: key → (hard_expire_ts, soft_expire_ts, value)
_memory_cache: dict[str, tuple[float, float, Any]] = {}
_MAX_MEMORY_ENTRIES = 4096


def _get_redis():
    """Lazily connect to Redis."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client

    if not settings.REDIS_URL:
        return None

    try:
        import redis
        _redis_client = redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=1,
        )
        _redis_client.ping()
        logger.info("Redis connected: %s", settings.REDIS_URL)
        return _redis_client
    except Exception as exc:
        logger.warning("Redis not available: %s — using memory cache", exc)
        return None


def cache_key(prefix: str, *args: Any) -> str:
    """Generate a deterministic cache key."""
    raw = f"{prefix}:" + ":".join(str(a) for a in args)
    return hashlib.md5(raw.encode()).hexdigest()


def _market_aware_ttl(base_ttl: int) -> int:
    """Shorten TTL during market hours (data changes fast),
    lengthen after close (stale data is fine overnight)."""
    try:
        from app.services.market_session import get_session_state
        state = get_session_state()
        phase = state.get("phase", "closed")
        if phase in ("open", "pre_open"):
            return max(base_ttl // 3, 15)
        return base_ttl * 2
    except Exception:
        return base_ttl


def get(key: str) -> Any | None:
    """Retrieve a cached value (returns None on miss or hard expiry)."""
    r = _get_redis()
    if r:
        try:
            raw = r.get(key)
            if raw:
                payload = json.loads(raw)
                return payload.get("v")
        except Exception:
            pass

    entry = _memory_cache.get(key)
    if entry:
        hard_exp, _, val = entry
        if time.time() < hard_exp:
            return val
        del _memory_cache[key]
    return None


def get_or_revalidate(
    key: str,
    revalidate_fn: Callable[[], Any],
    ttl_seconds: int = 300,
    stale_ttl_seconds: int | None = None,
) -> Any:
    """Get from cache; if soft-expired, return stale value and revalidate in-band.

    - Within soft TTL → return cached value (fast path).
    - Past soft TTL but within hard TTL → return stale value, then
      update cache with fresh data for next caller.
    - Past hard TTL → call revalidate_fn synchronously.
    """
    stale_ttl = stale_ttl_seconds or ttl_seconds * 3
    now = time.time()

    # Try memory cache first (includes soft/hard expiry)
    entry = _memory_cache.get(key)
    if entry:
        hard_exp, soft_exp, val = entry
        if now < soft_exp:
            return val
        if now < hard_exp:
            # Stale but usable — revalidate for next caller
            try:
                fresh = revalidate_fn()
                put(key, fresh, ttl_seconds, stale_ttl)
                return fresh
            except Exception:
                return val

    # Try Redis
    r = _get_redis()
    if r:
        try:
            raw = r.get(key)
            if raw:
                payload = json.loads(raw)
                return payload.get("v")
        except Exception:
            pass

    # Full miss — must revalidate now
    fresh = revalidate_fn()
    put(key, fresh, ttl_seconds, stale_ttl)
    return fresh


def put(key: str, value: Any, ttl_seconds: int = 300, stale_ttl_seconds: int | None = None) -> None:
    """Store a value in cache with market-aware TTL."""
    effective_ttl = _market_aware_ttl(ttl_seconds)
    stale_ttl = stale_ttl_seconds or effective_ttl * 3

    r = _get_redis()
    if r:
        try:
            payload = json.dumps({"v": value, "ts": time.time()}, default=str)
            r.setex(key, effective_ttl, payload)
        except Exception:
            pass

    # Always populate memory cache (acts as L1)
    now = time.time()
    if len(_memory_cache) >= _MAX_MEMORY_ENTRIES:
        _evict_oldest()
    _memory_cache[key] = (now + stale_ttl, now + effective_ttl, value)


def _evict_oldest() -> None:
    """Remove the entry with the earliest hard-expire to stay under cap."""
    if not _memory_cache:
        return
    oldest_key = min(_memory_cache, key=lambda k: _memory_cache[k][0])
    del _memory_cache[oldest_key]


def invalidate(key: str) -> None:
    """Remove a key from cache."""
    r = _get_redis()
    if r:
        try:
            r.delete(key)
        except Exception:
            pass
    _memory_cache.pop(key, None)


def clear_all() -> None:
    """Clear all cached values."""
    r = _get_redis()
    if r:
        try:
            r.flushdb()
        except Exception:
            pass
    _memory_cache.clear()
