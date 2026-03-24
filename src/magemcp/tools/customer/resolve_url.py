"""c_resolve_url — resolve SEO-friendly URLs via Magento GraphQL route query."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from mcp.server.fastmcp import FastMCP

from magemcp.connectors.errors import MagentoNotFoundError
from magemcp.connectors.graphql_client import GraphQLClient

log = logging.getLogger(__name__)

RESOLVE_URL_QUERY = """
query ResolveUrl($url: String!) {
  route(url: $url) {
    __typename
    ... on SimpleProduct { sku name url_key }
    ... on ConfigurableProduct { sku name url_key }
    ... on BundleProduct { sku name url_key }
    ... on GroupedProduct { sku name url_key }
    ... on VirtualProduct { sku name url_key }
    ... on DownloadableProduct { sku name url_key }
    ... on CategoryTree { uid name url_key url_path }
    ... on CmsPage { identifier title url_key }
  }
}
"""


class CResolveUrlInput(BaseModel):
    """Input for URL resolution."""

    url: str = Field(
        description="SEO-friendly URL path to resolve (e.g., 'blue-jacket.html' or 'women/tops').",
        min_length=1,
        max_length=512,
    )
    store_scope: str = Field(
        default="default",
        description="Magento store view code.",
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    )


_PRODUCT_TYPES = {
    "SimpleProduct",
    "ConfigurableProduct",
    "BundleProduct",
    "GroupedProduct",
    "VirtualProduct",
    "DownloadableProduct",
}


def _parse_route(route: dict[str, Any] | None) -> dict[str, Any]:
    """Parse the route response into a clean dict."""
    if route is None:
        raise MagentoNotFoundError("URL not found")

    typename = route.get("__typename", "Unknown")
    result: dict[str, Any] = {"type": typename}

    if typename in _PRODUCT_TYPES:
        result["sku"] = route.get("sku")
        result["name"] = route.get("name")
        result["url_key"] = route.get("url_key")
    elif typename == "CategoryTree":
        result["uid"] = route.get("uid")
        result["name"] = route.get("name")
        result["url_key"] = route.get("url_key")
        result["url_path"] = route.get("url_path")
    elif typename == "CmsPage":
        result["identifier"] = route.get("identifier")
        result["title"] = route.get("title")
        result["url_key"] = route.get("url_key")
    else:
        result["raw"] = route

    return result


def register_resolve_url(mcp: FastMCP) -> None:
    """Register the c_resolve_url tool on the given MCP server."""

    @mcp.tool(
        name="c_resolve_url",
        title="Resolve URL",
        description=(
            "Resolve a SEO-friendly URL to a product, category, or CMS page. "
            "Returns the entity type and key identifiers (SKU, category UID, or CMS identifier)."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def c_resolve_url(
        url: str,
        store_scope: str = "default",
    ) -> dict[str, Any]:
        """Resolve a URL to a product, category, or CMS page."""
        inp = CResolveUrlInput(url=url, store_scope=store_scope)
        log.info("c_resolve_url url=%s store=%s", inp.url, inp.store_scope)
        async with GraphQLClient.from_env() as client:
            data = await client.query(
                RESOLVE_URL_QUERY,
                variables={"url": inp.url},
                store_code=inp.store_scope,
            )
        return _parse_route(data.get("route"))
