"""Tests for admin invoice and credit memo read tools."""

from __future__ import annotations

from typing import Any

import pytest
import respx
from httpx import Response

from magemcp.connectors.errors import MagentoNotFoundError
from magemcp.tools.admin.invoices import (
    admin_get_invoice,
    admin_search_invoices,
    admin_get_credit_memo,
)

BASE_URL = "https://magento.test"
STORE_CODE = "default"
TOKEN = "admin-token-123"


@pytest.fixture
def mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAGENTO_BASE_URL", BASE_URL)
    monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", TOKEN)


def _make_invoice(entity_id: int = 1, order_id: int = 100) -> dict[str, Any]:
    return {
        "entity_id": entity_id,
        "increment_id": f"INV-{entity_id:06d}",
        "order_id": order_id,
        "state": 2,
        "grand_total": 120.0,
        "subtotal": 100.0,
        "tax_amount": 20.0,
        "base_currency_code": "USD",
        "total_qty": 2.0,
        "created_at": "2025-03-01 10:00:00",
        "updated_at": "2025-03-01 10:01:00",
        "items": [
            {"sku": "SKU-1", "name": "Widget", "qty": 2.0, "price": 50.0, "row_total": 100.0}
        ],
    }


def _make_creditmemo(entity_id: int = 1, order_id: int = 100) -> dict[str, Any]:
    return {
        "entity_id": entity_id,
        "increment_id": f"CM-{entity_id:06d}",
        "order_id": order_id,
        "invoice_id": 5,
        "state": 2,
        "grand_total": 50.0,
        "subtotal": 45.0,
        "tax_amount": 5.0,
        "shipping_amount": 0.0,
        "adjustment": 0.0,
        "base_currency_code": "USD",
        "created_at": "2025-03-02 10:00:00",
        "items": [
            {"sku": "SKU-1", "name": "Widget", "qty": 1.0, "price": 50.0, "row_total": 50.0}
        ],
    }


class TestAdminGetInvoice:
    async def test_returns_invoice(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/invoices/1").mock(
            return_value=Response(200, json=_make_invoice(1, 100))
        )
        result = await admin_get_invoice(invoice_id=1)
        assert result["entity_id"] == 1
        assert result["order_id"] == 100
        assert result["grand_total"] == 120.0
        assert len(result["items"]) == 1

    async def test_not_found_raises(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/invoices/999").mock(
            return_value=Response(200, json={})
        )
        with pytest.raises(MagentoNotFoundError):
            await admin_get_invoice(invoice_id=999)

    async def test_item_fields(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/invoices/2").mock(
            return_value=Response(200, json=_make_invoice(2))
        )
        result = await admin_get_invoice(invoice_id=2)
        item = result["items"][0]
        assert item["sku"] == "SKU-1"
        assert item["qty"] == 2.0
        assert item["row_total"] == 100.0


class TestAdminSearchInvoices:
    async def test_search_by_order_id(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/invoices").mock(
            return_value=Response(200, json={"items": [_make_invoice(1, 100)], "total_count": 1})
        )
        result = await admin_search_invoices(order_id=100)
        assert result["total_count"] == 1
        assert result["invoices"][0]["order_id"] == 100

    async def test_search_returns_summary(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        invoices = [_make_invoice(i) for i in range(3)]
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/invoices").mock(
            return_value=Response(200, json={"items": invoices, "total_count": 3})
        )
        result = await admin_search_invoices()
        assert len(result["invoices"]) == 3
        # Summary should not include items list
        assert "items" not in result["invoices"][0]

    async def test_pagination(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/invoices").mock(
            return_value=Response(200, json={"items": [], "total_count": 50})
        )
        result = await admin_search_invoices(page_size=10, current_page=3)
        assert result["page_size"] == 10
        assert result["current_page"] == 3
        assert result["total_count"] == 50


class TestAdminGetCreditMemo:
    async def test_returns_creditmemo(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/creditmemos/1").mock(
            return_value=Response(200, json=_make_creditmemo(1, 100))
        )
        result = await admin_get_credit_memo(creditmemo_id=1)
        assert result["entity_id"] == 1
        assert result["order_id"] == 100
        assert result["grand_total"] == 50.0
        assert len(result["items"]) == 1

    async def test_not_found_raises(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/creditmemos/999").mock(
            return_value=Response(200, json={})
        )
        with pytest.raises(MagentoNotFoundError):
            await admin_get_credit_memo(creditmemo_id=999)

    async def test_adjustment_field(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        cm = _make_creditmemo(3)
        cm["adjustment"] = 5.0
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/creditmemos/3").mock(
            return_value=Response(200, json=cm)
        )
        result = await admin_get_credit_memo(creditmemo_id=3)
        assert result["adjustment"] == 5.0

    async def test_is_registered(self) -> None:
        from magemcp.server import mcp

        tool_names = [t.name for t in await mcp.list_tools()]
        assert "admin_get_invoice" in tool_names
        assert "admin_search_invoices" in tool_names
        assert "admin_get_credit_memo" in tool_names
