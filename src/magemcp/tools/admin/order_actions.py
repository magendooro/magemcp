"""admin_order_actions — modify orders (cancel, hold, comment, invoice, ship) via Magento REST API."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from magemcp.connectors.rest_client import RESTClient
from magemcp.tools.admin._confirmation import elicit_confirmation
from magemcp.utils.idempotency import idempotency_store

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


async def admin_cancel_order(
    order_id: int,
    confirm: bool = False,
    idempotency_key: str | None = None,
    store_scope: str = "default",
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Cancel an order."""
    log.info("admin_cancel_order id=%s confirm=%s", order_id, confirm)

    if idempotency_key:
        stored = idempotency_store.get("admin_cancel_order", idempotency_key)
        if stored is not None:
            return {**stored, "idempotent_replay": True}

    prompt = await elicit_confirmation(ctx, f"cancel order {order_id}", str(order_id), confirm)
    if prompt:
        return prompt

    async with RESTClient.from_env() as client:
        await client.post(
            f"/V1/orders/{order_id}/cancel",
            store_code=store_scope,
        )

    result = {"success": True, "order_id": order_id, "action": "cancelled"}
    if idempotency_key:
        idempotency_store.set("admin_cancel_order", idempotency_key, result)
    return result


async def admin_hold_order(
    order_id: int,
    confirm: bool = False,
    store_scope: str = "default",
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Hold an order."""
    log.info("admin_hold_order id=%s confirm=%s", order_id, confirm)

    prompt = await elicit_confirmation(ctx, f"hold order {order_id}", str(order_id), confirm)
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
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Unhold an order."""
    log.info("admin_unhold_order id=%s confirm=%s", order_id, confirm)

    prompt = await elicit_confirmation(ctx, f"unhold order {order_id}", str(order_id), confirm)
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
    idempotency_key: str | None = None,
    store_scope: str = "default",
) -> dict[str, Any]:
    """Add a comment to an order."""
    log.info("admin_add_order_comment id=%s status=%s", order_id, status)

    if idempotency_key:
        stored = idempotency_store.get("admin_add_order_comment", idempotency_key)
        if stored is not None:
            return {**stored, "idempotent_replay": True}

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

    result = {"success": True, "order_id": order_id, "comment": comment}
    if idempotency_key:
        idempotency_store.set("admin_add_order_comment", idempotency_key, result)
    return result


async def admin_create_invoice(
    order_id: int,
    capture: bool = False,
    notify_customer: bool = False,
    confirm: bool = False,
    idempotency_key: str | None = None,
    store_scope: str = "default",
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Create invoice for an order. Irreversible — requires confirmation."""
    log.info("admin_create_invoice id=%s capture=%s confirm=%s", order_id, capture, confirm)

    if idempotency_key:
        stored = idempotency_store.get("admin_create_invoice", idempotency_key)
        if stored is not None:
            return {**stored, "idempotent_replay": True}

    prompt = await elicit_confirmation(ctx, f"create invoice for order {order_id}", str(order_id), confirm)
    if prompt:
        return prompt

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

    result = {"success": True, "order_id": order_id, "invoice_id": invoice_id}
    if idempotency_key:
        idempotency_store.set("admin_create_invoice", idempotency_key, result)
    return result


async def admin_create_shipment(
    order_id: int,
    tracking_number: str | None = None,
    carrier_code: str | None = None,
    title: str | None = None,
    notify_customer: bool = False,
    confirm: bool = False,
    idempotency_key: str | None = None,
    store_scope: str = "default",
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Create a shipment for an order. Irreversible — requires confirmation."""
    log.info("admin_create_shipment id=%s tracking=%s confirm=%s", order_id, tracking_number, confirm)

    if idempotency_key:
        stored = idempotency_store.get("admin_create_shipment", idempotency_key)
        if stored is not None:
            return {**stored, "idempotent_replay": True}

    prompt = await elicit_confirmation(ctx, f"create shipment for order {order_id}", str(order_id), confirm)
    if prompt:
        return prompt

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

    result = {"success": True, "order_id": order_id, "shipment_id": shipment_id}
    if idempotency_key:
        idempotency_store.set("admin_create_shipment", idempotency_key, result)
    return result


async def admin_send_order_email(
    order_id: int,
    idempotency_key: str | None = None,
    store_scope: str = "default",
) -> dict[str, Any]:
    """Send order email."""
    log.info("admin_send_order_email id=%s", order_id)

    if idempotency_key:
        stored = idempotency_store.get("admin_send_order_email", idempotency_key)
        if stored is not None:
            return {**stored, "idempotent_replay": True}

    async with RESTClient.from_env() as client:
        await client.post(
            f"/V1/orders/{order_id}/emails",
            store_code=store_scope,
        )

    result = {"success": True, "order_id": order_id, "action": "email_sent"}
    if idempotency_key:
        idempotency_store.set("admin_send_order_email", idempotency_key, result)
    return result


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_order_actions(mcp: FastMCP) -> None:
    """Register all order action tools on the given MCP server."""

    mcp.tool(
        name="admin_cancel_order",
        title="Cancel Order",
        description=(
            "Cancel an order. Irreversible — only works for orders in cancellable states "
            "(pending, processing). Verify the order status with admin_get_order first. "
            "Call once to get a confirmation prompt, then again with confirm=True to proceed. "
            "Provide idempotency_key to prevent double-cancellation on retry."
        ),
        annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True},
    )(admin_cancel_order)

    mcp.tool(
        name="admin_hold_order",
        title="Hold Order",
        description=(
            "Put an order on hold to pause fulfilment. Reversible via admin_unhold_order. "
            "Requires confirmation — call twice with confirm=True to proceed."
        ),
        annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True},
    )(admin_hold_order)

    mcp.tool(
        name="admin_unhold_order",
        title="Unhold Order",
        description=(
            "Release an order from hold so fulfilment can resume. "
            "Requires confirmation — call twice with confirm=True to proceed."
        ),
        annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True},
    )(admin_unhold_order)

    mcp.tool(
        name="admin_add_order_comment",
        title="Add Order Comment",
        description=(
            "Add an internal or customer-visible comment to an order's status history. "
            "Set is_customer_notified=True to trigger an email to the customer. "
            "Provide idempotency_key to prevent duplicate comments on retry."
        ),
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
    )(admin_add_order_comment)

    mcp.tool(
        name="admin_create_invoice",
        title="Create Invoice",
        description=(
            "Create an invoice for an order (marks it as paid/captured). Irreversible. "
            "Requires confirmation — call twice with confirm=True. "
            "Always provide idempotency_key to prevent duplicate invoices on network retry."
        ),
        annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True},
    )(admin_create_invoice)

    mcp.tool(
        name="admin_create_shipment",
        title="Create Shipment",
        description=(
            "Create a shipment for an order with an optional tracking number. Irreversible. "
            "Requires confirmation — call twice with confirm=True. "
            "Always provide idempotency_key to prevent duplicate shipments on network retry."
        ),
        annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True},
    )(admin_create_shipment)

    mcp.tool(
        name="admin_send_order_email",
        title="Send Order Email",
        description=(
            "Resend the order confirmation email to the customer. "
            "Provide idempotency_key to avoid sending duplicate emails on retry."
        ),
        annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True},
    )(admin_send_order_email)