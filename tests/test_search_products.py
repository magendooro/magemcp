"""Tests for c_search_products tool."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from magemcp.connectors.magento import MagentoClient, MagentoError
from magemcp.models.catalog import (
    CSearchProductsInput,
    strip_html,
)
from magemcp.tools.customer.search_products import (
    _build_variables,
    _parse_product,
    _parse_response,
)

BASE_URL = "https://magento.test"
TOKEN = "test-token-123"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_gql_product(
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
    image_url: str | None = "https://magento.test/media/catalog/product/wj12.jpg",
    image_label: str | None = "Stellar Running Jacket",
    short_description_html: str | None = "<p>Lightweight running jacket.</p>",
) -> dict[str, Any]:
    """Build a mock GraphQL product item."""
    discount = None
    if discount_amount_off is not None:
        discount = {"amount_off": discount_amount_off, "percent_off": discount_percent_off}

    return {
        "sku": sku,
        "name": name,
        "url_key": url_key,
        "__typename": typename,
        "stock_status": stock_status,
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
        "small_image": {"url": image_url, "label": image_label} if image_url else None,
        "short_description": {"html": short_description_html} if short_description_html else None,
    }


def _make_gql_response(
    items: list[dict[str, Any]] | None = None,
    total_count: int = 1,
    current_page: int = 1,
    page_size: int = 20,
    total_pages: int = 1,
) -> dict[str, Any]:
    """Build a complete GraphQL products response (the 'data' portion)."""
    if items is None:
        items = [_make_gql_product()]
    return {
        "products": {
            "items": items,
            "total_count": total_count,
            "page_info": {
                "current_page": current_page,
                "page_size": page_size,
                "total_pages": total_pages,
            },
        },
    }


# ---------------------------------------------------------------------------
# strip_html
# ---------------------------------------------------------------------------


class TestStripHtml:
    def test_strips_tags(self) -> None:
        assert strip_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_returns_none_for_none(self) -> None:
        assert strip_html(None) is None

    def test_returns_none_for_empty(self) -> None:
        assert strip_html("") is None

    def test_returns_none_for_tags_only(self) -> None:
        assert strip_html("<br/><br/>") is None

    def test_preserves_text(self) -> None:
        assert strip_html("no tags here") == "no tags here"


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_defaults(self) -> None:
        inp = CSearchProductsInput()
        assert inp.search is None
        assert inp.page_size == 20
        assert inp.current_page == 1
        assert inp.sort_field == "relevance"
        assert inp.sort_direction == "ASC"
        assert inp.store_scope == "default"
        assert inp.in_stock_only is False

    def test_page_size_max(self) -> None:
        with pytest.raises(Exception):
            CSearchProductsInput(page_size=51)

    def test_page_size_min(self) -> None:
        with pytest.raises(Exception):
            CSearchProductsInput(page_size=0)

    def test_invalid_sort_field(self) -> None:
        with pytest.raises(Exception):
            CSearchProductsInput(sort_field="invalid")

    def test_invalid_sort_direction(self) -> None:
        with pytest.raises(Exception):
            CSearchProductsInput(sort_direction="UP")

    def test_invalid_store_scope(self) -> None:
        with pytest.raises(Exception):
            CSearchProductsInput(store_scope="INVALID!")

    def test_search_max_length(self) -> None:
        with pytest.raises(Exception):
            CSearchProductsInput(search="x" * 201)

    def test_valid_full_input(self) -> None:
        inp = CSearchProductsInput(
            search="jacket",
            category_id="15",
            price_from=50.0,
            price_to=150.0,
            in_stock_only=True,
            store_scope="fr",
            page_size=10,
            current_page=2,
            sort_field="price",
            sort_direction="DESC",
        )
        assert inp.search == "jacket"
        assert inp.category_id == "15"
        assert inp.price_from == 50.0
        assert inp.price_to == 150.0


# ---------------------------------------------------------------------------
# _build_variables
# ---------------------------------------------------------------------------


class TestBuildVariables:
    def test_minimal(self) -> None:
        inp = CSearchProductsInput()
        variables = _build_variables(inp)
        assert variables == {"pageSize": 20, "currentPage": 1, "search": ""}

    def test_with_search(self) -> None:
        inp = CSearchProductsInput(search="jacket")
        variables = _build_variables(inp)
        assert variables["search"] == "jacket"

    def test_with_category_filter(self) -> None:
        inp = CSearchProductsInput(category_id="15")
        variables = _build_variables(inp)
        assert variables["filter"]["category_id"] == {"eq": "15"}

    def test_with_price_range(self) -> None:
        inp = CSearchProductsInput(price_from=50.0, price_to=150.0)
        variables = _build_variables(inp)
        assert variables["filter"]["price"] == {"from": "50.0", "to": "150.0"}

    def test_with_price_from_only(self) -> None:
        inp = CSearchProductsInput(price_from=25.0)
        variables = _build_variables(inp)
        assert variables["filter"]["price"] == {"from": "25.0"}
        assert "to" not in variables["filter"]["price"]

    def test_with_price_to_only(self) -> None:
        inp = CSearchProductsInput(price_to=100.0)
        variables = _build_variables(inp)
        assert variables["filter"]["price"] == {"to": "100.0"}

    def test_sort_relevance_skipped(self) -> None:
        inp = CSearchProductsInput(sort_field="relevance")
        variables = _build_variables(inp)
        assert "sort" not in variables

    def test_sort_by_price(self) -> None:
        inp = CSearchProductsInput(sort_field="price", sort_direction="DESC")
        variables = _build_variables(inp)
        assert variables["sort"] == {"price": "DESC"}

    def test_sort_by_name(self) -> None:
        inp = CSearchProductsInput(sort_field="name", sort_direction="ASC")
        variables = _build_variables(inp)
        assert variables["sort"] == {"name": "ASC"}

    def test_combined_filters(self) -> None:
        inp = CSearchProductsInput(
            search="shirt",
            category_id="3",
            price_from=10.0,
            price_to=50.0,
            page_size=5,
            current_page=2,
        )
        variables = _build_variables(inp)
        assert variables["search"] == "shirt"
        assert variables["pageSize"] == 5
        assert variables["currentPage"] == 2
        assert variables["filter"]["category_id"] == {"eq": "3"}
        assert variables["filter"]["price"] == {"from": "10.0", "to": "50.0"}

    def test_filter_only_no_default_search(self) -> None:
        """When a filter is provided, no default search should be added."""
        inp = CSearchProductsInput(category_id="15")
        variables = _build_variables(inp)
        assert "search" not in variables


# ---------------------------------------------------------------------------
# _parse_product
# ---------------------------------------------------------------------------


class TestParseProduct:
    def test_basic_product(self) -> None:
        item = _make_gql_product()
        product = _parse_product(item)

        assert product.sku == "WJ12"
        assert product.name == "Stellar Running Jacket"
        assert product.url_key == "stellar-running-jacket"
        assert product.product_type == "ConfigurableProduct"
        assert product.stock_status == "IN_STOCK"
        assert product.image_url == "https://magento.test/media/catalog/product/wj12.jpg"
        assert product.image_label == "Stellar Running Jacket"
        assert product.short_description == "Lightweight running jacket."

    def test_price_parsing(self) -> None:
        item = _make_gql_product(regular_price=100.0, final_price=80.0)
        product = _parse_product(item)

        assert float(product.min_price.regular_price.value) == 100.0
        assert float(product.min_price.final_price.value) == 80.0
        assert product.min_price.regular_price.currency == "USD"

    def test_discount_parsing(self) -> None:
        item = _make_gql_product(
            regular_price=100.0,
            final_price=80.0,
            discount_amount_off=20.0,
            discount_percent_off=20.0,
        )
        product = _parse_product(item)

        assert float(product.min_price.discount_amount) == 20.0  # type: ignore[arg-type]
        assert float(product.min_price.discount_percent) == 20.0  # type: ignore[arg-type]

    def test_no_discount(self) -> None:
        item = _make_gql_product()
        product = _parse_product(item)

        assert product.min_price.discount_amount is None
        assert product.min_price.discount_percent is None

    def test_no_image(self) -> None:
        item = _make_gql_product(image_url=None)
        product = _parse_product(item)

        assert product.image_url is None
        assert product.image_label is None

    def test_no_short_description(self) -> None:
        item = _make_gql_product(short_description_html=None)
        product = _parse_product(item)

        assert product.short_description is None

    def test_html_stripped_from_description(self) -> None:
        item = _make_gql_product(short_description_html="<p>Bold <strong>text</strong>!</p>")
        product = _parse_product(item)

        assert product.short_description == "Bold text!"

    def test_simple_product_typename(self) -> None:
        item = _make_gql_product(typename="SimpleProduct")
        product = _parse_product(item)

        assert product.product_type == "SimpleProduct"

    def test_out_of_stock(self) -> None:
        item = _make_gql_product(stock_status="OUT_OF_STOCK")
        product = _parse_product(item)

        assert product.stock_status == "OUT_OF_STOCK"


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------


class TestParseResponse:
    def test_basic_response(self) -> None:
        data = _make_gql_response(total_count=1)
        result = _parse_response(data, in_stock_only=False)

        assert len(result.products) == 1
        assert result.total_count == 1
        assert result.page_info.current_page == 1
        assert result.page_info.page_size == 20
        assert result.page_info.total_pages == 1

    def test_multiple_products(self) -> None:
        items = [
            _make_gql_product(sku="SKU1", name="Product 1"),
            _make_gql_product(sku="SKU2", name="Product 2"),
            _make_gql_product(sku="SKU3", name="Product 3"),
        ]
        data = _make_gql_response(items=items, total_count=3)
        result = _parse_response(data, in_stock_only=False)

        assert len(result.products) == 3
        assert result.products[0].sku == "SKU1"
        assert result.products[2].sku == "SKU3"

    def test_empty_results(self) -> None:
        data = _make_gql_response(items=[], total_count=0)
        result = _parse_response(data, in_stock_only=False)

        assert len(result.products) == 0
        assert result.total_count == 0

    def test_in_stock_only_filtering(self) -> None:
        items = [
            _make_gql_product(sku="IN1", stock_status="IN_STOCK"),
            _make_gql_product(sku="OUT1", stock_status="OUT_OF_STOCK"),
            _make_gql_product(sku="IN2", stock_status="IN_STOCK"),
        ]
        data = _make_gql_response(items=items, total_count=3)
        result = _parse_response(data, in_stock_only=True)

        assert len(result.products) == 2
        assert all(p.stock_status == "IN_STOCK" for p in result.products)

    def test_in_stock_only_false_keeps_all(self) -> None:
        items = [
            _make_gql_product(sku="IN1", stock_status="IN_STOCK"),
            _make_gql_product(sku="OUT1", stock_status="OUT_OF_STOCK"),
        ]
        data = _make_gql_response(items=items, total_count=2)
        result = _parse_response(data, in_stock_only=False)

        assert len(result.products) == 2

    def test_pagination_info(self) -> None:
        data = _make_gql_response(
            total_count=47,
            current_page=3,
            page_size=10,
            total_pages=5,
        )
        result = _parse_response(data, in_stock_only=False)

        assert result.total_count == 47
        assert result.page_info.current_page == 3
        assert result.page_info.page_size == 10
        assert result.page_info.total_pages == 5


# ---------------------------------------------------------------------------
# End-to-end tool invocation (mocked GraphQL)
# ---------------------------------------------------------------------------


class TestToolEndToEnd:
    @respx.mock
    async def test_search_products_basic(self) -> None:
        """Full tool invocation with mocked GraphQL response."""
        gql_response = {
            "data": _make_gql_response(
                items=[_make_gql_product()],
                total_count=1,
            ),
        }
        route = respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        async with MagentoClient(base_url=BASE_URL, token=TOKEN) as client:
            data = await client.graphql(
                "query { products { items { sku } } }",
                store_code="default",
            )

        result = _parse_response(data, in_stock_only=False)
        assert len(result.products) == 1
        assert result.products[0].sku == "WJ12"
        assert route.called
        assert route.calls[0].request.headers["store"] == "default"

    @respx.mock
    async def test_search_with_store_scope(self) -> None:
        """Verify store scope is sent as Store header."""
        gql_response = {"data": _make_gql_response(items=[], total_count=0)}
        route = respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        async with MagentoClient(base_url=BASE_URL, token=TOKEN) as client:
            await client.graphql("query { products { items { sku } } }", store_code="fr")

        assert route.calls[0].request.headers["store"] == "fr"

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
        data = _make_gql_response(
            items=[
                _make_gql_product(
                    regular_price=89.99,
                    final_price=71.99,
                    discount_amount_off=18.0,
                    discount_percent_off=20.0,
                ),
            ],
            total_count=1,
        )
        result = _parse_response(data, in_stock_only=False)
        dumped = result.model_dump(mode="json")

        assert isinstance(dumped, dict)
        assert isinstance(dumped["products"], list)
        assert dumped["products"][0]["sku"] == "WJ12"
        assert dumped["total_count"] == 1
        assert dumped["page_info"]["current_page"] == 1
        # Decimal values should serialize as strings or numbers
        assert dumped["products"][0]["min_price"]["final_price"]["value"] is not None
