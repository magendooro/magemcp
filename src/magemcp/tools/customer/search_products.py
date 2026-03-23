"""c_search_products — storefront product search via Magento GraphQL."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from magemcp.connectors.graphql_client import GraphQLClient
from magemcp.models.catalog import (
    CSearchProductsInput,
    CSearchProductsOutput,
    PageInfo,
    PriceAmount,
    ProductPrice,
    StorefrontProduct,
    strip_html,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GraphQL query
# ---------------------------------------------------------------------------

SEARCH_PRODUCTS_QUERY = """
query SearchProducts(
  $search: String
  $filter: ProductAttributeFilterInput
  $sort: ProductAttributeSortInput
  $pageSize: Int!
  $currentPage: Int!
) {
  products(
    search: $search
    filter: $filter
    sort: $sort
    pageSize: $pageSize
    currentPage: $currentPage
  ) {
    items {
      sku
      name
      url_key
      stock_status
      price_range {
        minimum_price {
          regular_price { value currency }
          final_price { value currency }
          discount { amount_off percent_off }
        }
        maximum_price {
          regular_price { value currency }
          final_price { value currency }
        }
      }
      small_image { url label }
      short_description { html }
      __typename
    }
    total_count
    page_info { current_page page_size total_pages }
  }
}
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_variables(inp: CSearchProductsInput) -> dict[str, Any]:
    """Build GraphQL variables from validated input."""
    variables: dict[str, Any] = {
        "pageSize": inp.page_size,
        "currentPage": inp.current_page,
    }

    if inp.search:
        variables["search"] = inp.search

    # Filters
    filt: dict[str, Any] = {}
    if inp.category_id:
        filt["category_id"] = {"eq": inp.category_id}
    if inp.price_from is not None or inp.price_to is not None:
        price_filter: dict[str, Any] = {}
        if inp.price_from is not None:
            price_filter["from"] = str(inp.price_from)
        if inp.price_to is not None:
            price_filter["to"] = str(inp.price_to)
        filt["price"] = price_filter
    if filt:
        variables["filter"] = filt

    # Magento requires at least search or filter — default to empty search for browsing
    if "search" not in variables and "filter" not in variables:
        variables["search"] = ""

    # Sort (skip for relevance — Magento uses relevance by default with a search term)
    if inp.sort_field != "relevance":
        variables["sort"] = {inp.sort_field: inp.sort_direction}

    return variables


def _parse_price(price_node: dict[str, Any], discount_node: dict[str, Any] | None) -> ProductPrice:
    """Parse a minimum/maximum price node into a ProductPrice."""
    return ProductPrice(
        regular_price=PriceAmount(
            value=price_node["regular_price"]["value"],
            currency=price_node["regular_price"]["currency"],
        ),
        final_price=PriceAmount(
            value=price_node["final_price"]["value"],
            currency=price_node["final_price"]["currency"],
        ),
        discount_amount=discount_node.get("amount_off") if discount_node else None,
        discount_percent=discount_node.get("percent_off") if discount_node else None,
    )


def _parse_product(item: dict[str, Any]) -> StorefrontProduct:
    """Transform a raw GraphQL product item into a StorefrontProduct."""
    price_range = item["price_range"]
    min_price_node = price_range["minimum_price"]
    max_price_node = price_range["maximum_price"]

    small_image = item.get("small_image") or {}
    short_desc = item.get("short_description") or {}

    return StorefrontProduct(
        sku=item["sku"],
        name=item["name"],
        url_key=item["url_key"],
        product_type=item.get("__typename", "SimpleProduct"),
        stock_status=item.get("stock_status", "OUT_OF_STOCK"),
        min_price=_parse_price(min_price_node, min_price_node.get("discount")),
        max_price=_parse_price(max_price_node, None),
        image_url=small_image.get("url"),
        image_label=small_image.get("label"),
        short_description=strip_html(short_desc.get("html")),
    )


def _parse_response(
    data: dict[str, Any],
    in_stock_only: bool,
) -> CSearchProductsOutput:
    """Parse the GraphQL response into the output model."""
    products_data = data["products"]
    items = products_data.get("items") or []

    products = [_parse_product(item) for item in items]

    if in_stock_only:
        products = [p for p in products if p.stock_status == "IN_STOCK"]

    page_info_raw = products_data["page_info"]

    return CSearchProductsOutput(
        products=products,
        total_count=products_data["total_count"],
        page_info=PageInfo(
            current_page=page_info_raw["current_page"],
            page_size=page_info_raw["page_size"],
            total_pages=page_info_raw["total_pages"],
        ),
    )


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_search_products(mcp: FastMCP) -> None:
    """Register the c_search_products tool on the given MCP server."""

    @mcp.tool(
        name="c_search_products",
        description=(
            "Search the product catalog as a shopper would see it. "
            "Returns storefront-visible products with pricing, images, and stock status."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": True,
        },
    )
    async def c_search_products(
        search: str | None = None,
        category_id: str | None = None,
        price_from: float | None = None,
        price_to: float | None = None,
        in_stock_only: bool = False,
        store_scope: str = "default",
        page_size: int = 20,
        current_page: int = 1,
        sort_field: str = "relevance",
        sort_direction: str = "ASC",
    ) -> dict[str, Any]:
        """Search the storefront catalog."""
        inp = CSearchProductsInput(
            search=search,
            category_id=category_id,
            price_from=price_from,
            price_to=price_to,
            in_stock_only=in_stock_only,
            store_scope=store_scope,
            page_size=page_size,
            current_page=current_page,
            sort_field=sort_field,
            sort_direction=sort_direction,
        )

        variables = _build_variables(inp)
        log.info("c_search_products store=%s variables=%s", inp.store_scope, variables)

        async with GraphQLClient.from_env() as client:
            data = await client.query(
                SEARCH_PRODUCTS_QUERY,
                variables=variables,
                store_code=inp.store_scope,
            )

        result = _parse_response(data, inp.in_stock_only)
        return result.model_dump(mode="json")
