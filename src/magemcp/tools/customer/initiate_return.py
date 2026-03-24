"""c_initiate_return — initiate a return request via Magento GraphQL."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from magemcp.connectors.graphql_client import GraphQLClient
from magemcp.tools.admin._confirmation import elicit_confirmation
from magemcp.utils.idempotency import idempotency_store

log = logging.getLogger(__name__)

_REQUEST_RETURN_MUTATION = """
mutation RequestReturn($input: RequestReturnInput!) {
  requestReturn(input: $input) {
    return {
      uid
      number
      status
      created_at
      items {
        uid
        quantity
        request_quantity
        status
      }
    }
  }
}
"""


async def c_initiate_return(
    order_uid: str,
    contact_email: str,
    items: list[dict[str, Any]],
    comment: str | None = None,
    customer_token: str | None = None,
    confirm: bool = False,
    idempotency_key: str | None = None,
    store_scope: str = "default",
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Initiate a return request for an order via the GraphQL requestReturn mutation.

    Requires Adobe Commerce with the RMA module enabled.

    Args:
        order_uid: GraphQL UID for the order (base64-encoded).
        contact_email: Contact email for the return request.
        items: Items to return. Each dict must have:
            - order_item_uid (str): GraphQL UID for the order item.
            - quantity_to_return (float): Quantity to return.
        comment: Optional comment / reason for the return.
        customer_token: Optional customer bearer token for authenticated returns.
        confirm: Set True to confirm and proceed.
        idempotency_key: Optional key to prevent duplicate return submissions.
        store_scope: Magento store view code.
    """
    if not items:
        raise ValueError("items list must not be empty")

    if idempotency_key:
        stored = idempotency_store.get("c_initiate_return", idempotency_key)
        if stored is not None:
            return {**stored, "idempotent_replay": True}

    prompt = await elicit_confirmation(
        ctx,
        f"initiate return for order {order_uid} ({len(items)} item(s))",
        order_uid,
        confirm,
    )
    if prompt:
        return prompt

    log.info(
        "c_initiate_return order_uid=%s items=%d store=%s",
        order_uid, len(items), store_scope,
    )

    return_items = [
        {
            "order_item_uid": item["order_item_uid"],
            "quantity_to_return": float(item["quantity_to_return"]),
        }
        for item in items
    ]

    gql_input: dict[str, Any] = {
        "order_uid": order_uid,
        "contact_email": contact_email,
        "items": return_items,
    }
    if comment:
        gql_input["comment_text"] = comment

    async with GraphQLClient.from_env(customer_token=customer_token) as gql:
        data = await gql.query(
            _REQUEST_RETURN_MUTATION,
            variables={"input": gql_input},
            store_code=store_scope,
        )

    rma = (data.get("requestReturn") or {}).get("return") or {}
    out: dict[str, Any] = {
        "success": True,
        "uid": rma.get("uid"),
        "number": rma.get("number"),
        "status": rma.get("status"),
        "created_at": rma.get("created_at"),
        "items": rma.get("items") or [],
    }
    if idempotency_key:
        idempotency_store.set("c_initiate_return", idempotency_key, out)
    return out


def register_initiate_return(mcp: FastMCP) -> None:
    """Register the c_initiate_return tool on the given MCP server."""
    mcp.tool(
        name="c_initiate_return",
        title="Initiate Return",
        description=(
            "Initiate a return (RMA) request for an order via GraphQL. "
            "Requires Adobe Commerce with the RMA module enabled. "
            "order_uid and order_item_uid are base64-encoded GraphQL UIDs from a prior order query. "
            "items: [{order_item_uid, quantity_to_return}] — at least one item required. "
            "Pass customer_token for an authenticated customer return. "
            "Pass idempotency_key to prevent duplicate submissions. "
            "Requires confirmation — call with confirm=True to proceed."
        ),
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )(c_initiate_return)
