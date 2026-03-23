"""MageMCP — MCP server for Magento 2 / Adobe Commerce.

Dual-namespace tool registration:
  c_*     — customer-facing operations via GraphQL (catalog, cart, account)
  admin_* — admin operations via REST API (orders, customers, inventory)
"""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

log = logging.getLogger(__name__)

mcp = FastMCP(
    "MageMCP",
    instructions=(
        "MageMCP v2 — Magento 2 MCP Server with dual namespaces. "
        "c_* tools: customer-facing operations via GraphQL (catalog, cart, account). "
        "admin_* tools: admin operations via REST API (orders, customers, inventory "
        "— full access, no PII masking). "
    ),
)

# ---------------------------------------------------------------------------
# Tool registration — customer namespace (GraphQL)
# ---------------------------------------------------------------------------

from magemcp.tools.customer.search_products import register_search_products

register_search_products(mcp)

from magemcp.tools.customer.get_product import register_get_product

register_get_product(mcp)

# ---------------------------------------------------------------------------
# Tool registration — admin namespace (REST)
# ---------------------------------------------------------------------------

from magemcp.tools.admin.get_order import register_get_order

register_get_order(mcp)

from magemcp.tools.admin.get_customer import register_get_customer

register_get_customer(mcp)

from magemcp.tools.admin.get_inventory import register_get_inventory

register_get_inventory(mcp)


def main() -> None:
    """Entry point for the MageMCP server."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
    log.info("Starting MageMCP server …")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
