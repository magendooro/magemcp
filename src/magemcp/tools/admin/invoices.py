"""admin invoice read tools — get and search invoices via Magento REST API."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from magemcp.connectors.errors import MagentoNotFoundError
from magemcp.connectors.rest_client import RESTClient

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_invoice_summary(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "entity_id": raw.get("entity_id"),
        "increment_id": raw.get("increment_id"),
        "order_id": raw.get("order_id"),
        "state": raw.get("state"),
        "grand_total": raw.get("grand_total"),
        "subtotal": raw.get("subtotal"),
        "tax_amount": raw.get("tax_amount"),
        "base_currency_code": raw.get("base_currency_code"),
        "created_at": raw.get("created_at"),
        "updated_at": raw.get("updated_at"),
        "total_qty": raw.get("total_qty"),
    }


def _parse_invoice_detail(raw: dict[str, Any]) -> dict[str, Any]:
    summary = _parse_invoice_summary(raw)
    items = [
        {
            "sku": item.get("sku"),
            "name": item.get("name"),
            "qty": item.get("qty"),
            "price": item.get("price"),
            "row_total": item.get("row_total"),
        }
        for item in (raw.get("items") or [])
    ]
    return {**summary, "items": items}


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


async def admin_get_invoice(
    invoice_id: int,
    store_scope: str = "default",
) -> dict[str, Any]:
    """Get full detail for a Magento invoice by its entity ID."""
    log.info("admin_get_invoice invoice_id=%s", invoice_id)

    async with RESTClient.from_env() as client:
        raw = await client.get(f"/V1/invoices/{invoice_id}", store_code=store_scope)

    if not raw or "entity_id" not in raw:
        raise MagentoNotFoundError(f"Invoice {invoice_id} not found.")

    return _parse_invoice_detail(raw)


async def admin_search_invoices(
    order_id: int | None = None,
    state: int | None = None,
    page_size: int = 20,
    current_page: int = 1,
    store_scope: str = "default",
) -> dict[str, Any]:
    """Search invoices by order ID or state."""
    log.info("admin_search_invoices order_id=%s state=%s", order_id, state)

    filters: dict[str, Any] = {}
    if order_id is not None:
        filters["order_id"] = order_id
    if state is not None:
        filters["state"] = state

    params = RESTClient.search_params(
        filters=filters or None,
        page_size=max(1, min(page_size, 100)),
        current_page=max(1, current_page),
        sort_field="created_at",
        sort_direction="DESC",
    )

    async with RESTClient.from_env() as client:
        data = await client.get("/V1/invoices", params=params, store_code=store_scope)

    items = data.get("items") or []
    return {
        "total_count": data.get("total_count", len(items)),
        "page_size": page_size,
        "current_page": current_page,
        "invoices": [_parse_invoice_summary(item) for item in items],
    }


async def admin_get_credit_memo(
    creditmemo_id: int,
    store_scope: str = "default",
) -> dict[str, Any]:
    """Get full detail for a credit memo by its entity ID."""
    log.info("admin_get_credit_memo creditmemo_id=%s", creditmemo_id)

    async with RESTClient.from_env() as client:
        raw = await client.get(f"/V1/creditmemos/{creditmemo_id}", store_code=store_scope)

    if not raw or "entity_id" not in raw:
        raise MagentoNotFoundError(f"Credit memo {creditmemo_id} not found.")

    items = [
        {
            "sku": item.get("sku"),
            "name": item.get("name"),
            "qty": item.get("qty"),
            "price": item.get("price"),
            "row_total": item.get("row_total"),
        }
        for item in (raw.get("items") or [])
    ]

    return {
        "entity_id": raw.get("entity_id"),
        "increment_id": raw.get("increment_id"),
        "order_id": raw.get("order_id"),
        "invoice_id": raw.get("invoice_id"),
        "state": raw.get("state"),
        "grand_total": raw.get("grand_total"),
        "subtotal": raw.get("subtotal"),
        "tax_amount": raw.get("tax_amount"),
        "shipping_amount": raw.get("shipping_amount"),
        "adjustment": raw.get("adjustment"),
        "base_currency_code": raw.get("base_currency_code"),
        "created_at": raw.get("created_at"),
        "items": items,
    }


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_invoice_tools(mcp: FastMCP) -> None:
    """Register all admin invoice / credit memo tools on the given MCP server."""

    mcp.tool(
        name="admin_get_invoice",
        title="Get Invoice",
        description=(
            "Get full detail for a Magento invoice by invoice entity ID. "
            "Returns line items, totals, and state. "
            "Use admin_search_invoices to find the entity ID from an order."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )(admin_get_invoice)

    mcp.tool(
        name="admin_search_invoices",
        title="Search Invoices",
        description=(
            "Search invoices by order ID or state. "
            "State values: 1=pending, 2=paid, 3=cancelled. "
            "Returns invoice summaries with totals."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )(admin_search_invoices)

    mcp.tool(
        name="admin_get_credit_memo",
        title="Get Credit Memo",
        description=(
            "Get full detail for a credit memo (refund document) by its entity ID. "
            "Returns line items, totals, adjustment amounts, and state."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )(admin_get_credit_memo)
