"""admin_get_analytics — client-side aggregation over Magento order data."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Literal

from mcp.server.fastmcp import Context, FastMCP

from magemcp.connectors.rest_client import RESTClient
from magemcp.utils.dates import parse_date_expr

log = logging.getLogger(__name__)

Metric = Literal["order_count", "revenue", "average_order_value", "top_products"]
GroupBy = Literal["day", "week", "month", "status"]

# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------

_PAGE_SIZE = 100  # items per page when fetching all orders


def _date_bucket(created_at: str, group_by: GroupBy) -> str:
    """Derive a bucket key from an ISO timestamp based on group_by."""
    if not created_at:
        return "unknown"
    date_part = created_at[:10]  # YYYY-MM-DD
    if group_by == "day":
        return date_part
    if group_by == "month":
        return date_part[:7]  # YYYY-MM
    if group_by == "week":
        from datetime import date
        y, m, d = int(date_part[:4]), int(date_part[5:7]), int(date_part[8:10])
        dt = date(y, m, d)
        iso_year, iso_week, _ = dt.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    return date_part  # fallback


def _build_date_params(
    from_date: str | None,
    to_date: str | None,
    status: str | None,
    page_size: int,
    page: int,
) -> dict[str, str]:
    """Build searchCriteria params for orders with date range and optional status."""
    simple_filters: dict[str, Any] = {}
    if status:
        simple_filters["status"] = status

    params = RESTClient.search_params(
        filters=simple_filters or None,
        page_size=page_size,
        current_page=page,
        sort_field="created_at",
        sort_direction="ASC",
    )

    idx = len(simple_filters)
    if from_date:
        prefix = f"searchCriteria[filterGroups][{idx}][filters][0]"
        params[f"{prefix}[field]"] = "created_at"
        params[f"{prefix}[value]"] = from_date
        params[f"{prefix}[conditionType]"] = "gteq"
        idx += 1
    if to_date:
        prefix = f"searchCriteria[filterGroups][{idx}][filters][0]"
        params[f"{prefix}[field]"] = "created_at"
        params[f"{prefix}[value]"] = to_date
        params[f"{prefix}[conditionType]"] = "lteq"
        idx += 1

    return params


async def _fetch_all_orders(
    from_date: str | None,
    to_date: str | None,
    status: str | None,
    store_code: str,
    ctx: Context | None = None,
) -> list[dict[str, Any]]:
    """Paginate through all matching orders and return raw items."""
    from anyio.lowlevel import checkpoint as anyio_checkpoint

    all_items: list[dict[str, Any]] = []
    page = 1
    total = None
    while True:
        # Explicit cancellation checkpoint — allows task cancellation between pages
        await anyio_checkpoint()
        params = _build_date_params(from_date, to_date, status, _PAGE_SIZE, page)
        async with RESTClient.from_env() as client:
            data = await client.get("/V1/orders", params=params, store_code=store_code)
        items = data.get("items") or []
        all_items.extend(items)
        if total is None:
            total = data.get("total_count", 0)
        if ctx and total:
            await ctx.report_progress(len(all_items), total)
        if len(all_items) >= total or not items:
            break
        page += 1
    if ctx:
        await ctx.debug(f"Fetched {len(all_items)} orders total.")
    return all_items


# ---------------------------------------------------------------------------
# Metric calculators
# ---------------------------------------------------------------------------

def _calc_order_count(orders: list[dict[str, Any]], group_by: GroupBy | None) -> dict[str, Any]:
    if not group_by:
        return {"metric": "order_count", "value": len(orders)}
    buckets: dict[str, int] = defaultdict(int)
    for o in orders:
        key = o.get("status", "unknown") if group_by == "status" else _date_bucket(o.get("created_at", ""), group_by)
        buckets[key] += 1
    return {"metric": "order_count", "group_by": group_by, "breakdown": dict(sorted(buckets.items()))}


def _calc_revenue(orders: list[dict[str, Any]], group_by: GroupBy | None) -> dict[str, Any]:
    if not group_by:
        total = sum(float(o.get("grand_total", 0)) for o in orders)
        currency = orders[0].get("order_currency_code") if orders else None
        return {"metric": "revenue", "value": round(total, 2), "currency": currency}
    buckets: dict[str, float] = defaultdict(float)
    currency = None
    for o in orders:
        key = o.get("status", "unknown") if group_by == "status" else _date_bucket(o.get("created_at", ""), group_by)
        buckets[key] += float(o.get("grand_total", 0))
        if not currency:
            currency = o.get("order_currency_code")
    return {
        "metric": "revenue",
        "group_by": group_by,
        "currency": currency,
        "breakdown": {k: round(v, 2) for k, v in sorted(buckets.items())},
    }


def _calc_aov(orders: list[dict[str, Any]]) -> dict[str, Any]:
    if not orders:
        return {"metric": "average_order_value", "value": 0, "order_count": 0}
    total = sum(float(o.get("grand_total", 0)) for o in orders)
    currency = orders[0].get("order_currency_code")
    return {
        "metric": "average_order_value",
        "value": round(total / len(orders), 2),
        "order_count": len(orders),
        "currency": currency,
    }


def _calc_top_products(orders: list[dict[str, Any]], top_n: int = 10) -> dict[str, Any]:
    """Aggregate sold quantity by SKU across all order line items."""
    sku_qty: dict[str, float] = defaultdict(float)
    sku_name: dict[str, str] = {}
    sku_revenue: dict[str, float] = defaultdict(float)

    for o in orders:
        for item in o.get("items") or []:
            if item.get("parent_item_id"):
                continue  # skip child items (configurable children)
            sku = item.get("sku", "unknown")
            qty = float(item.get("qty_ordered", 0))
            sku_qty[sku] += qty
            sku_revenue[sku] += float(item.get("row_total", 0))
            if sku not in sku_name:
                sku_name[sku] = item.get("name", sku)

    ranked = sorted(sku_qty.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    return {
        "metric": "top_products",
        "products": [
            {
                "sku": sku,
                "name": sku_name.get(sku, sku),
                "qty_ordered": qty,
                "revenue": round(sku_revenue[sku], 2),
            }
            for sku, qty in ranked
        ],
    }


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------

async def admin_get_analytics(
    metric: str = "order_count",
    from_date: str | None = None,
    to_date: str | None = None,
    status_filter: str | None = None,
    group_by: str | None = None,
    store_scope: str = "default",
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Aggregate order analytics from Magento.

    Fetches all matching orders (with pagination) and aggregates client-side.
    """
    _valid_metrics = {"order_count", "revenue", "average_order_value", "top_products"}
    _valid_group_by = {"day", "week", "month", "status", None}

    if metric not in _valid_metrics:
        raise ValueError(f"Invalid metric '{metric}'. Choose from: {', '.join(sorted(_valid_metrics))}")
    if group_by is not None and group_by not in _valid_group_by:
        raise ValueError(f"Invalid group_by '{group_by}'. Choose from: day, week, month, status")

    resolved_from = parse_date_expr(from_date) if from_date else None
    resolved_to = parse_date_expr(to_date) if to_date else None

    log.info(
        "admin_get_analytics metric=%s from=%s to=%s status=%s group_by=%s store=%s",
        metric, resolved_from, resolved_to, status_filter, group_by, store_scope,
    )
    if ctx:
        await ctx.info(
            f"Fetching orders for metric={metric}"
            + (f" from={resolved_from}" if resolved_from else "")
            + (f" to={resolved_to}" if resolved_to else "")
        )

    orders = await _fetch_all_orders(resolved_from, resolved_to, status_filter, store_scope, ctx=ctx)

    result: dict[str, Any] = {
        "from_date": resolved_from,
        "to_date": resolved_to,
        "status_filter": status_filter,
        "order_count_fetched": len(orders),
    }

    if metric == "order_count":
        result.update(_calc_order_count(orders, group_by))  # type: ignore[arg-type]
    elif metric == "revenue":
        result.update(_calc_revenue(orders, group_by))  # type: ignore[arg-type]
    elif metric == "average_order_value":
        result.update(_calc_aov(orders))
    elif metric == "top_products":
        result.update(_calc_top_products(orders))

    return result


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def register_analytics(mcp: FastMCP) -> None:
    """Register the admin_get_analytics tool on the given MCP server."""
    mcp.tool(
        name="admin_get_analytics",
        title="Get Analytics",
        description=(
            "Aggregate order analytics for a date range. Use for questions like 'how much revenue this month?' "
            "or 'what are the top-selling products this week?'. "
            "metric: order_count | revenue | average_order_value | top_products. "
            "from_date / to_date: YYYY-MM-DD or natural language (today, yesterday, this week, "
            "last month, this month, ytd, last 7 days, last 30 days). "
            "group_by: day | week | month | status — breaks down the metric into a time series or by order status. "
            "status_filter: restrict to a specific order status (e.g. 'complete', 'processing'). "
            "Note: fetches all matching orders via pagination — avoid very large date ranges without status_filter."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )(admin_get_analytics)
