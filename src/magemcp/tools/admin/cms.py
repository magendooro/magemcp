"""admin CMS tools — search, get, and update CMS pages via Magento REST API."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from magemcp.connectors.errors import MagentoNotFoundError
from magemcp.connectors.rest_client import RESTClient
from magemcp.tools.admin._confirmation import elicit_confirmation

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_page(raw: dict[str, Any]) -> dict[str, Any]:
    """Return a clean CMS page dict from a raw Magento REST response."""
    return {
        "id": raw.get("id"),
        "identifier": raw.get("identifier"),
        "title": raw.get("title"),
        "content": raw.get("content"),
        "content_heading": raw.get("content_heading"),
        "is_active": raw.get("is_active"),
        "page_layout": raw.get("page_layout"),
        "meta_title": raw.get("meta_title"),
        "meta_keywords": raw.get("meta_keywords"),
        "meta_description": raw.get("meta_description"),
        "created_at": raw.get("created_at"),
        "updated_at": raw.get("updated_at"),
        "store_id": raw.get("store_id") or [],
    }


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


async def admin_get_cms_page(
    page_id: int | None = None,
    identifier: str | None = None,
    store_scope: str = "default",
) -> dict[str, Any]:
    """Get a CMS page by numeric ID or URL identifier."""
    if page_id is None and not identifier:
        raise ValueError("Provide either page_id or identifier.")

    log.info("admin_get_cms_page id=%s identifier=%s", page_id, identifier)

    async with RESTClient.from_env() as client:
        if page_id is not None:
            raw = await client.get(f"/V1/cmsPage/{page_id}", store_code=store_scope)
            return _parse_page(raw)

        # Lookup by identifier via search
        params = RESTClient.search_params(
            filters={"identifier": identifier},
            page_size=1,
        )
        data = await client.get("/V1/cmsPage/search", params=params, store_code=store_scope)

    items = data.get("items") or []
    if not items:
        raise MagentoNotFoundError(f"CMS page '{identifier}' not found.")
    return _parse_page(items[0])


async def admin_search_cms_pages(
    title: str | None = None,
    identifier: str | None = None,
    is_active: bool | None = None,
    page_size: int = 20,
    current_page: int = 1,
    store_scope: str = "default",
) -> dict[str, Any]:
    """Search CMS pages by title, identifier, or active status."""
    log.info(
        "admin_search_cms_pages title=%s identifier=%s is_active=%s",
        title, identifier, is_active,
    )

    filters: dict[str, Any] = {}
    if title:
        filters["title"] = (title, "like")
    if identifier:
        filters["identifier"] = (identifier, "like")
    if is_active is not None:
        filters["is_active"] = int(is_active)

    params = RESTClient.search_params(
        filters=filters or None,
        page_size=max(1, min(page_size, 50)),
        current_page=max(1, current_page),
    )

    async with RESTClient.from_env() as client:
        data = await client.get("/V1/cmsPage/search", params=params, store_code=store_scope)

    items = data.get("items") or []
    return {
        "total_count": data.get("total_count", len(items)),
        "page_size": page_size,
        "current_page": current_page,
        "pages": [_parse_page(item) for item in items],
    }


async def admin_update_cms_page(
    page_id: int,
    title: str | None = None,
    content: str | None = None,
    content_heading: str | None = None,
    is_active: bool | None = None,
    meta_title: str | None = None,
    meta_description: str | None = None,
    confirm: bool = False,
    store_scope: str = "default",
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Update a CMS page. Only specified fields are changed. Requires confirmation."""
    log.info("admin_update_cms_page id=%s confirm=%s", page_id, confirm)

    prompt = await elicit_confirmation(ctx, f"update CMS page {page_id}", str(page_id), confirm)
    if prompt:
        return prompt

    page: dict[str, Any] = {"id": page_id}
    if title is not None:
        page["title"] = title
    if content is not None:
        page["content"] = content
    if content_heading is not None:
        page["content_heading"] = content_heading
    if is_active is not None:
        page["is_active"] = is_active
    if meta_title is not None:
        page["meta_title"] = meta_title
    if meta_description is not None:
        page["meta_description"] = meta_description

    updated_fields = [k for k in page if k != "id"]
    if not updated_fields:
        raise ValueError("No fields to update. Provide at least one field to change.")

    async with RESTClient.from_env() as client:
        await client.put(
            f"/V1/cmsPage/{page_id}",
            json={"page": page},
            store_code=store_scope,
        )

    return {"success": True, "page_id": page_id, "updated_fields": updated_fields}


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_cms_tools(mcp: FastMCP) -> None:
    """Register all admin CMS tools on the given MCP server."""

    mcp.tool(
        name="admin_get_cms_page",
        title="Get CMS Page",
        description=(
            "Get a CMS page by numeric ID or URL identifier slug (e.g. 'about-us', 'privacy-policy'). "
            "Returns full page: title, HTML content body, meta description, and active status. "
            "Use admin_search_cms_pages to discover identifiers first."
        ),
        annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    )(admin_get_cms_page)

    mcp.tool(
        name="admin_search_cms_pages",
        title="Search CMS Pages",
        description=(
            "Search CMS pages by title, URL identifier, or active status. "
            "Title and identifier filters support wildcards (e.g. %about%, %policy%). "
            "Returns page summaries with their identifiers. "
            "Use admin_get_cms_page to read the full HTML content."
        ),
        annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    )(admin_search_cms_pages)

    mcp.tool(
        name="admin_update_cms_page",
        title="Update CMS Page",
        description=(
            "Update a CMS page's content or settings by numeric ID. Only fields you provide are changed — "
            "omitted fields are left untouched. Editable: title, HTML content body, content_heading, "
            "is_active (publish/unpublish), meta_title, meta_description. "
            "Use admin_get_cms_page first to read current values. "
            "Requires confirmation — call twice with confirm=True to proceed."
        ),
        annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True},
    )(admin_update_cms_page)
