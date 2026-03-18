#!/usr/bin/env python3
"""MageMCP demo — shows the MCP server tools in action against a real Magento instance.

Usage:

    # Set env vars first
    export MAGENTO_BASE_URL=https://magento.example.com
    export MAGENTO_TOKEN=<your-integration-token>
    export MAGENTO_STORE_CODE=default  # optional

    # Run the demo
    python scripts/demo.py

The script calls each MCP tool function directly (bypassing MCP transport)
to demonstrate what an AI agent would see when connected to MageMCP.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s  %(name)s  %(message)s",
)

DIVIDER = "=" * 72
SUBDIV = "-" * 40


def banner(title: str) -> None:
    print(f"\n{DIVIDER}")
    print(f"  {title}")
    print(DIVIDER)


def section(title: str) -> None:
    print(f"\n{SUBDIV}")
    print(f"  {title}")
    print(SUBDIV)


def pretty(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def check_env() -> bool:
    url = os.environ.get("MAGENTO_BASE_URL", "")
    token = os.environ.get("MAGENTO_TOKEN", "")
    if not url or not token:
        print("Error: MAGENTO_BASE_URL and MAGENTO_TOKEN env vars are required.")
        print()
        print("  export MAGENTO_BASE_URL=https://magento.example.com")
        print("  export MAGENTO_TOKEN=<your-integration-token>")
        print("  python scripts/demo.py")
        return False
    print(f"Magento instance: {url}")
    print(f"Store code:       {os.environ.get('MAGENTO_STORE_CODE', 'default')}")
    return True


# ---------------------------------------------------------------------------
# Tool access helper
# ---------------------------------------------------------------------------


def get_tools() -> dict[str, Any]:
    """Import the MCP server and return its registered tool functions."""
    from magemcp.server import mcp

    return {name: tool.fn for name, tool in mcp._tool_manager._tools.items()}


# ---------------------------------------------------------------------------
# Demo scenarios
# ---------------------------------------------------------------------------


async def demo_search_products(tools: dict[str, Any]) -> str | None:
    """Search the catalog and return the first SKU found."""
    banner("1. Search Products")
    print("Searching the catalog (first 5 products)...")

    result = await tools["c_search_products"](page_size=5)
    print(f"\nTotal products in catalog: {result['total_count']}")

    sku = None
    for i, p in enumerate(result["products"], 1):
        print(f"\n  [{i}] {p['sku']}")
        print(f"      Name:   {p['name']}")
        print(f"      Type:   {p['product_type']}")
        print(f"      Stock:  {p['stock_status']}")
        if p.get("min_price"):
            print(f"      Price:  {p['min_price']}")
        sku = sku or p["sku"]

    if not result["products"]:
        print("  (no products found)")

    # Also demo keyword search
    section("Keyword search: 'shirt'")
    shirt_result = await tools["c_search_products"](search="shirt", page_size=3)
    print(f"Results for 'shirt': {shirt_result['total_count']} total")
    for p in shirt_result["products"]:
        print(f"  - {p['sku']}: {p['name']}")

    return sku


async def demo_get_product(tools: dict[str, Any], sku: str) -> None:
    """Fetch full product detail for a SKU."""
    banner("2. Get Product Detail")
    print(f"Fetching detail for SKU: {sku}")

    result = await tools["c_get_product"](sku=sku)
    print(f"\n  SKU:         {result['sku']}")
    print(f"  Name:        {result['name']}")
    print(f"  Type:        {result['product_type']}")
    print(f"  URL Key:     {result.get('url_key', 'N/A')}")
    print(f"  Stock:       {result['stock_status']}")
    if result.get("description"):
        desc = result["description"][:120]
        print(f"  Description: {desc}{'...' if len(result['description']) > 120 else ''}")
    if result.get("images"):
        print(f"  Images:      {len(result['images'])} image(s)")
    if result.get("categories"):
        print(f"  Categories:  {', '.join(c.get('full_path', c.get('name', '')) for c in result['categories'])}")
    if result.get("custom_attributes"):
        print(f"  Attributes:  {len(result['custom_attributes'])} configurable option(s)")


async def demo_get_order(tools: dict[str, Any]) -> str | None:
    """Fetch the most recent order in both redacted and full PII modes."""
    banner("3. Get Order")

    # Discover an order
    from magemcp.connectors.magento import MagentoClient

    async with MagentoClient.from_config() as client:
        params = MagentoClient.search_params(
            page_size=1, sort_field="entity_id", sort_direction="DESC"
        )
        raw = await client.get("/V1/orders", params=params)
        items = raw.get("items", [])

    if not items:
        print("  No orders found — skipping.")
        return None

    increment_id = str(items[0]["increment_id"])

    # Redacted mode (default)
    section(f"Order {increment_id} — Redacted (default)")
    result = await tools["c_get_order"](increment_id=increment_id)
    print(f"\n  Order:     {result['increment_id']}")
    print(f"  State:     {result['state']}")
    print(f"  Status:    {result['status']}")
    print(f"  Created:   {result['created_at']}")
    print(f"  Total:     {result['grand_total']} {result.get('currency_code', '')}")
    print(f"  Customer:  {result.get('customer_name', 'N/A')} ({result.get('customer_email', 'N/A')})")
    print(f"  PII Mode:  {result['pii_mode']}")
    print(f"  Items:     {len(result.get('items', []))} line item(s)")
    for item in result.get("items", [])[:3]:
        print(f"    - {item['sku']}: {item['name']} x{item['qty_ordered']} @ {item['price']}")
    if result.get("shipping_method"):
        print(f"  Shipping:  {result['shipping_method']}")
    if result.get("shipments"):
        for s in result["shipments"]:
            for t in s.get("tracks", []):
                print(f"  Tracking:  {t.get('carrier_code', '')} — {t.get('track_number', '')}")

    # Full PII mode
    section(f"Order {increment_id} — Full PII")
    full = await tools["c_get_order"](increment_id=increment_id, pii_mode="full")
    print(f"  Customer:  {full.get('customer_name', 'N/A')} ({full.get('customer_email', 'N/A')})")
    print(f"  PII Mode:  {full['pii_mode']}")
    if full.get("billing_address"):
        addr = full["billing_address"]
        print(f"  Billing:   {addr.get('city', '')}, {addr.get('region', '')} {addr.get('postcode', '')} {addr.get('country_id', '')}")

    return increment_id


async def demo_get_customer(tools: dict[str, Any]) -> None:
    """Fetch a customer in both redacted and full PII modes."""
    banner("4. Get Customer")

    # Discover a customer
    from magemcp.connectors.magento import MagentoClient

    async with MagentoClient.from_config() as client:
        params = MagentoClient.search_params(page_size=1)
        raw = await client.get("/V1/customers/search", params=params)
        items = raw.get("items", [])

    if not items:
        print("  No customers found — skipping.")
        return

    customer_id = items[0]["id"]

    # Redacted
    section(f"Customer {customer_id} — Redacted")
    result = await tools["c_get_customer"](customer_id=customer_id)
    print(f"\n  ID:        {result['customer_id']}")
    print(f"  Name:      {result['firstname']} {result['lastname']}")
    print(f"  Email:     {result['email']}")
    print(f"  Group:     {result.get('group_id', 'N/A')}")
    print(f"  Active:    {result.get('is_active', 'N/A')}")
    print(f"  PII Mode:  {result['pii_mode']}")

    # Full
    section(f"Customer {customer_id} — Full PII")
    full = await tools["c_get_customer"](customer_id=customer_id, pii_mode="full")
    print(f"  Name:      {full['firstname']} {full['lastname']}")
    print(f"  Email:     {full['email']}")
    print(f"  PII Mode:  {full['pii_mode']}")


async def demo_get_inventory(tools: dict[str, Any], sku: str) -> None:
    """Check inventory for a product SKU."""
    banner("5. Get Inventory")
    print(f"Checking salable inventory for: {sku}")

    from magemcp.connectors.magento import MagentoError

    try:
        result = await tools["c_get_inventory"](skus=[sku])
        for item in result["items"]:
            print(f"\n  SKU:              {item['sku']}")
            print(f"  Salable Qty:      {item['salable_quantity']}")
            print(f"  Is Salable:       {item['is_salable']}")
            print(f"  Stock ID:         {item['stock_id']}")
            if item.get("error"):
                print(f"  Error:            {item['error']}")
    except MagentoError as exc:
        print(f"\n  Inventory endpoints not available: {exc}")
        print("  (MSI may not be enabled on this instance)")


async def demo_scenario_customer_support(tools: dict[str, Any]) -> None:
    """Simulate a customer support workflow: order lookup -> product check -> inventory."""
    banner("6. Scenario: Customer Support Workflow")
    print("Simulating: 'Where is my order? Is item X still in stock?'\n")

    # Step 1: Look up order
    from magemcp.connectors.magento import MagentoClient, MagentoError

    async with MagentoClient.from_config() as client:
        params = MagentoClient.search_params(
            page_size=1, sort_field="entity_id", sort_direction="DESC"
        )
        raw = await client.get("/V1/orders", params=params)
        items = raw.get("items", [])

    if not items:
        print("  No orders to demonstrate with.")
        return

    increment_id = str(items[0]["increment_id"])
    print(f"Step 1: Customer asks about order {increment_id}")
    order = await tools["c_get_order"](increment_id=increment_id)
    print(f"  -> Order {order['increment_id']}: {order['status']} ({order['state']})")
    print(f"  -> Total: {order['grand_total']} {order.get('currency_code', '')}")

    if not order.get("items"):
        print("  -> No items in order")
        return

    # Step 2: Customer asks about one of the items
    first_sku = order["items"][0]["sku"]
    print(f"\nStep 2: Customer asks about product {first_sku}")
    try:
        product = await tools["c_get_product"](sku=first_sku)
        print(f"  -> {product['name']} ({product['product_type']})")
        print(f"  -> Stock: {product['stock_status']}")
    except Exception as exc:
        print(f"  -> Could not fetch product detail: {exc}")

    # Step 3: Check inventory
    print(f"\nStep 3: Check if {first_sku} is available for reorder")
    try:
        inv = await tools["c_get_inventory"](skus=[first_sku])
        item_inv = inv["items"][0]
        available = "Yes" if item_inv["is_salable"] else "No"
        print(f"  -> Available: {available} (qty: {item_inv['salable_quantity']})")
    except MagentoError:
        print("  -> Inventory check not available (MSI may be disabled)")

    print("\nWorkflow complete.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    banner("MageMCP Demo")

    if not check_env():
        sys.exit(1)

    tools = get_tools()
    print(f"\nRegistered tools: {', '.join(sorted(tools.keys()))}")

    # Run each demo, collecting data to pass between them
    sku = await demo_search_products(tools)

    if sku:
        await demo_get_product(tools, sku)

    await demo_get_order(tools)
    await demo_get_customer(tools)

    if sku:
        await demo_get_inventory(tools, sku)

    await demo_scenario_customer_support(tools)

    banner("Demo Complete")
    print("\nAll tools demonstrated successfully.")
    print("To connect via MCP transport, run: magemcp")
    print("Or configure in your MCP client's settings.\n")


if __name__ == "__main__":
    asyncio.run(main())
