"""
A tiny in-memory TTL (time-to-live) cache.

WHY THIS EXISTS:
Clarity's Data Export API allows only 10 requests per project, per day.
If your manager asks "what's our traffic overview" three times in a
meeting, that's 3 of your 10 calls gone on an identical question. This
cache means: same question within the TTL window -> answer from memory,
no API call spent.

HOW IT WORKS:
Every cached item is stored with the timestamp it was fetched. When
someone asks for it again, we check: has more time passed than the TTL?
- No  -> return the cached value instantly, for free.
- Yes -> treat it as stale, let the caller fetch fresh data and re-cache it.

This is deliberately simple (a plain Python dict), because this server
runs as a single process for a single small team -- there's no need for
Redis or anything external here.
"""

import time
from typing import Any, Callable, Optional


class TTLCache:
    def __init__(self, default_ttl_seconds: int = 3600):
        """
        default_ttl_seconds: how long a cached value stays valid.
        3600 = 1 hour by default. Given Clarity data itself only
        refreshes periodically (it's not truly real-time to the second),
        a 1-hour cache doesn't lose you meaningfully fresh data, but it
        drastically cuts API usage if multiple questions land within
        that hour.
        """
        self._store: dict[str, tuple[float, Any]] = {}
        self.default_ttl_seconds = default_ttl_seconds

    def _make_key(self, *args: Any) -> str:
        """Turn a tool's arguments into a single string key.
        e.g. ("traffic_overview", 3) -> "traffic_overview:3" """
        return ":".join(str(a) for a in args)

    def get_or_set(
        self,
        key_parts: tuple,
        fetch_fn: Callable[[], Any],
        ttl_seconds: Optional[int] = None,
    ) -> Any:
        """
        The main entry point. Give it:
          - key_parts: the tool name + its arguments, e.g. ("insights_by_dimension", 3, "Device")
          - fetch_fn: a zero-argument function that actually calls the Clarity API
        It returns cached data if fresh, otherwise calls fetch_fn(), caches
        the result, and returns it.
        """
        key = self._make_key(*key_parts)
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds

        cached = self._store.get(key)
        if cached is not None:
            cached_at, value = cached
            age = time.time() - cached_at
            if age < ttl:
                return {"data": value, "from_cache": True, "cache_age_seconds": round(age)}

        # Cache miss or expired -- actually spend an API call.
        value = fetch_fn()
        self._store[key] = (time.time(), value)
        return {"data": value, "from_cache": False, "cache_age_seconds": 0}

    def clear(self) -> None:
        """Wipe the whole cache. Useful for manual testing."""
        self._store.clear()

    def stats(self) -> dict:
        """How many distinct queries are currently cached -- handy for a
        debug/status tool so you can see cache health at a glance."""
        return {"cached_keys": len(self._store), "keys": list(self._store.keys())}
