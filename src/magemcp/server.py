"""MageMCP — MCP server for Magento 2 / Adobe Commerce.

Registers read-only MCP tools for catalog, orders, customers, and inventory.
"""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

log = logging.getLogger(__name__)

mcp = FastMCP(
    "MageMCP",
    instructions=(
        "You are connected to a Magento 2 instance via MageMCP. "
        "Use the available tools to query and manage catalog, orders, "
        "customers, and inventory. All operations are read-only unless "
        "explicitly stated otherwise."
    ),
)

# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

from magemcp.tools.search_products import register_search_products

register_search_products(mcp)

from magemcp.tools.get_product import register_get_product

register_get_product(mcp)

from magemcp.tools.get_order import register_get_order

register_get_order(mcp)

from magemcp.tools.get_customer import register_get_customer

register_get_customer(mcp)

from magemcp.tools.get_inventory import register_get_inventory

register_get_inventory(mcp)


def main() -> None:
    """Entry point for the MageMCP server."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
    log.info("Starting MageMCP server …")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
