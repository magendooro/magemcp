"""Tests for admin bulk async tools."""

from __future__ import annotations

import json
from typing import Any

import pytest
import respx
from httpx import Response

from magemcp.tools.admin.bulk import (
    admin_bulk_catalog_update,
    admin_bulk_inventory_update,
    admin_get_bulk_status,
)

BASE_URL = "https://magento.test"
TOKEN = "admin-token-123"
STORE_CODE = "default"


@pytest.fixture
def mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAGENTO_BASE_URL", BASE_URL)
    monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("MAGENTO_STORE_CODE", STORE_CODE)


_BULK_RESPONSE: dict[str, Any] = {
    "bulk_uuid": "abc-123-def-456",
    "request_items": [{"id": 0, "data_hash": "h1"}, {"id": 1, "data_hash": "h2"}],
    "errors": False,
}


# ---------------------------------------------------------------------------
# admin_bulk_inventory_update
# ---------------------------------------------------------------------------


class TestBulkInventoryUpdate:
    async def test_requires_confirmation(self, mock_env: None) -> None:
        result = await admin_bulk_inventory_update(
            items=[{"sku": "SKU-A", "quantity": 100}]
        )
        assert result["confirmation_required"] is True

    async def test_empty_items_raises(self, mock_env: None) -> None:
        with pytest.raises(ValueError):
            await admin_bulk_inventory_update(items=[], confirm=True)

    async def test_returns_bulk_uuid(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.post(
            f"{BASE_URL}/rest/{STORE_CODE}/async/bulk/V1/inventory/source-items"
        ).mock(return_value=Response(200, json=_BULK_RESPONSE))

        result = await admin_bulk_inventory_update(
            items=[
                {"sku": "SKU-A", "quantity": 100},
                {"sku": "SKU-B", "quantity": 50, "source_code": "warehouse-1"},
            ],
            confirm=True,
        )
        assert result["success"] is True
        assert result["bulk_uuid"] == "abc-123-def-456"
        assert result["item_count"] == 2
        assert result["operation_count"] == 2

    async def test_payload_structure(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.post(
            f"{BASE_URL}/rest/{STORE_CODE}/async/bulk/V1/inventory/source-items"
        ).mock(return_value=Response(200, json=_BULK_RESPONSE))

        await admin_bulk_inventory_update(
            items=[{"sku": "SKU-A", "quantity": 75, "source_code": "wh1"}],
            confirm=True,
        )
        payload = json.loads(respx_mock.calls.last.request.content)
        assert isinstance(payload, list)
        item = payload[0]["sourceItems"][0]
        assert item["sku"] == "SKU-A"
        assert item["quantity"] == 75.0
        assert item["source_code"] == "wh1"
        assert item["status"] == 1

    async def test_default_source_code_and_status(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.post(
            f"{BASE_URL}/rest/{STORE_CODE}/async/bulk/V1/inventory/source-items"
        ).mock(return_value=Response(200, json=_BULK_RESPONSE))

        await admin_bulk_inventory_update(
            items=[{"sku": "SKU-X", "quantity": 10}],
            confirm=True,
        )
        payload = json.loads(respx_mock.calls.last.request.content)
        item = payload[0]["sourceItems"][0]
        assert item["source_code"] == "default"
        assert item["status"] == 1

    async def test_idempotency_key_replays(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.post(
            f"{BASE_URL}/rest/{STORE_CODE}/async/bulk/V1/inventory/source-items"
        ).mock(return_value=Response(200, json=_BULK_RESPONSE))

        result = await admin_bulk_inventory_update(
            items=[{"sku": "SKU-INV", "quantity": 10}],
            confirm=True,
            idempotency_key="bulk-inv-idem-001",
        )
        assert result["success"] is True

        result2 = await admin_bulk_inventory_update(
            items=[{"sku": "SKU-INV", "quantity": 10}],
            confirm=True,
            idempotency_key="bulk-inv-idem-001",
        )
        assert result2.get("idempotent_replay") is True


# ---------------------------------------------------------------------------
# admin_bulk_catalog_update
# ---------------------------------------------------------------------------


class TestBulkCatalogUpdate:
    async def test_requires_confirmation(self, mock_env: None) -> None:
        result = await admin_bulk_catalog_update(
            products=[{"sku": "SKU-A", "price": 29.99}]
        )
        assert result["confirmation_required"] is True

    async def test_empty_products_raises(self, mock_env: None) -> None:
        with pytest.raises(ValueError):
            await admin_bulk_catalog_update(products=[], confirm=True)

    async def test_returns_bulk_uuid(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.post(
            f"{BASE_URL}/rest/{STORE_CODE}/async/bulk/V1/products"
        ).mock(return_value=Response(200, json=_BULK_RESPONSE))

        result = await admin_bulk_catalog_update(
            products=[
                {"sku": "SKU-A", "price": 29.99},
                {"sku": "SKU-B", "name": "New Name"},
            ],
            confirm=True,
        )
        assert result["success"] is True
        assert result["bulk_uuid"] == "abc-123-def-456"
        assert result["product_count"] == 2

    async def test_payload_wrapped_in_product_key(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.post(
            f"{BASE_URL}/rest/{STORE_CODE}/async/bulk/V1/products"
        ).mock(return_value=Response(200, json=_BULK_RESPONSE))

        await admin_bulk_catalog_update(
            products=[{"sku": "SKU-A", "price": 9.99, "status": 1}],
            confirm=True,
        )
        payload = json.loads(respx_mock.calls.last.request.content)
        assert isinstance(payload, list)
        assert payload[0]["product"]["sku"] == "SKU-A"
        assert payload[0]["product"]["price"] == 9.99

    async def test_idempotency_key_replays(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.post(
            f"{BASE_URL}/rest/{STORE_CODE}/async/bulk/V1/products"
        ).mock(return_value=Response(200, json=_BULK_RESPONSE))

        result = await admin_bulk_catalog_update(
            products=[{"sku": "SKU-CAT", "price": 5.0}],
            confirm=True,
            idempotency_key="bulk-cat-idem-001",
        )
        assert result["success"] is True

        result2 = await admin_bulk_catalog_update(
            products=[{"sku": "SKU-CAT", "price": 5.0}],
            confirm=True,
            idempotency_key="bulk-cat-idem-001",
        )
        assert result2.get("idempotent_replay") is True


# ---------------------------------------------------------------------------
# admin_get_bulk_status
# ---------------------------------------------------------------------------


class TestGetBulkStatus:
    async def test_returns_status_counts(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(
            f"{BASE_URL}/rest/{STORE_CODE}/V1/bulk/abc-123/status"
        ).mock(return_value=Response(200, json={
            "bulk_uuid": "abc-123",
            "start_time": "2025-01-01 10:00:00",
            "operation_count": 3,
            "operations_list": [
                {"id": 0, "status": 1, "result_message": "OK"},
                {"id": 1, "status": 1, "result_message": "OK"},
                {"id": 2, "status": 4, "result_message": "Failed"},
            ],
        }))
        result = await admin_get_bulk_status(bulk_uuid="abc-123")
        assert result["bulk_uuid"] == "abc-123"
        assert result["operation_count"] == 3
        assert result["complete"] == 2
        assert result["failed"] == 1
        assert result["open"] == 0

    async def test_open_operations(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        """Operations still pending have status=5."""
        respx_mock.get(
            f"{BASE_URL}/rest/{STORE_CODE}/V1/bulk/pending-uuid/status"
        ).mock(return_value=Response(200, json={
            "bulk_uuid": "pending-uuid",
            "operation_count": 2,
            "operations_list": [
                {"id": 0, "status": 5, "result_message": None},
                {"id": 1, "status": 5, "result_message": None},
            ],
        }))
        result = await admin_get_bulk_status(bulk_uuid="pending-uuid")
        assert result["complete"] == 0
        assert result["open"] == 2

    async def test_bulk_uuid_in_url(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(
            f"{BASE_URL}/rest/{STORE_CODE}/V1/bulk/my-test-uuid/status"
        ).mock(return_value=Response(200, json={
            "bulk_uuid": "my-test-uuid",
            "operations_list": [],
        }))
        await admin_get_bulk_status(bulk_uuid="my-test-uuid")
        url = str(respx_mock.calls.last.request.url)
        assert "my-test-uuid" in url

    async def test_operations_list_in_response(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(
            f"{BASE_URL}/rest/{STORE_CODE}/V1/bulk/uuid-ops/status"
        ).mock(return_value=Response(200, json={
            "bulk_uuid": "uuid-ops",
            "operations_list": [
                {"id": 0, "status": 1, "result_message": "Done"},
            ],
        }))
        result = await admin_get_bulk_status(bulk_uuid="uuid-ops")
        assert len(result["operations"]) == 1
        assert result["operations"][0]["id"] == 0
        assert result["operations"][0]["status"] == 1

    async def test_tools_are_registered(self) -> None:
        from magemcp.server import mcp
        tool_names = [t.name for t in await mcp.list_tools()]
        assert "admin_bulk_inventory_update" in tool_names
        assert "admin_bulk_catalog_update" in tool_names
        assert "admin_get_bulk_status" in tool_names
