"""c_search_products — storefront product search via Magento GraphQL."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from magemcp.connectors.graphql_client import GraphQLClient
from magemcp.models.catalog import (
    Aggregation,
    AggregationOption,
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
    aggregations {
      attribute_code
      label
      count
      options { label value count }
    }
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
    if inp.attributes:
        for attr_code, attr_value in inp.attributes.items():
            filt[attr_code] = {"eq": str(attr_value)}
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


def _parse_aggregations(raw_aggs: list[dict[str, Any]]) -> list[Aggregation]:
    """Parse raw GraphQL aggregation data into Aggregation models."""
    aggregations: list[Aggregation] = []
    for agg in raw_aggs:
        options = [
            AggregationOption(
                label=opt["label"],
                value=str(opt["value"]),
                count=opt["count"],
            )
            for opt in agg.get("options") or []
        ]
        aggregations.append(Aggregation(
            attribute_code=agg["attribute_code"],
            label=agg.get("label", agg["attribute_code"]),
            count=agg.get("count", len(options)),
            options=options,
        ))
    return aggregations


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
    raw_aggs = products_data.get("aggregations") or []

    return CSearchProductsOutput(
        products=products,
        total_count=products_data["total_count"],
        page_info=PageInfo(
            current_page=page_info_raw["current_page"],
            page_size=page_info_raw["page_size"],
            total_pages=page_info_raw["total_pages"],
        ),
        aggregations=_parse_aggregations(raw_aggs),
    )


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


async def c_search_products(
    search: str | None = None,
    category_id: str | None = None,
    price_from: float | None = None,
    price_to: float | None = None,
    attributes: dict[str, str] | None = None,
    in_stock_only: bool = False,
    store_scope: str = "default",
    page_size: int = 20,
    current_page: int = 1,
    sort_field: str = "relevance",
    sort_direction: str = "ASC",
) -> CSearchProductsOutput:
    """Search the storefront catalog."""
    inp = CSearchProductsInput(
        search=search,
        category_id=category_id,
        price_from=price_from,
        price_to=price_to,
        attributes=attributes,
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


def register_search_products(mcp: FastMCP) -> None:
    """Register the c_search_products tool on the given MCP server."""
    mcp.tool(
        name="c_search_products",
        title="Search Products",
        description=(
            "Search the storefront product catalog by keyword, category, or price range — "
            "exactly what a shopper sees (no disabled/hidden products). "
            "Returns SKU, name, url_key, stock_status (IN_STOCK/OUT_OF_STOCK), "
            "regular and final pricing with any discount percent, and thumbnail image. "
            "Also returns aggregations (faceted filters): available brands, sizes, colors, "
            "price ranges, and other custom attributes with product counts per option. "
            "Use aggregation option 'value' fields as input to the 'attributes' parameter "
            "to filter by brand, color, size, or any custom attribute "
            "(e.g. attributes={\"brand\": \"115\"} to filter by Bvlgari). "
            "Use in_stock_only=True to filter to orderable items. "
            "sort_field: relevance (default with search term), name, price. "
            "Use c_get_product for full description, images, and configurable options."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )(c_search_products)
