"""Tests for admin_update_inventory tool."""

from __future__ import annotations

import json

import pytest
import respx
from httpx import Response

BASE_URL = "https://magento.test"
TOKEN = "admin-token-123"
STORE_CODE = "default"


@pytest.fixture
def mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAGENTO_BASE_URL", BASE_URL)
    monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("MAGENTO_STORE_CODE", STORE_CODE)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestUpdateInventory:
    async def test_requires_confirmation(self, mock_env: None) -> None:
        """Update requires confirm=True — inventory change is destructive."""
        from magemcp.tools.admin.update_inventory import admin_update_inventory
        result = await admin_update_inventory(sku="TEST-SKU", quantity=10.0)
        assert result["confirmation_required"] is True
        assert "TEST-SKU" in result["message"]

    async def test_payload_structure(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        """Verify the sourceItems payload matches Magento MSI schema."""
        respx_mock.post(f"{BASE_URL}/rest/{STORE_CODE}/V1/inventory/source-items").mock(
            return_value=Response(200, json=True)
        )

        from magemcp.tools.admin.update_inventory import admin_update_inventory
        await admin_update_inventory(
            sku="TEST-SKU",
            quantity=25.0,
            source_code="warehouse_east",
            status=1,
            confirm=True,
        )

        request = respx_mock.calls.last.request
        payload = json.loads(request.content)

        assert "sourceItems" in payload
        assert len(payload["sourceItems"]) == 1
        item = payload["sourceItems"][0]
        assert item["sku"] == "TEST-SKU"
        assert item["quantity"] == 25.0
        assert item["source_code"] == "warehouse_east"
        assert item["status"] == 1

    async def test_returns_success(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        """Verify success response structure."""
        respx_mock.post(f"{BASE_URL}/rest/{STORE_CODE}/V1/inventory/source-items").mock(
            return_value=Response(200, json=True)
        )

        from magemcp.tools.admin.update_inventory import admin_update_inventory
        result = await admin_update_inventory(
            sku="PROD-001",
            quantity=50.0,
            confirm=True,
        )

        assert result["success"] is True
        assert result["sku"] == "PROD-001"
        assert result["quantity"] == 50.0
        assert result["source_code"] == "default"

    async def test_default_source_code(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        """source_code defaults to 'default'."""
        respx_mock.post(f"{BASE_URL}/rest/{STORE_CODE}/V1/inventory/source-items").mock(
            return_value=Response(200, json=True)
        )

        from magemcp.tools.admin.update_inventory import admin_update_inventory
        await admin_update_inventory(sku="SKU-X", quantity=5.0, confirm=True)

        request = respx_mock.calls.last.request
        payload = json.loads(request.content)
        assert payload["sourceItems"][0]["source_code"] == "default"

    async def test_skip_confirmation_env(self, mock_env: None, respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch) -> None:
        """MAGEMCP_SKIP_CONFIRMATION bypasses confirmation."""
        monkeypatch.setenv("MAGEMCP_SKIP_CONFIRMATION", "true")
        respx_mock.post(f"{BASE_URL}/rest/{STORE_CODE}/V1/inventory/source-items").mock(
            return_value=Response(200, json=True)
        )

        from magemcp.tools.admin.update_inventory import admin_update_inventory
        result = await admin_update_inventory(sku="SKU-Y", quantity=0.0)
        assert result["success"] is True
