"""c_get_store_config — fetch store configuration via Magento GraphQL."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from magemcp.connectors.graphql_client import GraphQLClient

log = logging.getLogger(__name__)

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


def register_store_config(mcp: FastMCP) -> None:
    """Register the c_get_store_config tool on the given MCP server."""

    @mcp.tool(
        name="c_get_store_config",
        description=(
            "Get store configuration: locale, currency, URLs, catalog settings, "
            "CMS pages, and SEO defaults."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": True,
        },
    )
    async def c_get_store_config(
        store_scope: str = "default",
    ) -> dict[str, Any]:
        """Get store configuration."""
        log.info("c_get_store_config store=%s", store_scope)
        async with GraphQLClient.from_env() as client:
            data = await client.query(STORE_CONFIG_QUERY, store_code=store_scope)
        return data["storeConfig"]
