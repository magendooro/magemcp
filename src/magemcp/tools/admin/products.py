"""admin product tools — search, get, and update products via Magento REST API."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from magemcp.connectors.errors import MagentoNotFoundError
from magemcp.connectors.rest_client import RESTClient
from magemcp.models.product import (
    MediaGalleryEntry,
    ProductDetail,
    ProductOption,
    ProductSummary,
    StockItem,
    TierPrice,
)
from magemcp.tools.admin._confirmation import needs_confirmation

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_custom_attributes(raw_list: list[dict[str, Any]]) -> dict[str, Any]:
    """Flatten Magento [{attribute_code, value}] list to a plain dict."""
    return {item["attribute_code"]: item.get("value") for item in raw_list if "attribute_code" in item}


def _parse_product_summary(raw: dict[str, Any]) -> ProductSummary:
    attrs = _parse_custom_attributes(raw.get("custom_attributes") or [])
    return ProductSummary(
        sku=raw["sku"],
        name=raw.get("name"),
        price=raw.get("price"),
        status=raw.get("status"),
        visibility=raw.get("visibility"),
        type_id=raw.get("type_id"),
        weight=raw.get("weight"),
        created_at=raw.get("created_at"),
        updated_at=raw.get("updated_at"),
    )


def _parse_product_detail(raw: dict[str, Any]) -> ProductDetail:
    attrs = _parse_custom_attributes(raw.get("custom_attributes") or [])

    # Stock from extension_attributes.stock_item
    ext = raw.get("extension_attributes") or {}
    stock_raw = ext.get("stock_item") or {}
    stock = StockItem(
        qty=stock_raw.get("qty"),
        is_in_stock=stock_raw.get("is_in_stock"),
        manage_stock=stock_raw.get("manage_stock"),
        min_sale_qty=stock_raw.get("min_sale_qty"),
        max_sale_qty=stock_raw.get("max_sale_qty"),
    ) if stock_raw else None

    # Media gallery
    media = [
        MediaGalleryEntry(
            id=m.get("id"),
            media_type=m.get("media_type"),
            label=m.get("label"),
            position=m.get("position"),
            disabled=m.get("disabled", False),
            types=m.get("types") or [],
            file=m.get("file"),
        )
        for m in raw.get("media_gallery_entries") or []
    ]

    # Tier prices
    tier_prices = [
        TierPrice(
            customer_group_id=tp.get("customer_group_id"),
            qty=tp.get("qty"),
            value=tp.get("value"),
            extension_attributes=tp.get("extension_attributes") or {},
        )
        for tp in raw.get("tier_prices") or []
    ]

    # Customizable options
    options = [
        ProductOption(
            option_id=o.get("option_id"),
            title=o.get("title"),
            type=o.get("type"),
            is_require=o.get("is_require", False),
            values=o.get("values") or [],
        )
        for o in raw.get("options") or []
    ]

    # Category IDs from extension_attributes or category_links
    category_links = ext.get("category_links") or []
    category_ids = [int(cl["category_id"]) for cl in category_links if "category_id" in cl]

    # Extension attributes without stock_item (already extracted)
    ext_clean = {k: v for k, v in ext.items() if k != "stock_item"}

    return ProductDetail(
        sku=raw["sku"],
        name=raw.get("name"),
        attribute_set_id=raw.get("attribute_set_id"),
        price=raw.get("price"),
        status=raw.get("status"),
        visibility=raw.get("visibility"),
        type_id=raw.get("type_id"),
        weight=raw.get("weight"),
        created_at=raw.get("created_at"),
        updated_at=raw.get("updated_at"),
        description=attrs.get("description"),
        short_description=attrs.get("short_description"),
        meta_title=attrs.get("meta_title"),
        meta_description=attrs.get("meta_description"),
        meta_keyword=attrs.get("meta_keyword"),
        url_key=attrs.get("url_key"),
        media_gallery=media,
        stock=stock,
        tier_prices=tier_prices,
        options=options,
        category_ids=category_ids,
        custom_attributes=attrs,
        extension_attributes=ext_clean,
    )


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


async def admin_search_products(
    name: str | None = None,
    sku: str | None = None,
    type_id: str | None = None,
    status: int | None = None,
    visibility: int | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    page_size: int = 20,
    current_page: int = 1,
    sort_field: str = "entity_id",
    sort_direction: str = "DESC",
    store_scope: str = "default",
) -> dict[str, Any]:
    """Search products with optional filters — full admin view, no storefront restrictions."""
    log.info(
        "admin_search_products name=%s sku=%s type=%s status=%s",
        name, sku, type_id, status,
    )

    # Simple equality/like filters
    simple: dict[str, Any] = {}
    if name:
        simple["name"] = (name, "like")
    if sku:
        simple["sku"] = (sku, "like")
    if type_id:
        simple["type_id"] = type_id
    if status is not None:
        simple["status"] = status
    if visibility is not None:
        simple["visibility"] = visibility

    params = RESTClient.search_params(
        filters=simple or None,
        page_size=max(1, min(page_size, 50)),
        current_page=max(1, current_page),
        sort_field=sort_field,
        sort_direction=sort_direction,
    )

    # Price range — separate filter groups (same-field range needs this)
    idx = len(simple)
    if price_min is not None:
        prefix = f"searchCriteria[filterGroups][{idx}][filters][0]"
        params[f"{prefix}[field]"] = "price"
        params[f"{prefix}[value]"] = str(price_min)
        params[f"{prefix}[conditionType]"] = "gteq"
        idx += 1
    if price_max is not None:
        prefix = f"searchCriteria[filterGroups][{idx}][filters][0]"
        params[f"{prefix}[field]"] = "price"
        params[f"{prefix}[value]"] = str(price_max)
        params[f"{prefix}[conditionType]"] = "lteq"

    async with RESTClient.from_env() as client:
        data = await client.get("/V1/products", params=params, store_code=store_scope)

    items = data.get("items") or []
    total_count = data.get("total_count", len(items))
    products = [_parse_product_summary(item) for item in items]

    return {
        "total_count": total_count,
        "page_size": page_size,
        "current_page": current_page,
        "products": [p.model_dump(mode="json") for p in products],
    }


async def admin_get_product(
    sku: str,
    store_scope: str = "default",
) -> dict[str, Any]:
    """Get full product detail by SKU — all attributes, media, stock, options."""
    log.info("admin_get_product sku=%s store=%s", sku, store_scope)

    async with RESTClient.from_env() as client:
        raw = await client.get(f"/V1/products/{sku}", store_code=store_scope)

    if not raw or "sku" not in raw:
        raise MagentoNotFoundError(f"Product '{sku}' not found.")

    result = _parse_product_detail(raw)
    return result.model_dump(mode="json")


async def admin_update_product(
    sku: str,
    name: str | None = None,
    price: float | None = None,
    status: int | None = None,
    weight: float | None = None,
    description: str | None = None,
    short_description: str | None = None,
    meta_title: str | None = None,
    meta_description: str | None = None,
    confirm: bool = False,
    store_scope: str = "default",
) -> dict[str, Any]:
    """Update product attributes. Only specified fields are changed. Requires confirmation."""
    log.info("admin_update_product sku=%s confirm=%s", sku, confirm)

    prompt = needs_confirmation(f"update product {sku}", sku, confirm)
    if prompt:
        return prompt

    # Build the product payload — only include fields that were explicitly set
    product: dict[str, Any] = {"sku": sku}
    if name is not None:
        product["name"] = name
    if price is not None:
        product["price"] = price
    if status is not None:
        product["status"] = status
    if weight is not None:
        product["weight"] = weight

    # Text attributes go in custom_attributes
    custom_attributes: list[dict[str, Any]] = []
    for attr_code, value in [
        ("description", description),
        ("short_description", short_description),
        ("meta_title", meta_title),
        ("meta_description", meta_description),
    ]:
        if value is not None:
            custom_attributes.append({"attribute_code": attr_code, "value": value})

    if custom_attributes:
        product["custom_attributes"] = custom_attributes

    updated_fields = [k for k in product if k != "sku"] + [
        ca["attribute_code"] for ca in custom_attributes
    ]

    if not updated_fields:
        raise ValueError("No fields to update. Provide at least one field to change.")

    async with RESTClient.from_env() as client:
        await client.put(
            f"/V1/products/{sku}",
            json={"product": product},
            store_code=store_scope,
        )

    return {"success": True, "sku": sku, "updated_fields": updated_fields}


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_product_tools(mcp: FastMCP) -> None:
    """Register all admin product tools on the given MCP server."""

    mcp.tool(
        name="admin_search_products",
        title="Search Products",
        description=(
            "Search products by name, SKU, type, status, visibility, or price range. "
            "Name and SKU filters support wildcards (e.g. %duffle%). "
            "Returns product summaries. Use admin_get_product for full detail."
        ),
        annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    )(admin_search_products)

    mcp.tool(
        name="admin_get_product",
        title="Get Product",
        description=(
            "Get full product detail by SKU: all attributes, descriptions, media gallery, "
            "stock item, tier prices, customizable options, and category links."
        ),
        annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    )(admin_get_product)

    mcp.tool(
        name="admin_update_product",
        title="Update Product",
        description=(
            "Update product attributes (name, price, status, weight, descriptions, meta fields). "
            "Only specified fields are changed — omitted fields are untouched. "
            "Requires confirmation — call with confirm=True to proceed."
        ),
        annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True},
    )(admin_update_product)
