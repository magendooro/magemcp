"""In-memory idempotency store for write tools.

Prevents duplicate Magento operations when agents retry calls (e.g. after a
timeout).  The caller supplies an ``idempotency_key``; if the same key is
seen again within the TTL the stored result is returned without re-executing.

Usage::

    from magemcp.utils.idempotency import idempotency_store

    async def my_write_tool(order_id: int, idempotency_key: str | None = None):
        if idempotency_key:
            stored = idempotency_store.get("my_write_tool", idempotency_key)
            if stored is not None:
                return {**stored, "idempotent_replay": True}

        result = await do_work(order_id)

        if idempotency_key:
            idempotency_store.set("my_write_tool", idempotency_key, result)
        return result
"""

from __future__ import annotations

from magemcp.utils.cache import TTLCache

_TTL = 86_400  # 24 hours


class IdempotencyStore:
    """Thin wrapper around ``TTLCache`` that namespaces keys by tool name."""

    def __init__(self, ttl: float = _TTL) -> None:
        self._cache = TTLCache(ttl=ttl)

    def _key(self, tool_name: str, idempotency_key: str) -> str:
        return f"{tool_name}:{idempotency_key}"

    def get(self, tool_name: str, idempotency_key: str) -> dict | None:  # type: ignore[type-arg]
        """Return the stored result, or *None* if absent / expired."""
        return self._cache.get(self._key(tool_name, idempotency_key))

    def set(self, tool_name: str, idempotency_key: str, result: dict) -> None:  # type: ignore[type-arg]
        """Persist *result* under the given key."""
        self._cache.set(self._key(tool_name, idempotency_key), result)

    def clear(self) -> None:
        """Remove all stored entries (test helper)."""
        self._cache.clear()

    def __len__(self) -> int:
        return len(self._cache)


# Module-level singleton shared across all tools.
idempotency_store = IdempotencyStore()
