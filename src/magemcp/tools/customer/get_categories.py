"""c_get_categories — fetch category tree via Magento GraphQL."""

from __future__ import annotations

import logging
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from magemcp.connectors.graphql_client import GraphQLClient
from magemcp.utils.cache import TTLCache
from magemcp.models.catalog import PageInfo
from magemcp.models.customer_ns.categories import (
    CategoryNode,
    CGetCategoriesInput,
    CGetCategoriesOutput,
)

log = logging.getLogger(__name__)

_cache = TTLCache(ttl=float(os.getenv("MAGEMCP_CACHE_CATEGORIES_TTL", "300")))

# ---------------------------------------------------------------------------
# GraphQL query
# ---------------------------------------------------------------------------

GET_CATEGORIES_QUERY = """
query GetCategories($filters: CategoryFilterInput, $pageSize: Int, $currentPage: Int) {
  categories(filters: $filters, pageSize: $pageSize, currentPage: $currentPage) {
    items {
      uid
      name
      url_key
      url_path
      position
      level
      product_count
      include_in_menu
      children {
        uid
        name
        url_key
        url_path
        position
        level
        product_count
        include_in_menu
        children {
          uid
          name
          url_key
          url_path
          position
          level
          product_count
          include_in_menu
        }
      }
    }
    total_count
    page_info { current_page page_size total_pages }
  }
}
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_variables(inp: CGetCategoriesInput) -> dict[str, Any]:
    """Build GraphQL variables from validated input."""
    variables: dict[str, Any] = {
        "pageSize": inp.page_size,
        "currentPage": inp.current_page,
    }

    filters: dict[str, Any] = {}
    if inp.parent_id is not None:
        filters["parent_id"] = {"eq": inp.parent_id}
    if inp.name is not None:
        filters["name"] = {"match": inp.name}
    if inp.include_in_menu is not None:
        filters["include_in_menu"] = {"eq": inp.include_in_menu}

    if filters:
        variables["filters"] = filters

    return variables


def _parse_category_node(raw: dict[str, Any]) -> CategoryNode:
    """Recursively parse a category node with children."""
    children = [
        _parse_category_node(child)
        for child in (raw.get("children") or [])
    ]
    return CategoryNode(
        uid=raw.get("uid", ""),
        name=raw.get("name", ""),
        url_key=raw.get("url_key"),
        url_path=raw.get("url_path"),
        position=raw.get("position"),
        level=raw.get("level"),
        product_count=raw.get("product_count", 0),
        include_in_menu=raw.get("include_in_menu", True),
        children=children,
    )


def _parse_response(data: dict[str, Any]) -> CGetCategoriesOutput:
    """Parse the GraphQL categories response into the output model."""
    cats_data = data["categories"]
    items = cats_data.get("items") or []
    page_info_raw = cats_data["page_info"]

    return CGetCategoriesOutput(
        categories=[_parse_category_node(item) for item in items],
        total_count=cats_data.get("total_count", 0),
        page_info=PageInfo(
            current_page=page_info_raw["current_page"],
            page_size=page_info_raw["page_size"],
            total_pages=page_info_raw["total_pages"],
        ),
    )


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_get_categories(mcp: FastMCP) -> None:
    """Register the c_get_categories tool on the given MCP server."""

    @mcp.tool(
        name="c_get_categories",
        title="Get Categories",
        description=(
            "Fetch the category tree as a shopper would see it. "
            "Returns categories with nested children (up to 3 levels), "
            "product counts, and menu visibility. "
            "Filter by parent category, name, or menu inclusion."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def c_get_categories(
        parent_id: str | None = None,
        name: str | None = None,
        include_in_menu: bool | None = None,
        store_scope: str = "default",
        page_size: int = 20,
        current_page: int = 1,
    ) -> dict[str, Any]:
        """Get the category tree."""
        inp = CGetCategoriesInput(
            parent_id=parent_id,
            name=name,
            include_in_menu=include_in_menu,
            store_scope=store_scope,
            page_size=page_size,
            current_page=current_page,
        )

        variables = _build_variables(inp)
        cache_key = (
            f"categories:{inp.store_scope}:{inp.parent_id}:{inp.name}:"
            f"{inp.include_in_menu}:{inp.page_size}:{inp.current_page}"
        )
        cached = _cache.get(cache_key)
        if cached is not None:
            log.debug("c_get_categories cache hit store=%s", inp.store_scope)
            return cached

        log.info("c_get_categories store=%s variables=%s", inp.store_scope, variables)

        async with GraphQLClient.from_env() as client:
            data = await client.query(
                GET_CATEGORIES_QUERY,
                variables=variables,
                store_code=inp.store_scope,
            )

        result = _parse_response(data)
        dumped = result.model_dump(mode="json")
        _cache.set(cache_key, dumped)
        return dumped
