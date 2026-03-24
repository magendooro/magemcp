"""admin shipment read tools — get and search shipments via Magento REST API."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from magemcp.connectors.errors import MagentoNotFoundError
from magemcp.connectors.rest_client import RESTClient

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_shipment(raw: dict[str, Any]) -> dict[str, Any]:
    tracks = [
        {
            "track_number": t.get("track_number"),
            "carrier_code": t.get("carrier_code"),
            "title": t.get("title"),
            "created_at": t.get("created_at"),
        }
        for t in (raw.get("tracks") or [])
    ]
    items = [
        {
            "sku": item.get("sku"),
            "name": item.get("name"),
            "qty": item.get("qty"),
            "price": item.get("price"),
        }
        for item in (raw.get("items") or [])
    ]
    return {
        "entity_id": raw.get("entity_id"),
        "increment_id": raw.get("increment_id"),
        "order_id": raw.get("order_id"),
        "created_at": raw.get("created_at"),
        "updated_at": raw.get("updated_at"),
        "total_qty": raw.get("total_qty"),
        "tracks": tracks,
        "items": items,
    }


def _parse_shipment_summary(raw: dict[str, Any]) -> dict[str, Any]:
    tracks = [
        {
            "track_number": t.get("track_number"),
            "carrier_code": t.get("carrier_code"),
            "title": t.get("title"),
        }
        for t in (raw.get("tracks") or [])
    ]
    return {
        "entity_id": raw.get("entity_id"),
        "increment_id": raw.get("increment_id"),
        "order_id": raw.get("order_id"),
        "created_at": raw.get("created_at"),
        "total_qty": raw.get("total_qty"),
        "tracks": tracks,
    }


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


async def admin_get_shipment(
    shipment_id: int,
    store_scope: str = "default",
) -> dict[str, Any]:
    """Get full detail for a Magento shipment by its entity ID."""
    log.info("admin_get_shipment shipment_id=%s", shipment_id)

    async with RESTClient.from_env() as client:
        raw = await client.get(f"/V1/shipments/{shipment_id}", store_code=store_scope)

    if not raw or "entity_id" not in raw:
        raise MagentoNotFoundError(f"Shipment {shipment_id} not found.")

    return _parse_shipment(raw)


async def admin_search_shipments(
    order_id: int | None = None,
    page_size: int = 20,
    current_page: int = 1,
    store_scope: str = "default",
) -> dict[str, Any]:
    """Search shipments, optionally filtered by order ID."""
    log.info("admin_search_shipments order_id=%s", order_id)

    filters: dict[str, Any] = {}
    if order_id is not None:
        filters["order_id"] = order_id

    params = RESTClient.search_params(
        filters=filters or None,
        page_size=max(1, min(page_size, 100)),
        current_page=max(1, current_page),
        sort_field="created_at",
        sort_direction="DESC",
    )

    async with RESTClient.from_env() as client:
        data = await client.get("/V1/shipments", params=params, store_code=store_scope)

    items = data.get("items") or []
    return {
        "total_count": data.get("total_count", len(items)),
        "page_size": page_size,
        "current_page": current_page,
        "shipments": [_parse_shipment_summary(item) for item in items],
    }


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_shipment_tools(mcp: FastMCP) -> None:
    """Register all admin shipment read tools on the given MCP server."""

    mcp.tool(
        name="admin_get_shipment",
        title="Get Shipment",
        description=(
            "Get full detail for a shipment by its entity ID, including tracking numbers "
            "and line items. Use admin_search_shipments to find the entity ID from an order."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )(admin_get_shipment)

    mcp.tool(
        name="admin_search_shipments",
        title="Search Shipments",
        description=(
            "Search shipments, optionally filtered by order ID. "
            "Returns shipment summaries with tracking numbers."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )(admin_search_shipments)
