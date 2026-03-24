"""c_get_store_config — fetch store configuration via Magento GraphQL."""

from __future__ import annotations

import logging
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from magemcp.connectors.graphql_client import GraphQLClient
from magemcp.utils.cache import TTLCache

log = logging.getLogger(__name__)

_cache = TTLCache(ttl=float(os.getenv("MAGEMCP_CACHE_STORE_CONFIG_TTL", "300")))

STORE_CONFIG_QUERY = """
query StoreConfig {
  storeConfig {
    store_code
    store_name
    locale
    base_currency_code
    default_display_currency_code
    timezone
    weight_unit
    base_url
    base_link_url
    base_media_url
    catalog_default_sort_by
    grid_per_page
    list_per_page
    product_url_suffix
    category_url_suffix
    title_prefix
    title_suffix
    default_title
    default_description
    head_includes
    cms_home_page
    cms_no_route
    copyright
  }
}
"""


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------


async def c_get_store_config(
    store_scope: str = "default",
) -> dict[str, Any]:
    """Get store configuration."""
    cache_key = f"store_config:{store_scope}"
    cached = _cache.get(cache_key)
    if cached is not None:
        log.debug("c_get_store_config cache hit store=%s", store_scope)
        return cached

    log.info("c_get_store_config store=%s", store_scope)
    async with GraphQLClient.from_env() as client:
        data = await client.query(STORE_CONFIG_QUERY, store_code=store_scope)
    result = data["storeConfig"]
    _cache.set(cache_key, result)
    return result


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_store_config(mcp: FastMCP) -> None:
    """Register the c_get_store_config tool on the given MCP server."""
    mcp.tool(
        name="c_get_store_config",
        title="Get Store Config",
        description=(
            "Get store-level configuration. Use when you need locale (language), currency code, "
            "base URLs, default CMS page identifiers (cms_home_page, cms_no_route), "
            "catalog defaults (sort order, items per page), or SEO title/description defaults. "
            "Results are cached for 5 minutes — safe to call at conversation start to orient context."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )(c_get_store_config)
