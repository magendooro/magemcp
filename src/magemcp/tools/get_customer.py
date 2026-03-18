"""c_get_customer — fetch a customer by ID or email via Magento REST API."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from magemcp.connectors.magento import MagentoClient
from magemcp.models.customer import CGetCustomerInput, CGetCustomerOutput
from magemcp.models.order import mask_email, mask_name

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_customer(raw: dict[str, Any], *, redact: bool) -> CGetCustomerOutput:
    """Transform a raw Magento REST customer into a CGetCustomerOutput."""
    firstname = raw.get("firstname")
    lastname = raw.get("lastname")
    email_raw = raw.get("email")

    if redact:
        display_first = mask_name(firstname, None).split(".")[0] + "."  # "J."
        display_last = mask_name(None, lastname).split(". ")[-1]  # "D."
        display_email = mask_email(email_raw)
        display_dob = "***" if raw.get("dob") else None
    else:
        display_first = firstname
        display_last = lastname
        display_email = email_raw
        display_dob = raw.get("dob")

    return CGetCustomerOutput(
        customer_id=raw["id"],
        group_id=raw.get("group_id"),
        store_id=raw.get("store_id"),
        website_id=raw.get("website_id"),
        created_at=raw.get("created_at"),
        updated_at=raw.get("updated_at"),
        firstname=display_first,
        lastname=display_last,
        email=display_email,
        dob=display_dob,
        gender=raw.get("gender"),
        is_active=not raw.get("disable_auto_group_change", False),
        default_billing_id=raw.get("default_billing"),
        default_shipping_id=raw.get("default_shipping"),
        pii_mode="redacted" if redact else "full",
    )


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_get_customer(mcp: FastMCP) -> None:
    """Register the c_get_customer tool on the given MCP server."""

    @mcp.tool(
        name="c_get_customer",
        description=(
            "Look up a customer by internal ID or email address. Returns customer group, "
            "account dates, and basic profile. Customer PII (email, name, DOB) is "
            "redacted by default."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": True,
        },
    )
    async def c_get_customer(
        customer_id: int | None = None,
        email: str | None = None,
        website_id: int = 1,
        store_scope: str = "default",
        pii_mode: str = "redacted",
    ) -> dict[str, Any]:
        """Get a customer by ID or email."""
        inp = CGetCustomerInput(
            customer_id=customer_id,
            email=email,
            website_id=website_id,
            store_scope=store_scope,
            pii_mode=pii_mode,  # type: ignore[arg-type]
        )

        redact = inp.pii_mode == "redacted"

        log.info(
            "c_get_customer id=%s email=%s store=%s pii_mode=%s",
            inp.customer_id,
            "***" if inp.email else None,
            inp.store_scope,
            inp.pii_mode,
        )

        async with MagentoClient.from_config() as client:
            if inp.customer_id is not None:
                # Direct ID lookup
                data = await client.get(
                    f"/V1/customers/{inp.customer_id}",
                    store_code=inp.store_scope,
                )
                result = parse_customer(data, redact=redact)
                return result.model_dump(mode="json")

            # Email lookup via search
            params = MagentoClient.search_params(
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
            return {"error": f"Customer not found."}

        result = parse_customer(items[0], redact=redact)
        return result.model_dump(mode="json")
