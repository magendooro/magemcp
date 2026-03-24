"""admin_get_order_tracking — get all shipment tracking numbers for an order."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from magemcp.connectors.rest_client import RESTClient

log = logging.getLogger(__name__)


async def admin_get_order_tracking(
    order_id: int,
    store_scope: str = "default",
) -> dict[str, Any]:
    """Get all shipment tracking numbers for an order by its entity ID.

    Aggregates tracking numbers across every shipment for the order — useful
    when a customer asks 'where is my order?' or 'what is my tracking number?'.
    """
    log.info("admin_get_order_tracking order_id=%s store=%s", order_id, store_scope)

    params = RESTClient.search_params(
        filters={"order_id": order_id},
        page_size=50,
        sort_field="created_at",
        sort_direction="DESC",
    )

    async with RESTClient.from_env() as client:
        data = await client.get("/V1/shipments", params=params, store_code=store_scope)

    shipments = data.get("items") or []
    tracking: list[dict[str, Any]] = []
    for shipment in shipments:
        for track in (shipment.get("tracks") or []):
            tracking.append({
                "shipment_id": shipment.get("entity_id"),
                "shipment_increment_id": shipment.get("increment_id"),
                "track_number": track.get("track_number"),
                "carrier_code": track.get("carrier_code"),
                "title": track.get("title"),
                "created_at": track.get("created_at"),
            })

    return {
        "order_id": order_id,
        "shipment_count": len(shipments),
        "tracking": tracking,
    }


def register_order_tracking(mcp: FastMCP) -> None:
    """Register the admin_get_order_tracking tool on the given MCP server."""
    mcp.tool(
        name="admin_get_order_tracking",
        title="Get Order Tracking",
        description=(
            "Get all shipment tracking numbers for an order by its entity ID. "
            "Returns every carrier tracking number across all shipments for the order. "
            "Use admin_get_order or admin_search_orders to find the entity_id first."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )(admin_get_order_tracking)
