"""MageMCP — MCP server for Magento 2 / Adobe Commerce.

Dual-namespace tool registration:
  c_*     — customer-facing operations via GraphQL (catalog, cart, account)
  admin_* — admin operations via REST API (orders, customers, inventory)
"""

from __future__ import annotations

import logging
import os

from mcp.server.fastmcp import FastMCP

log = logging.getLogger(__name__)

# Host/port are only used when MAGEMCP_TRANSPORT=streamable-http.
# For stdio (default) these values are ignored.
_host = os.getenv("MAGEMCP_HOST", "127.0.0.1")
_port = int(os.getenv("MAGEMCP_PORT", "8000"))

mcp = FastMCP(
    "MageMCP",
    instructions=(
        "MageMCP v2 — Magento 2 MCP Server with dual namespaces. "
        "c_* tools: customer-facing operations via GraphQL (catalog, cart, account). "
        "admin_* tools: admin operations via REST API (orders, customers, inventory "
        "— full access, no PII masking). "
    ),
    host=_host,
    port=_port,
)

# ---------------------------------------------------------------------------
# Tool registration — customer namespace (GraphQL)
# ---------------------------------------------------------------------------

from magemcp.tools.customer.search_products import register_search_products

register_search_products(mcp)

from magemcp.tools.customer.get_product import register_get_product

register_get_product(mcp)

from magemcp.tools.customer.get_categories import register_get_categories

register_get_categories(mcp)

from magemcp.tools.customer.cart import register_cart_tools

register_cart_tools(mcp)

from magemcp.tools.customer.store_config import register_store_config

register_store_config(mcp)

from magemcp.tools.customer.resolve_url import register_resolve_url

register_resolve_url(mcp)

# ---------------------------------------------------------------------------
# Tool registration — admin namespace (REST)
# ---------------------------------------------------------------------------

from magemcp.tools.admin.search_orders import register_search_orders

register_search_orders(mcp)

from magemcp.tools.admin.get_order import register_get_order

register_get_order(mcp)

from magemcp.tools.admin.search_customers import register_search_customers

register_search_customers(mcp)

from magemcp.tools.admin.get_customer import register_get_customer

register_get_customer(mcp)

from magemcp.tools.admin.get_inventory import register_get_inventory

register_get_inventory(mcp)

from magemcp.tools.admin.update_inventory import register_update_inventory

register_update_inventory(mcp)

from magemcp.tools.admin.products import register_product_tools

register_product_tools(mcp)

from magemcp.tools.admin.cms import register_cms_tools

register_cms_tools(mcp)

from magemcp.tools.admin.promotions import register_promotion_tools

register_promotion_tools(mcp)

from magemcp.tools.admin.order_actions import register_order_actions

register_order_actions(mcp)

from magemcp.tools.admin.analytics import register_analytics

register_analytics(mcp)

# ---------------------------------------------------------------------------
# Apply policy engine to all registered tools
# ---------------------------------------------------------------------------

from magemcp.policy.engine import with_policy

for _tool_name, _tool_obj in mcp._tool_manager._tools.items():
    _tool_obj.fn = with_policy(_tool_name)(_tool_obj.fn)


def main() -> None:
    """Entry point for the MageMCP server."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
    transport = os.getenv("MAGEMCP_TRANSPORT", "stdio")
    log.info("Starting MageMCP server (transport=%s) …", transport)
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
