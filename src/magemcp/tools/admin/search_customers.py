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
# Customer group lookup
# ---------------------------------------------------------------------------


async def admin_get_customer_groups(
    store_scope: str = "default",
) -> dict[str, Any]:
    """Return all customer groups with their integer IDs.

    Customer groups are referenced by integer ID throughout the Magento REST API
    (e.g. when filtering customers, or reading which groups a sales rule applies to).
    Use this tool to map a group name like 'Wholesale' to its ID before filtering.

    Standard Magento groups (IDs may vary per installation):
      0 = NOT LOGGED IN, 1 = General, 2 = Wholesale, 3 = Retailer

    Workflow::

        groups = await admin_get_customer_groups()
        # → {"groups": [{"id": 2, "code": "Wholesale", ...}, ...]}

        customers = await admin_search_customers(group_id=2)
    """
    log.info("admin_get_customer_groups")

    params = RESTClient.search_params(page_size=200, current_page=1)

    async with RESTClient.from_env() as client:
        data = await client.get("/V1/customerGroups/search", params=params, store_code=store_scope)

    items = data.get("items") or []
    return {
        "total_count": data.get("total_count", len(items)),
        "groups": [
            {
                "id": g.get("id"),
                "code": g.get("code"),
                "tax_class_id": g.get("tax_class_id"),
                "tax_class_name": g.get("tax_class_name"),
            }
            for g in items
        ],
    }


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_search_customers(mcp: FastMCP) -> None:
    """Register admin customer tools on the given MCP server."""

    mcp.tool(
        name="admin_get_customer_groups",
        title="Get Customer Groups",
        description=(
            "Return all customer groups with their integer IDs. "
            "Customer groups are referenced by integer ID throughout the REST API — "
            "use this tool to map a group name ('Wholesale', 'Retailer') to its ID "
            "before filtering customers or interpreting sales rule customer_group_ids. "
            "Standard groups: 0=NOT LOGGED IN, 1=General, 2=Wholesale, 3=Retailer "
            "(IDs may differ per installation)."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )(admin_get_customer_groups)

    mcp.tool(
        name="admin_search_customers",
        title="Search Customers",
        description=(
            "Search customers by email, first/last name, group, or registration date. "
            "Email and name filters support SQL wildcards (e.g. %@example.com, %Smith%). "
            "group_id is an integer — use admin_get_customer_groups to look up group IDs by name. "
            "from_date accepts 'today', 'this month', 'last month', or ISO dates. "
            "Returns full unmasked email and name (admin only). Use admin_get_customer for full profile."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )(admin_search_customers)
