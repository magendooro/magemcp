"""admin_update_inventory — update inventory source item quantity via Magento REST API."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from magemcp.connectors.rest_client import RESTClient
from magemcp.tools.admin._confirmation import needs_confirmation

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------


async def admin_update_inventory(
    sku: str,
    quantity: float,
    source_code: str = "default",
    status: int = 1,
    confirm: bool = False,
    store_scope: str = "default",
) -> dict[str, Any]:
    """Update source item quantity for a SKU. Requires confirmation."""
    log.info(
        "admin_update_inventory sku=%s qty=%s source=%s confirm=%s",
        sku, quantity, source_code, confirm,
    )

    prompt = needs_confirmation(f"set inventory for {sku} to {quantity}", sku, confirm)
    if prompt:
        return prompt

    payload: dict[str, Any] = {
        "sourceItems": [{
            "sku": sku,
            "source_code": source_code,
            "quantity": quantity,
            "status": status,
        }]
    }

    async with RESTClient.from_env() as client:
        await client.post(
            "/V1/inventory/source-items",
            json=payload,
            store_code=store_scope,
        )

    return {
        "success": True,
        "sku": sku,
        "source_code": source_code,
        "quantity": quantity,
        "status": status,
    }


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_update_inventory(mcp: FastMCP) -> None:
    """Register the admin_update_inventory tool on the given MCP server."""
    mcp.tool(
        name="admin_update_inventory",
        title="Update Inventory",
        description=(
            "Update the inventory source item quantity for a SKU. "
            "Uses the Magento MSI source-items endpoint. "
            "Requires confirmation — call with confirm=True to proceed."
        ),
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )(admin_update_inventory)
