"""admin_search_quotes — search abandoned/active guest carts via Magento REST API."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from magemcp.connectors.rest_client import RESTClient
from magemcp.utils.dates import parse_date_expr

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_quote_summary(raw: dict[str, Any]) -> dict[str, Any]:
    """Return a lean cart/quote dict from a raw Magento REST response."""
    return {
        "id": raw.get("id"),
        "customer_email": raw.get("customer_email"),
        "customer_firstname": raw.get("customer_firstname"),
        "customer_lastname": raw.get("customer_lastname"),
        "items_count": raw.get("items_count"),
        "items_qty": raw.get("items_qty"),
        "grand_total": raw.get("grand_total"),
        "base_grand_total": raw.get("base_grand_total"),
        "currency_code": (raw.get("currency") or {}).get("quote_currency_code"),
        "store_id": raw.get("store_id"),
        "is_active": raw.get("is_active"),
        "is_virtual": raw.get("is_virtual"),
        "created_at": raw.get("created_at"),
        "updated_at": raw.get("updated_at"),
    }


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------


async def admin_search_quotes(
    customer_email: str | None = None,
    min_grand_total: float | None = None,
    updated_from: str | None = None,
    is_active: bool | None = None,
    store_id: int | None = None,
    page_size: int = 20,
    current_page: int = 1,
    store_scope: str = "default",
) -> dict[str, Any]:
    """Search active and abandoned guest/customer carts (quotes)."""
    log.info(
        "admin_search_quotes email=%s min_total=%s updated_from=%s is_active=%s",
        customer_email, min_grand_total, updated_from, is_active,
    )

    filters: dict[str, Any] = {}
    if customer_email:
        filters["customer_email"] = (customer_email, "like")
    if is_active is not None:
        filters["is_active"] = int(is_active)
    if store_id is not None:
        filters["store_id"] = store_id

    params = RESTClient.search_params(
        filters=filters or None,
        page_size=max(1, min(page_size, 50)),
        current_page=max(1, current_page),
        sort_field="updated_at",
        sort_direction="DESC",
    )

    idx = len(filters)
    if min_grand_total is not None:
        prefix = f"searchCriteria[filterGroups][{idx}][filters][0]"
        params[f"{prefix}[field]"] = "grand_total"
        params[f"{prefix}[value]"] = str(min_grand_total)
        params[f"{prefix}[conditionType]"] = "gteq"
        idx += 1
    if updated_from:
        resolved = parse_date_expr(updated_from)
        prefix = f"searchCriteria[filterGroups][{idx}][filters][0]"
        params[f"{prefix}[field]"] = "updated_at"
        params[f"{prefix}[value]"] = resolved
        params[f"{prefix}[conditionType]"] = "gteq"

    async with RESTClient.from_env() as client:
        data = await client.get("/V1/carts/search", params=params, store_code=store_scope)

    items = data.get("items") or []
    return {
        "total_count": data.get("total_count", len(items)),
        "page_size": page_size,
        "current_page": current_page,
        "quotes": [_parse_quote_summary(item) for item in items],
    }


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_quotes(mcp: FastMCP) -> None:
    """Register the admin_search_quotes tool on the given MCP server."""
    mcp.tool(
        name="admin_search_quotes",
        title="Search Abandoned Carts",
        description=(
            "Search active and abandoned shopping carts (Magento quotes). "
            "Use to identify high-value abandoned carts for recovery campaigns: "
            "filter by min_grand_total and updated_from (e.g. 'last 7 days'). "
            "is_active=True returns carts that have not yet been converted to orders; "
            "is_active=False returns converted or cancelled carts. "
            "updated_from accepts natural language dates (today, last week, this month) or YYYY-MM-DD. "
            "Returns customer email, item counts, grand_total, and last activity timestamp."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )(admin_search_quotes)
