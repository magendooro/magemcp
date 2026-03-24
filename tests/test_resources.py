"""Tests for MageMCP MCP Resources (T07)."""

from __future__ import annotations

import json

import pytest
import respx
from httpx import Response


BASE_URL = "https://magento.test"
TOKEN = "admin-token-123"


@pytest.fixture
def mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAGENTO_BASE_URL", BASE_URL)
    monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", TOKEN)


class TestResourceRegistration:
    async def test_static_resources_listed(self) -> None:
        from magemcp.server import mcp

        resources = await mcp.list_resources()
        uris = [str(r.uri) for r in resources]
        assert "magento://store/config" in uris
        assert "magento://catalog/categories" in uris

    async def test_resource_templates_listed(self) -> None:
        from magemcp.server import mcp

        templates = await mcp.list_resource_templates()
        uri_templates = [t.uriTemplate for t in templates]
        assert "magento://product/{sku}" in uri_templates
        assert "magento://order/{increment_id}" in uri_templates
        assert "magento://cms/{identifier}" in uri_templates

    async def test_resource_mime_types(self) -> None:
        from magemcp.server import mcp

        resources = await mcp.list_resources()
        for r in resources:
            assert r.mimeType == "application/json", f"{r.uri} has wrong MIME type"


class TestStoreConfigResource:
    async def test_returns_json(self, mock_env: None) -> None:
        from magemcp.tools.customer.store_config import _cache

        _cache.clear()
        _cache.set(
            "store_config:default",
            {"locale": "en_US", "base_currency_code": "USD"},
        )

        from magemcp.resources import register_resources
        from mcp.server.fastmcp import FastMCP

        _mcp = FastMCP("test-resources")
        register_resources(_mcp)

        # Read the resource
        contents = await _mcp.read_resource("magento://store/config")
        assert contents
        data = json.loads(contents[0].content)
        assert data["locale"] == "en_US"


class TestCategoryTreeResource:
    async def test_returns_json(self, mock_env: None) -> None:
        from magemcp.tools.customer.get_categories import _cache

        _cache.clear()
        _cache.set(
            "categories:default:None:None:None:20:1",
            {"categories": [], "total_count": 0, "page_info": {}},
        )

        from magemcp.resources import register_resources
        from mcp.server.fastmcp import FastMCP

        _mcp = FastMCP("test-resources-cat")
        register_resources(_mcp)

        contents = await _mcp.read_resource("magento://catalog/categories")
        assert contents
        data = json.loads(contents[0].content)
        assert "categories" in data or "total_count" in data


class TestProductResource:
    async def test_product_resource(self, mock_env: None) -> None:
        from magemcp.tools.customer.get_categories import _cache as cat_cache
        from magemcp.tools.customer.store_config import _cache as sc_cache

        cat_cache.clear()
        sc_cache.clear()

        gql_response = {
            "data": {
                "products": {
                    "items": [
                        {
                            "sku": "TEST-001",
                            "name": "Test Widget",
                            "url_key": "test-widget",
                            "stock_status": "IN_STOCK",
                            "__typename": "SimpleProduct",
                            "description": {"html": "<p>A widget</p>"},
                            "short_description": {"html": ""},
                            "meta_title": None,
                            "meta_description": None,
                            "price_range": {
                                "minimum_price": {
                                    "regular_price": {"value": 29.99, "currency": "USD"},
                                    "final_price": {"value": 29.99, "currency": "USD"},
                                    "discount": None,
                                },
                                "maximum_price": {
                                    "regular_price": {"value": 29.99, "currency": "USD"},
                                    "final_price": {"value": 29.99, "currency": "USD"},
                                    "discount": None,
                                },
                            },
                            "media_gallery": [],
                            "categories": [],
                            "custom_attributesV2": {"items": []},
                        }
                    ]
                }
            }
        }

        with respx.mock:
            respx.post(f"{BASE_URL}/graphql").mock(
                return_value=Response(200, json=gql_response)
            )

            from magemcp.resources import register_resources
            from mcp.server.fastmcp import FastMCP

            _mcp = FastMCP("test-product-resource")
            register_resources(_mcp)

            contents = await _mcp.read_resource("magento://product/TEST-001")

        assert contents
        data = json.loads(contents[0].content)
        assert data["sku"] == "TEST-001"
        assert data["name"] == "Test Widget"


class TestOrderResource:
    async def test_order_resource(self, mock_env: None) -> None:
        order_response = {
            "items": [
                {
                    "increment_id": "000000042",
                    "entity_id": 42,
                    "state": "complete",
                    "status": "complete",
                    "grand_total": 99.0,
                    "subtotal": 90.0,
                    "shipping_amount": 9.0,
                    "tax_amount": 0.0,
                    "total_qty_ordered": 1,
                    "customer_firstname": "Jane",
                    "customer_lastname": "Doe",
                    "customer_email": "jane@example.com",
                    "order_currency_code": "USD",
                    "created_at": "2025-03-01 10:00:00",
                    "updated_at": "2025-03-02 10:00:00",
                    "items": [],
                    "extension_attributes": {"shipping_assignments": []},
                }
            ],
            "total_count": 1,
        }

        with respx.mock:
            respx.get(f"{BASE_URL}/rest/default/V1/orders").mock(
                return_value=Response(200, json=order_response)
            )

            from magemcp.resources import register_resources
            from mcp.server.fastmcp import FastMCP

            _mcp = FastMCP("test-order-resource")
            register_resources(_mcp)

            contents = await _mcp.read_resource("magento://order/000000042")

        assert contents
        data = json.loads(contents[0].content)
        assert data["increment_id"] == "000000042"
        assert data["status"] == "complete"


class TestStoreConfigResourceLive:
    async def test_fetches_when_cache_empty(self, mock_env: None, respx_mock) -> None:
        from magemcp.tools.customer.store_config import _cache

        _cache.clear()

        gql_response = {"data": {"storeConfig": {"locale": "fr_FR", "base_currency_code": "EUR"}}}
        respx_mock.post(f"{BASE_URL}/graphql").mock(
            return_value=Response(200, json=gql_response)
        )

        from magemcp.resources import register_resources
        from mcp.server.fastmcp import FastMCP

        _mcp = FastMCP("test-sc-live")
        register_resources(_mcp)

        contents = await _mcp.read_resource("magento://store/config")
        data = json.loads(contents[0].content)
        assert data["locale"] == "fr_FR"


class TestCategoryTreeResourceLive:
    async def test_fetches_when_cache_empty(self, mock_env: None, respx_mock) -> None:
        from magemcp.tools.customer.get_categories import _cache

        _cache.clear()

        gql_response = {
            "data": {
                "categories": {
                    "items": [],
                    "total_count": 0,
                    "page_info": {"current_page": 1, "page_size": 20, "total_pages": 1},
                }
            }
        }
        respx_mock.post(f"{BASE_URL}/graphql").mock(
            return_value=Response(200, json=gql_response)
        )

        from magemcp.resources import register_resources
        from mcp.server.fastmcp import FastMCP

        _mcp = FastMCP("test-cat-live")
        register_resources(_mcp)

        contents = await _mcp.read_resource("magento://catalog/categories")
        data = json.loads(contents[0].content)
        assert "categories" in data


class TestProductResourceNotFound:
    async def test_not_found_raises(self, mock_env: None, respx_mock) -> None:
        gql_response = {"data": {"products": {"items": []}}}
        respx_mock.post(f"{BASE_URL}/graphql").mock(
            return_value=Response(200, json=gql_response)
        )

        from magemcp.resources import register_resources
        from mcp.server.fastmcp import FastMCP

        _mcp = FastMCP("test-product-nf")
        register_resources(_mcp)

        # FastMCP wraps resource errors in ValueError
        with pytest.raises((ValueError, Exception), match="NOPE"):
            await _mcp.read_resource("magento://product/NOPE")


class TestOrderResourceNotFound:
    async def test_not_found_raises(self, mock_env: None, respx_mock) -> None:
        respx_mock.get(f"{BASE_URL}/rest/default/V1/orders").mock(
            return_value=Response(200, json={"items": [], "total_count": 0})
        )

        from magemcp.resources import register_resources
        from mcp.server.fastmcp import FastMCP

        _mcp = FastMCP("test-order-nf")
        register_resources(_mcp)

        with pytest.raises((ValueError, Exception), match="999999"):
            await _mcp.read_resource("magento://order/999999")


class TestCmsPageResource:
    async def test_returns_cms_content(self, mock_env: None, respx_mock) -> None:
        respx_mock.get(f"{BASE_URL}/rest/default/V1/cmsPage/search").mock(
            return_value=Response(200, json={
                "items": [{
                    "id": 5,
                    "identifier": "about-us",
                    "title": "About Us",
                    "content": "<p>About us content.</p>",
                    "is_active": True,
                    "page_layout": "1column",
                }],
                "total_count": 1,
            })
        )

        from magemcp.resources import register_resources
        from mcp.server.fastmcp import FastMCP

        _mcp = FastMCP("test-cms-resource")
        register_resources(_mcp)

        contents = await _mcp.read_resource("magento://cms/about-us")
        data = json.loads(contents[0].content)
        assert data["identifier"] == "about-us"
        assert data["title"] == "About Us"
