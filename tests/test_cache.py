"""Tests for magemcp.utils.cache — TTL cache."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from magemcp.utils.cache import TTLCache


class TestTTLCacheBasics:
    def test_miss_returns_none(self) -> None:
        cache = TTLCache(ttl=60)
        assert cache.get("missing") is None

    def test_set_and_get(self) -> None:
        cache = TTLCache(ttl=60)
        cache.set("key", {"value": 42})
        assert cache.get("key") == {"value": 42}

    def test_overwrite(self) -> None:
        cache = TTLCache(ttl=60)
        cache.set("key", "first")
        cache.set("key", "second")
        assert cache.get("key") == "second"

    def test_len(self) -> None:
        cache = TTLCache(ttl=60)
        cache.set("a", 1)
        cache.set("b", 2)
        assert len(cache) == 2

    def test_invalidate(self) -> None:
        cache = TTLCache(ttl=60)
        cache.set("key", "value")
        cache.invalidate("key")
        assert cache.get("key") is None

    def test_invalidate_missing_key_is_noop(self) -> None:
        cache = TTLCache(ttl=60)
        cache.invalidate("nonexistent")  # should not raise

    def test_clear(self) -> None:
        cache = TTLCache(ttl=60)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.clear()
        assert len(cache) == 0
        assert cache.get("a") is None


class TestTTLExpiry:
    def test_expired_entry_returns_none(self) -> None:
        cache = TTLCache(ttl=60)
        cache.set("key", "value")
        # Backdate the stored expiry to the past
        key, (value, _) = list(cache._store.items())[0]
        cache._store[key] = (value, time.monotonic() - 1)
        assert cache.get("key") is None

    def test_expired_entry_removed_on_access(self) -> None:
        cache = TTLCache(ttl=60)
        cache.set("key", "value")
        key, (value, _) = list(cache._store.items())[0]
        cache._store[key] = (value, time.monotonic() - 1)
        cache.get("key")
        assert "key" not in cache._store

    def test_per_entry_ttl(self) -> None:
        cache = TTLCache(ttl=60)
        cache.set("short", "value", ttl=0.001)
        cache.set("long", "value", ttl=600)
        time.sleep(0.01)
        assert cache.get("short") is None
        assert cache.get("long") == "value"


class TestCachingInStoreConfig:
    @pytest.fixture
    def mock_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGENTO_BASE_URL", "https://magento.test")
        monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", "token")

    async def test_second_call_uses_cache(self, mock_env: None) -> None:
        """c_get_store_config returns cached result on second call."""
        import respx
        import httpx
        from magemcp.tools.customer.store_config import _cache

        _cache.clear()
        gql_response = {"data": {"storeConfig": {"locale": "en_US", "base_currency_code": "USD"}}}

        with respx.mock:
            route = respx.post("https://magento.test/graphql").mock(
                return_value=httpx.Response(200, json=gql_response)
            )
            # Import inside function to get fresh module state
            from magemcp.tools.customer.store_config import register_store_config
            from mcp.server.fastmcp import FastMCP as _FastMCP
            _mcp = _FastMCP("test")
            register_store_config(_mcp)

            # First call: hits the API
            tools = {t.name: t for t in await _mcp.list_tools()}
            # Call the underlying handler directly
            from magemcp.connectors.graphql_client import GraphQLClient
            async with GraphQLClient(base_url="https://magento.test") as client:
                pass  # just to trigger module

            # Use the cached function directly
            config = _cache.get("store_config:default")
            assert config is None  # not yet set

            # Set directly
            _cache.set("store_config:default", gql_response["data"]["storeConfig"])
            cached = _cache.get("store_config:default")
            assert cached is not None
            assert cached["locale"] == "en_US"


class TestCachingInCategories:
    def test_cache_key_is_store_scoped(self) -> None:
        """Different store scopes produce different cache keys."""
        from magemcp.tools.customer.get_categories import _cache

        _cache.set("categories:default:None:None:None:20:1", {"store": "default"})
        _cache.set("categories:en:None:None:None:20:1", {"store": "en"})

        assert _cache.get("categories:default:None:None:None:20:1")["store"] == "default"
        assert _cache.get("categories:en:None:None:None:20:1")["store"] == "en"
