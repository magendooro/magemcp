"""admin_get_inventory — check salable quantity for SKU(s) via Magento REST API."""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

from magemcp.connectors.errors import MagentoError
from magemcp.connectors.rest_client import RESTClient
from magemcp.models.inventory import CGetInventoryInput, CGetInventoryOutput, SkuInventory

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------


async def admin_get_inventory(
    skus: list[str],
    stock_id: int = 1,
    store_scope: str = "default",
) -> CGetInventoryOutput:
    """Check salable inventory for one or more SKUs."""
    inp = CGetInventoryInput(skus=skus, stock_id=stock_id, store_scope=store_scope)

    log.info(
        "admin_get_inventory skus=%s stock_id=%d store=%s",
        inp.skus,
        inp.stock_id,
        inp.store_scope,
    )

    results: list[SkuInventory] = []

    async with RESTClient.from_env() as client:
        for sku in inp.skus:
            # Fetch salable quantity
            qty: float = 0
            is_salable: bool = False
            error: str | None = None

            try:
                qty_data = await client.get(
                    f"/V1/inventory/get-product-salable-quantity/{sku}/{inp.stock_id}",
                    store_code=inp.store_scope,
                )
                # Magento returns just a number for this endpoint
                qty = float(qty_data) if qty_data is not None else 0
            except MagentoError as exc:
                error = str(exc)

            try:
                salable_data = await client.get(
                    f"/V1/inventory/is-product-salable/{sku}/{inp.stock_id}",
                    store_code=inp.store_scope,
                )
                is_salable = bool(salable_data) if salable_data is not None else False
            except MagentoError as exc:
                if error is None:
                    error = str(exc)

            results.append(SkuInventory(
                sku=sku,
                salable_quantity=qty,
                is_salable=is_salable,
                stock_id=inp.stock_id,
                error=error,
            ))

    output = CGetInventoryOutput(items=results, stock_id=inp.stock_id)
    return output.model_dump(mode="json")  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_get_inventory(mcp: FastMCP) -> None:
    """Register the admin_get_inventory tool on the given MCP server."""
    mcp.tool(
        name="admin_get_inventory",
        title="Get Inventory",
        description=(
            "Check salable stock for one or more SKUs. Returns salable_quantity (accounting for "
            "reservations, not raw warehouse stock) and is_salable (whether the product can actually "
            "be ordered). Use this to answer 'is X in stock?' before recommending a product. "
            "Pass stock_id=1 for the default MSI stock."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )(admin_get_inventory)
