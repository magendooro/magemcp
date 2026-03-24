"""Tests for admin_get_analytics tool."""

from __future__ import annotations

from typing import Any

import pytest
import respx
from httpx import Response

from magemcp.tools.admin.analytics import (
    _calc_aov,
    _calc_order_count,
    _calc_revenue,
    _calc_top_products,
    _date_bucket,
    admin_get_analytics,
)

BASE_URL = "https://magento.test"
STORE_CODE = "default"
TOKEN = "admin-token-123"


@pytest.fixture
def mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAGENTO_BASE_URL", BASE_URL)
    monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", TOKEN)


def _make_order(
    increment_id: str = "000000001",
    grand_total: float = 100.0,
    status: str = "complete",
    created_at: str = "2025-03-01 10:00:00",
    currency: str = "USD",
    items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "increment_id": increment_id,
        "grand_total": grand_total,
        "status": status,
        "created_at": created_at,
        "order_currency_code": currency,
        "items": items or [],
    }


def _wrap_search(items: list[dict[str, Any]], total: int | None = None) -> dict[str, Any]:
    return {"items": items, "total_count": total if total is not None else len(items)}


# ---------------------------------------------------------------------------
# Unit tests for aggregation helpers
# ---------------------------------------------------------------------------


class TestDateBucket:
    def test_day(self) -> None:
        assert _date_bucket("2025-03-15 10:30:00", "day") == "2025-03-15"

    def test_month(self) -> None:
        assert _date_bucket("2025-03-15 10:30:00", "month") == "2025-03"

    def test_week(self) -> None:
        # 2025-03-17 is Monday of week 12
        result = _date_bucket("2025-03-17 00:00:00", "week")
        assert result.startswith("2025-W")

    def test_empty_date(self) -> None:
        assert _date_bucket("", "day") == "unknown"

    def test_unknown_group_by_returns_date_part(self) -> None:
        # fallback branch: unknown group_by returns YYYY-MM-DD date_part
        assert _date_bucket("2025-03-15 10:30:00", "unknown_granularity") == "2025-03-15"


class TestCalcOrderCount:
    def test_no_group_by(self) -> None:
        orders = [_make_order(), _make_order("2")]
        result = _calc_order_count(orders, None)
        assert result["metric"] == "order_count"
        assert result["value"] == 2

    def test_group_by_status(self) -> None:
        orders = [
            _make_order(status="complete"),
            _make_order(status="complete"),
            _make_order(status="pending"),
        ]
        result = _calc_order_count(orders, "status")
        assert result["breakdown"]["complete"] == 2
        assert result["breakdown"]["pending"] == 1

    def test_group_by_month(self) -> None:
        orders = [
            _make_order(created_at="2025-01-15 00:00:00"),
            _make_order(created_at="2025-01-20 00:00:00"),
            _make_order(created_at="2025-02-01 00:00:00"),
        ]
        result = _calc_order_count(orders, "month")
        assert result["breakdown"]["2025-01"] == 2
        assert result["breakdown"]["2025-02"] == 1


class TestCalcRevenue:
    def test_total_revenue(self) -> None:
        orders = [_make_order(grand_total=100.0), _make_order(grand_total=200.5)]
        result = _calc_revenue(orders, None)
        assert result["metric"] == "revenue"
        assert result["value"] == 300.5
        assert result["currency"] == "USD"

    def test_empty_orders(self) -> None:
        result = _calc_revenue([], None)
        assert result["value"] == 0

    def test_group_by_status(self) -> None:
        orders = [
            _make_order(grand_total=100.0, status="complete"),
            _make_order(grand_total=50.0, status="complete"),
            _make_order(grand_total=200.0, status="pending"),
        ]
        result = _calc_revenue(orders, "status")
        assert result["breakdown"]["complete"] == 150.0
        assert result["breakdown"]["pending"] == 200.0


class TestCalcAov:
    def test_aov(self) -> None:
        orders = [_make_order(grand_total=100.0), _make_order(grand_total=200.0)]
        result = _calc_aov(orders)
        assert result["metric"] == "average_order_value"
        assert result["value"] == 150.0
        assert result["order_count"] == 2

    def test_empty(self) -> None:
        result = _calc_aov([])
        assert result["value"] == 0
        assert result["order_count"] == 0


class TestCalcTopProducts:
    def test_top_products(self) -> None:
        items_a = [
            {"sku": "SKU-A", "name": "Widget A", "qty_ordered": 5, "row_total": 50.0},
            {"sku": "SKU-B", "name": "Widget B", "qty_ordered": 2, "row_total": 40.0},
        ]
        items_b = [
            {"sku": "SKU-A", "name": "Widget A", "qty_ordered": 3, "row_total": 30.0},
        ]
        orders = [_make_order(items=items_a), _make_order(items=items_b)]
        result = _calc_top_products(orders)
        assert result["metric"] == "top_products"
        products = result["products"]
        assert products[0]["sku"] == "SKU-A"
        assert products[0]["qty_ordered"] == 8

    def test_skips_child_items(self) -> None:
        items = [
            {"sku": "PARENT", "qty_ordered": 1, "row_total": 100.0},
            {"sku": "CHILD", "qty_ordered": 1, "row_total": 0.0, "parent_item_id": 1},
        ]
        result = _calc_top_products([_make_order(items=items)])
        skus = [p["sku"] for p in result["products"]]
        assert "CHILD" not in skus


# ---------------------------------------------------------------------------
# Tool end-to-end (mocked REST)
# ---------------------------------------------------------------------------


class TestAdminGetAnalytics:
    async def test_order_count_basic(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        orders = [_make_order("1"), _make_order("2"), _make_order("3")]
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/orders").mock(
            return_value=Response(200, json=_wrap_search(orders))
        )
        result = await admin_get_analytics(metric="order_count")
        assert result["metric"] == "order_count"
        assert result["value"] == 3

    async def test_revenue_metric(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        orders = [_make_order(grand_total=100.0), _make_order(grand_total=250.0)]
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/orders").mock(
            return_value=Response(200, json=_wrap_search(orders))
        )
        result = await admin_get_analytics(metric="revenue")
        assert result["metric"] == "revenue"
        assert result["value"] == 350.0

    async def test_invalid_metric_raises(self, mock_env: None) -> None:
        with pytest.raises(ValueError, match="Invalid metric"):
            await admin_get_analytics(metric="bad_metric")

    async def test_invalid_group_by_raises(self, mock_env: None) -> None:
        with pytest.raises(ValueError, match="Invalid group_by"):
            await admin_get_analytics(metric="order_count", group_by="quarter")

    async def test_date_range_passed_to_api(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/orders").mock(
            return_value=Response(200, json=_wrap_search([]))
        )
        result = await admin_get_analytics(
            metric="order_count",
            from_date="2025-01-01",
            to_date="2025-01-31",
        )
        url = str(respx_mock.calls.last.request.url)
        assert "created_at" in url
        assert result["from_date"] == "2025-01-01"
        assert result["to_date"] == "2025-01-31"

    async def test_natural_language_date(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/orders").mock(
            return_value=Response(200, json=_wrap_search([]))
        )
        result = await admin_get_analytics(metric="order_count", from_date="today")
        from datetime import date
        assert result["from_date"] == date.today().isoformat()

    async def test_pagination_fetches_all(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        """When total_count > page, tool makes multiple requests."""
        page1 = _wrap_search([_make_order(str(i)) for i in range(100)], total=150)
        page2 = _wrap_search([_make_order(str(i)) for i in range(100, 150)], total=150)
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/orders").mock(
            side_effect=[Response(200, json=page1), Response(200, json=page2)]
        )
        result = await admin_get_analytics(metric="order_count")
        assert result["order_count_fetched"] == 150
        assert result["value"] == 150

    async def test_is_registered(self) -> None:
        from magemcp.server import mcp
        tool_names = [t.name for t in await mcp.list_tools()]
        assert "admin_get_analytics" in tool_names

    async def test_aov_metric(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        orders = [_make_order(grand_total=100.0), _make_order(grand_total=200.0)]
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/orders").mock(
            return_value=Response(200, json=_wrap_search(orders))
        )
        result = await admin_get_analytics(metric="average_order_value")
        assert result["metric"] == "average_order_value"
        assert result["value"] == 150.0

    async def test_top_products_metric(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        orders = [_make_order(items=[
            {"sku": "SKU1", "name": "Product 1", "qty_ordered": 2, "parent_item_id": None},
        ])]
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/orders").mock(
            return_value=Response(200, json=_wrap_search(orders))
        )
        result = await admin_get_analytics(metric="top_products")
        assert result["metric"] == "top_products"
        assert len(result["products"]) >= 1

    async def test_status_filter_applied(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        route = respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/orders").mock(
            return_value=Response(200, json=_wrap_search([]))
        )
        await admin_get_analytics(metric="order_count", status_filter="complete")
        url = str(route.calls[0].request.url)
        assert "status" in url
        assert "complete" in url
