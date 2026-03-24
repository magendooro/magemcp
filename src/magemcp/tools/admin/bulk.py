"""admin bulk async tools — bulk inventory/catalog updates and status polling."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from magemcp.connectors.rest_client import RESTClient
from magemcp.tools.admin._confirmation import elicit_confirmation
from magemcp.utils.idempotency import idempotency_store

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


async def admin_bulk_inventory_update(
    items: list[dict[str, Any]],
    confirm: bool = False,
    idempotency_key: str | None = None,
    store_scope: str = "default",
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Update inventory for multiple SKUs in a single async bulk operation.

    Each element of `items` must include:
      - sku (str): the product SKU
      - quantity (float): new quantity
    Optional per-item fields:
      - source_code (str): MSI source code (default: 'default')
      - status (int): 1=in-stock, 0=out-of-stock (default: 1)

    Returns a bulk_uuid to poll with admin_get_bulk_status.
    Requires confirmation — call with confirm=True to proceed.
    """
    if not items:
        raise ValueError("items list must not be empty")

    if idempotency_key:
        stored = idempotency_store.get("admin_bulk_inventory_update", idempotency_key)
        if stored is not None:
            return {**stored, "idempotent_replay": True}

    prompt = await elicit_confirmation(
        ctx,
        f"bulk-update inventory for {len(items)} SKU(s)",
        f"{len(items)} items",
        confirm,
    )
    if prompt:
        return prompt

    log.info(
        "admin_bulk_inventory_update item_count=%d store=%s", len(items), store_scope
    )

    # Async/bulk endpoint expects an array; each element is one API-call payload
    payload = [
        {
            "sourceItems": [{
                "sku": item["sku"],
                "source_code": item.get("source_code", "default"),
                "quantity": float(item["quantity"]),
                "status": int(item.get("status", 1)),
            }]
        }
        for item in items
    ]

    async with RESTClient.from_env() as client:
        result = await client.post(
            "/async/bulk/V1/inventory/source-items",
            json=payload,
            store_code=store_scope,
        )

    bulk_uuid = result.get("bulk_uuid", "")
    out: dict[str, Any] = {
        "success": True,
        "bulk_uuid": bulk_uuid,
        "item_count": len(items),
        "operation_count": len(result.get("request_items") or []),
    }
    if idempotency_key:
        idempotency_store.set("admin_bulk_inventory_update", idempotency_key, out)
    return out


async def admin_bulk_catalog_update(
    products: list[dict[str, Any]],
    confirm: bool = False,
    idempotency_key: str | None = None,
    store_scope: str = "default",
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Update multiple products in a single async bulk operation.

    Each element of `products` must include `sku` plus any fields to update
    (name, price, status, weight).  Text/EAV attributes go in
    custom_attributes: [{attribute_code, value}] inside each product dict.

    Returns a bulk_uuid to poll with admin_get_bulk_status.
    Requires confirmation — call with confirm=True to proceed.
    """
    if not products:
        raise ValueError("products list must not be empty")

    if idempotency_key:
        stored = idempotency_store.get("admin_bulk_catalog_update", idempotency_key)
        if stored is not None:
            return {**stored, "idempotent_replay": True}

    prompt = await elicit_confirmation(
        ctx,
        f"bulk-update {len(products)} product(s)",
        f"{len(products)} products",
        confirm,
    )
    if prompt:
        return prompt

    log.info(
        "admin_bulk_catalog_update product_count=%d store=%s", len(products), store_scope
    )

    # Async/bulk endpoint expects an array; each element is one API-call payload
    payload = [{"product": product} for product in products]

    async with RESTClient.from_env() as client:
        result = await client.post(
            "/async/bulk/V1/products",
            json=payload,
            store_code=store_scope,
        )

    bulk_uuid = result.get("bulk_uuid", "")
    out: dict[str, Any] = {
        "success": True,
        "bulk_uuid": bulk_uuid,
        "product_count": len(products),
        "operation_count": len(result.get("request_items") or []),
    }
    if idempotency_key:
        idempotency_store.set("admin_bulk_catalog_update", idempotency_key, out)
    return out


async def admin_get_bulk_status(
    bulk_uuid: str,
    store_scope: str = "default",
) -> dict[str, Any]:
    """Get the status of an async bulk operation by its bulk_uuid.

    Poll this after calling admin_bulk_inventory_update or admin_bulk_catalog_update.
    Operation statuses: 1=complete, 2=retriable-failed, 4=not-retriable-failed, 5=open.
    """
    log.info("admin_get_bulk_status bulk_uuid=%s", bulk_uuid)

    async with RESTClient.from_env() as client:
        data = await client.get(
            f"/V1/bulk/{bulk_uuid}/status",
            store_code=store_scope,
        )

    operations = data.get("operations_list") or []
    status_counts: dict[int, int] = {}
    for op in operations:
        s = int(op.get("status", 0))
        status_counts[s] = status_counts.get(s, 0) + 1

    return {
        "bulk_uuid": bulk_uuid,
        "start_time": data.get("start_time"),
        "operation_count": data.get("operation_count", len(operations)),
        "complete": status_counts.get(1, 0),
        "failed": status_counts.get(4, 0),
        "open": status_counts.get(5, 0),
        "status_breakdown": status_counts,
        "operations": [
            {
                "id": op.get("id"),
                "status": op.get("status"),
                "result_message": op.get("result_message"),
            }
            for op in operations
        ],
    }


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_bulk_tools(mcp: FastMCP) -> None:
    """Register all admin bulk async tools on the given MCP server."""

    mcp.tool(
        name="admin_bulk_inventory_update",
        title="Bulk Inventory Update",
        description=(
            "Update inventory quantities for multiple SKUs in a single async bulk operation. "
            "Each item requires: sku (str), quantity (float). "
            "Optional per-item: source_code (default: 'default'), status (1=in-stock, 0=out-of-stock). "
            "Returns a bulk_uuid — use admin_get_bulk_status to check completion. "
            "Pass idempotency_key to safely retry without duplicating operations. "
            "Requires confirmation — call with confirm=True to proceed."
        ),
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )(admin_bulk_inventory_update)

    mcp.tool(
        name="admin_bulk_catalog_update",
        title="Bulk Catalog Update",
        description=(
            "Update multiple products in a single async bulk operation. "
            "Each product dict must include 'sku' plus any fields to update "
            "(name, price, status, weight, custom_attributes). "
            "Returns a bulk_uuid — use admin_get_bulk_status to check completion. "
            "Pass idempotency_key to safely retry without duplicating operations. "
            "Requires confirmation — call with confirm=True to proceed."
        ),
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )(admin_bulk_catalog_update)

    mcp.tool(
        name="admin_get_bulk_status",
        title="Get Bulk Operation Status",
        description=(
            "Check the status of an async bulk operation by its bulk_uuid. "
            "Returns operation counts broken down by status: complete, failed, open (still processing). "
            "Poll until operation_count == complete + failed. "
            "Use after admin_bulk_inventory_update or admin_bulk_catalog_update."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )(admin_get_bulk_status)
