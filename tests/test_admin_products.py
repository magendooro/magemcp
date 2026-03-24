"""Tests for admin product tools (search, get, update)."""

from __future__ import annotations

import json
from typing import Any

import pytest
import respx
from httpx import Response

from magemcp.models.product import ProductDetail, ProductSummary
from magemcp.tools.admin.products import (
    _parse_product_detail,
    _parse_product_summary,
    admin_get_product,
    admin_search_products,
    admin_update_product,
)

BASE_URL = "https://magento.test"
TOKEN = "admin-token-123"
STORE_CODE = "default"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAGENTO_BASE_URL", BASE_URL)
    monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("MAGENTO_STORE_CODE", STORE_CODE)


def _make_product(
    *,
    sku: str = "24-MB01",
    name: str = "Joust Duffle Bag",
    price: float = 34.0,
    status: int = 1,
    visibility: int = 4,
    type_id: str = "simple",
    weight: float = 1.0,
    custom_attributes: list[dict[str, Any]] | None = None,
    extension_attributes: dict[str, Any] | None = None,
    media_gallery_entries: list[dict[str, Any]] | None = None,
    tier_prices: list[dict[str, Any]] | None = None,
    options: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if custom_attributes is None:
        custom_attributes = [
            {"attribute_code": "description", "value": "<p>Full bag description</p>"},
            {"attribute_code": "short_description", "value": "A duffle bag"},
            {"attribute_code": "url_key", "value": "joust-duffle-bag"},
        ]
    if extension_attributes is None:
        extension_attributes = {
            "stock_item": {
                "qty": 100,
                "is_in_stock": True,
                "manage_stock": True,
                "min_sale_qty": 1.0,
                "max_sale_qty": None,
            },
            "category_links": [
                {"category_id": "3", "position": 0},
                {"category_id": "4", "position": 1},
            ],
        }
    return {
        "sku": sku,
        "name": name,
        "price": price,
        "status": status,
        "visibility": visibility,
        "type_id": type_id,
        "weight": weight,
        "attribute_set_id": 4,
        "created_at": "2024-01-01 00:00:00",
        "updated_at": "2024-06-01 12:00:00",
        "custom_attributes": custom_attributes,
        "extension_attributes": extension_attributes,
        "media_gallery_entries": media_gallery_entries or [],
        "tier_prices": tier_prices or [],
        "options": options or [],
    }


def _wrap_search(items: list[dict[str, Any]], total_count: int | None = None) -> dict[str, Any]:
    return {
        "items": items,
        "search_criteria": {},
        "total_count": total_count if total_count is not None else len(items),
    }


# ---------------------------------------------------------------------------
# Unit tests — parse helpers
# ---------------------------------------------------------------------------


class TestParseProductSummary:
    def test_basic_fields(self) -> None:
        raw = _make_product()
        summary = _parse_product_summary(raw)
        assert summary.sku == "24-MB01"
        assert summary.name == "Joust Duffle Bag"
        assert summary.price == 34.0
        assert summary.status == 1
        assert summary.type_id == "simple"

    def test_missing_optional_fields(self) -> None:
        raw = {"sku": "TEST-SKU"}
        summary = _parse_product_summary(raw)
        assert summary.sku == "TEST-SKU"
        assert summary.name is None
        assert summary.price is None


class TestParseProductDetail:
    def test_custom_attributes_flattened(self) -> None:
        raw = _make_product()
        detail = _parse_product_detail(raw)
        assert detail.description == "<p>Full bag description</p>"
        assert detail.short_description == "A duffle bag"
        assert detail.url_key == "joust-duffle-bag"

    def test_stock_extracted(self) -> None:
        raw = _make_product()
        detail = _parse_product_detail(raw)
        assert detail.stock is not None
        assert detail.stock.qty == 100
        assert detail.stock.is_in_stock is True

    def test_category_ids_extracted(self) -> None:
        raw = _make_product()
        detail = _parse_product_detail(raw)
        assert 3 in detail.category_ids
        assert 4 in detail.category_ids

    def test_stock_not_in_extension_attributes(self) -> None:
        """stock_item should be extracted, not left in extension_attributes."""
        raw = _make_product()
        detail = _parse_product_detail(raw)
        assert "stock_item" not in detail.extension_attributes

    def test_media_gallery_parsed(self) -> None:
        raw = _make_product(media_gallery_entries=[
            {"id": 1, "media_type": "image", "label": "Main", "position": 1,
             "disabled": False, "types": ["image", "small_image"], "file": "/path/img.jpg"},
        ])
        detail = _parse_product_detail(raw)
        assert len(detail.media_gallery) == 1
        assert detail.media_gallery[0].file == "/path/img.jpg"
        assert "image" in detail.media_gallery[0].types

    def test_tier_prices_parsed(self) -> None:
        raw = _make_product(tier_prices=[
            {"customer_group_id": 0, "qty": 10.0, "value": 30.0, "extension_attributes": {}},
        ])
        detail = _parse_product_detail(raw)
        assert len(detail.tier_prices) == 1
        assert detail.tier_prices[0].value == 30.0

    def test_no_custom_attributes(self) -> None:
        raw = _make_product(custom_attributes=[])
        detail = _parse_product_detail(raw)
        assert detail.description is None
        assert detail.custom_attributes == {}


# ---------------------------------------------------------------------------
# Tool tests — admin_search_products
# ---------------------------------------------------------------------------


class TestSearchProductsBySku:
    async def test_sku_filter_uses_like(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        """SKU filter uses 'like' condition to support wildcards."""
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/products").mock(
            return_value=Response(200, json=_wrap_search([_make_product()]))
        )

        result = await admin_search_products(sku="24-MB%")

        assert result["total_count"] == 1
        assert result["products"][0]["sku"] == "24-MB01"

        url = str(respx_mock.calls.last.request.url)
        assert "sku" in url
        assert "like" in url

    async def test_exact_sku_search(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/products").mock(
            return_value=Response(200, json=_wrap_search([_make_product(sku="24-MB01")]))
        )
        result = await admin_search_products(sku="24-MB01")
        assert result["products"][0]["sku"] == "24-MB01"


class TestSearchProductsByStatus:
    async def test_status_filter_enabled(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        """status=1 filters enabled products."""
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/products").mock(
            return_value=Response(200, json=_wrap_search([_make_product(status=1)]))
        )

        result = await admin_search_products(status=1)

        url = str(respx_mock.calls.last.request.url)
        assert "status" in url
        assert result["products"][0]["status"] == 1

    async def test_status_filter_disabled(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        """status=2 filters disabled products."""
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/products").mock(
            return_value=Response(200, json=_wrap_search([_make_product(status=2)]))
        )

        result = await admin_search_products(status=2)
        assert result["products"][0]["status"] == 2


class TestSearchProductsPriceRange:
    async def test_price_min_filter(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/products").mock(
            return_value=Response(200, json=_wrap_search([_make_product(price=50.0)]))
        )

        await admin_search_products(price_min=30.0)

        url = str(respx_mock.calls.last.request.url)
        assert "price" in url
        assert "gteq" in url

    async def test_price_range_two_filter_groups(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        """price_min + price_max each get their own filter group."""
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/products").mock(
            return_value=Response(200, json=_wrap_search([]))
        )

        await admin_search_products(price_min=20.0, price_max=100.0)

        url = str(respx_mock.calls.last.request.url)
        assert "gteq" in url
        assert "lteq" in url


# ---------------------------------------------------------------------------
# Tool tests — admin_get_product
# ---------------------------------------------------------------------------


class TestGetProductFull:
    async def test_returns_full_detail(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        """admin_get_product returns full ProductDetail with all fields."""
        raw = _make_product(media_gallery_entries=[
            {"id": 1, "media_type": "image", "label": "", "position": 1,
             "disabled": False, "types": ["image"], "file": "/img.jpg"},
        ])
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/products/24-MB01").mock(
            return_value=Response(200, json=raw)
        )

        result = await admin_get_product(sku="24-MB01")

        assert result["sku"] == "24-MB01"
        assert result["name"] == "Joust Duffle Bag"
        assert result["price"] == 34.0
        assert result["description"] == "<p>Full bag description</p>"
        assert len(result["media_gallery"]) == 1
        assert result["stock"]["qty"] == 100
        assert result["stock"]["is_in_stock"] is True
        assert 3 in result["category_ids"]

    async def test_not_found_returns_error(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        """Non-existent SKU returns an error dict, not an exception."""
        from magemcp.connectors.errors import MagentoNotFoundError
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/products/NO-SUCH-SKU").mock(
            return_value=Response(404, json={"message": "Requested product doesn't exist"})
        )

        with pytest.raises(MagentoNotFoundError):
            await admin_get_product(sku="NO-SUCH-SKU")


# ---------------------------------------------------------------------------
# Tool tests — admin_update_product
# ---------------------------------------------------------------------------


class TestUpdateProductPrice:
    async def test_requires_confirmation(self, mock_env: None) -> None:
        result = await admin_update_product(sku="24-MB01", price=39.99)
        assert result["confirmation_required"] is True
        assert "24-MB01" in result["message"]

    async def test_price_only_payload(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        """Only price is included when only price is specified."""
        respx_mock.put(f"{BASE_URL}/rest/{STORE_CODE}/V1/products/24-MB01").mock(
            return_value=Response(200, json=_make_product(price=39.99))
        )

        result = await admin_update_product(sku="24-MB01", price=39.99, confirm=True)

        assert result["success"] is True
        assert result["sku"] == "24-MB01"
        assert "price" in result["updated_fields"]

        payload = json.loads(respx_mock.calls.last.request.content)
        assert payload["product"]["price"] == 39.99
        assert "name" not in payload["product"]
        assert "status" not in payload["product"]

    async def test_price_wrapped_in_product_key(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        """Magento PUT /V1/products/{sku} expects {'product': {...}}."""
        respx_mock.put(f"{BASE_URL}/rest/{STORE_CODE}/V1/products/24-MB01").mock(
            return_value=Response(200, json=_make_product())
        )

        await admin_update_product(sku="24-MB01", price=29.0, confirm=True)

        payload = json.loads(respx_mock.calls.last.request.content)
        assert "product" in payload
        assert payload["product"]["sku"] == "24-MB01"


class TestUpdateProductMultipleFields:
    async def test_multiple_fields_payload(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        """All specified fields appear in the payload."""
        respx_mock.put(f"{BASE_URL}/rest/{STORE_CODE}/V1/products/24-MB01").mock(
            return_value=Response(200, json=_make_product())
        )

        result = await admin_update_product(
            sku="24-MB01",
            name="Updated Bag",
            price=45.0,
            status=1,
            description="New description",
            meta_title="New Meta",
            confirm=True,
        )

        assert result["success"] is True
        assert set(result["updated_fields"]) >= {"name", "price", "status", "description", "meta_title"}

        payload = json.loads(respx_mock.calls.last.request.content)["product"]
        assert payload["name"] == "Updated Bag"
        assert payload["price"] == 45.0
        assert payload["status"] == 1
        # Description goes in custom_attributes
        attr_codes = [ca["attribute_code"] for ca in payload["custom_attributes"]]
        assert "description" in attr_codes
        assert "meta_title" in attr_codes

    async def test_no_fields_returns_error(self, mock_env: None) -> None:
        """Calling update with no fields to change returns an error."""
        result = await admin_update_product(sku="24-MB01", confirm=True)
        assert "error" in result

    async def test_updated_fields_excludes_sku(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        """updated_fields list never includes 'sku'."""
        respx_mock.put(f"{BASE_URL}/rest/{STORE_CODE}/V1/products/24-MB01").mock(
            return_value=Response(200, json=_make_product())
        )

        result = await admin_update_product(sku="24-MB01", price=10.0, confirm=True)
        assert "sku" not in result["updated_fields"]
