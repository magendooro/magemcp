"""In-memory TTL cache for stable Magento responses."""

from __future__ import annotations

import time
from typing import Any


class TTLCache:
    """Simple in-memory cache with per-entry time-to-live (TTL).

    Thread-safety: This cache is designed for use within a single asyncio event
    loop. No locking is applied — concurrent coroutines in the same loop will
    not corrupt state (dict operations are atomic in CPython).

    Usage::

        _cache = TTLCache(ttl=300)  # 5-minute default TTL

        async def get_value(key: str) -> dict:
            cached = _cache.get(key)
            if cached is not None:
                return cached
            result = await expensive_call()
            _cache.set(key, result)
            return result
    """

    def __init__(self, ttl: float = 300.0) -> None:
        """Initialise the cache.

        Args:
            ttl: Default time-to-live in seconds. Entries older than this are
                 considered stale and will not be returned.
        """
        self._ttl = ttl
        self._store: dict[str, tuple[Any, float]] = {}  # key → (value, expires_at)

    def get(self, key: str) -> Any | None:
        """Return the cached value for *key*, or ``None`` if missing or expired."""
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Store *value* under *key* with the given TTL (defaults to instance TTL)."""
        expires_at = time.monotonic() + (ttl if ttl is not None else self._ttl)
        self._store[key] = (value, expires_at)

    def invalidate(self, key: str) -> None:
        """Remove a specific entry from the cache."""
        self._store.pop(key, None)

    def clear(self) -> None:
        """Remove all entries from the cache."""
        self._store.clear()

    def __len__(self) -> int:
        """Return the number of currently stored (possibly expired) entries."""
        return len(self._store)
