"""admin_get_customer — fetch a customer by ID or email via Magento REST API."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from magemcp.connectors.errors import MagentoNotFoundError
from magemcp.connectors.rest_client import RESTClient
from magemcp.models.customer import CGetCustomerInput, CGetCustomerOutput, CustomerAddress

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_address(raw: dict[str, Any]) -> CustomerAddress:
    return CustomerAddress(
        id=raw.get("id"),
        firstname=raw.get("firstname"),
        lastname=raw.get("lastname"),
        street=raw.get("street") or [],
        city=raw.get("city"),
        region=raw.get("region", {}).get("region") if isinstance(raw.get("region"), dict) else raw.get("region"),
        region_code=raw.get("region", {}).get("region_code") if isinstance(raw.get("region"), dict) else None,
        postcode=raw.get("postcode"),
        country_id=raw.get("country_id"),
        telephone=raw.get("telephone"),
        default_billing=raw.get("default_billing", False),
        default_shipping=raw.get("default_shipping", False),
    )


def _parse_custom_attributes(raw_list: list[dict[str, Any]]) -> dict[str, Any]:
    """Flatten Magento's [{attribute_code, value}] list to a plain dict."""
    return {item["attribute_code"]: item.get("value") for item in raw_list if "attribute_code" in item}


def parse_customer(raw: dict[str, Any]) -> CGetCustomerOutput:
    """Transform a raw Magento REST customer into a CGetCustomerOutput.

    Admin tools always return full data — no PII redaction.
    """
    addresses = [_parse_address(a) for a in raw.get("addresses") or []]

    custom_attrs_raw = raw.get("custom_attributes") or []
    custom_attributes = _parse_custom_attributes(custom_attrs_raw) if isinstance(custom_attrs_raw, list) else {}

    ext = raw.get("extension_attributes") or {}

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
        addresses=addresses,
        custom_attributes=custom_attributes,
        extension_attributes=dict(ext),
        pii_mode="full",
    )


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


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
        raise MagentoNotFoundError("Customer not found.")

    result = parse_customer(items[0])
    return result.model_dump(mode="json")


def register_get_customer(mcp: FastMCP) -> None:
    """Register the admin_get_customer tool on the given MCP server."""
    mcp.tool(
        name="admin_get_customer",
        title="Get Customer",
        description=(
            "Get a customer's full profile by customer ID or email. Returns name, email, "
            "DOB, customer group, registration date, all saved addresses, and custom attributes. "
            "Full unmasked data — admin context only. Use admin_search_customers first if you "
            "only have partial info (name, domain, etc.)."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )(admin_get_customer)
