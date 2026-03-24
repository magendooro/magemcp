"""MageMCP — MCP Resources.

Static resources and resource templates that expose Magento data as
addressable, browseable URIs.  Resources are *user-controlled* context
(the agent or user chooses to include them) rather than model-controlled
tool calls.

URI scheme: ``magento://``

Static resources:
  magento://store/config          — store locale, currency, base URLs
  magento://catalog/categories    — full category tree (top-level menu)

Resource templates (RFC 6570):
  magento://product/{sku}         — product detail by SKU
  magento://order/{increment_id}  — order detail by increment ID
  magento://cms/{identifier}      — CMS page by URL identifier
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

log = logging.getLogger(__name__)


def register_resources(mcp: FastMCP) -> None:
    """Register all MageMCP resources and resource templates."""

    # ------------------------------------------------------------------
    # Static: store config
    # ------------------------------------------------------------------

    @mcp.resource(
        "magento://store/config",
        name="store_config",
        title="Store Configuration",
        description=(
            "Magento store settings: locale, currency code, base URLs, "
            "catalog defaults, and SEO metadata. Stable data — refreshed every 5 minutes."
        ),
        mime_type="application/json",
    )
    async def store_config_resource() -> str:
        from magemcp.tools.customer.store_config import (
            STORE_CONFIG_QUERY,
            _cache,
        )
        from magemcp.connectors.graphql_client import GraphQLClient

        cache_key = "store_config:default"
        cached = _cache.get(cache_key)
        if cached is not None:
            return json.dumps(cached)

        async with GraphQLClient.from_env() as client:
            data = await client.query(STORE_CONFIG_QUERY, store_code="default")
        result = data["storeConfig"]
        _cache.set(cache_key, result)
        return json.dumps(result)

    # ------------------------------------------------------------------
    # Static: category tree
    # ------------------------------------------------------------------

    @mcp.resource(
        "magento://catalog/categories",
        name="category_tree",
        title="Category Tree",
        description=(
            "The top-level category tree as the customer sees it (3 levels deep). "
            "Includes product counts and menu visibility. Refreshed every 5 minutes."
        ),
        mime_type="application/json",
    )
    async def category_tree_resource() -> str:
        from magemcp.tools.customer.get_categories import (
            GET_CATEGORIES_QUERY,
            _cache,
            _parse_response,
        )
        from magemcp.connectors.graphql_client import GraphQLClient

        cache_key = "categories:default:None:None:None:20:1"
        cached = _cache.get(cache_key)
        if cached is not None:
            return json.dumps(cached)

        async with GraphQLClient.from_env() as client:
            data = await client.query(
                GET_CATEGORIES_QUERY,
                variables={"pageSize": 20, "currentPage": 1},
                store_code="default",
            )
        result = _parse_response(data)
        dumped = result.model_dump(mode="json")
        _cache.set(cache_key, dumped)
        return json.dumps(dumped)

    # ------------------------------------------------------------------
    # Template: product by SKU
    # ------------------------------------------------------------------

    @mcp.resource(
        "magento://product/{sku}",
        name="product",
        title="Product Detail",
        description=(
            "Full product detail by SKU: name, description, pricing, images, "
            "categories, stock status, and custom attributes."
        ),
        mime_type="application/json",
    )
    async def product_resource(sku: str) -> str:
        from magemcp.tools.customer.get_product import (
            GET_PRODUCT_QUERY,
            _parse_product_detail,
        )
        from magemcp.connectors.errors import MagentoNotFoundError
        from magemcp.connectors.graphql_client import GraphQLClient

        log.info("resource magento://product/%s", sku)
        async with GraphQLClient.from_env() as client:
            data = await client.query(
                GET_PRODUCT_QUERY,
                variables={"sku": sku},
                store_code="default",
            )
        items = (data.get("products") or {}).get("items") or []
        if not items:
            raise MagentoNotFoundError(f"Product '{sku}' not found.")
        result = _parse_product_detail(items[0])
        return json.dumps(result.model_dump(mode="json"))

    # ------------------------------------------------------------------
    # Template: order by increment ID
    # ------------------------------------------------------------------

    @mcp.resource(
        "magento://order/{increment_id}",
        name="order",
        title="Order Detail",
        description=(
            "Full order detail by increment ID (e.g. '000000042'): items, totals, "
            "addresses, shipment tracking, and status history."
        ),
        mime_type="application/json",
    )
    async def order_resource(increment_id: str) -> str:
        from magemcp.tools.admin.get_order import parse_order
        from magemcp.connectors.errors import MagentoNotFoundError
        from magemcp.connectors.rest_client import RESTClient

        log.info("resource magento://order/%s", increment_id)
        params = RESTClient.search_params(
            filters={"increment_id": increment_id},
            page_size=1,
        )
        async with RESTClient.from_env() as client:
            data = await client.get("/V1/orders", params=params)
        items = data.get("items") or []
        if not items:
            raise MagentoNotFoundError(f"Order '{increment_id}' not found.")
        result = parse_order(items[0])
        return json.dumps(result.model_dump(mode="json"))

    # ------------------------------------------------------------------
    # Template: CMS page by identifier
    # ------------------------------------------------------------------

    @mcp.resource(
        "magento://cms/{identifier}",
        name="cms_page",
        title="CMS Page",
        description=(
            "CMS page content by URL identifier (e.g. 'about-us', 'privacy-policy'). "
            "Returns title, HTML content, and SEO metadata."
        ),
        mime_type="application/json",
    )
    async def cms_page_resource(identifier: str) -> str:
        from magemcp.tools.admin.cms import admin_get_cms_page

        log.info("resource magento://cms/%s", identifier)
        result = await admin_get_cms_page(identifier=identifier)
        return json.dumps(result)
