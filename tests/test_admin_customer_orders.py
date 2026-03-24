"""Tests for admin_get_customer_orders tool."""

from __future__ import annotations

from typing import Any

import pytest
import respx
from httpx import Response

from magemcp.tools.admin.customer_orders import register_customer_orders

BASE_URL = "https://magento.test"
STORE_CODE = "default"
TOKEN = "admin-token-123"


@pytest.fixture
def mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAGENTO_BASE_URL", BASE_URL)
    monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", TOKEN)


def _make_order(increment_id: str = "000000001", customer_id: int = 42) -> dict[str, Any]:
    return {
        "increment_id": increment_id,
        "customer_id": customer_id,
        "customer_email": "customer@example.com",
        "customer_firstname": "Jane",
        "customer_lastname": "Doe",
        "state": "complete",
        "status": "complete",
        "grand_total": 99.0,
        "order_currency_code": "USD",
        "total_qty_ordered": 2,
        "created_at": "2025-03-01 10:00:00",
        "items": [],
    }


def _wrap(items: list[dict], total: int | None = None) -> dict[str, Any]:
    return {"items": items, "total_count": total if total is not None else len(items)}


class TestAdminGetCustomerOrders:
    async def test_by_customer_id(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        orders = [_make_order("1"), _make_order("2")]
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/orders").mock(
            return_value=Response(200, json=_wrap(orders))
        )

        from magemcp.tools.admin.customer_orders import admin_get_customer_orders

        result = await admin_get_customer_orders(customer_id=42)
        assert result["customer_id"] == 42
        assert len(result["orders"]) == 2
        assert result["total_count"] == 2

    async def test_by_email(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        orders = [_make_order("3")]
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/orders").mock(
            return_value=Response(200, json=_wrap(orders))
        )

        from magemcp.tools.admin.customer_orders import admin_get_customer_orders

        result = await admin_get_customer_orders(email="customer@example.com")
        assert result["email"] == "customer@example.com"
        assert len(result["orders"]) == 1

    async def test_neither_raises(self, mock_env: None) -> None:
        from magemcp.tools.admin.customer_orders import admin_get_customer_orders

        with pytest.raises(ValueError, match="customer_id or email"):
            await admin_get_customer_orders()

    async def test_customer_id_filter_in_query(
        self, mock_env: None, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/orders").mock(
            return_value=Response(200, json=_wrap([]))
        )

        from magemcp.tools.admin.customer_orders import admin_get_customer_orders

        await admin_get_customer_orders(customer_id=99)
        url = str(respx_mock.calls.last.request.url)
        assert "customer_id" in url
        assert "99" in url

    async def test_pagination_returned(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        orders = [_make_order(str(i)) for i in range(5)]
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/orders").mock(
            return_value=Response(200, json=_wrap(orders, total=25))
        )

        from magemcp.tools.admin.customer_orders import admin_get_customer_orders

        result = await admin_get_customer_orders(customer_id=1, page_size=5, current_page=2)
        assert result["total_count"] == 25
        assert result["page_size"] == 5
        assert result["current_page"] == 2

    async def test_order_summary_fields(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/orders").mock(
            return_value=Response(200, json=_wrap([_make_order("100")]))
        )

        from magemcp.tools.admin.customer_orders import admin_get_customer_orders

        result = await admin_get_customer_orders(customer_id=42)
        order = result["orders"][0]
        assert order["increment_id"] == "100"
        assert order["status"] == "complete"
        assert order["grand_total"] == 99.0
        assert order["customer_name"] == "Jane Doe"

    async def test_is_registered(self) -> None:
        from magemcp.server import mcp

        tool_names = [t.name for t in await mcp.list_tools()]
        assert "admin_get_customer_orders" in tool_names
