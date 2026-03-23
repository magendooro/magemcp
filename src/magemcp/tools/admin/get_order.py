"""admin_get_order — fetch an order by increment ID via Magento REST API."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from magemcp.connectors.magento import MagentoClient
from magemcp.models.order import (
    CGetOrderInput,
    CGetOrderOutput,
    OrderAddress,
    OrderItem,
    ShipmentSummary,
    ShipmentTrack,
    StatusHistoryEntry,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers — address parsing
# ---------------------------------------------------------------------------


def _parse_address(raw: dict[str, Any] | None) -> OrderAddress | None:
    """Parse a Magento address object — always returns full data."""
    if not raw:
        return None

    return OrderAddress(
        city=raw.get("city"),
        region=raw.get("region"),
        postcode=raw.get("postcode"),
        country_id=raw.get("country_id"),
        street=raw.get("street"),
        telephone=raw.get("telephone"),
        firstname=raw.get("firstname"),
        lastname=raw.get("lastname"),
    )


# ---------------------------------------------------------------------------
# Helpers — items
# ---------------------------------------------------------------------------


def _parse_items(raw_items: list[dict[str, Any]]) -> list[OrderItem]:
    """Parse order line items."""
    items: list[OrderItem] = []
    for item in raw_items:
        # Skip child items of configurables (parent has the display info)
        if item.get("parent_item_id"):
            continue
        items.append(OrderItem(
            sku=item.get("sku", ""),
            name=item.get("name", ""),
            qty_ordered=item.get("qty_ordered", 0),
            price=item.get("price", 0),
            row_total=item.get("row_total", 0),
        ))
    return items


# ---------------------------------------------------------------------------
# Helpers — shipments
# ---------------------------------------------------------------------------


def _parse_shipments(order: dict[str, Any]) -> list[ShipmentSummary]:
    """Extract shipment summaries from extension_attributes.shipping_assignments."""
    shipments: list[ShipmentSummary] = []
    ext = order.get("extension_attributes") or {}

    # Shipment tracking info lives under the order's shipments if present
    for shipment in ext.get("shipments") or []:
        tracks: list[ShipmentTrack] = []
        for track in shipment.get("tracks") or []:
            tracks.append(ShipmentTrack(
                track_number=track.get("track_number", ""),
                carrier_code=track.get("carrier_code"),
                title=track.get("title"),
            ))
        shipments.append(ShipmentSummary(tracks=tracks))

    return shipments


# ---------------------------------------------------------------------------
# Helpers — shipping method
# ---------------------------------------------------------------------------


def _extract_shipping_method(order: dict[str, Any]) -> str | None:
    """Extract the shipping method description from the order."""
    return order.get("shipping_description") or None


# ---------------------------------------------------------------------------
# Helpers — shipping address from extension_attributes
# ---------------------------------------------------------------------------


def _extract_shipping_address(order: dict[str, Any]) -> dict[str, Any] | None:
    """Extract shipping address from extension_attributes.shipping_assignments."""
    ext = order.get("extension_attributes") or {}
    assignments = ext.get("shipping_assignments") or []
    if assignments:
        shipping = assignments[0].get("shipping") or {}
        return shipping.get("address")
    return None


# ---------------------------------------------------------------------------
# Helpers — status history
# ---------------------------------------------------------------------------


def _parse_status_history(
    raw_history: list[dict[str, Any]],
) -> list[StatusHistoryEntry]:
    """Parse and return the last 3 status history entries (newest first)."""
    entries: list[StatusHistoryEntry] = []
    for entry in raw_history:
        entries.append(StatusHistoryEntry(
            comment=entry.get("comment"),
            status=entry.get("status"),
            created_at=entry.get("created_at"),
            is_customer_notified=bool(entry.get("is_customer_notified", False)),
            is_visible_on_front=bool(entry.get("is_visible_on_front", False)),
        ))
    # Magento returns newest first; keep that order, limit to 3
    return entries[:3]


# ---------------------------------------------------------------------------
# Core parser
# ---------------------------------------------------------------------------


def parse_order(order: dict[str, Any]) -> CGetOrderOutput:
    """Transform a raw Magento REST order into a CGetOrderOutput.

    Admin tools always return full data — no PII redaction.
    """
    billing = order.get("billing_address")
    shipping = _extract_shipping_address(order)

    firstname = order.get("customer_firstname")
    lastname = order.get("customer_lastname")
    email = order.get("customer_email")

    parts = [p for p in [firstname, lastname] if p]
    customer_name = " ".join(parts) if parts else "Unknown"

    return CGetOrderOutput(
        increment_id=order.get("increment_id", ""),
        state=order.get("state", ""),
        status=order.get("status", ""),
        created_at=order.get("created_at", ""),
        updated_at=order.get("updated_at"),
        customer_name=customer_name,
        customer_email=email,
        grand_total=order.get("grand_total", 0),
        subtotal=order.get("subtotal", 0),
        tax_amount=order.get("tax_amount", 0),
        discount_amount=order.get("discount_amount", 0),
        shipping_amount=order.get("shipping_amount", 0),
        currency_code=order.get("order_currency_code"),
        total_qty_ordered=order.get("total_qty_ordered", 0),
        items=_parse_items(order.get("items") or []),
        billing_address=_parse_address(billing),
        shipping_address=_parse_address(shipping),
        shipping_method=_extract_shipping_method(order),
        shipments=_parse_shipments(order),
        status_history=_parse_status_history(order.get("status_histories") or []),
        pii_mode="full",
    )


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_get_order(mcp: FastMCP) -> None:
    """Register the admin_get_order tool on the given MCP server."""

    @mcp.tool(
        name="admin_get_order",
        description=(
            "Fetch an order by its increment ID. Returns order status, "
            "totals, line items, shipment tracking, recent comments, "
            "and full customer details (name, email, phone, addresses)."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": True,
        },
    )
    async def admin_get_order(
        increment_id: str,
        store_scope: str = "default",
    ) -> dict[str, Any]:
        """Get an order by increment ID — full admin view."""
        inp = CGetOrderInput(
            increment_id=increment_id,
            store_scope=store_scope,
            pii_mode="full",
        )

        log.info(
            "admin_get_order increment_id=%s store=%s",
            inp.increment_id,
            inp.store_scope,
        )

        params = MagentoClient.search_params(
            filters={"increment_id": inp.increment_id},
            page_size=1,
        )

        async with MagentoClient.from_config() as client:
            data = await client.get(
                "/V1/orders",
                params=params,
                store_code=inp.store_scope,
            )

        items = data.get("items") or []
        if not items:
            return {"error": f"Order '{inp.increment_id}' not found."}

        result = parse_order(items[0])
        return result.model_dump(mode="json")
