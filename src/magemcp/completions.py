"""MCP completion (autocomplete) handler for prompts and resource templates."""

from __future__ import annotations

import logging
import os
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import (
    Completion,
    CompletionArgument,
    PromptReference,
    ResourceTemplateReference,
)

log = logging.getLogger(__name__)

# Static enum completions for well-known argument names
_ORDER_STATUSES = [
    "pending", "pending_payment", "processing", "complete",
    "closed", "canceled", "holded", "payment_review",
]

_METRICS = ["order_count", "revenue", "average_order_value", "top_products"]
_GROUP_BY = ["day", "week", "month", "status"]
_COUPON_FORMATS = ["alphanum", "alpha", "num"]


def _filter(values: list[str], partial: str) -> list[str]:
    """Return values that start with the partial string (case-insensitive)."""
    p = partial.lower()
    return [v for v in values if v.lower().startswith(p)][:20]


async def _complete_sku(partial: str) -> list[str]:
    """Search products by SKU prefix."""
    try:
        from magemcp.connectors.rest_client import RESTClient
        params = RESTClient.search_params(
            filters={"sku": (f"{partial}%", "like")} if partial else None,
            page_size=20,
        )
        async with RESTClient.from_env() as client:
            data = await client.get("/V1/products", params=params)
        return [item["sku"] for item in (data.get("items") or []) if "sku" in item]
    except Exception as exc:
        log.debug("SKU completion failed: %s", exc)
        return []


async def _complete_order_id(partial: str) -> list[str]:
    """Search orders by increment_id prefix."""
    try:
        from magemcp.connectors.rest_client import RESTClient
        params = RESTClient.search_params(
            filters={"increment_id": (f"{partial}%", "like")} if partial else None,
            page_size=20,
            sort_field="entity_id",
            sort_direction="DESC",
        )
        async with RESTClient.from_env() as client:
            data = await client.get("/V1/orders", params=params)
        return [item["increment_id"] for item in (data.get("items") or []) if "increment_id" in item]
    except Exception as exc:
        log.debug("Order ID completion failed: %s", exc)
        return []


async def _complete_cms_identifier(partial: str) -> list[str]:
    """Search CMS pages by identifier prefix."""
    try:
        from magemcp.connectors.rest_client import RESTClient
        params = RESTClient.search_params(
            filters={"identifier": (f"{partial}%", "like")} if partial else None,
            page_size=20,
        )
        async with RESTClient.from_env() as client:
            data = await client.get("/V1/cmsPage/search", params=params)
        return [item["identifier"] for item in (data.get("items") or []) if "identifier" in item]
    except Exception as exc:
        log.debug("CMS identifier completion failed: %s", exc)
        return []


async def handle_completion(
    ref: PromptReference | ResourceTemplateReference,
    argument: CompletionArgument,
    context: Any = None,
) -> Completion | None:
    """Autocomplete handler for prompts and resource templates."""
    partial = argument.value or ""
    name = argument.name

    # Resource template completions
    if isinstance(ref, ResourceTemplateReference):
        uri = ref.uri
        if "product" in uri and name == "sku":
            values = await _complete_sku(partial)
            return Completion(values=values)
        if "order" in uri and name == "increment_id":
            values = await _complete_order_id(partial)
            return Completion(values=values)
        if "cms" in uri and name == "identifier":
            values = await _complete_cms_identifier(partial)
            return Completion(values=values)

    # Prompt argument completions
    if isinstance(ref, PromptReference):
        prompt_name = ref.name
        if prompt_name in ("investigate_order", "handle_return_request") and name in ("order_id", "order_increment_id"):
            values = await _complete_order_id(partial)
            return Completion(values=values)
        if prompt_name == "customer_360" and name in ("customer_id", "email"):
            return Completion(values=[])
        if prompt_name == "search_and_compare" and name == "query":
            return Completion(values=[])

    # Generic argument completions by name
    if name in ("status", "status_filter"):
        return Completion(values=_filter(_ORDER_STATUSES, partial))
    if name == "metric":
        return Completion(values=_filter(_METRICS, partial))
    if name == "group_by":
        return Completion(values=_filter(_GROUP_BY, partial))
    if name == "format" and "coupon" in (getattr(ref, "name", "") + getattr(ref, "uri", "")):
        return Completion(values=_filter(_COUPON_FORMATS, partial))

    return None


def register_completions(mcp: FastMCP) -> None:
    """Register the MCP completion handler."""
    mcp.completion()(handle_completion)
