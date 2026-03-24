"""c_get_product — fetch full product detail by SKU via Magento GraphQL."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from magemcp.connectors.errors import MagentoNotFoundError
from magemcp.connectors.graphql_client import GraphQLClient
from magemcp.models.catalog import (
    CategoryBreadcrumb,
    CGetProductInput,
    CGetProductOutput,
    CustomAttribute,
    MediaGalleryEntry,
    PriceAmount,
    ProductPrice,
    strip_html,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GraphQL query
# ---------------------------------------------------------------------------

GET_PRODUCT_QUERY = """
query GetProduct($sku: String!) {
  products(filter: { sku: { eq: $sku } }) {
    items {
      sku
      name
      url_key
      meta_title
      meta_description
      stock_status
      __typename
      description { html }
      short_description { html }
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
      media_gallery {
        url
        label
        position
        disabled
      }
      categories {
        id
        name
        url_path
        breadcrumbs {
          category_id
          category_name
          category_url_path
        }
      }
      ... on ConfigurableProduct {
        configurable_options {
          attribute_code
          label
          values { label value_index }
        }
      }
    }
  }
}
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _parse_categories(raw_categories: list[dict[str, Any]]) -> list[CategoryBreadcrumb]:
    """Parse GraphQL category nodes into CategoryBreadcrumb models."""
    categories: list[CategoryBreadcrumb] = []
    for cat in raw_categories:
        breadcrumbs = cat.get("breadcrumbs") or []
        full_path_parts: list[str] = [
            bc["category_name"] for bc in breadcrumbs
        ]
        full_path_parts.append(cat["name"])

        categories.append(CategoryBreadcrumb(
            id=str(cat["id"]),
            name=cat["name"],
            url_path=cat.get("url_path"),
            full_path=" > ".join(full_path_parts),
        ))
    return categories


def _parse_media_gallery(raw_gallery: list[dict[str, Any]]) -> list[MediaGalleryEntry]:
    """Parse GraphQL media gallery nodes, filtering out disabled entries."""
    entries: list[MediaGalleryEntry] = []
    for item in raw_gallery:
        if item.get("disabled"):
            continue
        entries.append(MediaGalleryEntry(
            url=item["url"],
            label=item.get("label"),
            position=item.get("position"),
        ))
    entries.sort(key=lambda e: e.position if e.position is not None else 999)
    return entries


def _parse_custom_attributes(item: dict[str, Any]) -> list[CustomAttribute]:
    """Extract configurable options as custom attributes."""
    attrs: list[CustomAttribute] = []
    for opt in item.get("configurable_options") or []:
        values = [v["label"] for v in opt.get("values", [])]
        attrs.append(CustomAttribute(
            attribute_code=opt["attribute_code"],
            label=opt["label"],
            values=values,
        ))
    return attrs


def _parse_product_detail(item: dict[str, Any]) -> CGetProductOutput:
    """Transform a raw GraphQL product item into CGetProductOutput."""
    price_range = item["price_range"]
    min_price_node = price_range["minimum_price"]
    max_price_node = price_range["maximum_price"]

    description_raw = item.get("description") or {}
    short_desc_raw = item.get("short_description") or {}

    return CGetProductOutput(
        sku=item["sku"],
        name=item["name"],
        url_key=item["url_key"],
        product_type=item.get("__typename", "SimpleProduct"),
        meta_title=item.get("meta_title"),
        meta_description=item.get("meta_description"),
        stock_status=item.get("stock_status", "OUT_OF_STOCK"),
        description=strip_html(description_raw.get("html")),
        short_description=strip_html(short_desc_raw.get("html")),
        min_price=_parse_price(min_price_node, min_price_node.get("discount")),
        max_price=_parse_price(max_price_node, None),
        images=_parse_media_gallery(item.get("media_gallery") or []),
        categories=_parse_categories(item.get("categories") or []),
        custom_attributes=_parse_custom_attributes(item),
    )


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


async def c_get_product(
    sku: str,
    store_scope: str = "default",
) -> CGetProductOutput:
    """Get full product detail by SKU."""
    inp = CGetProductInput(sku=sku, store_scope=store_scope)

    log.info("c_get_product sku=%s store=%s", inp.sku, inp.store_scope)

    async with GraphQLClient.from_env() as client:
        data = await client.query(
            GET_PRODUCT_QUERY,
            variables={"sku": inp.sku},
            store_code=inp.store_scope,
        )

    items = (data.get("products") or {}).get("items") or []
    if not items:
        raise MagentoNotFoundError(f"Product with SKU '{inp.sku}' not found.")

    result = _parse_product_detail(items[0])
    return result.model_dump(mode="json")


def register_get_product(mcp: FastMCP) -> None:
    """Register the c_get_product tool on the given MCP server."""
    mcp.tool(
        name="c_get_product",
        title="Get Product",
        description=(
            "Get complete storefront product detail by SKU. "
            "Returns name, full HTML-stripped description, pricing (regular + final + discount %), "
            "all gallery images, category breadcrumbs, stock_status, "
            "and configurable options (size/color choices with labels) for ConfigurableProduct types. "
            "Use c_search_products to discover SKUs first. "
            "For raw warehouse stock quantity use admin_get_product or admin_get_inventory instead."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )(c_get_product)
