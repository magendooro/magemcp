"""admin_update_inventory — update inventory source item quantity via Magento REST API."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from magemcp.connectors.rest_client import RESTClient
from magemcp.tools.admin._confirmation import elicit_confirmation

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
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Update source item quantity for a SKU. Requires confirmation."""
    log.info(
        "admin_update_inventory sku=%s qty=%s source=%s confirm=%s",
        sku, quantity, source_code, confirm,
    )

    prompt = await elicit_confirmation(ctx, f"set inventory for {sku} to {quantity}", sku, confirm)
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
            "Update the physical stock quantity for a SKU at a specific warehouse source. "
            "source_code is the MSI source identifier (usually 'default'). "
            "Use admin_get_inventory to check current levels first. "
            "Requires confirmation — call twice with confirm=True to proceed."
        ),
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )(admin_update_inventory)
