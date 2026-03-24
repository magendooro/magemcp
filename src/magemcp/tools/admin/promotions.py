"""admin promotions tools — search rules, get rules, generate coupons via Magento REST API."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from magemcp.connectors.errors import MagentoNotFoundError
from magemcp.connectors.rest_client import RESTClient
from magemcp.tools.admin._confirmation import elicit_confirmation
from magemcp.utils.idempotency import idempotency_store

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_rule_summary(raw: dict[str, Any]) -> dict[str, Any]:
    """Return a lean sales rule dict."""
    return {
        "rule_id": raw.get("rule_id"),
        "name": raw.get("name"),
        "description": raw.get("description"),
        "is_active": raw.get("is_active"),
        "coupon_type": raw.get("coupon_type"),
        "coupon_code": raw.get("coupon_code"),
        "uses_per_coupon": raw.get("uses_per_coupon"),
        "uses_per_customer": raw.get("uses_per_customer"),
        "discount_amount": raw.get("discount_amount"),
        "simple_action": raw.get("simple_action"),
        "from_date": raw.get("from_date"),
        "to_date": raw.get("to_date"),
        "website_ids": raw.get("website_ids") or [],
        "customer_group_ids": raw.get("customer_group_ids") or [],
    }


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


async def admin_search_sales_rules(
    name: str | None = None,
    is_active: bool | None = None,
    coupon_type: int | None = None,
    page_size: int = 20,
    current_page: int = 1,
    store_scope: str = "default",
) -> dict[str, Any]:
    """Search cart price rules (sales rules) by name or active status."""
    log.info(
        "admin_search_sales_rules name=%s is_active=%s coupon_type=%s",
        name, is_active, coupon_type,
    )

    filters: dict[str, Any] = {}
    if name:
        filters["name"] = (name, "like")
    if is_active is not None:
        filters["is_active"] = int(is_active)
    if coupon_type is not None:
        filters["coupon_type"] = coupon_type

    params = RESTClient.search_params(
        filters=filters or None,
        page_size=max(1, min(page_size, 50)),
        current_page=max(1, current_page),
    )

    async with RESTClient.from_env() as client:
        data = await client.get("/V1/salesRules/search", params=params, store_code=store_scope)

    items = data.get("items") or []
    return {
        "total_count": data.get("total_count", len(items)),
        "page_size": page_size,
        "current_page": current_page,
        "rules": [_parse_rule_summary(item) for item in items],
    }


async def admin_get_sales_rule(
    rule_id: int,
    store_scope: str = "default",
) -> dict[str, Any]:
    """Get full detail for a cart price rule by ID."""
    log.info("admin_get_sales_rule rule_id=%s", rule_id)

    async with RESTClient.from_env() as client:
        raw = await client.get(f"/V1/salesRules/{rule_id}", store_code=store_scope)

    if not raw or "rule_id" not in raw:
        raise MagentoNotFoundError(f"Sales rule {rule_id} not found.")

    # Return full rule including conditions/actions
    return {
        **_parse_rule_summary(raw),
        "stop_rules_processing": raw.get("stop_rules_processing"),
        "sort_order": raw.get("sort_order"),
        "discount_qty": raw.get("discount_qty"),
        "discount_step": raw.get("discount_step"),
        "apply_to_shipping": raw.get("apply_to_shipping"),
        "times_used": raw.get("times_used"),
        "conditions": raw.get("conditions"),
        "actions": raw.get("actions"),
        "store_labels": raw.get("store_labels") or [],
    }


async def admin_generate_coupons(
    rule_id: int,
    quantity: int = 1,
    length: int = 12,
    format: str = "alphanum",
    confirm: bool = False,
    idempotency_key: str | None = None,
    store_scope: str = "default",
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Generate coupon codes for a cart price rule. Requires confirmation."""
    log.info(
        "admin_generate_coupons rule_id=%s qty=%s format=%s confirm=%s",
        rule_id, quantity, format, confirm,
    )

    _VALID_FORMATS = ("alphanum", "alpha", "num")
    if format not in _VALID_FORMATS:
        raise ValueError(f"Invalid coupon format '{format}'. Must be one of: {', '.join(_VALID_FORMATS)}")

    if idempotency_key:
        stored = idempotency_store.get("admin_generate_coupons", idempotency_key)
        if stored is not None:
            return {**stored, "idempotent_replay": True}

    prompt = await elicit_confirmation(
        ctx, f"generate {quantity} coupon(s) for rule {rule_id}", str(rule_id), confirm
    )
    if prompt:
        return prompt

    payload: dict[str, Any] = {
        "couponSpec": {
            "rule_id": rule_id,
            "qty": max(1, quantity),
            "length": max(6, length),
            "format": format,
        }
    }

    async with RESTClient.from_env() as client:
        result = await client.post(
            "/V1/coupons/generate",
            json=payload,
            store_code=store_scope,
        )

    # Magento returns a list of generated coupon codes
    codes = result if isinstance(result, list) else []
    out = {
        "success": True,
        "rule_id": rule_id,
        "generated": len(codes),
        "coupon_codes": codes,
    }
    if idempotency_key:
        idempotency_store.set("admin_generate_coupons", idempotency_key, out)
    return out


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_promotion_tools(mcp: FastMCP) -> None:
    """Register all admin promotion tools on the given MCP server."""

    mcp.tool(
        name="admin_search_sales_rules",
        title="Search Sales Rules",
        description=(
            "Search cart price rules (promotions) by name or active status. "
            "Use when answering 'what promotions are running?' or 'is there a discount for X?'. "
            "Name filter supports SQL wildcards (e.g. %summer%, %VIP%). "
            "coupon_type: 1=no coupon, 2=specific coupon, 3=auto-generated. "
            "Returns summaries with discount_amount, simple_action, validity dates, and coupon code. "
            "Use admin_get_sales_rule for full conditions and usage statistics."
        ),
        annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    )(admin_search_sales_rules)

    mcp.tool(
        name="admin_get_sales_rule",
        title="Get Sales Rule",
        description=(
            "Get full detail for a cart price rule by rule_id. "
            "Returns complete discount configuration: conditions (what cart must match), "
            "actions (what discount applies), usage limits, times_used, and store labels. "
            "Use admin_search_sales_rules to find rule IDs first."
        ),
        annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    )(admin_get_sales_rule)

    mcp.tool(
        name="admin_generate_coupons",
        title="Generate Coupons",
        description=(
            "Generate one or more unique coupon codes for an existing cart price rule. "
            "The rule must have coupon_type=3 (auto-generated). "
            "format: 'alphanum' (default), 'alpha', or 'num'. length: minimum 6 characters. "
            "Returns the list of generated coupon codes. "
            "Pass idempotency_key to safely retry without generating duplicates. "
            "Requires confirmation — call twice with confirm=True to proceed."
        ),
        annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True},
    )(admin_generate_coupons)
