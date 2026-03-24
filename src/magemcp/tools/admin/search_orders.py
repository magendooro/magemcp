"""admin_search_orders — search orders via Magento REST API."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from mcp.server.fastmcp import FastMCP

from magemcp.connectors.rest_client import RESTClient
from magemcp.models.order import OrderSummary
from magemcp.utils.dates import parse_date_expr

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------


class AdminSearchOrdersInput(BaseModel):
    """Search orders with filters."""

    status: str | None = Field(default=None, max_length=32)
    customer_email: str | None = Field(default=None, max_length=254)
    created_from: str | None = Field(
        default=None,
        description="Filter orders created on or after this date (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS).",
        max_length=32,
    )
    created_to: str | None = Field(
        default=None,
        description="Filter orders created on or before this date.",
        max_length=32,
    )
    grand_total_min: float | None = Field(default=None, ge=0)
    grand_total_max: float | None = Field(default=None, ge=0)
    page_size: int = Field(default=20, ge=1, le=100)
    current_page: int = Field(default=1, ge=1)
    sort_field: str = Field(default="created_at")
    sort_direction: str = Field(default="DESC", pattern=r"^(ASC|DESC)$")
    store_scope: str = Field(
        default="default",
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_search_params(inp: AdminSearchOrdersInput) -> dict[str, str]:
    """Build complete searchCriteria params including range filters.

    Magento's searchCriteria requires separate filter groups for range queries
    on the same field (created_at gteq AND lteq).
    """
    # Start with simple filters
    simple_filters: dict[str, Any] = {}
    if inp.status:
        simple_filters["status"] = inp.status
    if inp.customer_email:
        simple_filters["customer_email"] = inp.customer_email

    params = RESTClient.search_params(
        filters=simple_filters,
        page_size=inp.page_size,
        current_page=inp.current_page,
        sort_field=inp.sort_field,
        sort_direction=inp.sort_direction,
    )

    # Add range filters manually (separate filter groups)
    idx = len(simple_filters)

    if inp.created_from:
        prefix = f"searchCriteria[filterGroups][{idx}][filters][0]"
        params[f"{prefix}[field]"] = "created_at"
        params[f"{prefix}[value]"] = inp.created_from
        params[f"{prefix}[conditionType]"] = "gteq"
        idx += 1

    if inp.created_to:
        prefix = f"searchCriteria[filterGroups][{idx}][filters][0]"
        params[f"{prefix}[field]"] = "created_at"
        params[f"{prefix}[value]"] = inp.created_to
        params[f"{prefix}[conditionType]"] = "lteq"
        idx += 1

    if inp.grand_total_min is not None:
        prefix = f"searchCriteria[filterGroups][{idx}][filters][0]"
        params[f"{prefix}[field]"] = "grand_total"
        params[f"{prefix}[value]"] = str(inp.grand_total_min)
        params[f"{prefix}[conditionType]"] = "gteq"
        idx += 1

    if inp.grand_total_max is not None:
        prefix = f"searchCriteria[filterGroups][{idx}][filters][0]"
        params[f"{prefix}[field]"] = "grand_total"
        params[f"{prefix}[value]"] = str(inp.grand_total_max)
        params[f"{prefix}[conditionType]"] = "lteq"
        idx += 1

    return params


def _parse_order_summary(raw: dict[str, Any]) -> OrderSummary:
    """Extract a lightweight summary from a raw REST order."""
    firstname = raw.get("customer_firstname") or ""
    lastname = raw.get("customer_lastname") or ""
    name = f"{firstname} {lastname}".strip() or "Guest"

    parent_items = [i for i in (raw.get("items") or []) if not i.get("parent_item_id")]

    return OrderSummary(
        increment_id=str(raw.get("increment_id", "")),
        state=raw.get("state", ""),
        status=raw.get("status", ""),
        created_at=raw.get("created_at", ""),
        grand_total=raw.get("grand_total", 0),
        currency_code=raw.get("order_currency_code"),
        total_qty_ordered=raw.get("total_qty_ordered", 0),
        customer_name=name,
        customer_email=raw.get("customer_email"),
        total_items=len(parent_items),
    )


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


async def admin_search_orders(
    status: str | None = None,
    customer_email: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    grand_total_min: float | None = None,
    grand_total_max: float | None = None,
    page_size: int = 20,
    current_page: int = 1,
    sort_field: str = "created_at",
    sort_direction: str = "DESC",
    store_scope: str = "default",
) -> dict[str, Any]:
    """Search orders — returns summaries."""
    inp = AdminSearchOrdersInput(
        status=status,
        customer_email=customer_email,
        created_from=parse_date_expr(created_from) if created_from else None,
        created_to=parse_date_expr(created_to) if created_to else None,
        grand_total_min=grand_total_min,
        grand_total_max=grand_total_max,
        page_size=page_size,
        current_page=current_page,
        sort_field=sort_field,
        sort_direction=sort_direction,
        store_scope=store_scope,
    )

    log.info(
        "admin_search_orders store=%s status=%s email=%s page=%d",
        inp.store_scope, inp.status, inp.customer_email, inp.current_page,
    )

    params = _build_search_params(inp)

    async with RESTClient.from_env() as client:
        data = await client.get(
            "/V1/orders",
            params=params,
            store_code=inp.store_scope,
        )

    raw_items = data.get("items") or []
    summaries = [_parse_order_summary(item) for item in raw_items]

    return {
        "orders": [s.model_dump(mode="json") for s in summaries],
        "total_count": data.get("total_count", 0),
        "page_size": inp.page_size,
        "current_page": inp.current_page,
    }


def register_search_orders(mcp: FastMCP) -> None:
    """Register the admin_search_orders tool on the given MCP server."""
    mcp.tool(
        name="admin_search_orders",
        title="Search Orders",
        description=(
            "Search orders with filters: status, customer email, date range, total range. "
            "from_date/to_date accept natural language: 'today', 'this week', 'last month', 'ytd', "
            "or ISO date strings. Returns lightweight summaries — use admin_get_order for full detail "
            "including items, tracking, and addresses. For a single customer's orders use "
            "admin_get_customer_orders instead."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )(admin_search_orders)
