"""admin_order_actions — modify orders (cancel, hold, comment, invoice, ship) via Magento REST API."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from magemcp.connectors.rest_client import RESTClient
from magemcp.tools.admin._confirmation import needs_confirmation

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


async def admin_cancel_order(
    order_id: int,
    confirm: bool = False,
    store_scope: str = "default",
) -> dict[str, Any]:
    """Cancel an order."""
    log.info("admin_cancel_order id=%s confirm=%s", order_id, confirm)
    
    prompt = needs_confirmation("cancel", str(order_id), confirm)
    if prompt:
        return prompt

    async with RESTClient.from_env() as client:
        await client.post(
            f"/V1/orders/{order_id}/cancel",
            store_code=store_scope,
        )
    
    return {"success": True, "order_id": order_id, "action": "cancelled"}


async def admin_hold_order(
    order_id: int,
    confirm: bool = False,
    store_scope: str = "default",
) -> dict[str, Any]:
    """Hold an order."""
    log.info("admin_hold_order id=%s confirm=%s", order_id, confirm)
    
    prompt = needs_confirmation("hold", str(order_id), confirm)
    if prompt:
        return prompt

    async with RESTClient.from_env() as client:
        await client.post(
            f"/V1/orders/{order_id}/hold",
            store_code=store_scope,
        )
    
    return {"success": True, "order_id": order_id, "action": "held"}


async def admin_unhold_order(
    order_id: int,
    confirm: bool = False,
    store_scope: str = "default",
) -> dict[str, Any]:
    """Unhold an order."""
    log.info("admin_unhold_order id=%s confirm=%s", order_id, confirm)
    
    prompt = needs_confirmation("unhold", str(order_id), confirm)
    if prompt:
        return prompt

    async with RESTClient.from_env() as client:
        await client.post(
            f"/V1/orders/{order_id}/unhold",
            store_code=store_scope,
        )
    
    return {"success": True, "order_id": order_id, "action": "unheld"}


async def admin_add_order_comment(
    order_id: int,
    comment: str,
    is_visible_on_front: bool = False,
    is_customer_notified: bool = False,
    status: str | None = None,
    store_scope: str = "default",
) -> dict[str, Any]:
    """Add a comment to an order."""
    log.info("admin_add_order_comment id=%s status=%s", order_id, status)
    
    payload: dict[str, Any] = {
        "statusHistory": {
            "comment": comment,
            "is_visible_on_front": int(is_visible_on_front),
            "is_customer_notified": int(is_customer_notified),
        }
    }
    if status:
        payload["statusHistory"]["status"] = status
    
    async with RESTClient.from_env() as client:
        await client.post(
            f"/V1/orders/{order_id}/comments",
            json=payload,
            store_code=store_scope,
        )
        
    return {"success": True, "order_id": order_id, "comment": comment}


async def admin_create_invoice(
    order_id: int,
    capture: bool = False,
    notify_customer: bool = False,
    store_scope: str = "default",
) -> dict[str, Any]:
    """Create invoice."""
    log.info("admin_create_invoice id=%s capture=%s", order_id, capture)
    
    payload = {
        "capture": capture,
        "notify": notify_customer,
    }
    
    async with RESTClient.from_env() as client:
        # Note: Magento endpoint is /order/{id}/invoice (singular 'order')
        invoice_id = await client.post(
            f"/V1/order/{order_id}/invoice",
            json=payload,
            store_code=store_scope,
        )
        
    return {"success": True, "order_id": order_id, "invoice_id": invoice_id}


async def admin_create_shipment(
    order_id: int,
    tracking_number: str | None = None,
    carrier_code: str | None = None,
    title: str | None = None,
    notify_customer: bool = False,
    store_scope: str = "default",
) -> dict[str, Any]:
    """Create shipment."""
    log.info("admin_create_shipment id=%s tracking=%s", order_id, tracking_number)
    
    payload: dict[str, Any] = {"notify": notify_customer}
    
    if tracking_number:
        payload["tracks"] = [{
            "track_number": tracking_number,
            "carrier_code": carrier_code or "custom",
            "title": title or "Shipping",
        }]
        
    async with RESTClient.from_env() as client:
        # Note: Magento endpoint is /order/{id}/ship (singular 'order')
        shipment_id = await client.post(
            f"/V1/order/{order_id}/ship",
            json=payload,
            store_code=store_scope,
        )
        
    return {"success": True, "order_id": order_id, "shipment_id": shipment_id}


async def admin_send_order_email(
    order_id: int,
    store_scope: str = "default",
) -> dict[str, Any]:
    """Send order email."""
    log.info("admin_send_order_email id=%s", order_id)
    
    async with RESTClient.from_env() as client:
        await client.post(
            f"/V1/orders/{order_id}/emails",
            store_code=store_scope,
        )
        
    return {"success": True, "order_id": order_id, "action": "email_sent"}


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_order_actions(mcp: FastMCP) -> None:
    """Register all order action tools on the given MCP server."""

    mcp.tool(
        name="admin_cancel_order",
        description="Cancel an order. Destructive action requiring confirmation.",
        annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True},
    )(admin_cancel_order)

    mcp.tool(
        name="admin_hold_order",
        description="Put an order on hold. Destructive action requiring confirmation.",
        annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True},
    )(admin_hold_order)

    mcp.tool(
        name="admin_unhold_order",
        description="Release an order from hold. Destructive action requiring confirmation.",
        annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True},
    )(admin_unhold_order)

    mcp.tool(
        name="admin_add_order_comment",
        description="Add a comment to an order history.",
        annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
    )(admin_add_order_comment)

    mcp.tool(
        name="admin_create_invoice",
        description="Create an invoice for an order (captures payment).",
        annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True},
    )(admin_create_invoice)

    mcp.tool(
        name="admin_create_shipment",
        description="Create a shipment for an order (with optional tracking).",
        annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True},
    )(admin_create_shipment)

    mcp.tool(
        name="admin_send_order_email",
        description="Resend the order confirmation email to the customer.",
        annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
    )(admin_send_order_email)