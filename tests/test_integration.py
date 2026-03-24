"""Integration tests — hit a real Magento 2 instance.

These tests require a running Magento instance and valid credentials.
Configure via environment variables:

    MAGENTO_BASE_URL=https://magento.example.com
    MAGENTO_TOKEN=<integration-token>
    MAGENTO_STORE_CODE=default  (optional)

Run with:

    pytest tests/test_integration.py -v --tb=short

Skip when no Magento instance is configured:

    pytest tests/test_integration.py  # auto-skips if env vars missing

The tests discover real data from the instance (products, orders, customers)
rather than relying on hardcoded IDs, so they work against any Magento instance.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import pytest

from magemcp.connectors.magento import (
    MagentoClient,
    MagentoConfig,
    MagentoError,
    MagentoNotFoundError,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Skip entire module when Magento is not configured
# ---------------------------------------------------------------------------

_MAGENTO_URL = os.environ.get("MAGENTO_BASE_URL", "")
_MAGENTO_TOKEN = os.environ.get("MAGENTO_TOKEN", "")

pytestmark = pytest.mark.skipif(
    not (_MAGENTO_URL and _MAGENTO_TOKEN),
    reason="MAGENTO_BASE_URL and MAGENTO_TOKEN env vars required for integration tests",
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def magento_config() -> MagentoConfig:
    return MagentoConfig()  # type: ignore[call-arg]


@pytest.fixture
async def client(magento_config: MagentoConfig) -> MagentoClient:
    async with MagentoClient.from_config(magento_config) as c:
        yield c  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Connector-level smoke tests
# ---------------------------------------------------------------------------


class TestConnectorSmoke:
    """Verify the connector can reach Magento at all."""

    async def test_rest_store_config(self, client: MagentoClient) -> None:
        """GET /V1/store/storeConfigs should return a list of store configs."""
        data = await client.get("/V1/store/storeConfigs")
        assert isinstance(data, list)
        assert len(data) >= 1
        first = data[0]
        assert "code" in first
        assert "base_url" in first
        log.info("Store configs: %d store(s) found", len(data))

    async def test_graphql_store_config(self, client: MagentoClient) -> None:
        """A simple GraphQL storeConfig query should succeed."""
        data = await client.graphql("{ storeConfig { store_code store_name } }")
        cfg = data["storeConfig"]
        assert "store_code" in cfg
        assert "store_name" in cfg
        log.info("GraphQL storeConfig: %s (%s)", cfg["store_name"], cfg["store_code"])

    async def test_rest_invalid_endpoint(self, client: MagentoClient) -> None:
        """An invalid endpoint should raise MagentoError (404)."""
        with pytest.raises(MagentoError):
            await client.get("/V1/nonexistent-endpoint-xyz")


# ---------------------------------------------------------------------------
# Helper: discover real data from the instance
# ---------------------------------------------------------------------------


async def _discover_product_sku(client: MagentoClient) -> str | None:
    """Find a real product SKU from the catalog."""
    data = await client.graphql(
        '{ products(search: "", pageSize: 1) { items { sku } } }'
    )
    items = data.get("products", {}).get("items", [])
    return items[0]["sku"] if items else None


async def _discover_order_increment_id(client: MagentoClient) -> str | None:
    """Find a real order increment ID."""
    params = MagentoClient.search_params(page_size=1, sort_field="entity_id", sort_direction="DESC")
    data = await client.get("/V1/orders", params=params)
    items = data.get("items", [])
    return str(items[0]["increment_id"]) if items else None


async def _discover_customer_id(client: MagentoClient) -> int | None:
    """Find a real customer ID."""
    params = MagentoClient.search_params(page_size=1)
    data = await client.get("/V1/customers/search", params=params)
    items = data.get("items", [])
    return items[0]["id"] if items else None


# ---------------------------------------------------------------------------
# search_products integration
# ---------------------------------------------------------------------------


class TestSearchProducts:
    """Integration tests for c_search_products via direct API calls."""

    async def test_basic_search(self, client: MagentoClient) -> None:
        """Search with no filters should return some products."""
        data = await client.graphql(
            """
            query {
              products(search: "", pageSize: 5) {
                total_count
                items { sku name stock_status }
              }
            }
            """
        )
        products = data["products"]
        assert products["total_count"] >= 0
        log.info("Catalog has %d total products", products["total_count"])
        if products["items"]:
            first = products["items"][0]
            log.info("First product: %s — %s", first["sku"], first["name"])

    async def test_search_by_keyword(self, client: MagentoClient) -> None:
        """Keyword search should return matching products."""
        data = await client.graphql(
            """
            query($search: String) {
              products(search: $search, pageSize: 3) {
                total_count
                items { sku name }
              }
            }
            """,
            variables={"search": "shirt"},
        )
        total = data["products"]["total_count"]
        log.info("Search 'shirt': %d results", total)
        # Even 0 is valid — just verify the query executed

    async def test_search_pagination(self, client: MagentoClient) -> None:
        """Pagination parameters should be respected."""
        data = await client.graphql(
            """
            query {
              products(search: "", pageSize: 2, currentPage: 1) {
                total_count
                page_info { current_page page_size total_pages }
                items { sku }
              }
            }
            """
        )
        page_info = data["products"]["page_info"]
        assert page_info["current_page"] == 1
        assert page_info["page_size"] == 2
        items = data["products"]["items"]
        assert len(items) <= 2


# ---------------------------------------------------------------------------
# get_categories integration
# ---------------------------------------------------------------------------


class TestGetCategories:
    """Integration tests for c_get_categories via direct GraphQL calls."""

    async def test_categories_returns_tree(self, client: MagentoClient) -> None:
        """Verify category tree loads from real Magento."""
        data = await client.graphql(
            """
            query {
              categories(pageSize: 10, currentPage: 1) {
                total_count
                items {
                  uid name url_key level product_count include_in_menu
                  children { uid name level }
                }
                page_info { current_page page_size total_pages }
              }
            }
            """
        )
        cats = data["categories"]
        assert cats["total_count"] >= 1
        root = cats["items"][0]
        assert root["name"]  # Not empty
        assert isinstance(root.get("children", []), list)
        log.info(
            "Categories: %d total, root=%s with %d children",
            cats["total_count"],
            root["name"],
            len(root.get("children", [])),
        )

    async def test_categories_with_children(self, client: MagentoClient) -> None:
        """Verify nested children are returned."""
        data = await client.graphql(
            """
            query {
              categories(pageSize: 50) {
                items {
                  uid name level
                  children {
                    uid name level
                    children { uid name level }
                  }
                }
              }
            }
            """
        )
        items = data["categories"]["items"]
        # Find any category with children
        has_children = any(
            len(item.get("children") or []) > 0 for item in items
        )
        if not has_children:
            pytest.skip("No categories with children found")
        log.info("Found categories with nested children")


# ---------------------------------------------------------------------------
# get_product integration
# ---------------------------------------------------------------------------


class TestGetProduct:
    """Integration tests for c_get_product via direct API calls."""

    async def test_get_existing_product(self, client: MagentoClient) -> None:
        """Fetch a real product by SKU."""
        sku = await _discover_product_sku(client)
        if sku is None:
            pytest.skip("No products in catalog")

        data = await client.graphql(
            """
            query($sku: String!) {
              products(filter: { sku: { eq: $sku } }) {
                items {
                  sku name url_key type_id stock_status
                  price_range {
                    minimum_price { regular_price { value currency } }
                  }
                  media_gallery { url label disabled position }
                  categories { name url_path breadcrumbs { category_name } }
                }
              }
            }
            """,
            variables={"sku": sku},
        )
        items = data["products"]["items"]
        assert len(items) == 1
        product = items[0]
        assert product["sku"] == sku
        assert product["name"]
        log.info(
            "Product detail: %s — %s (type=%s, stock=%s)",
            product["sku"],
            product["name"],
            product["type_id"],
            product["stock_status"],
        )

    async def test_get_nonexistent_product(self, client: MagentoClient) -> None:
        """A bogus SKU should return an empty items list."""
        data = await client.graphql(
            """
            query($sku: String!) {
              products(filter: { sku: { eq: $sku } }) {
                items { sku }
              }
            }
            """,
            variables={"sku": "NONEXISTENT_SKU_999999"},
        )
        assert data["products"]["items"] == []


# ---------------------------------------------------------------------------
# search_orders integration
# ---------------------------------------------------------------------------


class TestSearchOrders:
    """Integration tests for admin_search_orders via REST API."""

    async def test_search_orders_real(self, client: MagentoClient) -> None:
        """Search orders returns results from real Magento."""
        params = MagentoClient.search_params(
            page_size=5, sort_field="created_at", sort_direction="DESC",
        )
        data = await client.get("/V1/orders", params=params)
        assert "items" in data
        if data["items"]:
            order = data["items"][0]
            assert "increment_id" in order
            assert "customer_email" in order  # Full email, not masked
            assert "grand_total" in order
            log.info("Search orders: %d total, first=%s", data.get("total_count", 0), order["increment_id"])

    async def test_tool_search_orders(self) -> None:
        """admin_search_orders tool returns summaries."""
        from magemcp.server import mcp as server

        tools = server._tool_manager._tools
        tool_fn = tools["admin_search_orders"].fn

        result = await tool_fn(page_size=5)
        assert "orders" in result
        assert "total_count" in result
        if result["orders"]:
            first = result["orders"][0]
            assert "increment_id" in first
            assert "customer_email" in first
            assert "total_items" in first
            # Summaries should NOT have full order fields
            assert "billing_address" not in first
            assert "items" not in first
            log.info(
                "Tool admin_search_orders: %d total, first=%s (%s)",
                result["total_count"], first["increment_id"], first["customer_email"],
            )

    async def test_tool_search_orders_by_status(self) -> None:
        """admin_search_orders with status filter."""
        from magemcp.server import mcp as server

        tools = server._tool_manager._tools
        tool_fn = tools["admin_search_orders"].fn

        # Search for "pending" or whatever status exists
        result = await tool_fn(page_size=3)
        if not result["orders"]:
            pytest.skip("No orders to filter")

        known_status = result["orders"][0]["status"]
        filtered = await tool_fn(status=known_status, page_size=50)
        assert all(o["status"] == known_status for o in filtered["orders"])
        log.info("Filtered by status=%s: %d orders", known_status, filtered["total_count"])


# ---------------------------------------------------------------------------
# get_order integration
# ---------------------------------------------------------------------------


class TestGetOrder:
    """Integration tests for admin_get_order via REST API."""

    async def test_get_existing_order(self, client: MagentoClient) -> None:
        """Fetch a real order by increment ID."""
        increment_id = await _discover_order_increment_id(client)
        if increment_id is None:
            pytest.skip("No orders in the system")

        params = MagentoClient.search_params(
            filters={"increment_id": increment_id},
            page_size=1,
        )
        data = await client.get("/V1/orders", params=params)
        items = data.get("items", [])
        assert len(items) == 1
        order = items[0]
        assert str(order["increment_id"]) == increment_id
        assert "state" in order
        assert "status" in order
        assert "grand_total" in order
        log.info(
            "Order %s: state=%s status=%s total=%s %s",
            order["increment_id"],
            order["state"],
            order["status"],
            order["grand_total"],
            order.get("order_currency_code", ""),
        )

    async def test_order_not_found(self, client: MagentoClient) -> None:
        """Searching for a non-existent order returns empty results."""
        params = MagentoClient.search_params(
            filters={"increment_id": "000000000"},
            page_size=1,
        )
        data = await client.get("/V1/orders", params=params)
        assert data.get("items", []) == [] or data.get("total_count", 0) == 0

    async def test_order_has_expected_structure(self, client: MagentoClient) -> None:
        """Verify the raw REST order has the fields our parser expects."""
        increment_id = await _discover_order_increment_id(client)
        if increment_id is None:
            pytest.skip("No orders in the system")

        params = MagentoClient.search_params(
            filters={"increment_id": increment_id},
            page_size=1,
        )
        data = await client.get("/V1/orders", params=params)
        order = data["items"][0]

        expected_fields = [
            "increment_id", "state", "status", "created_at", "updated_at",
            "grand_total", "subtotal", "tax_amount",
            "order_currency_code", "total_qty_ordered", "items",
        ]
        for field in expected_fields:
            assert field in order, f"Missing expected field: {field}"

        assert isinstance(order["items"], list)
        assert len(order["items"]) >= 1
        first_item = order["items"][0]
        assert "sku" in first_item
        assert "name" in first_item


# ---------------------------------------------------------------------------
# get_customer integration
# ---------------------------------------------------------------------------


class TestGetCustomer:
    """Integration tests for c_get_customer via REST API."""

    async def test_get_customer_by_id(self, client: MagentoClient) -> None:
        """Fetch a customer by internal ID."""
        customer_id = await _discover_customer_id(client)
        if customer_id is None:
            pytest.skip("No customers in the system")

        data = await client.get(f"/V1/customers/{customer_id}")
        assert data["id"] == customer_id
        assert "firstname" in data
        assert "lastname" in data
        assert "email" in data
        log.info(
            "Customer %d: %s %s (group=%s)",
            data["id"],
            data["firstname"],
            data["lastname"],
            data.get("group_id"),
        )

    async def test_search_customer_by_email(self, client: MagentoClient) -> None:
        """Search for a customer by email."""
        customer_id = await _discover_customer_id(client)
        if customer_id is None:
            pytest.skip("No customers in the system")

        # First get the email
        customer = await client.get(f"/V1/customers/{customer_id}")
        email = customer["email"]

        # Now search by email
        params = MagentoClient.search_params(
            filters={"email": email},
            page_size=1,
        )
        data = await client.get("/V1/customers/search", params=params)
        assert data["total_count"] >= 1
        assert data["items"][0]["email"] == email

    async def test_customer_not_found(self, client: MagentoClient) -> None:
        """A non-existent customer ID should raise 404."""
        with pytest.raises(MagentoNotFoundError):
            await client.get("/V1/customers/999999999")


# ---------------------------------------------------------------------------
# get_inventory integration
# ---------------------------------------------------------------------------


class TestGetInventory:
    """Integration tests for c_get_inventory via REST API."""

    async def test_salable_quantity(self, client: MagentoClient) -> None:
        """Check salable quantity for a real SKU."""
        sku = await _discover_product_sku(client)
        if sku is None:
            pytest.skip("No products in catalog")

        stock_id = 1
        try:
            qty = await client.get(
                f"/V1/inventory/get-product-salable-quantity/{sku}/{stock_id}"
            )
            assert isinstance(qty, (int, float))
            log.info("Salable quantity for %s (stock %d): %s", sku, stock_id, qty)
        except MagentoError as exc:
            # Some Magento editions / configs may not have MSI enabled
            log.warning("Inventory endpoint failed for %s: %s", sku, exc)
            pytest.skip(f"Inventory endpoint not available: {exc}")

    async def test_is_salable(self, client: MagentoClient) -> None:
        """Check is_salable flag for a real SKU."""
        sku = await _discover_product_sku(client)
        if sku is None:
            pytest.skip("No products in catalog")

        stock_id = 1
        try:
            is_salable = await client.get(
                f"/V1/inventory/is-product-salable/{sku}/{stock_id}"
            )
            assert isinstance(is_salable, bool)
            log.info("Is salable for %s (stock %d): %s", sku, stock_id, is_salable)
        except MagentoError as exc:
            log.warning("Inventory endpoint failed for %s: %s", sku, exc)
            pytest.skip(f"Inventory endpoint not available: {exc}")

    async def test_nonexistent_sku_inventory(self, client: MagentoClient) -> None:
        """A bogus SKU should raise an error from the inventory endpoint."""
        stock_id = 1
        with pytest.raises(MagentoError):
            await client.get(
                f"/V1/inventory/get-product-salable-quantity/BOGUS_SKU_999/{stock_id}"
            )


# ---------------------------------------------------------------------------
# Full tool-level integration (calls the actual tool functions)
# ---------------------------------------------------------------------------


class TestToolEndToEnd:
    """Call the registered MCP tool functions directly against real Magento.

    These tests import the tool modules and invoke the underlying logic,
    which creates its own MagentoClient from env vars internally.
    """

    async def test_tool_search_products(self) -> None:
        """c_search_products returns a valid response dict."""
        from magemcp.server import mcp as server

        tools = server._tool_manager._tools
        tool_fn = tools["c_search_products"].fn

        result = await tool_fn(page_size=3)
        assert isinstance(result, dict)
        assert "total_count" in result
        assert "products" in result
        assert isinstance(result["products"], list)
        log.info("Tool c_search_products: %d total, %d returned", result["total_count"], len(result["products"]))

    async def test_tool_get_categories(self) -> None:
        """c_get_categories returns a valid category tree."""
        from magemcp.server import mcp as server

        tools = server._tool_manager._tools
        tool_fn = tools["c_get_categories"].fn

        result = await tool_fn(page_size=10)
        assert isinstance(result, dict)
        assert "total_count" in result
        assert "categories" in result
        assert isinstance(result["categories"], list)
        assert result["total_count"] >= 1
        # First category should have a name
        assert result["categories"][0]["name"]
        log.info(
            "Tool c_get_categories: %d total, root=%s",
            result["total_count"],
            result["categories"][0]["name"],
        )

    async def test_tool_get_product(self) -> None:
        """c_get_product returns detail for a discovered SKU."""
        # Discover a SKU first
        async with MagentoClient.from_config() as client:
            sku = await _discover_product_sku(client)
        if sku is None:
            pytest.skip("No products in catalog")

        from magemcp.server import mcp as server

        tools = server._tool_manager._tools
        tool_fn = tools["c_get_product"].fn

        result = await tool_fn(sku=sku)
        assert isinstance(result, dict)
        assert result["sku"] == sku
        assert "name" in result
        log.info("Tool c_get_product: %s — %s", result["sku"], result["name"])

    async def test_tool_get_order(self) -> None:
        """admin_get_order returns full order data."""
        async with MagentoClient.from_config() as client:
            increment_id = await _discover_order_increment_id(client)
        if increment_id is None:
            pytest.skip("No orders in the system")

        from magemcp.server import mcp as server

        tools = server._tool_manager._tools
        tool_fn = tools["admin_get_order"].fn

        result = await tool_fn(increment_id=increment_id)
        assert isinstance(result, dict)
        assert result["increment_id"] == increment_id
        assert result["pii_mode"] == "full"
        # Enhanced: payment info should be present
        assert "payment_method" in result
        assert "payment_additional" in result
        assert "invoice_ids" in result
        assert "credit_memo_ids" in result
        log.info(
            "Tool admin_get_order: %s state=%s payment=%s email=%s",
            result["increment_id"], result["state"],
            result.get("payment_method"), result.get("customer_email", "N/A"),
        )

    async def test_tool_get_customer(self) -> None:
        """admin_get_customer returns full customer data."""
        async with MagentoClient.from_config() as client:
            customer_id = await _discover_customer_id(client)
        if customer_id is None:
            pytest.skip("No customers in the system")

        from magemcp.server import mcp as server

        tools = server._tool_manager._tools
        tool_fn = tools["admin_get_customer"].fn

        result = await tool_fn(customer_id=customer_id)
        assert isinstance(result, dict)
        assert result["customer_id"] == customer_id
        assert result["pii_mode"] == "full"
        log.info("Tool admin_get_customer: id=%d name=%s %s", result["customer_id"], result["firstname"], result["lastname"])

    async def test_tool_get_inventory(self) -> None:
        """admin_get_inventory returns salable data for real SKUs."""
        async with MagentoClient.from_config() as client:
            sku = await _discover_product_sku(client)
        if sku is None:
            pytest.skip("No products in catalog")

        from magemcp.server import mcp as server

        tools = server._tool_manager._tools
        tool_fn = tools["admin_get_inventory"].fn

        try:
            result = await tool_fn(skus=[sku])
        except MagentoError:
            pytest.skip("MSI inventory endpoints not available")

        assert isinstance(result, dict)
        assert "items" in result
        assert len(result["items"]) == 1
        item = result["items"][0]
        assert item["sku"] == sku
        log.info("Tool admin_get_inventory: %s qty=%s salable=%s", item["sku"], item["salable_quantity"], item["is_salable"])


# ---------------------------------------------------------------------------
# Cross-tool scenario tests
# ---------------------------------------------------------------------------


class TestStoreConfig:
    """Integration tests for c_get_store_config."""

    async def test_store_config_real(self, client: MagentoClient) -> None:
        """storeConfig returns locale and currency from real Magento."""
        data = await client.graphql("{ storeConfig { locale base_currency_code store_code store_name } }")
        config = data["storeConfig"]
        assert config["locale"]
        assert config["base_currency_code"]
        assert config["store_code"]
        log.info("Store config: %s (%s), currency=%s", config["store_name"], config["locale"], config["base_currency_code"])

    async def test_tool_store_config(self) -> None:
        """c_get_store_config tool returns config from real Magento."""
        from magemcp.server import mcp as server

        tools = server._tool_manager._tools
        tool_fn = tools["c_get_store_config"].fn

        result = await tool_fn()
        assert result["locale"]
        assert result["base_currency_code"]
        assert result["store_code"]
        assert result["base_url"]
        log.info("Tool c_get_store_config: locale=%s currency=%s", result["locale"], result["base_currency_code"])


class TestResolveUrl:
    """Integration tests for c_resolve_url."""

    async def test_resolve_product_url_real(self, client: MagentoClient) -> None:
        """Resolve a real product URL from the catalog."""
        data = await client.graphql(
            '{ products(search: "", pageSize: 1) { items { url_key } } }'
        )
        items = data.get("products", {}).get("items", [])
        if not items:
            pytest.skip("No products in catalog")

        url_key = items[0]["url_key"]
        route_data = await client.graphql(
            "query($url: String!) { route(url: $url) { __typename ... on SimpleProduct { sku name } } }",
            variables={"url": f"{url_key}.html"},
        )
        route = route_data.get("route")
        assert route is not None, f"Route not found for {url_key}.html"
        assert "Product" in route["__typename"]
        log.info("Resolved %s.html -> %s (sku=%s)", url_key, route["__typename"], route.get("sku"))

    async def test_resolve_cms_home_page(self, client: MagentoClient) -> None:
        """Resolve the CMS home page."""
        data = await client.graphql(
            'query($url: String!) { route(url: $url) { __typename ... on CmsPage { identifier title } } }',
            variables={"url": "home"},
        )
        route = data.get("route")
        assert route is not None
        assert route["__typename"] == "CmsPage"
        assert route["identifier"] == "home"
        log.info("Resolved 'home' -> CmsPage (title=%s)", route.get("title"))

    async def test_resolve_nonexistent_url(self, client: MagentoClient) -> None:
        """Nonexistent URL returns null route."""
        data = await client.graphql(
            'query($url: String!) { route(url: $url) { __typename } }',
            variables={"url": "nonexistent-page-xyz-123"},
        )
        assert data.get("route") is None

    async def test_tool_resolve_url(self) -> None:
        """c_resolve_url tool resolves CMS home page."""
        from magemcp.server import mcp as server

        tools = server._tool_manager._tools
        tool_fn = tools["c_resolve_url"].fn

        result = await tool_fn(url="home")
        assert result["type"] == "CmsPage"
        assert result["identifier"] == "home"
        log.info("Tool c_resolve_url: home -> %s", result["type"])


class TestCartCheckoutFlow:
    """Full guest checkout flow against real Magento."""

    async def test_full_checkout_flow(self) -> None:
        """Create cart -> add item -> set addresses -> set payment -> place order."""
        from magemcp.server import mcp as server

        tools = server._tool_manager._tools

        # Discover a real simple product SKU
        async with MagentoClient.from_config() as client:
            sku = await _discover_product_sku(client)
        if sku is None:
            pytest.skip("No products in catalog")

        # 1. Create cart
        create_fn = tools["c_create_cart"].fn
        cart_result = await create_fn()
        cart_id = cart_result["cart_id"]
        assert cart_id
        log.info("Created cart: %s", cart_id)

        # 2. Add product
        add_fn = tools["c_add_to_cart"].fn
        add_result = await add_fn(cart_id=cart_id, sku=sku, quantity=1)
        assert "error" not in add_result, f"Add to cart failed: {add_result}"
        assert len(add_result["items"]) >= 1
        log.info("Added %s to cart, %d items", sku, len(add_result["items"]))

        # 3. Set guest email
        email_fn = tools["c_set_guest_email"].fn
        email_result = await email_fn(cart_id=cart_id, email="integration-test@example.com")
        assert email_result["email"] == "integration-test@example.com"

        # 4. Set shipping address
        ship_addr_fn = tools["c_set_shipping_address"].fn
        ship_result = await ship_addr_fn(
            cart_id=cart_id,
            firstname="Test", lastname="User",
            street=["123 Main St"], city="Austin", region="TX",
            postcode="78701", country_code="US", telephone="5551234567",
        )
        assert ship_result["shipping_addresses"]
        log.info("Shipping address set, methods available: %d",
                 len(ship_result["shipping_addresses"][0].get("available_shipping_methods", [])))

        # 5. Set billing address
        bill_addr_fn = tools["c_set_billing_address"].fn
        await bill_addr_fn(
            cart_id=cart_id,
            firstname="Test", lastname="User",
            street=["123 Main St"], city="Austin", region="TX",
            postcode="78701", country_code="US", telephone="5551234567",
        )

        # 6. Set shipping method
        ship_method_fn = tools["c_set_shipping_method"].fn
        await ship_method_fn(
            cart_id=cart_id, carrier_code="flatrate", method_code="flatrate",
        )

        # 7. Set payment method
        pay_fn = tools["c_set_payment_method"].fn
        await pay_fn(cart_id=cart_id, payment_method_code="checkmo")

        # 8. Verify cart state before placing order
        get_fn = tools["c_get_cart"].fn
        cart = await get_fn(cart_id=cart_id)
        assert len(cart["items"]) >= 1
        assert cart["email"] == "integration-test@example.com"

        # 9. Place order
        place_fn = tools["c_place_order"].fn
        order_result = await place_fn(cart_id=cart_id)
        assert "error" not in order_result, f"Place order failed: {order_result}"
        assert order_result["order_number"]
        log.info("Order placed: %s", order_result["order_number"])


class TestCrossToolScenarios:
    """End-to-end scenarios that chain multiple tools together."""

    async def test_search_then_get_detail(self) -> None:
        """Search for products, then fetch detail for the first result."""
        from magemcp.server import mcp as server

        tools = server._tool_manager._tools
        search_fn = tools["c_search_products"].fn
        detail_fn = tools["c_get_product"].fn

        search_result = await search_fn(page_size=1)
        if not search_result["products"]:
            pytest.skip("No products in catalog")

        sku = search_result["products"][0]["sku"]
        detail_result = await detail_fn(sku=sku)
        assert detail_result["sku"] == sku
        assert detail_result["name"] == search_result["products"][0]["name"]
        log.info("Search->Detail: %s — %s", sku, detail_result["name"])

    async def test_order_then_customer(self) -> None:
        """Fetch an order, then look up the associated customer."""
        from magemcp.server import mcp as server

        tools = server._tool_manager._tools
        order_fn = tools["admin_get_order"].fn
        customer_fn = tools["admin_get_customer"].fn

        async with MagentoClient.from_config() as client:
            increment_id = await _discover_order_increment_id(client)
        if increment_id is None:
            pytest.skip("No orders in the system")

        # Get order — admin always returns full data
        order_result = await order_fn(increment_id=increment_id)

        # Look up the order in REST to get customer_id (not in our redacted DTO)
        async with MagentoClient.from_config() as client:
            params = MagentoClient.search_params(
                filters={"increment_id": increment_id}, page_size=1
            )
            raw = await client.get("/V1/orders", params=params)
            customer_id = raw["items"][0].get("customer_id")

        if not customer_id or customer_id == 0:
            pytest.skip("Order is guest — no customer to look up")

        customer_result = await customer_fn(customer_id=customer_id)
        assert customer_result["customer_id"] == customer_id
        log.info(
            "Order %s -> Customer %d (%s %s)",
            increment_id,
            customer_id,
            customer_result["firstname"],
            customer_result["lastname"],
        )

    async def test_product_inventory_check(self) -> None:
        """Search for a product, then check its inventory."""
        from magemcp.server import mcp as server

        tools = server._tool_manager._tools
        search_fn = tools["c_search_products"].fn
        inventory_fn = tools["admin_get_inventory"].fn

        search_result = await search_fn(page_size=1)
        if not search_result["products"]:
            pytest.skip("No products in catalog")

        sku = search_result["products"][0]["sku"]
        try:
            inv_result = await inventory_fn(skus=[sku])
        except MagentoError:
            pytest.skip("MSI inventory endpoints not available")

        assert inv_result["items"][0]["sku"] == sku
        log.info(
            "Product %s: salable_qty=%s, is_salable=%s",
            sku,
            inv_result["items"][0]["salable_quantity"],
            inv_result["items"][0]["is_salable"],
        )


# ---------------------------------------------------------------------------
# MCP vs raw API comparison tests
# ---------------------------------------------------------------------------


class TestMcpVsRawApi:
    """Compare MCP tool output against raw Magento API responses.

    These tests fetch the same data via both the raw API and the MCP tool,
    then verify that every field the tool exposes matches the source data.
    Catches field mapping bugs, dropped data, and parsing regressions.
    """

    async def test_get_categories_matches_graphql(self) -> None:
        """c_get_categories output matches raw GraphQL categories query."""
        from magemcp.server import mcp as server

        tools = server._tool_manager._tools
        tool_fn = tools["c_get_categories"].fn

        tool_result = await tool_fn(page_size=10)
        if not tool_result["categories"]:
            pytest.skip("No categories in Magento")

        # Fetch same data via raw GraphQL
        async with MagentoClient.from_config() as client:
            raw = await client.graphql(
                """
                query {
                  categories(pageSize: 10, currentPage: 1) {
                    total_count
                    items {
                      uid name url_key url_path position level product_count include_in_menu
                      children { uid name }
                    }
                    page_info { current_page page_size total_pages }
                  }
                }
                """
            )

        raw_cats = raw["categories"]

        assert tool_result["total_count"] == raw_cats["total_count"]
        assert tool_result["page_info"]["current_page"] == raw_cats["page_info"]["current_page"]

        for tool_cat, raw_cat in zip(tool_result["categories"], raw_cats["items"]):
            assert tool_cat["uid"] == raw_cat["uid"], f"UID mismatch"
            assert tool_cat["name"] == raw_cat["name"], f"Name mismatch for {raw_cat['uid']}"
            assert tool_cat["url_key"] == raw_cat.get("url_key")
            assert tool_cat["level"] == raw_cat.get("level")
            assert tool_cat["product_count"] == raw_cat.get("product_count", 0)

            # Children count
            tool_children = tool_cat.get("children") or []
            raw_children = raw_cat.get("children") or []
            assert len(tool_children) == len(raw_children), (
                f"Children count mismatch for {raw_cat['name']}"
            )

        log.info(
            "MCP vs GraphQL categories: %d categories compared, all fields match",
            len(tool_result["categories"]),
        )

    async def test_search_products_matches_graphql(self) -> None:
        """c_search_products output matches raw GraphQL products query."""
        from magemcp.server import mcp as server

        tools = server._tool_manager._tools
        tool_fn = tools["c_search_products"].fn

        tool_result = await tool_fn(search="", page_size=5)
        if not tool_result["products"]:
            pytest.skip("No products in catalog")

        # Fetch the same data via raw GraphQL
        async with MagentoClient.from_config() as client:
            raw = await client.graphql(
                """
                query {
                  products(search: "", pageSize: 5) {
                    total_count
                    items {
                      sku name url_key stock_status __typename
                      price_range {
                        minimum_price {
                          regular_price { value currency }
                          final_price { value currency }
                        }
                      }
                    }
                    page_info { current_page page_size total_pages }
                  }
                }
                """
            )

        raw_products = raw["products"]

        # Total count must match
        assert tool_result["total_count"] == raw_products["total_count"]

        # Page info must match
        assert tool_result["page_info"]["current_page"] == raw_products["page_info"]["current_page"]
        assert tool_result["page_info"]["page_size"] == raw_products["page_info"]["page_size"]

        # Compare each product
        for tool_prod, raw_prod in zip(tool_result["products"], raw_products["items"]):
            assert tool_prod["sku"] == raw_prod["sku"], f"SKU mismatch"
            assert tool_prod["name"] == raw_prod["name"], f"Name mismatch for {raw_prod['sku']}"
            assert tool_prod["url_key"] == raw_prod["url_key"], f"url_key mismatch for {raw_prod['sku']}"
            assert tool_prod["stock_status"] == raw_prod["stock_status"], f"stock_status mismatch for {raw_prod['sku']}"

            # Price comparison
            raw_min = raw_prod["price_range"]["minimum_price"]
            assert float(tool_prod["min_price"]["regular_price"]["value"]) == raw_min["regular_price"]["value"]
            assert float(tool_prod["min_price"]["final_price"]["value"]) == raw_min["final_price"]["value"]
            assert tool_prod["min_price"]["regular_price"]["currency"] == raw_min["regular_price"]["currency"]

        log.info(
            "MCP vs GraphQL search: %d products compared, all fields match",
            len(tool_result["products"]),
        )

    async def test_get_product_matches_graphql(self) -> None:
        """c_get_product output matches raw GraphQL product detail query."""
        async with MagentoClient.from_config() as client:
            sku = await _discover_product_sku(client)
        if sku is None:
            pytest.skip("No products in catalog")

        from magemcp.server import mcp as server

        tools = server._tool_manager._tools
        tool_fn = tools["c_get_product"].fn

        tool_result = await tool_fn(sku=sku)

        # Fetch same product via raw GraphQL
        async with MagentoClient.from_config() as client:
            raw = await client.graphql(
                """
                query($sku: String!) {
                  products(filter: { sku: { eq: $sku } }) {
                    items {
                      sku name url_key stock_status __typename
                      meta_title meta_description
                      description { html }
                      short_description { html }
                      price_range {
                        minimum_price {
                          regular_price { value currency }
                          final_price { value currency }
                        }
                      }
                      media_gallery { url label position disabled }
                      categories { name url_path }
                    }
                  }
                }
                """,
                variables={"sku": sku},
            )

        raw_prod = raw["products"]["items"][0]

        # Core fields
        assert tool_result["sku"] == raw_prod["sku"]
        assert tool_result["name"] == raw_prod["name"]
        assert tool_result["url_key"] == raw_prod["url_key"]
        assert tool_result["stock_status"] == raw_prod["stock_status"]
        assert tool_result["meta_title"] == raw_prod.get("meta_title")
        assert tool_result["meta_description"] == raw_prod.get("meta_description")

        # Price
        raw_min = raw_prod["price_range"]["minimum_price"]
        assert float(tool_result["min_price"]["regular_price"]["value"]) == raw_min["regular_price"]["value"]
        assert float(tool_result["min_price"]["final_price"]["value"]) == raw_min["final_price"]["value"]

        # Images — tool filters disabled and sorts by position
        raw_enabled = [img for img in (raw_prod.get("media_gallery") or []) if not img.get("disabled")]
        assert len(tool_result["images"]) == len(raw_enabled)

        # Categories
        raw_cats = raw_prod.get("categories") or []
        assert len(tool_result["categories"]) == len(raw_cats)
        for tool_cat, raw_cat in zip(tool_result["categories"], raw_cats):
            assert tool_cat["name"] == raw_cat["name"]

        log.info("MCP vs GraphQL product: %s — all fields match", sku)

    async def test_get_order_matches_rest(self) -> None:
        """admin_get_order output matches raw REST order response."""
        async with MagentoClient.from_config() as client:
            increment_id = await _discover_order_increment_id(client)
        if increment_id is None:
            pytest.skip("No orders in the system")

        from magemcp.server import mcp as server

        tools = server._tool_manager._tools
        tool_fn = tools["admin_get_order"].fn

        tool_result = await tool_fn(increment_id=increment_id)

        # Fetch same order via raw REST
        async with MagentoClient.from_config() as client:
            params = MagentoClient.search_params(
                filters={"increment_id": increment_id}, page_size=1,
            )
            raw_data = await client.get("/V1/orders", params=params)

        raw_order = raw_data["items"][0]

        # Core order fields
        assert tool_result["increment_id"] == str(raw_order["increment_id"])
        assert tool_result["state"] == raw_order["state"]
        assert tool_result["status"] == raw_order["status"]
        assert tool_result["created_at"] == raw_order["created_at"]
        assert tool_result["currency_code"] == raw_order.get("order_currency_code")

        # Totals
        assert tool_result["grand_total"] == raw_order["grand_total"]
        assert tool_result["subtotal"] == raw_order["subtotal"]
        assert tool_result["tax_amount"] == raw_order["tax_amount"]
        assert tool_result["shipping_amount"] == raw_order.get("shipping_amount", 0)
        assert tool_result["total_qty_ordered"] == raw_order["total_qty_ordered"]

        # Customer info — admin returns full PII
        assert tool_result["pii_mode"] == "full"
        assert tool_result["customer_email"] == raw_order.get("customer_email")
        firstname = raw_order.get("customer_firstname") or ""
        lastname = raw_order.get("customer_lastname") or ""
        expected_name = f"{firstname} {lastname}".strip() or "Unknown"
        assert tool_result["customer_name"] == expected_name

        # Line items — tool skips child items of configurables
        raw_parent_items = [i for i in raw_order["items"] if not i.get("parent_item_id")]
        assert len(tool_result["items"]) == len(raw_parent_items)
        for tool_item, raw_item in zip(tool_result["items"], raw_parent_items):
            assert tool_item["sku"] == raw_item["sku"]
            assert tool_item["name"] == raw_item["name"]
            assert tool_item["qty_ordered"] == raw_item["qty_ordered"]
            assert tool_item["price"] == raw_item["price"]

        # Billing address
        if raw_order.get("billing_address"):
            assert tool_result["billing_address"] is not None
            assert tool_result["billing_address"]["city"] == raw_order["billing_address"].get("city")
            assert tool_result["billing_address"]["country_id"] == raw_order["billing_address"].get("country_id")
            assert tool_result["billing_address"]["telephone"] == raw_order["billing_address"].get("telephone")
            assert tool_result["billing_address"]["street"] == raw_order["billing_address"].get("street")

        log.info(
            "MCP vs REST order: %s — %d fields + %d items compared, all match",
            increment_id,
            10,
            len(tool_result["items"]),
        )

    async def test_get_customer_matches_rest(self) -> None:
        """admin_get_customer output matches raw REST customer response."""
        async with MagentoClient.from_config() as client:
            customer_id = await _discover_customer_id(client)
        if customer_id is None:
            pytest.skip("No customers in the system")

        from magemcp.server import mcp as server

        tools = server._tool_manager._tools
        tool_fn = tools["admin_get_customer"].fn

        tool_result = await tool_fn(customer_id=customer_id)

        # Fetch same customer via raw REST
        async with MagentoClient.from_config() as client:
            raw = await client.get(f"/V1/customers/{customer_id}")

        # Core fields
        assert tool_result["customer_id"] == raw["id"]
        assert tool_result["group_id"] == raw.get("group_id")
        assert tool_result["store_id"] == raw.get("store_id")
        assert tool_result["website_id"] == raw.get("website_id")
        assert tool_result["created_at"] == raw.get("created_at")
        assert tool_result["updated_at"] == raw.get("updated_at")

        # PII — admin returns full
        assert tool_result["pii_mode"] == "full"
        assert tool_result["firstname"] == raw.get("firstname")
        assert tool_result["lastname"] == raw.get("lastname")
        assert tool_result["email"] == raw.get("email")
        assert tool_result["dob"] == raw.get("dob")
        assert tool_result["gender"] == raw.get("gender")

        log.info(
            "MCP vs REST customer: id=%d (%s %s) — all fields match",
            customer_id,
            tool_result["firstname"],
            tool_result["lastname"],
        )

    async def test_get_inventory_matches_rest(self) -> None:
        """admin_get_inventory output matches raw REST inventory endpoints."""
        async with MagentoClient.from_config() as client:
            sku = await _discover_product_sku(client)
        if sku is None:
            pytest.skip("No products in catalog")

        from magemcp.server import mcp as server

        tools = server._tool_manager._tools
        tool_fn = tools["admin_get_inventory"].fn

        try:
            tool_result = await tool_fn(skus=[sku])
        except MagentoError:
            pytest.skip("MSI inventory endpoints not available")

        tool_item = tool_result["items"][0]

        # Fetch same data via raw REST
        async with MagentoClient.from_config() as client:
            try:
                raw_qty = await client.get(
                    f"/V1/inventory/get-product-salable-quantity/{sku}/1"
                )
                raw_salable = await client.get(
                    f"/V1/inventory/is-product-salable/{sku}/1"
                )
            except MagentoError:
                pytest.skip("MSI inventory endpoints not available")

        assert tool_item["sku"] == sku
        assert tool_item["salable_quantity"] == float(raw_qty)
        assert tool_item["is_salable"] == bool(raw_salable)
        assert tool_item["stock_id"] == 1

        log.info(
            "MCP vs REST inventory: %s qty=%s salable=%s — match",
            sku,
            tool_item["salable_quantity"],
            tool_item["is_salable"],
        )


# ---------------------------------------------------------------------------
# admin_search_customers integration
# ---------------------------------------------------------------------------


class TestSearchCustomers:
    """Integration tests for admin_search_customers tool."""

    async def test_search_customers_real(self, client: MagentoClient) -> None:
        """Raw REST call to /V1/customers/search returns items with full data."""
        from magemcp.connectors.rest_client import RESTClient
        params = RESTClient.search_params(page_size=5)
        async with RESTClient.from_env() as rest:
            data = await rest.get("/V1/customers/search", params=params)

        assert "items" in data
        if data["items"]:
            customer = data["items"][0]
            assert "email" in customer
            assert "firstname" in customer
            assert "id" in customer
            # Full unmasked email
            assert "@" in customer["email"]
            log.info(
                "Customer search: %d results, first=%s %s <%s>",
                data["total_count"],
                customer.get("firstname"),
                customer.get("lastname"),
                customer.get("email"),
            )

    async def test_tool_search_customers(self) -> None:
        """admin_search_customers tool returns CustomerSummary list."""
        from magemcp.tools.admin.search_customers import admin_search_customers
        result = await admin_search_customers(page_size=5)

        assert "customers" in result
        assert "total_count" in result
        # If any customers exist, verify full data is returned
        if result["customers"]:
            c = result["customers"][0]
            assert "customer_id" in c
            assert "email" in c
            assert "@" in (c["email"] or "")
            log.info(
                "Tool search customers: %d results, first=%s <%s>",
                result["total_count"],
                c.get("firstname"),
                c.get("email"),
            )

    async def test_search_by_email_wildcard(self, client: MagentoClient) -> None:
        """Search by partial email using like condition."""
        from magemcp.connectors.rest_client import RESTClient
        # First discover a real email domain
        params = RESTClient.search_params(page_size=1)
        async with RESTClient.from_env() as rest:
            data = await rest.get("/V1/customers/search", params=params)

        if not data.get("items"):
            pytest.skip("No customers found")

        email = data["items"][0]["email"]
        domain = email.split("@")[-1]

        from magemcp.tools.admin.search_customers import admin_search_customers
        result = await admin_search_customers(email=f"%@{domain}")

        assert result["total_count"] >= 1
        assert all("@" + domain in (c["email"] or "") for c in result["customers"])


# ---------------------------------------------------------------------------
# admin_get_customer enhanced integration
# ---------------------------------------------------------------------------


class TestGetCustomerEnhanced:
    """Integration tests for enhanced admin_get_customer (addresses + custom_attributes)."""

    async def test_get_customer_includes_addresses(self, client: MagentoClient) -> None:
        """admin_get_customer returns addresses list."""
        from magemcp.connectors.rest_client import RESTClient
        params = RESTClient.search_params(page_size=1)
        async with RESTClient.from_env() as rest:
            data = await rest.get("/V1/customers/search", params=params)

        if not data.get("items"):
            pytest.skip("No customers found")

        customer_id = data["items"][0]["id"]
        from magemcp.tools.admin.get_customer import parse_customer
        async with RESTClient.from_env() as rest:
            raw = await rest.get(f"/V1/customers/{customer_id}")

        result = parse_customer(raw)
        # addresses is always a list (may be empty)
        assert isinstance(result.addresses, list)
        assert isinstance(result.custom_attributes, dict)
        assert isinstance(result.extension_attributes, dict)
        log.info(
            "Customer %d has %d addresses, %d custom attrs",
            customer_id,
            len(result.addresses),
            len(result.custom_attributes),
        )


# ---------------------------------------------------------------------------
# admin product tools integration
# ---------------------------------------------------------------------------


class TestAdminProducts:
    """Integration tests for admin product tools."""

    async def test_get_product_24_mb01(self) -> None:
        """Get Magento sample data product by SKU."""
        from magemcp.connectors.rest_client import RESTClient
        async with RESTClient.from_env() as client:
            product = await client.get("/V1/products/24-MB01")

        assert product["sku"] == "24-MB01"
        assert product["name"]
        assert "price" in product
        assert "media_gallery_entries" in product
        log.info(
            "Product 24-MB01: name=%s price=%s media=%d",
            product["name"],
            product["price"],
            len(product.get("media_gallery_entries") or []),
        )

    async def test_tool_get_product(self) -> None:
        """admin_get_product returns parsed ProductDetail."""
        from magemcp.tools.admin.products import admin_get_product
        result = await admin_get_product(sku="24-MB01")

        if "error" in result:
            pytest.skip("24-MB01 not in this Magento instance")

        assert result["sku"] == "24-MB01"
        assert result["name"]
        assert "stock" in result
        assert "media_gallery" in result
        assert "custom_attributes" in result
        log.info(
            "admin_get_product 24-MB01: stock_qty=%s description_len=%s",
            result.get("stock", {}).get("qty") if result.get("stock") else "n/a",
            len(result.get("custom_attributes", {}).get("description") or ""),
        )

    async def test_tool_search_products(self) -> None:
        """admin_search_products returns paginated product list."""
        from magemcp.tools.admin.products import admin_search_products
        result = await admin_search_products(page_size=5, status=1)

        assert "products" in result
        assert "total_count" in result
        if result["products"]:
            p = result["products"][0]
            assert "sku" in p
            assert "name" in p
            log.info(
                "admin_search_products: %d total, first=%s (%s)",
                result["total_count"],
                p["sku"],
                p["name"],
            )

    async def test_search_products_by_sku_wildcard(self) -> None:
        """Wildcard SKU search returns matching products."""
        from magemcp.tools.admin.products import admin_search_products
        result = await admin_search_products(sku="24-MB%", page_size=10)

        assert "products" in result
        for p in result["products"]:
            assert p["sku"].startswith("24-MB")
