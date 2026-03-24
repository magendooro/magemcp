"""Tests for admin_get_order_tracking tool."""

from __future__ import annotations

from typing import Any

import pytest
import respx
from httpx import Response

from magemcp.tools.admin.order_tracking import admin_get_order_tracking

BASE_URL = "https://magento.test"
TOKEN = "admin-token-123"
STORE_CODE = "default"


@pytest.fixture
def mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAGENTO_BASE_URL", BASE_URL)
    monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("MAGENTO_STORE_CODE", STORE_CODE)


def _make_shipment(
    *,
    entity_id: int = 1,
    increment_id: str = "100000001",
    order_id: int = 42,
    tracks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "entity_id": entity_id,
        "increment_id": increment_id,
        "order_id": order_id,
        "created_at": "2025-01-01 10:00:00",
        "total_qty": 1,
        "tracks": tracks or [],
        "items": [],
    }


def _wrap_search(items: list[dict[str, Any]], total: int | None = None) -> dict[str, Any]:
    return {"items": items, "total_count": total if total is not None else len(items)}


class TestAdminGetOrderTracking:
    async def test_returns_tracking_numbers(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        shipments = [_make_shipment(tracks=[{
            "track_number": "1Z999AA10123456784",
            "carrier_code": "ups",
            "title": "UPS Ground",
            "created_at": "2025-01-01",
        }])]
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/shipments").mock(
            return_value=Response(200, json=_wrap_search(shipments))
        )
        result = await admin_get_order_tracking(order_id=42)
        assert result["order_id"] == 42
        assert result["shipment_count"] == 1
        assert len(result["tracking"]) == 1
        t = result["tracking"][0]
        assert t["track_number"] == "1Z999AA10123456784"
        assert t["carrier_code"] == "ups"
        assert t["shipment_id"] == 1

    async def test_no_shipments(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/shipments").mock(
            return_value=Response(200, json=_wrap_search([]))
        )
        result = await admin_get_order_tracking(order_id=99)
        assert result["shipment_count"] == 0
        assert result["tracking"] == []

    async def test_multiple_shipments_aggregated(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        shipments = [
            _make_shipment(entity_id=1, increment_id="S001", tracks=[
                {"track_number": "TRACK1", "carrier_code": "fedex", "title": "FedEx", "created_at": "2025-01-01"},
            ]),
            _make_shipment(entity_id=2, increment_id="S002", tracks=[
                {"track_number": "TRACK2", "carrier_code": "ups", "title": "UPS", "created_at": "2025-01-02"},
            ]),
        ]
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/shipments").mock(
            return_value=Response(200, json=_wrap_search(shipments))
        )
        result = await admin_get_order_tracking(order_id=42)
        assert result["shipment_count"] == 2
        assert len(result["tracking"]) == 2
        track_numbers = [t["track_number"] for t in result["tracking"]]
        assert "TRACK1" in track_numbers
        assert "TRACK2" in track_numbers

    async def test_shipment_with_no_tracks(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        """Shipment with empty tracks list contributes nothing to tracking."""
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/shipments").mock(
            return_value=Response(200, json=_wrap_search([_make_shipment(tracks=[])]))
        )
        result = await admin_get_order_tracking(order_id=42)
        assert result["shipment_count"] == 1
        assert result["tracking"] == []

    async def test_order_id_in_url(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/shipments").mock(
            return_value=Response(200, json=_wrap_search([]))
        )
        await admin_get_order_tracking(order_id=42)
        url = str(respx_mock.calls.last.request.url)
        assert "order_id" in url
        assert "42" in url

    async def test_is_registered(self) -> None:
        from magemcp.server import mcp
        tool_names = [t.name for t in await mcp.list_tools()]
        assert "admin_get_order_tracking" in tool_names
