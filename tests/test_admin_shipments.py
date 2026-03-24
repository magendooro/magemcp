"""Tests for admin shipment read tools."""

from __future__ import annotations

from typing import Any

import pytest
import respx
from httpx import Response

from magemcp.connectors.errors import MagentoNotFoundError
from magemcp.tools.admin.shipments import admin_get_shipment, admin_search_shipments

BASE_URL = "https://magento.test"
STORE_CODE = "default"
TOKEN = "admin-token-123"


@pytest.fixture
def mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAGENTO_BASE_URL", BASE_URL)
    monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", TOKEN)


def _make_shipment(entity_id: int = 1, order_id: int = 100) -> dict[str, Any]:
    return {
        "entity_id": entity_id,
        "increment_id": f"SHIP-{entity_id:06d}",
        "order_id": order_id,
        "created_at": "2025-03-01 10:00:00",
        "updated_at": "2025-03-01 10:01:00",
        "total_qty": 2.0,
        "tracks": [
            {
                "track_number": "1Z999AA10123456784",
                "carrier_code": "ups",
                "title": "UPS Ground",
                "created_at": "2025-03-01 10:00:00",
            }
        ],
        "items": [
            {"sku": "SKU-1", "name": "Widget", "qty": 2.0, "price": 50.0}
        ],
    }


class TestAdminGetShipment:
    async def test_returns_shipment(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/shipments/1").mock(
            return_value=Response(200, json=_make_shipment(1, 100))
        )
        result = await admin_get_shipment(shipment_id=1)
        assert result["entity_id"] == 1
        assert result["order_id"] == 100
        assert len(result["tracks"]) == 1
        assert result["tracks"][0]["track_number"] == "1Z999AA10123456784"

    async def test_not_found_raises(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/shipments/999").mock(
            return_value=Response(200, json={})
        )
        with pytest.raises(MagentoNotFoundError):
            await admin_get_shipment(shipment_id=999)

    async def test_items_in_detail(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/shipments/2").mock(
            return_value=Response(200, json=_make_shipment(2))
        )
        result = await admin_get_shipment(shipment_id=2)
        assert len(result["items"]) == 1
        assert result["items"][0]["sku"] == "SKU-1"


class TestAdminSearchShipments:
    async def test_search_by_order_id(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/shipments").mock(
            return_value=Response(200, json={"items": [_make_shipment(1, 100)], "total_count": 1})
        )
        result = await admin_search_shipments(order_id=100)
        assert result["total_count"] == 1
        assert result["shipments"][0]["order_id"] == 100

    async def test_summary_no_items(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/shipments").mock(
            return_value=Response(200, json={"items": [_make_shipment(1)], "total_count": 1})
        )
        result = await admin_search_shipments()
        # Summary should not include detailed items list
        assert "items" not in result["shipments"][0]
        # But tracks should be included
        assert "tracks" in result["shipments"][0]

    async def test_order_id_in_query(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/shipments").mock(
            return_value=Response(200, json={"items": [], "total_count": 0})
        )
        await admin_search_shipments(order_id=55)
        url = str(respx_mock.calls.last.request.url)
        assert "order_id" in url

    async def test_is_registered(self) -> None:
        from magemcp.server import mcp

        tool_names = [t.name for t in await mcp.list_tools()]
        assert "admin_get_shipment" in tool_names
        assert "admin_search_shipments" in tool_names
