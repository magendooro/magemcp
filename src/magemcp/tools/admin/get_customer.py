"""admin_get_customer — fetch a customer by ID or email via Magento REST API."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from magemcp.connectors.rest_client import RESTClient
from magemcp.models.customer import CGetCustomerInput, CGetCustomerOutput

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_customer(raw: dict[str, Any]) -> CGetCustomerOutput:
    """Transform a raw Magento REST customer into a CGetCustomerOutput.

    Admin tools always return full data — no PII redaction.
    """
    return CGetCustomerOutput(
        customer_id=raw["id"],
        group_id=raw.get("group_id"),
        store_id=raw.get("store_id"),
        website_id=raw.get("website_id"),
        created_at=raw.get("created_at"),
        updated_at=raw.get("updated_at"),
        firstname=raw.get("firstname"),
        lastname=raw.get("lastname"),
        email=raw.get("email"),
        dob=raw.get("dob"),
        gender=raw.get("gender"),
        is_active=not raw.get("disable_auto_group_change", False),
        default_billing_id=raw.get("default_billing"),
        default_shipping_id=raw.get("default_shipping"),
        pii_mode="full",
    )


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_get_customer(mcp: FastMCP) -> None:
    """Register the admin_get_customer tool on the given MCP server."""

    @mcp.tool(
        name="admin_get_customer",
        description=(
            "Look up a customer by internal ID or email address. Returns full customer "
            "profile including name, email, DOB, customer group, and account dates."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": True,
        },
    )
    async def admin_get_customer(
        customer_id: int | None = None,
        email: str | None = None,
        website_id: int = 1,
        store_scope: str = "default",
    ) -> dict[str, Any]:
        """Get a customer by ID or email — full admin view."""
        inp = CGetCustomerInput(
            customer_id=customer_id,
            email=email,
            website_id=website_id,
            store_scope=store_scope,
            pii_mode="full",
        )

        log.info(
            "admin_get_customer id=%s email=%s store=%s",
            inp.customer_id,
            inp.email,
            inp.store_scope,
        )

        async with RESTClient.from_env() as client:
            if inp.customer_id is not None:
                # Direct ID lookup
                data = await client.get(
                    f"/V1/customers/{inp.customer_id}",
                    store_code=inp.store_scope,
                )
                result = parse_customer(data)
                return result.model_dump(mode="json")

            # Email lookup via search
            params = RESTClient.search_params(
                filters={
                    "email": inp.email,
                    "website_id": inp.website_id,
                },
                page_size=1,
            )
            data = await client.get(
                "/V1/customers/search",
                params=params,
                store_code=inp.store_scope,
            )

        items = data.get("items") or []
        if not items:
            return {"error": "Customer not found."}

        result = parse_customer(items[0])
        return result.model_dump(mode="json")
