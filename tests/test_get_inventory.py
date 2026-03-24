"""Tests for admin_get_inventory tool."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from magemcp.connectors.magento import MagentoClient, MagentoError, MagentoNotFoundError
from magemcp.models.inventory import CGetInventoryInput, CGetInventoryOutput, SkuInventory

BASE_URL = "https://magento.test"
TOKEN = "test-token-123"


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_valid_single_sku(self) -> None:
        inp = CGetInventoryInput(skus=["WJ12"])
        assert inp.skus == ["WJ12"]
        assert inp.stock_id == 1
        assert inp.store_scope == "default"

    def test_valid_multiple_skus(self) -> None:
        inp = CGetInventoryInput(skus=["WJ12", "WT03", "WP01"])
        assert len(inp.skus) == 3

    def test_empty_skus_rejected(self) -> None:
        with pytest.raises(Exception):
            CGetInventoryInput(skus=[])

    def test_too_many_skus_rejected(self) -> None:
        with pytest.raises(Exception):
            CGetInventoryInput(skus=[f"SKU{i}" for i in range(51)])

    def test_custom_stock_id(self) -> None:
        inp = CGetInventoryInput(skus=["WJ12"], stock_id=2)
        assert inp.stock_id == 2

    def test_invalid_stock_id_zero(self) -> None:
        with pytest.raises(Exception):
            CGetInventoryInput(skus=["WJ12"], stock_id=0)

    def test_invalid_store_scope(self) -> None:
        with pytest.raises(Exception):
            CGetInventoryInput(skus=["WJ12"], store_scope="INVALID!")


# ---------------------------------------------------------------------------
# SkuInventory model
# ---------------------------------------------------------------------------


class TestSkuInventory:
    def test_basic(self) -> None:
        item = SkuInventory(sku="WJ12", salable_quantity=25.0, is_salable=True, stock_id=1)
        assert item.sku == "WJ12"
        assert item.salable_quantity == 25.0
        assert item.is_salable is True
        assert item.error is None

    def test_with_error(self) -> None:
        item = SkuInventory(
            sku="NOPE", salable_quantity=0, is_salable=False, stock_id=1,
            error="Product not found",
        )
        assert item.error == "Product not found"

    def test_zero_quantity(self) -> None:
        item = SkuInventory(sku="WJ12", salable_quantity=0, is_salable=False, stock_id=1)
        assert item.salable_quantity == 0
        assert item.is_salable is False


# ---------------------------------------------------------------------------
# CGetInventoryOutput model
# ---------------------------------------------------------------------------


class TestOutputModel:
    def test_basic(self) -> None:
        output = CGetInventoryOutput(
            items=[
                SkuInventory(sku="WJ12", salable_quantity=25.0, is_salable=True, stock_id=1),
                SkuInventory(sku="WT03", salable_quantity=0, is_salable=False, stock_id=1),
            ],
            stock_id=1,
        )
        assert len(output.items) == 2
        assert output.stock_id == 1


# ---------------------------------------------------------------------------
# End-to-end tool invocation (mocked REST)
# ---------------------------------------------------------------------------


class TestToolEndToEnd:
    @respx.mock
    async def test_single_sku_in_stock(self) -> None:
        """Single SKU returns salable quantity and is_salable."""
        qty_route = respx.get(
            f"{BASE_URL}/rest/default/V1/inventory/get-product-salable-quantity/WJ12/1",
        ).mock(return_value=httpx.Response(200, json=25))
        salable_route = respx.get(
            f"{BASE_URL}/rest/default/V1/inventory/is-product-salable/WJ12/1",
        ).mock(return_value=httpx.Response(200, json=True))

        async with MagentoClient(base_url=BASE_URL, token=TOKEN) as client:
            qty_data = await client.get(
                "/V1/inventory/get-product-salable-quantity/WJ12/1",
            )
            salable_data = await client.get(
                "/V1/inventory/is-product-salable/WJ12/1",
            )

        assert float(qty_data) == 25.0
        assert bool(salable_data) is True
        assert qty_route.called
        assert salable_route.called

    @respx.mock
    async def test_single_sku_out_of_stock(self) -> None:
        """SKU with zero quantity and not salable."""
        respx.get(
            f"{BASE_URL}/rest/default/V1/inventory/get-product-salable-quantity/WT03/1",
        ).mock(return_value=httpx.Response(200, json=0))
        respx.get(
            f"{BASE_URL}/rest/default/V1/inventory/is-product-salable/WT03/1",
        ).mock(return_value=httpx.Response(200, json=False))

        async with MagentoClient(base_url=BASE_URL, token=TOKEN) as client:
            qty_data = await client.get(
                "/V1/inventory/get-product-salable-quantity/WT03/1",
            )
            salable_data = await client.get(
                "/V1/inventory/is-product-salable/WT03/1",
            )

        item = SkuInventory(
            sku="WT03",
            salable_quantity=float(qty_data),
            is_salable=bool(salable_data),
            stock_id=1,
        )
        assert item.salable_quantity == 0
        assert item.is_salable is False

    @respx.mock
    async def test_store_scope_in_url(self) -> None:
        """Verify store scope is included in the REST URL."""
        route = respx.get(
            f"{BASE_URL}/rest/fr/V1/inventory/get-product-salable-quantity/WJ12/1",
        ).mock(return_value=httpx.Response(200, json=10))

        async with MagentoClient(base_url=BASE_URL, token=TOKEN) as client:
            await client.get(
                "/V1/inventory/get-product-salable-quantity/WJ12/1",
                store_code="fr",
            )

        assert route.called

    @respx.mock
    async def test_custom_stock_id(self) -> None:
        """Verify custom stock ID is passed in the URL."""
        route = respx.get(
            f"{BASE_URL}/rest/default/V1/inventory/get-product-salable-quantity/WJ12/3",
        ).mock(return_value=httpx.Response(200, json=5))

        async with MagentoClient(base_url=BASE_URL, token=TOKEN) as client:
            await client.get(
                "/V1/inventory/get-product-salable-quantity/WJ12/3",
            )

        assert route.called

    @respx.mock
    async def test_sku_not_found_error(self) -> None:
        """404 for nonexistent SKU raises MagentoNotFoundError."""
        respx.get(
            f"{BASE_URL}/rest/default/V1/inventory/get-product-salable-quantity/NOPE/1",
        ).mock(
            return_value=httpx.Response(
                404, json={"message": "The product that was requested doesn't exist."},
            ),
        )

        async with MagentoClient(base_url=BASE_URL, token=TOKEN) as client:
            with pytest.raises(MagentoNotFoundError, match="doesn't exist"):
                await client.get(
                    "/V1/inventory/get-product-salable-quantity/NOPE/1",
                )

    @respx.mock
    async def test_multiple_skus(self) -> None:
        """Multiple SKUs each get their own inventory result."""
        respx.get(
            f"{BASE_URL}/rest/default/V1/inventory/get-product-salable-quantity/WJ12/1",
        ).mock(return_value=httpx.Response(200, json=25))
        respx.get(
            f"{BASE_URL}/rest/default/V1/inventory/is-product-salable/WJ12/1",
        ).mock(return_value=httpx.Response(200, json=True))
        respx.get(
            f"{BASE_URL}/rest/default/V1/inventory/get-product-salable-quantity/WT03/1",
        ).mock(return_value=httpx.Response(200, json=0))
        respx.get(
            f"{BASE_URL}/rest/default/V1/inventory/is-product-salable/WT03/1",
        ).mock(return_value=httpx.Response(200, json=False))

        results: list[SkuInventory] = []
        async with MagentoClient(base_url=BASE_URL, token=TOKEN) as client:
            for sku in ["WJ12", "WT03"]:
                qty_data = await client.get(
                    f"/V1/inventory/get-product-salable-quantity/{sku}/1",
                )
                salable_data = await client.get(
                    f"/V1/inventory/is-product-salable/{sku}/1",
                )
                results.append(SkuInventory(
                    sku=sku,
                    salable_quantity=float(qty_data),
                    is_salable=bool(salable_data),
                    stock_id=1,
                ))

        output = CGetInventoryOutput(items=results, stock_id=1)
        assert len(output.items) == 2
        assert output.items[0].sku == "WJ12"
        assert output.items[0].salable_quantity == 25.0
        assert output.items[0].is_salable is True
        assert output.items[1].sku == "WT03"
        assert output.items[1].salable_quantity == 0
        assert output.items[1].is_salable is False


# ---------------------------------------------------------------------------
# Tool function invocation (exercises get_inventory.py lines 24-94)
# ---------------------------------------------------------------------------


BASE_URL = "https://magento.test"
TOKEN = "admin-token-123"
STORE_CODE = "default"


@pytest.fixture
def mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAGENTO_BASE_URL", BASE_URL)
    monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", TOKEN)


class TestToolFunction:
    async def test_single_sku_in_stock(
        self, mock_env: None, respx_mock: respx.MockRouter,
    ) -> None:
        """Tool function returns salable_quantity and is_salable for a single SKU."""
        respx_mock.get(
            f"{BASE_URL}/rest/{STORE_CODE}/V1/inventory/get-product-salable-quantity/WJ12/1",
        ).mock(return_value=httpx.Response(200, json=25))
        respx_mock.get(
            f"{BASE_URL}/rest/{STORE_CODE}/V1/inventory/is-product-salable/WJ12/1",
        ).mock(return_value=httpx.Response(200, json=True))

        from magemcp.tools.admin.get_inventory import admin_get_inventory

        result = await admin_get_inventory(skus=["WJ12"])
        assert isinstance(result, dict)
        assert result["stock_id"] == 1
        assert len(result["items"]) == 1
        assert result["items"][0]["sku"] == "WJ12"
        assert result["items"][0]["salable_quantity"] == 25.0
        assert result["items"][0]["is_salable"] is True
        assert result["items"][0]["error"] is None

    async def test_sku_not_found_records_error(
        self, mock_env: None, respx_mock: respx.MockRouter,
    ) -> None:
        """A 404 for a SKU is captured in the error field, not raised."""
        respx_mock.get(
            f"{BASE_URL}/rest/{STORE_CODE}/V1/inventory/get-product-salable-quantity/NOPE/1",
        ).mock(return_value=httpx.Response(
            404, json={"message": "The product that was requested doesn't exist."},
        ))
        respx_mock.get(
            f"{BASE_URL}/rest/{STORE_CODE}/V1/inventory/is-product-salable/NOPE/1",
        ).mock(return_value=httpx.Response(200, json=False))

        from magemcp.tools.admin.get_inventory import admin_get_inventory

        result = await admin_get_inventory(skus=["NOPE"])
        assert result["items"][0]["error"] is not None
        assert result["items"][0]["is_salable"] is False

    async def test_multiple_skus(
        self, mock_env: None, respx_mock: respx.MockRouter,
    ) -> None:
        """Two SKUs produce two entries in items."""
        for sku, qty, salable in [("WJ12", 10, True), ("WT03", 0, False)]:
            respx_mock.get(
                f"{BASE_URL}/rest/{STORE_CODE}/V1/inventory/get-product-salable-quantity/{sku}/1",
            ).mock(return_value=httpx.Response(200, json=qty))
            respx_mock.get(
                f"{BASE_URL}/rest/{STORE_CODE}/V1/inventory/is-product-salable/{sku}/1",
            ).mock(return_value=httpx.Response(200, json=salable))

        from magemcp.tools.admin.get_inventory import admin_get_inventory

        result = await admin_get_inventory(skus=["WJ12", "WT03"])
        assert len(result["items"]) == 2

    async def test_custom_stock_id_in_url(
        self, mock_env: None, respx_mock: respx.MockRouter,
    ) -> None:
        """Custom stock_id is reflected in the REST endpoint URL."""
        qty_route = respx_mock.get(
            f"{BASE_URL}/rest/{STORE_CODE}/V1/inventory/get-product-salable-quantity/WJ12/3",
        ).mock(return_value=httpx.Response(200, json=5))
        respx_mock.get(
            f"{BASE_URL}/rest/{STORE_CODE}/V1/inventory/is-product-salable/WJ12/3",
        ).mock(return_value=httpx.Response(200, json=True))

        from magemcp.tools.admin.get_inventory import admin_get_inventory

        result = await admin_get_inventory(skus=["WJ12"], stock_id=3)
        assert qty_route.called
        assert result["stock_id"] == 3

    async def test_is_salable_error_captured(
        self, mock_env: None, respx_mock: respx.MockRouter,
    ) -> None:
        """Error from is-product-salable endpoint is captured in error field."""
        respx_mock.get(
            f"{BASE_URL}/rest/{STORE_CODE}/V1/inventory/get-product-salable-quantity/WJ12/1",
        ).mock(return_value=httpx.Response(200, json=10))
        # is-product-salable returns 500 — should be caught and stored in error
        respx_mock.get(
            f"{BASE_URL}/rest/{STORE_CODE}/V1/inventory/is-product-salable/WJ12/1",
        ).mock(return_value=httpx.Response(500, text="Internal Server Error"))

        from magemcp.tools.admin.get_inventory import admin_get_inventory

        result = await admin_get_inventory(skus=["WJ12"])
        item = result["items"][0]
        assert item["salable_quantity"] == 10.0
        assert item["is_salable"] is False
        assert item["error"] is not None

    async def test_is_registered(self) -> None:
        """Tool is present in the MCP server."""
        from magemcp.server import mcp
        names = [t.name for t in await mcp.list_tools()]
        assert "admin_get_inventory" in names


# ---------------------------------------------------------------------------
# Output serialization
# ---------------------------------------------------------------------------


class TestOutputSerialization:
    def test_model_dump_json(self) -> None:
        """Verify that the output serializes cleanly to JSON-compatible dict."""
        output = CGetInventoryOutput(
            items=[
                SkuInventory(sku="WJ12", salable_quantity=25.0, is_salable=True, stock_id=1),
                SkuInventory(
                    sku="NOPE", salable_quantity=0, is_salable=False, stock_id=1,
                    error="Not found",
                ),
            ],
            stock_id=1,
        )
        dumped = output.model_dump(mode="json")

        assert isinstance(dumped, dict)
        assert dumped["stock_id"] == 1
        assert len(dumped["items"]) == 2
        assert dumped["items"][0]["sku"] == "WJ12"
        assert dumped["items"][0]["salable_quantity"] == 25.0
        assert dumped["items"][0]["is_salable"] is True
        assert dumped["items"][0]["error"] is None
        assert dumped["items"][1]["sku"] == "NOPE"
        assert dumped["items"][1]["error"] == "Not found"
