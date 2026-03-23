"""Tests for the GraphQL client."""

from __future__ import annotations

import httpx
import pytest
import respx

from magemcp.connectors.errors import MagentoError
from magemcp.connectors.graphql_client import GraphQLClient

BASE_URL = "https://magento.test"


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_base_url_trailing_slash_stripped(self) -> None:
        c = GraphQLClient(base_url="https://magento.test/")
        assert c.base_url == "https://magento.test"

    def test_default_store_code(self) -> None:
        c = GraphQLClient(base_url=BASE_URL)
        assert c.store_code == "default"

    def test_custom_store_code(self) -> None:
        c = GraphQLClient(base_url=BASE_URL, store_code="fr")
        assert c.store_code == "fr"

    def test_no_auth_header_by_default(self) -> None:
        """Guest browsing — no Authorization header."""
        c = GraphQLClient(base_url=BASE_URL)
        assert "authorization" not in c._client.headers

    def test_customer_token_sets_auth_header(self) -> None:
        c = GraphQLClient(base_url=BASE_URL, customer_token="cust-token-123")
        assert c._client.headers["authorization"] == "Bearer cust-token-123"

    def test_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGENTO_BASE_URL", "https://env.test")
        monkeypatch.setenv("MAGENTO_STORE_CODE", "de")

        c = GraphQLClient.from_env()
        assert c.base_url == "https://env.test"
        assert c.store_code == "de"
        assert c.customer_token is None

    def test_from_env_with_customer_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGENTO_BASE_URL", "https://env.test")
        monkeypatch.setenv("MAGENTO_CUSTOMER_TOKEN", "cust-abc")

        c = GraphQLClient.from_env()
        assert c.customer_token == "cust-abc"
        assert c._client.headers["authorization"] == "Bearer cust-abc"

    def test_from_env_missing_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MAGENTO_BASE_URL", raising=False)
        with pytest.raises(ValueError, match="MAGENTO_BASE_URL"):
            GraphQLClient.from_env()


# ---------------------------------------------------------------------------
# Query execution
# ---------------------------------------------------------------------------


class TestQuery:
    @respx.mock
    async def test_basic_query(self) -> None:
        gql_response = {"data": {"storeConfig": {"locale": "en_US"}}}
        route = respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        async with GraphQLClient(base_url=BASE_URL) as client:
            result = await client.query("{ storeConfig { locale } }")

        assert result["storeConfig"]["locale"] == "en_US"
        assert route.called

    @respx.mock
    async def test_sends_store_header(self) -> None:
        gql_response = {"data": {"storeConfig": {"locale": "fr_FR"}}}
        route = respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        async with GraphQLClient(base_url=BASE_URL, store_code="fr") as client:
            await client.query("{ storeConfig { locale } }")

        assert route.calls[0].request.headers["store"] == "fr"

    @respx.mock
    async def test_store_code_override(self) -> None:
        gql_response = {"data": {"storeConfig": {"locale": "de_DE"}}}
        route = respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        async with GraphQLClient(base_url=BASE_URL, store_code="default") as client:
            await client.query("{ storeConfig { locale } }", store_code="de")

        assert route.calls[0].request.headers["store"] == "de"

    @respx.mock
    async def test_with_variables(self) -> None:
        gql_response = {"data": {"product": {"sku": "SKU1"}}}
        route = respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        async with GraphQLClient(base_url=BASE_URL) as client:
            result = await client.query(
                "query($sku: String!) { product(sku: $sku) { sku } }",
                variables={"sku": "SKU1"},
            )

        assert result["product"]["sku"] == "SKU1"
        assert b'"variables"' in route.calls[0].request.content

    @respx.mock
    async def test_graphql_error_raises(self) -> None:
        gql_response = {"errors": [{"message": "Field 'foo' not found"}]}
        respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        async with GraphQLClient(base_url=BASE_URL) as client:
            with pytest.raises(MagentoError, match="Field 'foo' not found"):
                await client.query("{ foo }")

    @respx.mock
    async def test_no_auth_header_in_guest_request(self) -> None:
        """Verify guest requests don't send Authorization."""
        gql_response = {"data": {"storeConfig": {"locale": "en_US"}}}
        route = respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        async with GraphQLClient(base_url=BASE_URL) as client:
            await client.query("{ storeConfig { locale } }")

        request = route.calls[0].request
        assert "authorization" not in request.headers


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


class TestContextManager:
    async def test_async_context_manager(self) -> None:
        async with GraphQLClient(base_url=BASE_URL) as client:
            assert client is not None
        assert client._client.is_closed
