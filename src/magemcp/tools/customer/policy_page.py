"""c_get_policy_page — fetch CMS page content via Magento GraphQL."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from magemcp.connectors.errors import MagentoNotFoundError
from magemcp.connectors.graphql_client import GraphQLClient

log = logging.getLogger(__name__)

CMS_PAGE_QUERY = """
query CmsPage($identifier: String!) {
  cmsPage(identifier: $identifier) {
    identifier
    title
    content
    content_heading
    meta_title
    meta_description
    meta_keywords
    url_key
  }
}
"""


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------


async def c_get_policy_page(
    identifier: str,
    store_scope: str = "default",
) -> dict[str, Any]:
    """Fetch a CMS page by its URL identifier."""
    log.info("c_get_policy_page identifier=%s store=%s", identifier, store_scope)
    async with GraphQLClient.from_env() as client:
        data = await client.query(
            CMS_PAGE_QUERY,
            variables={"identifier": identifier},
            store_code=store_scope,
        )

    page = data.get("cmsPage")
    if not page:
        raise MagentoNotFoundError(f"CMS page '{identifier}' not found.")

    return page


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_policy_page(mcp: FastMCP) -> None:
    """Register the c_get_policy_page tool on the given MCP server."""
    mcp.tool(
        name="c_get_policy_page",
        title="Get Policy Page",
        description=(
            "Fetch the content of a CMS page by its URL identifier. Use this to answer "
            "policy questions: 'what is the return policy?', 'what is the privacy policy?', "
            "'what are the shipping terms?'. Common identifiers: 'privacy-policy', "
            "'returns', 'shipping', 'terms-and-conditions', 'about-us'. "
            "Returns title, HTML content, and meta fields. "
            "Use c_resolve_url if you have a URL path but not the identifier."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )(c_get_policy_page)
