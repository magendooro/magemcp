"""admin_search_customers — search customers via Magento REST API."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from magemcp.connectors.rest_client import RESTClient
from magemcp.models.customer import CustomerSummary
from magemcp.utils.dates import parse_date_expr

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_customer_summary(raw: dict[str, Any]) -> CustomerSummary:
    return CustomerSummary(
        customer_id=raw["id"],
        email=raw.get("email"),
        firstname=raw.get("firstname"),
        lastname=raw.get("lastname"),
        group_id=raw.get("group_id"),
        store_id=raw.get("store_id"),
        website_id=raw.get("website_id"),
        created_at=raw.get("created_at"),
        is_active=not raw.get("disable_auto_group_change", False),
    )


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------


async def admin_search_customers(
    email: str | None = None,
    firstname: str | None = None,
    lastname: str | None = None,
    group_id: int | None = None,
    created_from: str | None = None,
    page_size: int = 20,
    current_page: int = 1,
    store_scope: str = "default",
) -> dict[str, Any]:
    """Search customers with optional filters — full email and name, no PII masking."""
    log.info(
        "admin_search_customers email=%s firstname=%s lastname=%s group=%s created_from=%s",
        email, firstname, lastname, group_id, created_from,
    )

    filters: dict[str, Any] = {}
    if email:
        filters["email"] = (email, "like")
    if firstname:
        filters["firstname"] = (firstname, "like")
    if lastname:
        filters["lastname"] = (lastname, "like")
    if group_id is not None:
        filters["group_id"] = group_id
    if created_from:
        filters["created_at"] = (parse_date_expr(created_from), "gteq")

    params = RESTClient.search_params(
        filters=filters or None,
        page_size=max(1, min(page_size, 50)),
        current_page=max(1, current_page),
    )

    async with RESTClient.from_env() as client:
        data = await client.get(
            "/V1/customers/search",
            params=params,
            store_code=store_scope,
        )

    items = data.get("items") or []
    total_count = data.get("total_count", len(items))

    customers = [_parse_customer_summary(item) for item in items]

    return {
        "total_count": total_count,
        "page_size": page_size,
        "current_page": current_page,
        "customers": [c.model_dump(mode="json") for c in customers],
    }


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_search_customers(mcp: FastMCP) -> None:
    """Register the admin_search_customers tool on the given MCP server."""
    mcp.tool(
        name="admin_search_customers",
        title="Search Customers",
        description=(
            "Search customers by email, name, group, or creation date. "
            "Email and name filters support wildcards (e.g. %@example.com). "
            "Returns a list of customer summaries with full email and name — no PII masking."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )(admin_search_customers)
