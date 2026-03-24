"""MageMCP — MCP Prompts.

User-triggered workflow templates that prime the LLM with context and
guide it through multi-step commerce operations.

Prompts are surfaced as slash commands in MCP-aware clients (e.g., Claude
Desktop).  Each prompt returns a list of messages that set up the agent's
task with appropriate context.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP


def register_prompts(mcp: FastMCP) -> None:
    """Register all MageMCP prompt templates."""

    # ------------------------------------------------------------------
    # investigate_order — order triage workflow
    # ------------------------------------------------------------------

    @mcp.prompt(
        name="investigate_order",
        title="Investigate Order",
        description=(
            "Load full context for an order: detail, customer profile, shipment "
            "tracking, and status history. Use at the start of any order support session."
        ),
    )
    async def investigate_order(order_id: str) -> str:
        return (
            f"Please investigate order #{order_id} using the following steps:\n\n"
            "1. Call admin_get_order to get full order detail (items, totals, status, addresses).\n"
            "2. If the order has a customer_email, call admin_search_customers to find their profile.\n"
            "3. If the order has shipment IDs, call admin_search_shipments with the order entity_id "
            "to get tracking numbers and carrier information.\n"
            "4. Summarise: order status, what was ordered, estimated delivery, and any open issues.\n\n"
            f"Start with: admin_get_order(increment_id='{order_id}')"
        )

    # ------------------------------------------------------------------
    # daily_ops_briefing — operations morning summary
    # ------------------------------------------------------------------

    @mcp.prompt(
        name="daily_ops_briefing",
        title="Daily Operations Briefing",
        description=(
            "Generate a morning operations briefing: new orders today, revenue, "
            "order status breakdown, and top products. Takes ~30 seconds."
        ),
    )
    async def daily_ops_briefing() -> str:
        return (
            "Please generate a daily operations briefing for today. Run these calls in parallel:\n\n"
            "1. admin_get_analytics(metric='order_count', from_date='today', group_by='status') "
            "— count of today's orders by status\n"
            "2. admin_get_analytics(metric='revenue', from_date='today') "
            "— total revenue today\n"
            "3. admin_get_analytics(metric='top_products', from_date='this_month') "
            "— top 10 products this month\n"
            "4. admin_search_orders(status='pending', page_size=5, sort_direction='ASC') "
            "— oldest pending orders needing attention\n\n"
            "Present the results as a concise briefing with key numbers and any actions needed."
        )

    # ------------------------------------------------------------------
    # customer_360 — full customer profile
    # ------------------------------------------------------------------

    @mcp.prompt(
        name="customer_360",
        title="Customer 360 View",
        description=(
            "Build a complete picture of a customer: profile, order history, "
            "and lifetime value. Useful before handling a support request."
        ),
    )
    async def customer_360(customer_email: str) -> str:
        return (
            f"Please build a 360-degree view of the customer with email: {customer_email}\n\n"
            "Steps:\n"
            f"1. admin_search_customers(email='{customer_email}') — get customer profile and ID\n"
            "2. admin_get_customer_orders(email=customer_email, page_size=10) "
            "— last 10 orders with totals and status\n"
            "3. Summarise: account age, total orders, estimated lifetime value (sum of order totals), "
            "most recent order status, any open returns.\n\n"
            "Present as a structured customer profile card."
        )

    # ------------------------------------------------------------------
    # search_and_compare — product research workflow
    # ------------------------------------------------------------------

    @mcp.prompt(
        name="search_and_compare",
        title="Search and Compare Products",
        description=(
            "Search for products matching a query and compare the top results "
            "with full specifications. Useful for product recommendation workflows."
        ),
    )
    async def search_and_compare(query: str) -> str:
        return (
            f"Please search for products matching '{query}' and compare the top results.\n\n"
            "Steps:\n"
            f"1. c_search_products(search='{query}', page_size=5) — find matching products\n"
            "2. For each of the top 3 results, call c_get_product(sku=sku) to get full specs\n"
            "3. Compare them side by side: price, key specs/attributes, stock status, and ratings\n"
            "4. Recommend the best option with a clear reason\n\n"
            "Present as a comparison table followed by a recommendation."
        )

    # ------------------------------------------------------------------
    # return_request — guide a return initiation
    # ------------------------------------------------------------------

    @mcp.prompt(
        name="handle_return_request",
        title="Handle Return Request",
        description=(
            "Guide through handling a customer return request: verify the order, "
            "check eligibility, and review existing RMAs."
        ),
    )
    async def handle_return_request(order_id: str) -> str:
        return (
            f"A customer wants to return items from order #{order_id}. Please:\n\n"
            f"1. admin_get_order(increment_id='{order_id}') — verify order exists and is complete\n"
            f"2. admin_search_returns(order_id=<entity_id>) — check if a return already exists\n"
            "3. Review: which items are eligible for return (complete status, within return window)\n"
            "4. If no existing RMA and items are eligible, ask the customer which items they want "
            "to return and the reason, then proceed with the return request.\n\n"
            "Return policies are typically in the CMS page at magento://cms/return-policy."
        )
