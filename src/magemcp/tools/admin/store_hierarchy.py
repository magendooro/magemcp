"""admin_get_store_hierarchy — fetch store website/group/view hierarchy via Magento REST API."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from magemcp.connectors.rest_client import RESTClient

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_website(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": raw.get("id"),
        "code": raw.get("code"),
        "name": raw.get("name"),
        "default_group_id": raw.get("default_group_id"),
    }


def _parse_group(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": raw.get("id"),
        "website_id": raw.get("website_id"),
        "name": raw.get("name"),
        "root_category_id": raw.get("root_category_id"),
        "default_store_id": raw.get("default_store_id"),
        "code": raw.get("code"),
    }


def _parse_store_view(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": raw.get("id"),
        "code": raw.get("code"),
        "name": raw.get("name"),
        "website_id": raw.get("website_id"),
        "store_group_id": raw.get("store_group_id"),
        "is_active": raw.get("is_active"),
        "sort_order": raw.get("sort_order"),
    }


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------


async def admin_get_store_hierarchy(
    store_scope: str = "default",
) -> dict[str, Any]:
    """Fetch the full Magento store hierarchy: websites, store groups, and store views."""
    log.info("admin_get_store_hierarchy")

    async with RESTClient.from_env() as client:
        websites_raw, groups_raw, views_raw = await _fetch_all(client, store_scope)

    websites = [_parse_website(w) for w in websites_raw]
    groups = [_parse_group(g) for g in groups_raw]
    views = [_parse_store_view(v) for v in views_raw]

    # Build nested structure: website → groups → store views
    group_map: dict[int, dict[str, Any]] = {}
    for g in groups:
        g_copy = {**g, "store_views": []}
        group_map[g["id"]] = g_copy  # type: ignore[index]

    for v in views:
        gid = v.get("store_group_id")
        if gid in group_map:
            group_map[gid]["store_views"].append(v)  # type: ignore[index]

    website_map: list[dict[str, Any]] = []
    for w in websites:
        w_copy = {**w, "store_groups": []}
        for g in group_map.values():
            if g.get("website_id") == w["id"]:
                w_copy["store_groups"].append(g)
        website_map.append(w_copy)

    return {
        "websites": website_map,
        "flat": {
            "websites": websites,
            "store_groups": groups,
            "store_views": views,
        },
    }


async def _fetch_all(
    client: RESTClient, store_scope: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Fetch websites, groups, and store views concurrently."""
    import asyncio

    results = await asyncio.gather(
        client.get("/V1/store/websites", store_code=store_scope),
        client.get("/V1/store/storeGroups", store_code=store_scope),
        client.get("/V1/store/storeViews", store_code=store_scope),
    )
    return (
        results[0] if isinstance(results[0], list) else [],
        results[1] if isinstance(results[1], list) else [],
        results[2] if isinstance(results[2], list) else [],
    )


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_store_hierarchy(mcp: FastMCP) -> None:
    """Register the admin_get_store_hierarchy tool on the given MCP server."""
    mcp.tool(
        name="admin_get_store_hierarchy",
        title="Get Store Hierarchy",
        description=(
            "Get the full Magento store hierarchy: websites → store groups → store views. "
            "Use to discover valid store_scope values for other tools (store view codes like 'default', 'en', 'de'). "
            "Returns both a nested structure and a flat list of all entities with their IDs, codes, and names. "
            "Call this once at the start of a multi-store session to understand what stores are configured."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )(admin_get_store_hierarchy)
