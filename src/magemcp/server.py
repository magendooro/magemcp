"""MageMCP — MCP server for Magento 2 / Adobe Commerce.

Dual-namespace tool registration:
  c_*     — customer-facing operations via GraphQL (catalog, cart, account)
  admin_* — admin operations via REST API (orders, customers, inventory)
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from mcp.server.fastmcp import FastMCP

log = logging.getLogger(__name__)

# Host/port are only used when MAGEMCP_TRANSPORT=streamable-http.
# For stdio (default) these values are ignored.
_host = os.getenv("MAGEMCP_HOST", "127.0.0.1")
_port = int(os.getenv("MAGEMCP_PORT", "8000"))

# OAuth auth settings — only active when MAGEMCP_AUTH_ISSUER_URL and
# MAGEMCP_AUTH_RESOURCE_SERVER_URL env vars are set.  Disabled by default
# (appropriate for stdio and trusted internal deployments).
from magemcp.auth import build_auth_settings, build_token_verifier  # noqa: E402

_auth_settings = build_auth_settings()
_token_verifier = build_token_verifier()


@asynccontextmanager
async def _lifespan(app: FastMCP) -> AsyncIterator[None]:  # type: ignore[type-arg]
    """Initialise shared connection pool on startup; close on shutdown."""
    from magemcp.connectors.pool import init as pool_init, close as pool_close

    # Only initialise pool when env vars are present (skip in test environments)
    if os.environ.get("MAGENTO_BASE_URL") and os.environ.get("MAGEMCP_ADMIN_TOKEN"):
        try:
            await pool_init()
        except Exception:
            log.warning("Connection pool init failed — falling back to per-call clients.", exc_info=True)

    try:
        yield
    finally:
        await pool_close()


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
    lifespan=_lifespan,
    auth=_auth_settings,
    token_verifier=_token_verifier,
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

from magemcp.tools.customer.policy_page import register_policy_page

register_policy_page(mcp)

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

from magemcp.tools.admin.customer_orders import register_customer_orders

register_customer_orders(mcp)

from magemcp.tools.admin.invoices import register_invoice_tools

register_invoice_tools(mcp)

from magemcp.tools.admin.shipments import register_shipment_tools

register_shipment_tools(mcp)

from magemcp.tools.admin.returns import register_return_tools

register_return_tools(mcp)

from magemcp.tools.admin.quotes import register_quotes

register_quotes(mcp)

from magemcp.tools.admin.store_hierarchy import register_store_hierarchy

register_store_hierarchy(mcp)

from magemcp.tools.admin.reviews import register_review_tools

register_review_tools(mcp)

from magemcp.tools.admin.order_tracking import register_order_tracking

register_order_tracking(mcp)

from magemcp.tools.admin.bulk import register_bulk_tools

register_bulk_tools(mcp)

from magemcp.tools.customer.initiate_return import register_initiate_return

register_initiate_return(mcp)

# ---------------------------------------------------------------------------
# Apply policy engine to all registered tools
# ---------------------------------------------------------------------------

from magemcp.policy.engine import with_policy

for _tool_name, _tool_obj in mcp._tool_manager._tools.items():
    _tool_obj.fn = with_policy(_tool_name)(_tool_obj.fn)

# ---------------------------------------------------------------------------
# Audit log file handler — active when MAGEMCP_AUDIT_LOG_FILE is set
# ---------------------------------------------------------------------------

_audit_log_file = os.getenv("MAGEMCP_AUDIT_LOG_FILE", "").strip()
if _audit_log_file:
    import logging as _logging

    _audit_fh = _logging.FileHandler(_audit_log_file, encoding="utf-8")
    _audit_fh.setFormatter(_logging.Formatter("%(message)s"))
    _logging.getLogger("magemcp.audit").addHandler(_audit_fh)
    log.info("Audit log file: %s", _audit_log_file)

# ---------------------------------------------------------------------------
# Health / metrics / audit routes (HTTP transport only)
# ---------------------------------------------------------------------------

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from magemcp.health import get_health
from magemcp.policy.engine import get_audit_log, get_metrics


async def _health_endpoint(request: Request) -> JSONResponse:
    tool_count = len(mcp._tool_manager._tools)
    return JSONResponse(get_health(tool_count))


async def _metrics_endpoint(request: Request) -> JSONResponse:
    return JSONResponse({"metrics": get_metrics()})


async def _audit_endpoint(request: Request) -> JSONResponse:
    """Return recent audit log entries.

    Query parameters:
      limit       — max entries to return (default 50, max 500)
      tool        — filter by exact tool name
      class       — filter by tool_class: read | write | destructive
    """
    limit = int(request.query_params.get("limit", "50"))
    tool_filter = request.query_params.get("tool") or None
    cls_filter = request.query_params.get("class") or None
    entries = get_audit_log(limit=limit, tool_filter=tool_filter, classification_filter=cls_filter)
    return JSONResponse({"count": len(entries), "entries": entries})


mcp._custom_starlette_routes.append(
    Route("/health", _health_endpoint, methods=["GET"])
)
mcp._custom_starlette_routes.append(
    Route("/metrics", _metrics_endpoint, methods=["GET"])
)
mcp._custom_starlette_routes.append(
    Route("/audit", _audit_endpoint, methods=["GET"])
)

# ---------------------------------------------------------------------------
# Resources + Prompts
# ---------------------------------------------------------------------------

from magemcp.resources import register_resources

register_resources(mcp)

from magemcp.prompts import register_prompts

register_prompts(mcp)

from magemcp.completions import register_completions

register_completions(mcp)


def main() -> None:
    """Entry point for the MageMCP server."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
    transport = os.getenv("MAGEMCP_TRANSPORT", "stdio")
    log.info("Starting MageMCP server (transport=%s) …", transport)
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
