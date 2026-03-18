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
# get_order integration
# ---------------------------------------------------------------------------


class TestGetOrder:
    """Integration tests for c_get_order via REST API."""

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
        """c_get_order returns a redacted order view."""
        async with MagentoClient.from_config() as client:
            increment_id = await _discover_order_increment_id(client)
        if increment_id is None:
            pytest.skip("No orders in the system")

        from magemcp.server import mcp as server

        tools = server._tool_manager._tools
        tool_fn = tools["c_get_order"].fn

        result = await tool_fn(increment_id=increment_id)
        assert isinstance(result, dict)
        assert result["increment_id"] == increment_id
        assert result["pii_mode"] == "redacted"
        # Verify PII is masked in default mode
        if result.get("customer_email"):
            assert "***" in result["customer_email"]
        log.info("Tool c_get_order: %s state=%s pii=%s", result["increment_id"], result["state"], result["pii_mode"])

    async def test_tool_get_order_full_pii(self) -> None:
        """c_get_order with pii_mode=full returns unmasked data."""
        async with MagentoClient.from_config() as client:
            increment_id = await _discover_order_increment_id(client)
        if increment_id is None:
            pytest.skip("No orders in the system")

        from magemcp.server import mcp as server

        tools = server._tool_manager._tools
        tool_fn = tools["c_get_order"].fn

        result = await tool_fn(increment_id=increment_id, pii_mode="full")
        assert result["pii_mode"] == "full"
        log.info("Tool c_get_order (full): %s email=%s", result["increment_id"], result.get("customer_email", "N/A"))

    async def test_tool_get_customer(self) -> None:
        """c_get_customer returns a redacted customer view."""
        async with MagentoClient.from_config() as client:
            customer_id = await _discover_customer_id(client)
        if customer_id is None:
            pytest.skip("No customers in the system")

        from magemcp.server import mcp as server

        tools = server._tool_manager._tools
        tool_fn = tools["c_get_customer"].fn

        result = await tool_fn(customer_id=customer_id)
        assert isinstance(result, dict)
        assert result["customer_id"] == customer_id
        assert result["pii_mode"] == "redacted"
        log.info("Tool c_get_customer: id=%d name=%s %s", result["customer_id"], result["firstname"], result["lastname"])

    async def test_tool_get_inventory(self) -> None:
        """c_get_inventory returns salable data for real SKUs."""
        async with MagentoClient.from_config() as client:
            sku = await _discover_product_sku(client)
        if sku is None:
            pytest.skip("No products in catalog")

        from magemcp.server import mcp as server

        tools = server._tool_manager._tools
        tool_fn = tools["c_get_inventory"].fn

        try:
            result = await tool_fn(skus=[sku])
        except MagentoError:
            pytest.skip("MSI inventory endpoints not available")

        assert isinstance(result, dict)
        assert "items" in result
        assert len(result["items"]) == 1
        item = result["items"][0]
        assert item["sku"] == sku
        log.info("Tool c_get_inventory: %s qty=%s salable=%s", item["sku"], item["salable_quantity"], item["is_salable"])


# ---------------------------------------------------------------------------
# Cross-tool scenario tests
# ---------------------------------------------------------------------------


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
        order_fn = tools["c_get_order"].fn
        customer_fn = tools["c_get_customer"].fn

        async with MagentoClient.from_config() as client:
            increment_id = await _discover_order_increment_id(client)
        if increment_id is None:
            pytest.skip("No orders in the system")

        # Get order with full PII to extract customer info
        order_result = await order_fn(increment_id=increment_id, pii_mode="full")

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
        inventory_fn = tools["c_get_inventory"].fn

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
