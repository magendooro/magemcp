"""admin product review tools — search and moderate product reviews via Magento REST API."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from magemcp.connectors.errors import MagentoNotFoundError
from magemcp.connectors.rest_client import RESTClient
from magemcp.tools.admin._confirmation import elicit_confirmation

log = logging.getLogger(__name__)

# Review status constants
_STATUS_MAP = {1: "approved", 2: "pending", 3: "not_approved"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_review(raw: dict[str, Any]) -> dict[str, Any]:
    """Return a clean review dict from a raw Magento REST response."""
    return {
        "id": raw.get("id"),
        "product_id": raw.get("entity_pk_value"),
        "status_id": raw.get("status_id"),
        "status": _STATUS_MAP.get(raw.get("status_id", 0), "unknown"),
        "title": raw.get("title"),
        "detail": raw.get("detail"),
        "nickname": raw.get("nickname"),
        "ratings": [
            {
                "rating_name": r.get("rating_name"),
                "percent": r.get("percent"),
                "value": r.get("value"),
            }
            for r in (raw.get("ratings") or [])
        ],
        "created_at": raw.get("created_at"),
        "store_id": raw.get("store_id"),
    }


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


async def admin_get_product_reviews(
    sku: str,
    status_id: int | None = None,
    page_size: int = 20,
    current_page: int = 1,
    store_scope: str = "default",
) -> dict[str, Any]:
    """Get customer reviews for a product by SKU."""
    log.info("admin_get_product_reviews sku=%s status=%s", sku, status_id)

    params: dict[str, Any] = {
        "searchCriteria[filterGroups][0][filters][0][field]": "entity_pk_value",
        "searchCriteria[filterGroups][0][filters][0][value]": sku,
        "searchCriteria[filterGroups][0][filters][0][conditionType]": "eq",
        "searchCriteria[pageSize]": str(max(1, min(page_size, 50))),
        "searchCriteria[currentPage]": str(max(1, current_page)),
    }

    if status_id is not None:
        params["searchCriteria[filterGroups][1][filters][0][field]"] = "status_id"
        params["searchCriteria[filterGroups][1][filters][0][value]"] = str(status_id)
        params["searchCriteria[filterGroups][1][filters][0][conditionType]"] = "eq"

    async with RESTClient.from_env() as client:
        data = await client.get("/V1/products/review", params=params, store_code=store_scope)

    items = data.get("items") or []
    return {
        "total_count": data.get("total_count", len(items)),
        "page_size": page_size,
        "current_page": current_page,
        "sku": sku,
        "reviews": [_parse_review(item) for item in items],
    }


async def admin_moderate_review(
    review_id: int,
    status_id: int,
    confirm: bool = False,
    store_scope: str = "default",
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Approve or reject a product review. Requires confirmation.

    status_id: 1=approved, 2=pending, 3=not_approved
    """
    log.info("admin_moderate_review id=%s status=%s confirm=%s", review_id, status_id, confirm)

    if status_id not in (1, 2, 3):
        raise ValueError("status_id must be 1 (approved), 2 (pending), or 3 (not_approved).")

    action_name = _STATUS_MAP.get(status_id, str(status_id))
    prompt = await elicit_confirmation(ctx, f"set review {review_id} to {action_name}", str(review_id), confirm)
    if prompt:
        return prompt

    async with RESTClient.from_env() as client:
        await client.put(
            f"/V1/reviews/{review_id}",
            json={"review": {"status_id": status_id}},
            store_code=store_scope,
        )

    return {
        "success": True,
        "review_id": review_id,
        "status_id": status_id,
        "status": action_name,
    }


async def admin_get_review(
    review_id: int,
    store_scope: str = "default",
) -> dict[str, Any]:
    """Get a single product review by ID."""
    log.info("admin_get_review id=%s", review_id)

    async with RESTClient.from_env() as client:
        raw = await client.get(f"/V1/reviews/{review_id}", store_code=store_scope)

    if not raw or "id" not in raw:
        raise MagentoNotFoundError(f"Review {review_id} not found.")

    return _parse_review(raw)


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_review_tools(mcp: FastMCP) -> None:
    """Register all admin review tools on the given MCP server."""

    mcp.tool(
        name="admin_get_product_reviews",
        title="Get Product Reviews",
        description=(
            "Get customer reviews for a product by SKU. "
            "Use before recommending a product to check customer sentiment, or when a customer asks "
            "'what do people say about this product?'. "
            "status_id filter: 1=approved (public), 2=pending (awaiting moderation), 3=not_approved (rejected). "
            "Returns review title, body, nickname, star ratings, and submission date. "
            "Use admin_moderate_review to approve or reject pending reviews."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )(admin_get_product_reviews)

    mcp.tool(
        name="admin_get_review",
        title="Get Review",
        description=(
            "Get a single product review by its review ID. "
            "Use admin_get_product_reviews to discover review IDs first."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )(admin_get_review)

    mcp.tool(
        name="admin_moderate_review",
        title="Moderate Review",
        description=(
            "Approve, reject, or reset a product review to pending. "
            "status_id: 1=approved (visible on storefront), 2=pending, 3=not_approved (hidden). "
            "Use admin_get_product_reviews with status_id=2 to find pending reviews. "
            "Requires confirmation — call twice with confirm=True to proceed."
        ),
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )(admin_moderate_review)
