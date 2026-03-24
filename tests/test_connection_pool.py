"""Tests for magemcp.connectors.pool — shared connection pooling."""

from __future__ import annotations

import pytest

import magemcp.connectors.pool as pool_mod


@pytest.fixture(autouse=True)
def reset_pool():
    """Ensure pool is clear before and after each test."""
    pool_mod._rest = None
    pool_mod._graphql = None
    yield
    pool_mod._rest = None
    pool_mod._graphql = None


class TestPoolGetters:
    def test_get_rest_none_before_init(self) -> None:
        assert pool_mod.get_rest() is None

    def test_get_graphql_none_before_init(self) -> None:
        assert pool_mod.get_graphql() is None


class TestPoolInit:
    async def test_init_creates_clients(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGENTO_BASE_URL", "https://magento.test")
        monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", "token")

        await pool_mod.init()

        assert pool_mod.get_rest() is not None
        assert pool_mod.get_graphql() is not None

    async def test_close_clears_clients(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGENTO_BASE_URL", "https://magento.test")
        monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", "token")

        await pool_mod.init()
        await pool_mod.close()

        assert pool_mod.get_rest() is None
        assert pool_mod.get_graphql() is None

    async def test_close_is_safe_when_not_initialised(self) -> None:
        # Should not raise
        await pool_mod.close()


class TestBorrowedRESTClient:
    async def test_from_env_returns_borrowed_when_pool_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAGENTO_BASE_URL", "https://magento.test")
        monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", "token")

        await pool_mod.init()

        from magemcp.connectors.rest_client import RESTClient

        client = RESTClient.from_env()
        assert client._owned is False
        assert client._client is pool_mod.get_rest()._client  # same underlying httpx client

    async def test_borrowed_close_is_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGENTO_BASE_URL", "https://magento.test")
        monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", "token")

        await pool_mod.init()
        shared = pool_mod.get_rest()

        from magemcp.connectors.rest_client import RESTClient

        borrowed = RESTClient.from_env()
        # Closing the borrowed reference should NOT close the underlying httpx client
        await borrowed.close()

        # The pool client should still be usable (not closed)
        assert not shared._client.is_closed

    async def test_owned_client_when_pool_not_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGENTO_BASE_URL", "https://magento.test")
        monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", "token")
        # Pool is empty (reset_pool fixture cleared it)

        from magemcp.connectors.rest_client import RESTClient

        client = RESTClient.from_env()
        assert client._owned is True
        await client.close()


class TestBorrowedGraphQLClient:
    async def test_from_env_returns_borrowed_when_pool_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAGENTO_BASE_URL", "https://magento.test")
        monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", "token")

        await pool_mod.init()

        from magemcp.connectors.graphql_client import GraphQLClient

        client = GraphQLClient.from_env()
        assert client._owned is False
        assert client._client is pool_mod.get_graphql()._client

    async def test_customer_token_bypasses_pool(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """GraphQL client with customer token always creates a new owned instance."""
        monkeypatch.setenv("MAGENTO_BASE_URL", "https://magento.test")
        monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", "token")

        await pool_mod.init()

        from magemcp.connectors.graphql_client import GraphQLClient

        client = GraphQLClient.from_env(customer_token="cust-token-xyz")
        assert client._owned is True
        assert client.customer_token == "cust-token-xyz"
        await client.close()

    async def test_borrowed_close_is_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGENTO_BASE_URL", "https://magento.test")
        monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", "token")

        await pool_mod.init()
        shared = pool_mod.get_graphql()

        from magemcp.connectors.graphql_client import GraphQLClient

        borrowed = GraphQLClient.from_env()
        await borrowed.close()

        assert not shared._client.is_closed
