"""Tests for admin return / RMA read tools."""

from __future__ import annotations

from typing import Any

import pytest
import respx
from httpx import Response

from magemcp.connectors.errors import MagentoNotFoundError
from magemcp.tools.admin.returns import admin_search_returns, admin_get_return

BASE_URL = "https://magento.test"
STORE_CODE = "default"
TOKEN = "admin-token-123"


@pytest.fixture
def mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAGENTO_BASE_URL", BASE_URL)
    monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", TOKEN)


def _make_return(entity_id: int = 1, order_id: int = 100) -> dict[str, Any]:
    return {
        "entity_id": entity_id,
        "increment_id": f"RMA-{entity_id:06d}",
        "order_id": order_id,
        "store_id": 1,
        "date_requested": "2025-03-01 10:00:00",
        "status": "pending",
        "customer_id": 42,
        "customer_name": "Jane Doe",
        "items": [
            {
                "entity_id": 10,
                "order_item_id": 99,
                "qty_requested": 1,
                "qty_authorized": None,
                "qty_approved": None,
                "qty_returned": None,
                "reason_id": 1,
                "condition_id": 1,
                "resolution_id": 1,
            }
        ],
        "comments": [
            {
                "entity_id": 5,
                "comment": "Customer wants refund",
                "is_admin": False,
                "created_at": "2025-03-01 10:00:00",
            }
        ],
    }


class TestAdminSearchReturns:
    async def test_search_by_order_id(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/returns").mock(
            return_value=Response(200, json={"items": [_make_return(1, 100)], "total_count": 1})
        )
        result = await admin_search_returns(order_id=100)
        assert result["total_count"] == 1
        assert result["returns"][0]["order_id"] == 100

    async def test_search_by_status(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/returns").mock(
            return_value=Response(200, json={"items": [_make_return()], "total_count": 1})
        )
        result = await admin_search_returns(status="pending")
        assert result["returns"][0]["status"] == "pending"

    async def test_summary_includes_items_count(
        self, mock_env: None, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/returns").mock(
            return_value=Response(200, json={"items": [_make_return()], "total_count": 1})
        )
        result = await admin_search_returns()
        # Summary should show items_count, not full items list
        assert result["returns"][0]["items_count"] == 1
        assert "items" not in result["returns"][0]

    async def test_pagination(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/returns").mock(
            return_value=Response(200, json={"items": [], "total_count": 100})
        )
        result = await admin_search_returns(page_size=10, current_page=2)
        assert result["page_size"] == 10
        assert result["current_page"] == 2
        assert result["total_count"] == 100


class TestAdminGetReturn:
    async def test_returns_full_detail(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/returns/1").mock(
            return_value=Response(200, json=_make_return(1, 100))
        )
        result = await admin_get_return(return_id=1)
        assert result["entity_id"] == 1
        assert result["order_id"] == 100
        assert len(result["items"]) == 1
        assert len(result["comments"]) == 1

    async def test_not_found_raises(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/returns/999").mock(
            return_value=Response(200, json={})
        )
        with pytest.raises(MagentoNotFoundError):
            await admin_get_return(return_id=999)

    async def test_item_fields(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/returns/1").mock(
            return_value=Response(200, json=_make_return(1))
        )
        result = await admin_get_return(return_id=1)
        item = result["items"][0]
        assert item["qty_requested"] == 1
        assert item["order_item_id"] == 99

    async def test_comment_fields(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/returns/1").mock(
            return_value=Response(200, json=_make_return(1))
        )
        result = await admin_get_return(return_id=1)
        comment = result["comments"][0]
        assert comment["comment"] == "Customer wants refund"
        assert comment["is_admin"] is False

    async def test_is_registered(self) -> None:
        from magemcp.server import mcp

        tool_names = [t.name for t in await mcp.list_tools()]
        assert "admin_search_returns" in tool_names
        assert "admin_get_return" in tool_names
