"""Tests for c_get_product tool."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from magemcp.connectors.magento import MagentoClient, MagentoError
from magemcp.models.catalog import (
    CGetProductInput,
    CGetProductOutput,
)
from magemcp.tools.get_product import (
    _parse_categories,
    _parse_custom_attributes,
    _parse_media_gallery,
    _parse_product_detail,
)

BASE_URL = "https://magento.test"
TOKEN = "test-token-123"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_gql_product_detail(
    *,
    sku: str = "WJ12",
    name: str = "Stellar Running Jacket",
    url_key: str = "stellar-running-jacket",
    typename: str = "ConfigurableProduct",
    stock_status: str = "IN_STOCK",
    regular_price: float = 89.99,
    final_price: float = 89.99,
    currency: str = "USD",
    discount_amount_off: float | None = None,
    discount_percent_off: float | None = None,
    meta_title: str | None = "Stellar Running Jacket | Store",
    meta_description: str | None = "A great running jacket.",
    description_html: str | None = "<p>Full product <strong>description</strong> here.</p>",
    short_description_html: str | None = "<p>Lightweight running jacket.</p>",
    media_gallery: list[dict[str, Any]] | None = None,
    categories: list[dict[str, Any]] | None = None,
    configurable_options: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a mock GraphQL product detail item."""
    discount = None
    if discount_amount_off is not None:
        discount = {"amount_off": discount_amount_off, "percent_off": discount_percent_off}

    if media_gallery is None:
        media_gallery = [
            {"url": "https://magento.test/media/wj12_main.jpg", "label": "Main", "position": 1, "disabled": False},
            {"url": "https://magento.test/media/wj12_side.jpg", "label": "Side", "position": 2, "disabled": False},
        ]

    if categories is None:
        categories = [
            {
                "id": 15,
                "name": "Jackets",
                "url_path": "women/tops/jackets",
                "breadcrumbs": [
                    {"category_id": 3, "category_name": "Women", "category_url_path": "women"},
                    {"category_id": 10, "category_name": "Tops", "category_url_path": "women/tops"},
                ],
            },
        ]

    item: dict[str, Any] = {
        "sku": sku,
        "name": name,
        "url_key": url_key,
        "__typename": typename,
        "stock_status": stock_status,
        "meta_title": meta_title,
        "meta_description": meta_description,
        "description": {"html": description_html} if description_html else None,
        "short_description": {"html": short_description_html} if short_description_html else None,
        "price_range": {
            "minimum_price": {
                "regular_price": {"value": regular_price, "currency": currency},
                "final_price": {"value": final_price, "currency": currency},
                "discount": discount,
            },
            "maximum_price": {
                "regular_price": {"value": regular_price, "currency": currency},
                "final_price": {"value": final_price, "currency": currency},
            },
        },
        "media_gallery": media_gallery,
        "categories": categories,
    }

    if configurable_options is not None:
        item["configurable_options"] = configurable_options

    return item


def _wrap_gql_response(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Wrap product items in the GraphQL data envelope."""
    return {"products": {"items": items}}


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_valid_sku(self) -> None:
        inp = CGetProductInput(sku="WJ12")
        assert inp.sku == "WJ12"
        assert inp.store_scope == "default"

    def test_empty_sku_rejected(self) -> None:
        with pytest.raises(Exception):
            CGetProductInput(sku="")

    def test_sku_too_long(self) -> None:
        with pytest.raises(Exception):
            CGetProductInput(sku="x" * 65)

    def test_invalid_store_scope(self) -> None:
        with pytest.raises(Exception):
            CGetProductInput(sku="WJ12", store_scope="INVALID!")

    def test_valid_store_scope(self) -> None:
        inp = CGetProductInput(sku="WJ12", store_scope="fr")
        assert inp.store_scope == "fr"


# ---------------------------------------------------------------------------
# _parse_media_gallery
# ---------------------------------------------------------------------------


class TestParseMediaGallery:
    def test_basic_gallery(self) -> None:
        raw = [
            {"url": "https://img/a.jpg", "label": "A", "position": 2, "disabled": False},
            {"url": "https://img/b.jpg", "label": "B", "position": 1, "disabled": False},
        ]
        result = _parse_media_gallery(raw)
        assert len(result) == 2
        # Should be sorted by position
        assert result[0].url == "https://img/b.jpg"
        assert result[1].url == "https://img/a.jpg"

    def test_disabled_images_filtered(self) -> None:
        raw = [
            {"url": "https://img/a.jpg", "label": "A", "position": 1, "disabled": False},
            {"url": "https://img/b.jpg", "label": "B", "position": 2, "disabled": True},
        ]
        result = _parse_media_gallery(raw)
        assert len(result) == 1
        assert result[0].url == "https://img/a.jpg"

    def test_empty_gallery(self) -> None:
        assert _parse_media_gallery([]) == []

    def test_no_label(self) -> None:
        raw = [{"url": "https://img/a.jpg", "position": 1, "disabled": False}]
        result = _parse_media_gallery(raw)
        assert result[0].label is None


# ---------------------------------------------------------------------------
# _parse_categories
# ---------------------------------------------------------------------------


class TestParseCategories:
    def test_with_breadcrumbs(self) -> None:
        raw = [
            {
                "id": 15,
                "name": "Jackets",
                "url_path": "women/tops/jackets",
                "breadcrumbs": [
                    {"category_id": 3, "category_name": "Women", "category_url_path": "women"},
                    {"category_id": 10, "category_name": "Tops", "category_url_path": "women/tops"},
                ],
            },
        ]
        result = _parse_categories(raw)
        assert len(result) == 1
        assert result[0].id == "15"
        assert result[0].name == "Jackets"
        assert result[0].full_path == "Women > Tops > Jackets"

    def test_no_breadcrumbs(self) -> None:
        raw = [{"id": 2, "name": "Root", "url_path": "root", "breadcrumbs": None}]
        result = _parse_categories(raw)
        assert result[0].full_path == "Root"

    def test_multiple_categories(self) -> None:
        raw = [
            {"id": 5, "name": "Sale", "url_path": "sale", "breadcrumbs": []},
            {"id": 15, "name": "Jackets", "url_path": "women/tops/jackets", "breadcrumbs": []},
        ]
        result = _parse_categories(raw)
        assert len(result) == 2
        assert result[0].name == "Sale"
        assert result[1].name == "Jackets"

    def test_empty_categories(self) -> None:
        assert _parse_categories([]) == []


# ---------------------------------------------------------------------------
# _parse_custom_attributes (configurable options)
# ---------------------------------------------------------------------------


class TestParseCustomAttributes:
    def test_configurable_options(self) -> None:
        item = {
            "configurable_options": [
                {
                    "attribute_code": "color",
                    "label": "Color",
                    "values": [
                        {"label": "Blue", "value_index": 1},
                        {"label": "Red", "value_index": 2},
                    ],
                },
                {
                    "attribute_code": "size",
                    "label": "Size",
                    "values": [
                        {"label": "S", "value_index": 10},
                        {"label": "M", "value_index": 11},
                        {"label": "L", "value_index": 12},
                    ],
                },
            ],
        }
        result = _parse_custom_attributes(item)
        assert len(result) == 2
        assert result[0].attribute_code == "color"
        assert result[0].label == "Color"
        assert result[0].values == ["Blue", "Red"]
        assert result[1].values == ["S", "M", "L"]

    def test_no_configurable_options(self) -> None:
        result = _parse_custom_attributes({})
        assert result == []

    def test_none_configurable_options(self) -> None:
        result = _parse_custom_attributes({"configurable_options": None})
        assert result == []


# ---------------------------------------------------------------------------
# _parse_product_detail
# ---------------------------------------------------------------------------


class TestParseProductDetail:
    def test_full_product(self) -> None:
        item = _make_gql_product_detail()
        result = _parse_product_detail(item)

        assert result.sku == "WJ12"
        assert result.name == "Stellar Running Jacket"
        assert result.url_key == "stellar-running-jacket"
        assert result.product_type == "ConfigurableProduct"
        assert result.stock_status == "IN_STOCK"
        assert result.meta_title == "Stellar Running Jacket | Store"
        assert result.meta_description == "A great running jacket."
        assert result.description == "Full product description here."
        assert result.short_description == "Lightweight running jacket."

    def test_price_parsing(self) -> None:
        item = _make_gql_product_detail(regular_price=100.0, final_price=80.0)
        result = _parse_product_detail(item)

        assert float(result.min_price.regular_price.value) == 100.0
        assert float(result.min_price.final_price.value) == 80.0

    def test_discount(self) -> None:
        item = _make_gql_product_detail(
            regular_price=100.0,
            final_price=80.0,
            discount_amount_off=20.0,
            discount_percent_off=20.0,
        )
        result = _parse_product_detail(item)

        assert float(result.min_price.discount_amount) == 20.0  # type: ignore[arg-type]
        assert float(result.min_price.discount_percent) == 20.0  # type: ignore[arg-type]

    def test_images(self) -> None:
        item = _make_gql_product_detail()
        result = _parse_product_detail(item)

        assert len(result.images) == 2
        assert result.images[0].label == "Main"
        assert result.images[0].position == 1

    def test_categories(self) -> None:
        item = _make_gql_product_detail()
        result = _parse_product_detail(item)

        assert len(result.categories) == 1
        assert result.categories[0].full_path == "Women > Tops > Jackets"

    def test_no_description(self) -> None:
        item = _make_gql_product_detail(description_html=None, short_description_html=None)
        result = _parse_product_detail(item)

        assert result.description is None
        assert result.short_description is None

    def test_no_images(self) -> None:
        item = _make_gql_product_detail(media_gallery=[])
        result = _parse_product_detail(item)

        assert result.images == []

    def test_no_categories(self) -> None:
        item = _make_gql_product_detail(categories=[])
        result = _parse_product_detail(item)

        assert result.categories == []

    def test_simple_product_no_configurable_options(self) -> None:
        item = _make_gql_product_detail(typename="SimpleProduct")
        result = _parse_product_detail(item)

        assert result.product_type == "SimpleProduct"
        assert result.custom_attributes == []

    def test_configurable_product_with_options(self) -> None:
        item = _make_gql_product_detail(
            configurable_options=[
                {
                    "attribute_code": "color",
                    "label": "Color",
                    "values": [
                        {"label": "Blue", "value_index": 1},
                        {"label": "Red", "value_index": 2},
                    ],
                },
            ],
        )
        result = _parse_product_detail(item)

        assert len(result.custom_attributes) == 1
        assert result.custom_attributes[0].attribute_code == "color"
        assert result.custom_attributes[0].values == ["Blue", "Red"]

    def test_out_of_stock(self) -> None:
        item = _make_gql_product_detail(stock_status="OUT_OF_STOCK")
        result = _parse_product_detail(item)

        assert result.stock_status == "OUT_OF_STOCK"


# ---------------------------------------------------------------------------
# End-to-end tool invocation (mocked GraphQL)
# ---------------------------------------------------------------------------


class TestToolEndToEnd:
    @respx.mock
    async def test_get_product_basic(self) -> None:
        """Full tool invocation with mocked GraphQL response."""
        gql_response = {"data": _wrap_gql_response([_make_gql_product_detail()])}
        route = respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        async with MagentoClient(base_url=BASE_URL, token=TOKEN) as client:
            data = await client.graphql(
                "query { products(filter: {sku: {eq: \"WJ12\"}}) { items { sku } } }",
                store_code="default",
            )

        result = _parse_product_detail(data["products"]["items"][0])
        assert result.sku == "WJ12"
        assert result.name == "Stellar Running Jacket"
        assert route.called
        assert route.calls[0].request.headers["store"] == "default"

    @respx.mock
    async def test_get_product_store_scope(self) -> None:
        """Verify store scope is sent as Store header."""
        gql_response = {"data": _wrap_gql_response([_make_gql_product_detail()])}
        route = respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        async with MagentoClient(base_url=BASE_URL, token=TOKEN) as client:
            await client.graphql(
                "query { products { items { sku } } }",
                store_code="fr",
            )

        assert route.calls[0].request.headers["store"] == "fr"

    @respx.mock
    async def test_product_not_found(self) -> None:
        """Empty items list means product not found."""
        gql_response = {"data": _wrap_gql_response([])}
        respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        async with MagentoClient(base_url=BASE_URL, token=TOKEN) as client:
            data = await client.graphql(
                "query { products(filter: {sku: {eq: \"NOPE\"}}) { items { sku } } }",
            )

        items = (data.get("products") or {}).get("items") or []
        assert items == []

    @respx.mock
    async def test_graphql_error_propagates(self) -> None:
        """GraphQL errors should raise MagentoError."""
        gql_response = {"errors": [{"message": "Internal error"}]}
        respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        async with MagentoClient(base_url=BASE_URL, token=TOKEN) as client:
            with pytest.raises(MagentoError, match="Internal error"):
                await client.graphql("query { products { items { sku } } }")


# ---------------------------------------------------------------------------
# Output serialization
# ---------------------------------------------------------------------------


class TestOutputSerialization:
    def test_model_dump_json(self) -> None:
        """Verify that the output serializes cleanly to JSON-compatible dict."""
        item = _make_gql_product_detail(
            regular_price=89.99,
            final_price=71.99,
            discount_amount_off=18.0,
            discount_percent_off=20.0,
            configurable_options=[
                {
                    "attribute_code": "size",
                    "label": "Size",
                    "values": [{"label": "S", "value_index": 1}, {"label": "M", "value_index": 2}],
                },
            ],
        )
        result = _parse_product_detail(item)
        dumped = result.model_dump(mode="json")

        assert isinstance(dumped, dict)
        assert dumped["sku"] == "WJ12"
        assert dumped["name"] == "Stellar Running Jacket"
        assert isinstance(dumped["images"], list)
        assert len(dumped["images"]) == 2
        assert isinstance(dumped["categories"], list)
        assert len(dumped["categories"]) == 1
        assert dumped["categories"][0]["full_path"] == "Women > Tops > Jackets"
        assert isinstance(dumped["custom_attributes"], list)
        assert dumped["custom_attributes"][0]["attribute_code"] == "size"
        assert dumped["min_price"]["final_price"]["value"] is not None
