"""admin product tools — search, get, and update products via Magento REST API."""

from __future__ import annotations

import logging
import os
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

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
from magemcp.tools.admin._confirmation import elicit_confirmation

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
# EAV value resolution helpers
# ---------------------------------------------------------------------------

# These frontend_input types store integer option IDs, not label text.
_OPTION_ID_INPUT_TYPES = frozenset({"select", "multiselect", "swatch_visual", "swatch_text"})


def _looks_like_option_id(value: Any) -> bool:
    """Return True if value already appears to be a numeric option ID (or comma-separated IDs).

    If True, we skip the attribute lookup — the caller already has the correct ID.
    """
    if isinstance(value, bool):
        return False  # booleans must go through normalisation
    if isinstance(value, int):
        return True
    if isinstance(value, str):
        parts = [p.strip() for p in value.split(",")]
        return bool(parts) and all(p.isdigit() for p in parts)
    return False


async def _resolve_eav_value(
    attribute_code: str,
    value: Any,
    *,
    store_code: str,
) -> Any:
    """Resolve a human-readable value to the format Magento expects for this attribute type.

    - select / swatch_visual / swatch_text: non-numeric strings are matched
      case-insensitively against the option list and replaced with the option ID.
    - multiselect: same, but value may be a comma-separated list of labels.
    - boolean: normalises Yes/No/True/False → "1"/"0".
    - all other types (text, textarea, date, price, …): passed through unchanged.

    Numeric strings / ints are treated as already-resolved option IDs and are
    returned as-is without an API round-trip.

    Raises ValueError with the list of available options if a label cannot be matched.
    """
    if _looks_like_option_id(value):
        return str(value) if isinstance(value, int) else value

    str_value = str(value)

    try:
        async with RESTClient.from_env() as client:
            attr_raw = await client.get(f"/V1/products/attributes/{attribute_code}")
    except Exception as exc:
        log.warning(
            "admin_update_product: could not fetch attribute def for %s: %s — passing value through",
            attribute_code, exc,
        )
        return value

    frontend_input: str = attr_raw.get("frontend_input") or "text"

    # boolean → "1" / "0"
    if frontend_input == "boolean":
        if str_value.lower() in ("1", "true", "yes"):
            return "1"
        if str_value.lower() in ("0", "false", "no"):
            return "0"
        raise ValueError(
            f"Attribute '{attribute_code}' is boolean. "
            f"Use 'Yes'/'No', 'True'/'False', or '1'/'0'."
        )

    # Non-option types — pass through unchanged
    if frontend_input not in _OPTION_ID_INPUT_TYPES:
        return value

    # select / multiselect / swatch — resolve label → option ID
    options = [o for o in (attr_raw.get("options") or []) if o.get("value") not in ("", None)]
    option_map = {o["label"].strip().lower(): o["value"] for o in options}

    parts = [p.strip() for p in str_value.split(",")] if frontend_input == "multiselect" else [str_value]

    resolved: list[str] = []
    for part in parts:
        if part.isdigit():
            resolved.append(part)
            continue
        matched_id = option_map.get(part.lower())
        if matched_id is None:
            available = ", ".join(f"'{o['label']}' → {o['value']}" for o in options)
            raise ValueError(
                f"No option matching '{part}' for attribute '{attribute_code}' "
                f"(type: {frontend_input}). Available: {available}"
            )
        resolved.append(matched_id)

    return ",".join(resolved) if frontend_input == "multiselect" else resolved[0]


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
) -> ProductDetail:
    """Get full product detail by SKU — all attributes, media, stock, options."""
    log.info("admin_get_product sku=%s store=%s", sku, store_scope)

    async with RESTClient.from_env() as client:
        raw = await client.get(f"/V1/products/{sku}", store_code=store_scope)

    if not raw or "sku" not in raw:
        raise MagentoNotFoundError(f"Product '{sku}' not found.")

    result = _parse_product_detail(raw)
    return result.model_dump(mode="json")


# Top-level product fields that live on the product object directly (not EAV).
# Everything else is an EAV custom_attribute.
_TOP_LEVEL_PRODUCT_FIELDS = frozenset({"name", "price", "status", "weight"})


async def admin_update_product(
    sku: str,
    name: str | None = None,
    price: float | None = None,
    special_price: float | None = None,
    special_price_from: str | None = None,
    special_price_to: str | None = None,
    status: int | None = None,
    weight: float | None = None,
    description: str | None = None,
    short_description: str | None = None,
    meta_title: str | None = None,
    meta_description: str | None = None,
    attributes: dict[str, Any] | None = None,
    confirm: bool = False,
    store_scope: str = "default",
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Update product attributes. Only specified fields are changed. Requires confirmation.

    Named shortcuts cover the most common fields. For any other EAV attribute
    (e.g. color, material, manufacturer, custom fields) pass them in ``attributes``
    as ``{"attribute_code": value}``.

    Value handling by attribute type:
    - select / multiselect / swatch_visual / swatch_text: you may pass either the
      human-readable label (e.g. "Red") or the numeric option ID (e.g. "59").
      Labels are automatically resolved to option IDs via the Magento API.
    - boolean: accepts Yes/No, True/False, or "1"/"0" — normalised to "1"/"0".
    - text, textarea, date, price, etc.: plain value passed through unchanged.

    special_price sets a promotional / sale price that appears alongside the regular price.
    Pair with special_price_from / special_price_to (YYYY-MM-DD) to schedule the sale.
    Pass special_price=None explicitly with confirm=True to clear an existing special price
    (Magento interprets an empty string as removal).
    """
    log.info("admin_update_product sku=%s confirm=%s", sku, confirm)

    prompt = await elicit_confirmation(ctx, f"update product {sku}", sku, confirm)
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

    # Attributes stored in custom_attributes (EAV): named shortcuts + generic dict
    custom_attributes: list[dict[str, Any]] = []
    for attr_code, value in [
        ("description", description),
        ("short_description", short_description),
        ("meta_title", meta_title),
        ("meta_description", meta_description),
        ("special_price", str(special_price) if special_price is not None else None),
        ("special_from_date", special_price_from),
        ("special_to_date", special_price_to),
    ]:
        if value is not None:
            custom_attributes.append({"attribute_code": attr_code, "value": value})

    # Generic attributes — any EAV attribute_code not covered by named params.
    # select / multiselect / swatch types store integer option IDs; non-numeric values
    # are auto-resolved to the matching option ID via a GET /V1/products/attributes/{code}.
    # boolean values are normalised to "1"/"0". All other types pass through unchanged.
    if attributes:
        for attr_code, value in attributes.items():
            if value is not None:
                resolved = await _resolve_eav_value(attr_code, value, store_code=store_scope)
                custom_attributes.append({"attribute_code": attr_code, "value": resolved})

    if custom_attributes:
        product["custom_attributes"] = custom_attributes

    updated_fields = [k for k in product if k not in ("sku", "custom_attributes")] + [
        ca["attribute_code"] for ca in custom_attributes
    ]

    if not updated_fields:
        raise ValueError("No fields to update. Provide at least one field to change.")

    def _extract_fields(
        raw: dict[str, Any], fields: list[str]
    ) -> dict[str, Any]:
        """Extract updated fields from a raw product response."""
        attrs = {
            item["attribute_code"]: item.get("value")
            for item in (raw.get("custom_attributes") or [])
            if "attribute_code" in item
        }
        result: dict[str, Any] = {}
        for field in fields:
            if field in _TOP_LEVEL_PRODUCT_FIELDS:
                result[field] = raw.get(field)
            else:
                result[field] = attrs.get(field)
        return result

    # Optionally capture before-state for audit purposes.
    # Controlled by MAGEMCP_AUDIT_BEFORE_STATE=true (default: false) to avoid
    # an extra GET call on every write when not needed.
    before: dict[str, Any] | None = None
    if os.getenv("MAGEMCP_AUDIT_BEFORE_STATE", "false").lower() == "true":
        try:
            async with RESTClient.from_env() as client:
                raw_before = await client.get(f"/V1/products/{sku}", store_code=store_scope)
            before = _extract_fields(raw_before, updated_fields)
        except Exception as exc:
            log.warning("admin_update_product: could not fetch before-state for %s: %s", sku, exc)

    async with RESTClient.from_env() as client:
        raw_after = await client.put(
            f"/V1/products/{sku}",
            json={"product": product},
            store_code=store_scope,
        )

    after: dict[str, Any] = {}
    if raw_after and isinstance(raw_after, dict):
        after = _extract_fields(raw_after, updated_fields)

    result: dict[str, Any] = {
        "success": True,
        "sku": sku,
        "updated_fields": updated_fields,
    }
    if before is not None:
        result["before"] = before
    if after:
        result["after"] = after
    return result


# ---------------------------------------------------------------------------
# Attribute lookup
# ---------------------------------------------------------------------------


async def admin_get_product_attribute(
    attribute_code: str,
) -> dict[str, Any]:
    """Return the definition of a product EAV attribute, including its option list.

    For ``select`` and ``multiselect`` attributes Magento stores integer option IDs,
    not label text.  Use this tool to map a human-readable label (e.g. "Red") to the
    correct option value ID before calling ``admin_update_product``.

    Workflow::

        # 1. Find the option ID for "Red"
        attr = await admin_get_product_attribute("color")
        # → {"frontend_input": "select", "options": [{"label": "Red", "value": "59"}, ...]}

        # 2. Update using the ID, not the label
        await admin_update_product(sku="24-MB01", attributes={"color": "59"}, confirm=True)
    """
    log.info("admin_get_product_attribute attribute_code=%s", attribute_code)

    async with RESTClient.from_env() as client:
        raw = await client.get(f"/V1/products/attributes/{attribute_code}")

    if not raw or "attribute_code" not in raw:
        raise MagentoNotFoundError(f"Attribute '{attribute_code}' not found.")

    # Strip the empty placeholder option Magento always inserts at position 0
    raw_options: list[dict[str, Any]] = raw.get("options") or []
    options = [o for o in raw_options if o.get("value") not in ("", None)]

    return {
        "attribute_code": raw["attribute_code"],
        "attribute_id": raw.get("attribute_id"),
        "frontend_label": raw.get("default_frontend_label") or attribute_code,
        "frontend_input": raw.get("frontend_input"),  # select, multiselect, text, date, boolean …
        "is_required": raw.get("is_required", False),
        "is_user_defined": raw.get("is_user_defined", False),
        "scope": raw.get("scope"),  # global, website, store
        "options": options,  # [{label, value}, …] — empty for non-select types
    }


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_product_tools(mcp: FastMCP) -> None:
    """Register all admin product tools on the given MCP server."""

    mcp.tool(
        name="admin_search_products",
        title="Search Products",
        description=(
            "Search the admin product catalog by name, SKU, type (simple/configurable/bundle), "
            "status (1=enabled, 2=disabled), or price range. "
            "Name and SKU filters support wildcards (e.g. %duffle%, MH%). "
            "Returns summaries — use admin_get_product for full attribute detail."
        ),
        annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    )(admin_search_products)

    mcp.tool(
        name="admin_get_product",
        title="Get Product",
        description=(
            "Get complete product data by SKU (admin REST view): all EAV attributes, "
            "descriptions, images, stock item with raw warehouse quantity, tier prices, "
            "customizable options, and category assignments. "
            "For storefront-visible pricing and stock use c_get_product."
        ),
        annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    )(admin_get_product)

    mcp.tool(
        name="admin_get_product_attribute",
        title="Get Product Attribute",
        description=(
            "Return the definition and option list for a product EAV attribute. "
            "Essential before updating select/multiselect attributes (color, material, "
            "manufacturer, etc.): Magento stores these as integer option IDs, not labels. "
            "Call this first to map 'Red' → '59', then pass the ID to admin_update_product. "
            "Also shows frontend_input type (select, multiselect, text, date, boolean, price) "
            "and scope (global, website, store)."
        ),
        annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    )(admin_get_product_attribute)

    mcp.tool(
        name="admin_update_product",
        title="Update Product",
        description=(
            "Update product attributes by SKU. Named shortcuts: name, price, "
            "special_price (sale price shown alongside regular price), "
            "special_price_from / special_price_to (YYYY-MM-DD schedule), "
            "status (1=enabled, 2=disabled), weight, short/long description, meta fields. "
            "For any other EAV attribute pass attributes={\"attribute_code\": value}. "
            "select/multiselect/swatch attributes accept either a label ('Red') or the "
            "numeric option ID ('59') — labels are auto-resolved via the Magento API. "
            "boolean attributes accept Yes/No or 1/0. Text/date/price pass through unchanged. "
            "Only fields you provide are changed. "
            "Requires confirmation — call twice with confirm=True. Use admin_get_product first "
            "to see current values."
        ),
        annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True},
    )(admin_update_product)
