"""admin_get_customer_orders — fetch all orders for a specific customer."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from magemcp.connectors.rest_client import RESTClient
from magemcp.tools.admin.search_orders import _parse_order_summary, _build_search_params, AdminSearchOrdersInput

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------


async def admin_get_customer_orders(
    customer_id: int | None = None,
    email: str | None = None,
    page_size: int = 20,
    current_page: int = 1,
    store_scope: str = "default",
) -> dict[str, Any]:
    """Get all orders for a customer by customer ID or email."""
    if customer_id is None and email is None:
        raise ValueError("Provide either customer_id or email.")

    log.info(
        "admin_get_customer_orders customer_id=%s email=%s page=%d",
        customer_id, email, current_page,
    )

    inp = AdminSearchOrdersInput(
        customer_email=email,
        page_size=page_size,
        current_page=current_page,
        sort_field="created_at",
        sort_direction="DESC",
        store_scope=store_scope,
    )
    params = _build_search_params(inp)

    if customer_id is not None:
        # Count existing filter groups to append at the right index
        idx = sum(1 for k in params if "[filterGroups][" in k and "[filters][0][field]" in k)
        prefix = f"searchCriteria[filterGroups][{idx}][filters][0]"
        params[f"{prefix}[field]"] = "customer_id"
        params[f"{prefix}[value]"] = str(customer_id)
        params[f"{prefix}[conditionType]"] = "eq"

    async with RESTClient.from_env() as client:
        data = await client.get("/V1/orders", params=params, store_code=store_scope)

    raw_items = data.get("items") or []
    summaries = [_parse_order_summary(item) for item in raw_items]

    return {
        "customer_id": customer_id,
        "email": email,
        "orders": [s.model_dump(mode="json") for s in summaries],
        "total_count": data.get("total_count", 0),
        "page_size": page_size,
        "current_page": current_page,
    }


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_customer_orders(mcp: FastMCP) -> None:
    """Register the admin_get_customer_orders tool on the given MCP server."""
    mcp.tool(
        name="admin_get_customer_orders",
        title="Get Customer Orders",
        description=(
            "Fetch order history for a specific customer by customer ID or email. "
            "Returns a paginated list of order summaries sorted by most recent first. "
            "Provide either customer_id (preferred, exact match) or email (exact match). "
            "Use admin_get_order for full order detail."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )(admin_get_customer_orders)
