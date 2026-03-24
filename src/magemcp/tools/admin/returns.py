"""admin returns/RMA read tools — search and get returns via Magento REST API."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from magemcp.connectors.errors import MagentoNotFoundError
from magemcp.connectors.rest_client import RESTClient

log = logging.getLogger(__name__)

# Magento RMA status constants
RMA_STATES = {
    "pending": "Pending",
    "authorized": "Authorized",
    "partial_authorized": "Partially Authorized",
    "received": "Received",
    "rejected": "Rejected",
    "approved": "Approved",
    "partial_approved": "Partially Approved",
    "solved": "Solved",
    "closed": "Closed",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_return_summary(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "entity_id": raw.get("entity_id"),
        "increment_id": raw.get("increment_id"),
        "order_id": raw.get("order_id"),
        "store_id": raw.get("store_id"),
        "date_requested": raw.get("date_requested"),
        "status": raw.get("status"),
        "customer_id": raw.get("customer_id"),
        "customer_name": raw.get("customer_name"),
        "items_count": len(raw.get("items") or []),
    }


def _parse_return_detail(raw: dict[str, Any]) -> dict[str, Any]:
    summary = _parse_return_summary(raw)
    items = [
        {
            "entity_id": item.get("entity_id"),
            "order_item_id": item.get("order_item_id"),
            "qty_requested": item.get("qty_requested"),
            "qty_authorized": item.get("qty_authorized"),
            "qty_approved": item.get("qty_approved"),
            "qty_returned": item.get("qty_returned"),
            "reason": item.get("reason_id"),
            "condition": item.get("condition_id"),
            "resolution": item.get("resolution_id"),
        }
        for item in (raw.get("items") or [])
    ]
    comments = [
        {
            "entity_id": c.get("entity_id"),
            "comment": c.get("comment"),
            "is_admin": c.get("is_admin"),
            "created_at": c.get("created_at"),
        }
        for c in (raw.get("comments") or [])
    ]
    return {**summary, "items": items, "comments": comments}


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


async def admin_search_returns(
    order_id: int | None = None,
    status: str | None = None,
    customer_id: int | None = None,
    page_size: int = 20,
    current_page: int = 1,
    store_scope: str = "default",
) -> dict[str, Any]:
    """Search RMA / return requests."""
    log.info(
        "admin_search_returns order_id=%s status=%s customer_id=%s",
        order_id, status, customer_id,
    )

    if status is not None and status not in RMA_STATES:
        valid = ", ".join(sorted(RMA_STATES.keys()))
        raise ValueError(f"Invalid return status '{status}'. Valid values: {valid}")

    filters: dict[str, Any] = {}
    if order_id is not None:
        filters["order_id"] = order_id
    if status is not None:
        filters["status"] = status
    if customer_id is not None:
        filters["customer_id"] = customer_id

    params = RESTClient.search_params(
        filters=filters or None,
        page_size=max(1, min(page_size, 100)),
        current_page=max(1, current_page),
        sort_field="date_requested",
        sort_direction="DESC",
    )

    async with RESTClient.from_env() as client:
        data = await client.get("/V1/returns", params=params, store_code=store_scope)

    items = data.get("items") or []
    return {
        "total_count": data.get("total_count", len(items)),
        "page_size": page_size,
        "current_page": current_page,
        "returns": [_parse_return_summary(item) for item in items],
    }


async def admin_get_return(
    return_id: int,
    store_scope: str = "default",
) -> dict[str, Any]:
    """Get full detail for a return / RMA request by its entity ID."""
    log.info("admin_get_return return_id=%s", return_id)

    async with RESTClient.from_env() as client:
        raw = await client.get(f"/V1/returns/{return_id}", store_code=store_scope)

    if not raw or "entity_id" not in raw:
        raise MagentoNotFoundError(f"Return {return_id} not found.")

    return _parse_return_detail(raw)


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_return_tools(mcp: FastMCP) -> None:
    """Register all admin return / RMA read tools on the given MCP server."""

    mcp.tool(
        name="admin_search_returns",
        title="Search Returns",
        description=(
            "Search RMA / return requests by order ID, status, or customer ID. "
            "Status values: pending, authorized, received, rejected, approved, solved, closed. "
            "Returns a summary list. Use admin_get_return for full detail."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )(admin_search_returns)

    mcp.tool(
        name="admin_get_return",
        title="Get Return",
        description=(
            "Get full detail for an RMA / return request by its entity ID. "
            "Includes return items with quantities (requested/authorized/approved), "
            "reason, condition, resolution, and all comments."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )(admin_get_return)
