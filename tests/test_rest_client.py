"""Tests for the REST client."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from magemcp.connectors.errors import (
    MagentoAuthError,
    MagentoError,
    MagentoNotFoundError,
    MagentoRateLimitError,
    MagentoServerError,
    MagentoValidationError,
)
from magemcp.connectors.rest_client import RESTClient

BASE_URL = "https://magento.test"
TOKEN = "admin-token-123"


@pytest.fixture()
def client() -> RESTClient:
    return RESTClient(base_url=BASE_URL, admin_token=TOKEN, store_code="default")


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_base_url_trailing_slash_stripped(self) -> None:
        c = RESTClient(base_url="https://magento.test/", admin_token=TOKEN)
        assert c.base_url == "https://magento.test"

    def test_default_store_code(self) -> None:
        c = RESTClient(base_url=BASE_URL, admin_token=TOKEN)
        assert c.store_code == "default"

    def test_custom_store_code(self) -> None:
        c = RESTClient(base_url=BASE_URL, admin_token=TOKEN, store_code="fr")
        assert c.store_code == "fr"

    def test_auth_header_always_set(self) -> None:
        c = RESTClient(base_url=BASE_URL, admin_token=TOKEN)
        assert c._client.headers["authorization"] == f"Bearer {TOKEN}"

    def test_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGENTO_BASE_URL", "https://env.test")
        monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", "env-admin-token")
        monkeypatch.setenv("MAGENTO_STORE_CODE", "de")

        c = RESTClient.from_env()
        assert c.base_url == "https://env.test"
        assert c.admin_token == "env-admin-token"
        assert c.store_code == "de"

    def test_from_env_falls_back_to_magento_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGENTO_BASE_URL", "https://env.test")
        monkeypatch.delenv("MAGEMCP_ADMIN_TOKEN", raising=False)
        monkeypatch.setenv("MAGENTO_TOKEN", "legacy-token")

        c = RESTClient.from_env()
        assert c.admin_token == "legacy-token"

    def test_from_env_missing_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MAGENTO_BASE_URL", raising=False)
        monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", "tok")
        with pytest.raises(ValueError, match="MAGENTO_BASE_URL"):
            RESTClient.from_env()

    def test_from_env_missing_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGENTO_BASE_URL", "https://env.test")
        monkeypatch.delenv("MAGEMCP_ADMIN_TOKEN", raising=False)
        monkeypatch.delenv("MAGENTO_TOKEN", raising=False)
        with pytest.raises(ValueError, match="MAGEMCP_ADMIN_TOKEN"):
            RESTClient.from_env()


# ---------------------------------------------------------------------------
# URL building
# ---------------------------------------------------------------------------


class TestUrlBuilding:
    def test_default_store(self, client: RESTClient) -> None:
        assert client._rest_url("/V1/orders") == "/rest/default/V1/orders"

    def test_override_store(self, client: RESTClient) -> None:
        assert client._rest_url("/V1/orders", store_code="fr") == "/rest/fr/V1/orders"

    def test_endpoint_without_leading_slash(self, client: RESTClient) -> None:
        assert client._rest_url("V1/products") == "/rest/default/V1/products"


# ---------------------------------------------------------------------------
# GET
# ---------------------------------------------------------------------------


class TestGet:
    @respx.mock
    async def test_get_order(self, client: RESTClient) -> None:
        order = {"entity_id": 42, "increment_id": "100000042"}
        respx.get(f"{BASE_URL}/rest/default/V1/orders/42").mock(
            return_value=httpx.Response(200, json=order),
        )

        result = await client.get("/V1/orders/42")
        assert result == order

    @respx.mock
    async def test_get_with_params(self, client: RESTClient) -> None:
        body = {"items": [], "total_count": 0}
        route = respx.get(f"{BASE_URL}/rest/default/V1/orders").mock(
            return_value=httpx.Response(200, json=body),
        )

        params = RESTClient.search_params(filters={"status": "processing"}, page_size=5)
        result = await client.get("/V1/orders", params=params)

        assert result == body
        assert route.called

    @respx.mock
    async def test_get_with_store_override(self, client: RESTClient) -> None:
        respx.get(f"{BASE_URL}/rest/fr/V1/products/SKU1").mock(
            return_value=httpx.Response(200, json={"sku": "SKU1"}),
        )

        result = await client.get("/V1/products/SKU1", store_code="fr")
        assert result["sku"] == "SKU1"


# ---------------------------------------------------------------------------
# POST
# ---------------------------------------------------------------------------


class TestPost:
    @respx.mock
    async def test_post(self, client: RESTClient) -> None:
        respx.post(f"{BASE_URL}/rest/default/V1/order/42/ship").mock(
            return_value=httpx.Response(200, json=101),
        )

        result = await client.post("/V1/order/42/ship", json={"items": []})
        assert result == 101


# ---------------------------------------------------------------------------
# PUT
# ---------------------------------------------------------------------------


class TestPut:
    @respx.mock
    async def test_put(self, client: RESTClient) -> None:
        product = {"sku": "SKU1", "name": "Updated"}
        respx.put(f"{BASE_URL}/rest/default/V1/products/SKU1").mock(
            return_value=httpx.Response(200, json=product),
        )

        result = await client.put("/V1/products/SKU1", json={"product": product})
        assert result["name"] == "Updated"


# ---------------------------------------------------------------------------
# DELETE
# ---------------------------------------------------------------------------


class TestDelete:
    @respx.mock
    async def test_delete(self, client: RESTClient) -> None:
        respx.delete(f"{BASE_URL}/rest/default/V1/products/SKU1").mock(
            return_value=httpx.Response(200, json=True),
        )

        result = await client.delete("/V1/products/SKU1")
        assert result is True


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    @respx.mock
    async def test_401_raises_auth_error(self, client: RESTClient) -> None:
        respx.get(f"{BASE_URL}/rest/default/V1/orders/1").mock(
            return_value=httpx.Response(
                401, json={"message": "The consumer isn't authorized."},
            ),
        )

        with pytest.raises(MagentoAuthError) as exc_info:
            await client.get("/V1/orders/1")
        assert exc_info.value.status_code == 401

    @respx.mock
    async def test_404_raises_not_found(self, client: RESTClient) -> None:
        respx.get(f"{BASE_URL}/rest/default/V1/orders/999").mock(
            return_value=httpx.Response(
                404, json={"message": "Entity doesn't exist."},
            ),
        )

        with pytest.raises(MagentoNotFoundError) as exc_info:
            await client.get("/V1/orders/999")
        assert exc_info.value.status_code == 404

    @respx.mock
    async def test_400_raises_validation_error(self, client: RESTClient) -> None:
        respx.post(f"{BASE_URL}/rest/default/V1/orders").mock(
            return_value=httpx.Response(
                400, json={"message": 'The "%1" field is required.', "parameters": ["sku"]},
            ),
        )

        with pytest.raises(MagentoValidationError, match='The "sku" field is required.'):
            await client.post("/V1/orders", json={})

    @respx.mock
    async def test_429_raises_rate_limit_error(self, client: RESTClient) -> None:
        respx.get(f"{BASE_URL}/rest/default/V1/products").mock(
            return_value=httpx.Response(429, json={"message": "Too many requests"}),
        )

        with pytest.raises(MagentoRateLimitError):
            await client.get("/V1/products")

    @respx.mock
    async def test_500_raises_server_error(self, client: RESTClient) -> None:
        respx.get(f"{BASE_URL}/rest/default/V1/orders/1").mock(
            return_value=httpx.Response(500, json={"message": "Internal error"}),
        )

        with pytest.raises(MagentoServerError) as exc_info:
            await client.get("/V1/orders/1")
        assert exc_info.value.status_code == 500

    @respx.mock
    async def test_error_preserves_response_body(self, client: RESTClient) -> None:
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
        params = RESTClient.search_params()
        assert params["searchCriteria[pageSize]"] == "20"
        assert params["searchCriteria[currentPage]"] == "1"

    def test_simple_eq_filter(self) -> None:
        params = RESTClient.search_params(filters={"status": "processing"})
        assert params["searchCriteria[filterGroups][0][filters][0][field]"] == "status"
        assert params["searchCriteria[filterGroups][0][filters][0][conditionType]"] == "eq"

    def test_tuple_condition_filter(self) -> None:
        params = RESTClient.search_params(
            filters={"created_at": ("2024-01-01", "gteq")},
        )
        assert params["searchCriteria[filterGroups][0][filters][0][value]"] == "2024-01-01"
        assert params["searchCriteria[filterGroups][0][filters][0][conditionType]"] == "gteq"

    def test_multiple_filters(self) -> None:
        params = RESTClient.search_params(
            filters={"status": "complete", "customer_id": "7"},
        )
        assert params["searchCriteria[filterGroups][0][filters][0][field]"] == "status"
        assert params["searchCriteria[filterGroups][1][filters][0][field]"] == "customer_id"

    def test_sorting(self) -> None:
        params = RESTClient.search_params(sort_field="created_at", sort_direction="DESC")
        assert params["searchCriteria[sortOrders][0][field]"] == "created_at"
        assert params["searchCriteria[sortOrders][0][direction]"] == "DESC"


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


class TestContextManager:
    async def test_async_context_manager(self) -> None:
        async with RESTClient(base_url=BASE_URL, admin_token=TOKEN) as client:
            assert client is not None
        assert client._client.is_closed
