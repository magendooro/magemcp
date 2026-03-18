"""Tests for the Magento connector layer."""

from __future__ import annotations

import httpx
import pytest
import respx

from magemcp.connectors.magento import (
    MagentoAuthError,
    MagentoClient,
    MagentoConfig,
    MagentoError,
    MagentoNotFoundError,
    MagentoRateLimitError,
    MagentoServerError,
    MagentoValidationError,
)

BASE_URL = "https://magento.test"
TOKEN = "test-token-123"


@pytest.fixture()
def client() -> MagentoClient:
    return MagentoClient(base_url=BASE_URL, token=TOKEN, store_code="default")


# ---------------------------------------------------------------------------
# Construction & configuration
# ---------------------------------------------------------------------------


class TestClientConstruction:
    def test_base_url_trailing_slash_stripped(self) -> None:
        c = MagentoClient(base_url="https://magento.test/", token=TOKEN)
        assert c.base_url == "https://magento.test"

    def test_default_store_code(self) -> None:
        c = MagentoClient(base_url=BASE_URL, token=TOKEN)
        assert c.store_code == "default"

    def test_custom_store_code(self) -> None:
        c = MagentoClient(base_url=BASE_URL, token=TOKEN, store_code="fr")
        assert c.store_code == "fr"

    def test_from_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGENTO_BASE_URL", "https://env.test")
        monkeypatch.setenv("MAGENTO_TOKEN", "env-token")
        monkeypatch.setenv("MAGENTO_STORE_CODE", "de")

        config = MagentoConfig()  # type: ignore[call-arg]
        c = MagentoClient.from_config(config)

        assert c.base_url == "https://env.test"
        assert c.token == "env-token"
        assert c.store_code == "de"

    def test_auth_header_set(self) -> None:
        c = MagentoClient(base_url=BASE_URL, token=TOKEN)
        assert c._client.headers["authorization"] == f"Bearer {TOKEN}"


class TestRestUrlBuilding:
    def test_default_store(self, client: MagentoClient) -> None:
        assert client._rest_url("/V1/orders") == "/rest/default/V1/orders"

    def test_override_store(self, client: MagentoClient) -> None:
        assert client._rest_url("/V1/orders", store_code="fr") == "/rest/fr/V1/orders"

    def test_endpoint_without_leading_slash(self, client: MagentoClient) -> None:
        assert client._rest_url("V1/products") == "/rest/default/V1/products"


# ---------------------------------------------------------------------------
# REST — GET
# ---------------------------------------------------------------------------


class TestRestGet:
    @respx.mock
    async def test_get_order(self, client: MagentoClient) -> None:
        order = {"entity_id": 42, "increment_id": "100000042", "status": "processing"}
        respx.get(f"{BASE_URL}/rest/default/V1/orders/42").mock(
            return_value=httpx.Response(200, json=order),
        )

        result = await client.get("/V1/orders/42")
        assert result == order

    @respx.mock
    async def test_get_with_params(self, client: MagentoClient) -> None:
        body = {"items": [], "total_count": 0}
        route = respx.get(f"{BASE_URL}/rest/default/V1/orders").mock(
            return_value=httpx.Response(200, json=body),
        )

        params = MagentoClient.search_params(filters={"status": "processing"}, page_size=5)
        result = await client.get("/V1/orders", params=params)

        assert result == body
        assert route.called

    @respx.mock
    async def test_get_with_store_override(self, client: MagentoClient) -> None:
        respx.get(f"{BASE_URL}/rest/fr/V1/products/SKU1").mock(
            return_value=httpx.Response(200, json={"sku": "SKU1"}),
        )

        result = await client.get("/V1/products/SKU1", store_code="fr")
        assert result["sku"] == "SKU1"


# ---------------------------------------------------------------------------
# REST — POST
# ---------------------------------------------------------------------------


class TestRestPost:
    @respx.mock
    async def test_post_shipment(self, client: MagentoClient) -> None:
        respx.post(f"{BASE_URL}/rest/default/V1/order/42/ship").mock(
            return_value=httpx.Response(200, json=101),
        )

        result = await client.post("/V1/order/42/ship", json={"items": []})
        assert result == 101


# ---------------------------------------------------------------------------
# REST — PUT
# ---------------------------------------------------------------------------


class TestRestPut:
    @respx.mock
    async def test_put_product(self, client: MagentoClient) -> None:
        product = {"sku": "SKU1", "name": "Updated"}
        respx.put(f"{BASE_URL}/rest/default/V1/products/SKU1").mock(
            return_value=httpx.Response(200, json=product),
        )

        result = await client.put("/V1/products/SKU1", json={"product": product})
        assert result["name"] == "Updated"


# ---------------------------------------------------------------------------
# GraphQL
# ---------------------------------------------------------------------------


class TestGraphql:
    @respx.mock
    async def test_graphql_query(self, client: MagentoClient) -> None:
        gql_response = {
            "data": {
                "products": {
                    "items": [{"sku": "SHIRT1", "name": "Blue Shirt"}],
                },
            },
        }
        route = respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        query = '{ products(search: "shirt") { items { sku name } } }'
        result = await client.graphql(query)

        assert result["products"]["items"][0]["sku"] == "SHIRT1"
        # Verify the Store header was sent
        request = route.calls[0].request
        assert request.headers["store"] == "default"

    @respx.mock
    async def test_graphql_with_variables(self, client: MagentoClient) -> None:
        gql_response = {"data": {"product": {"sku": "SKU1"}}}
        route = respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        result = await client.graphql(
            "query($sku: String!) { product(sku: $sku) { sku } }",
            variables={"sku": "SKU1"},
        )

        assert result["product"]["sku"] == "SKU1"
        # Verify variables were included in the request body
        body = route.calls[0].request.content
        assert b'"variables"' in body

    @respx.mock
    async def test_graphql_store_override(self, client: MagentoClient) -> None:
        gql_response = {"data": {"storeConfig": {"locale": "fr_FR"}}}
        route = respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        result = await client.graphql("{ storeConfig { locale } }", store_code="fr")
        assert result["storeConfig"]["locale"] == "fr_FR"
        assert route.calls[0].request.headers["store"] == "fr"

    @respx.mock
    async def test_graphql_error_raises(self, client: MagentoClient) -> None:
        gql_response = {"errors": [{"message": "Field 'foo' not found"}]}
        respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        with pytest.raises(MagentoError, match="Field 'foo' not found"):
            await client.graphql("{ foo }")


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    @respx.mock
    async def test_401_raises_auth_error(self, client: MagentoClient) -> None:
        respx.get(f"{BASE_URL}/rest/default/V1/orders/1").mock(
            return_value=httpx.Response(
                401,
                json={"message": "The consumer isn't authorized to access the resource."},
            ),
        )

        with pytest.raises(MagentoAuthError) as exc_info:
            await client.get("/V1/orders/1")

        assert exc_info.value.status_code == 401
        assert "authorized" in str(exc_info.value)

    @respx.mock
    async def test_403_raises_auth_error(self, client: MagentoClient) -> None:
        respx.get(f"{BASE_URL}/rest/default/V1/orders/1").mock(
            return_value=httpx.Response(403, json={"message": "Forbidden"}),
        )

        with pytest.raises(MagentoAuthError) as exc_info:
            await client.get("/V1/orders/1")
        assert exc_info.value.status_code == 403

    @respx.mock
    async def test_404_raises_not_found(self, client: MagentoClient) -> None:
        respx.get(f"{BASE_URL}/rest/default/V1/orders/999").mock(
            return_value=httpx.Response(
                404,
                json={"message": "The entity that was requested doesn't exist."},
            ),
        )

        with pytest.raises(MagentoNotFoundError) as exc_info:
            await client.get("/V1/orders/999")
        assert exc_info.value.status_code == 404

    @respx.mock
    async def test_400_raises_validation_error(self, client: MagentoClient) -> None:
        respx.post(f"{BASE_URL}/rest/default/V1/orders").mock(
            return_value=httpx.Response(
                400,
                json={"message": 'The "%1" field is required.', "parameters": ["sku"]},
            ),
        )

        with pytest.raises(MagentoValidationError, match='The "sku" field is required.'):
            await client.post("/V1/orders", json={})

    @respx.mock
    async def test_429_raises_rate_limit_error(self, client: MagentoClient) -> None:
        respx.get(f"{BASE_URL}/rest/default/V1/products").mock(
            return_value=httpx.Response(429, json={"message": "Too many requests"}),
        )

        with pytest.raises(MagentoRateLimitError):
            await client.get("/V1/products")

    @respx.mock
    async def test_500_raises_server_error(self, client: MagentoClient) -> None:
        respx.get(f"{BASE_URL}/rest/default/V1/orders/1").mock(
            return_value=httpx.Response(500, json={"message": "Internal error"}),
        )

        with pytest.raises(MagentoServerError) as exc_info:
            await client.get("/V1/orders/1")
        assert exc_info.value.status_code == 500

    @respx.mock
    async def test_error_with_non_json_body(self, client: MagentoClient) -> None:
        respx.get(f"{BASE_URL}/rest/default/V1/orders/1").mock(
            return_value=httpx.Response(502, text="Bad Gateway"),
        )

        with pytest.raises(MagentoServerError, match="Bad Gateway"):
            await client.get("/V1/orders/1")

    @respx.mock
    async def test_error_preserves_response_body(self, client: MagentoClient) -> None:
        body = {"message": "Not found", "trace": "..."}
        respx.get(f"{BASE_URL}/rest/default/V1/orders/1").mock(
            return_value=httpx.Response(404, json=body),
        )

        with pytest.raises(MagentoNotFoundError) as exc_info:
            await client.get("/V1/orders/1")
        assert exc_info.value.response_body == body


# ---------------------------------------------------------------------------
# searchCriteria builder
# ---------------------------------------------------------------------------


class TestSearchParams:
    def test_defaults(self) -> None:
        params = MagentoClient.search_params()
        assert params["searchCriteria[pageSize]"] == "20"
        assert params["searchCriteria[currentPage]"] == "1"

    def test_simple_eq_filter(self) -> None:
        params = MagentoClient.search_params(filters={"status": "processing"})
        assert params["searchCriteria[filterGroups][0][filters][0][field]"] == "status"
        assert params["searchCriteria[filterGroups][0][filters][0][value]"] == "processing"
        assert params["searchCriteria[filterGroups][0][filters][0][conditionType]"] == "eq"

    def test_tuple_condition_filter(self) -> None:
        params = MagentoClient.search_params(
            filters={"created_at": ("2024-01-01", "gteq")},
        )
        assert params["searchCriteria[filterGroups][0][filters][0][value]"] == "2024-01-01"
        assert params["searchCriteria[filterGroups][0][filters][0][conditionType]"] == "gteq"

    def test_multiple_filters(self) -> None:
        params = MagentoClient.search_params(
            filters={"status": "complete", "customer_id": "7"},
        )
        assert params["searchCriteria[filterGroups][0][filters][0][field]"] == "status"
        assert params["searchCriteria[filterGroups][1][filters][0][field]"] == "customer_id"

    def test_pagination(self) -> None:
        params = MagentoClient.search_params(page_size=5, current_page=3)
        assert params["searchCriteria[pageSize]"] == "5"
        assert params["searchCriteria[currentPage]"] == "3"

    def test_sorting(self) -> None:
        params = MagentoClient.search_params(sort_field="created_at", sort_direction="DESC")
        assert params["searchCriteria[sortOrders][0][field]"] == "created_at"
        assert params["searchCriteria[sortOrders][0][direction]"] == "DESC"

    def test_no_sort_keys_when_not_specified(self) -> None:
        params = MagentoClient.search_params()
        assert "searchCriteria[sortOrders][0][field]" not in params


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


class TestContextManager:
    async def test_async_context_manager(self) -> None:
        async with MagentoClient(base_url=BASE_URL, token=TOKEN) as client:
            assert client is not None
        # After exiting, the underlying client should be closed
        assert client._client.is_closed

    async def test_external_client_not_closed(self) -> None:
        http_client = httpx.AsyncClient(base_url=BASE_URL)
        client = MagentoClient(base_url=BASE_URL, token=TOKEN, client=http_client)
        await client.close()
        # External client should NOT be closed by MagentoClient
        assert not http_client.is_closed
        await http_client.aclose()
