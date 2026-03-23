"""Tests for admin_search_orders tool."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from magemcp.connectors.rest_client import RESTClient
from magemcp.models.order import OrderSummary
from magemcp.tools.admin.search_orders import (
    AdminSearchOrdersInput,
    _build_search_params,
    _parse_order_summary,
)

BASE_URL = "https://magento.test"
TOKEN = "admin-token-123"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_rest_order(
    *,
    increment_id: str = "000000001",
    state: str = "processing",
    status: str = "processing",
    created_at: str = "2025-06-15 10:30:00",
    grand_total: float = 129.99,
    order_currency_code: str = "USD",
    total_qty_ordered: float = 2.0,
    customer_email: str = "jane@example.com",
    customer_firstname: str = "Jane",
    customer_lastname: str = "Doe",
    items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if items is None:
        items = [
            {"sku": "SKU1", "name": "Item 1", "qty_ordered": 1, "price": 100, "row_total": 100, "parent_item_id": None},
            {"sku": "SKU2", "name": "Item 2", "qty_ordered": 1, "price": 29.99, "row_total": 29.99, "parent_item_id": None},
        ]
    return {
        "increment_id": increment_id,
        "state": state,
        "status": status,
        "created_at": created_at,
        "grand_total": grand_total,
        "order_currency_code": order_currency_code,
        "total_qty_ordered": total_qty_ordered,
        "customer_email": customer_email,
        "customer_firstname": customer_firstname,
        "customer_lastname": customer_lastname,
        "items": items,
    }


def _wrap_rest_response(items: list[dict[str, Any]], total_count: int | None = None) -> dict[str, Any]:
    return {
        "items": items,
        "search_criteria": {},
        "total_count": total_count if total_count is not None else len(items),
    }


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_defaults(self) -> None:
        inp = AdminSearchOrdersInput()
        assert inp.status is None
        assert inp.page_size == 20
        assert inp.sort_field == "created_at"
        assert inp.sort_direction == "DESC"
        assert inp.store_scope == "default"

    def test_with_status(self) -> None:
        inp = AdminSearchOrdersInput(status="processing")
        assert inp.status == "processing"

    def test_with_date_range(self) -> None:
        inp = AdminSearchOrdersInput(created_from="2025-01-01", created_to="2025-12-31")
        assert inp.created_from == "2025-01-01"
        assert inp.created_to == "2025-12-31"

    def test_invalid_sort_direction(self) -> None:
        with pytest.raises(Exception):
            AdminSearchOrdersInput(sort_direction="UP")

    def test_invalid_store_scope(self) -> None:
        with pytest.raises(Exception):
            AdminSearchOrdersInput(store_scope="INVALID!")

    def test_page_size_max(self) -> None:
        with pytest.raises(Exception):
            AdminSearchOrdersInput(page_size=101)


# ---------------------------------------------------------------------------
# _build_search_params
# ---------------------------------------------------------------------------


class TestBuildSearchParams:
    def test_no_filters(self) -> None:
        inp = AdminSearchOrdersInput()
        params = _build_search_params(inp)
        assert params["searchCriteria[pageSize]"] == "20"
        assert params["searchCriteria[currentPage]"] == "1"
        assert params["searchCriteria[sortOrders][0][field]"] == "created_at"
        assert params["searchCriteria[sortOrders][0][direction]"] == "DESC"

    def test_status_filter(self) -> None:
        inp = AdminSearchOrdersInput(status="processing")
        params = _build_search_params(inp)
        assert params["searchCriteria[filterGroups][0][filters][0][field]"] == "status"
        assert params["searchCriteria[filterGroups][0][filters][0][value]"] == "processing"

    def test_email_filter(self) -> None:
        inp = AdminSearchOrdersInput(customer_email="jane@example.com")
        params = _build_search_params(inp)
        assert params["searchCriteria[filterGroups][0][filters][0][field]"] == "customer_email"
        assert params["searchCriteria[filterGroups][0][filters][0][value]"] == "jane@example.com"

    def test_date_range_filter(self) -> None:
        inp = AdminSearchOrdersInput(created_from="2025-01-01", created_to="2025-12-31")
        params = _build_search_params(inp)
        # Find created_at gteq and lteq
        gteq_found = False
        lteq_found = False
        for key, val in params.items():
            if "[conditionType]" in key and val == "gteq":
                field_key = key.replace("[conditionType]", "[field]")
                if params.get(field_key) == "created_at":
                    gteq_found = True
            if "[conditionType]" in key and val == "lteq":
                field_key = key.replace("[conditionType]", "[field]")
                if params.get(field_key) == "created_at":
                    lteq_found = True
        assert gteq_found, "created_at gteq filter not found"
        assert lteq_found, "created_at lteq filter not found"

    def test_grand_total_range(self) -> None:
        inp = AdminSearchOrdersInput(grand_total_min=50.0, grand_total_max=200.0)
        params = _build_search_params(inp)
        gteq_found = False
        lteq_found = False
        for key, val in params.items():
            if "[conditionType]" in key and val == "gteq":
                field_key = key.replace("[conditionType]", "[field]")
                if params.get(field_key) == "grand_total":
                    gteq_found = True
            if "[conditionType]" in key and val == "lteq":
                field_key = key.replace("[conditionType]", "[field]")
                if params.get(field_key) == "grand_total":
                    lteq_found = True
        assert gteq_found, "grand_total gteq filter not found"
        assert lteq_found, "grand_total lteq filter not found"

    def test_pagination(self) -> None:
        inp = AdminSearchOrdersInput(page_size=5, current_page=3)
        params = _build_search_params(inp)
        assert params["searchCriteria[pageSize]"] == "5"
        assert params["searchCriteria[currentPage]"] == "3"


# ---------------------------------------------------------------------------
# _parse_order_summary
# ---------------------------------------------------------------------------


class TestParseOrderSummary:
    def test_basic(self) -> None:
        raw = _make_rest_order()
        summary = _parse_order_summary(raw)
        assert summary.increment_id == "000000001"
        assert summary.status == "processing"
        assert summary.grand_total == 129.99
        assert summary.customer_name == "Jane Doe"
        assert summary.customer_email == "jane@example.com"
        assert summary.total_items == 2

    def test_guest_order(self) -> None:
        raw = _make_rest_order(customer_firstname="", customer_lastname="")
        summary = _parse_order_summary(raw)
        assert summary.customer_name == "Guest"

    def test_child_items_not_counted(self) -> None:
        items = [
            {"sku": "PARENT", "name": "Configurable", "qty_ordered": 1, "price": 50, "row_total": 50, "parent_item_id": None},
            {"sku": "CHILD-M", "name": "Configurable - M", "qty_ordered": 1, "price": 50, "row_total": 50, "parent_item_id": 1},
        ]
        raw = _make_rest_order(items=items)
        summary = _parse_order_summary(raw)
        assert summary.total_items == 1

    def test_serialization(self) -> None:
        raw = _make_rest_order()
        summary = _parse_order_summary(raw)
        dumped = summary.model_dump(mode="json")
        assert dumped["increment_id"] == "000000001"
        assert dumped["customer_email"] == "jane@example.com"
        assert dumped["total_items"] == 2


# ---------------------------------------------------------------------------
# End-to-end (mocked REST)
# ---------------------------------------------------------------------------


class TestToolEndToEnd:
    @respx.mock
    async def test_search_returns_summaries(self) -> None:
        """Verify response includes summaries, not full orders."""
        orders = [
            _make_rest_order(increment_id="001", grand_total=100),
            _make_rest_order(increment_id="002", grand_total=200),
        ]
        rest_response = _wrap_rest_response(orders, total_count=2)
        route = respx.get(f"{BASE_URL}/rest/default/V1/orders").mock(
            return_value=httpx.Response(200, json=rest_response),
        )

        async with RESTClient(base_url=BASE_URL, admin_token=TOKEN) as client:
            params = RESTClient.search_params(page_size=5)
            data = await client.get("/V1/orders", params=params)

        assert route.called
        summaries = [_parse_order_summary(item) for item in data["items"]]
        assert len(summaries) == 2
        assert summaries[0].increment_id == "001"
        assert summaries[1].increment_id == "002"
        # Summaries don't include full order fields like billing_address
        dumped = summaries[0].model_dump(mode="json")
        assert "billing_address" not in dumped
        assert "items" not in dumped

    @respx.mock
    async def test_search_empty_results(self) -> None:
        rest_response = _wrap_rest_response([], total_count=0)
        respx.get(f"{BASE_URL}/rest/default/V1/orders").mock(
            return_value=httpx.Response(200, json=rest_response),
        )

        async with RESTClient(base_url=BASE_URL, admin_token=TOKEN) as client:
            data = await client.get("/V1/orders", params=RESTClient.search_params())

        assert data["items"] == []
        assert data["total_count"] == 0

    @respx.mock
    async def test_search_by_status(self) -> None:
        """Verify status filter appears in request params."""
        rest_response = _wrap_rest_response([])
        route = respx.get(f"{BASE_URL}/rest/default/V1/orders").mock(
            return_value=httpx.Response(200, json=rest_response),
        )

        inp = AdminSearchOrdersInput(status="pending")
        params = _build_search_params(inp)

        async with RESTClient(base_url=BASE_URL, admin_token=TOKEN) as client:
            await client.get("/V1/orders", params=params)

        assert route.called
        url = str(route.calls[0].request.url)
        assert "status" in url
        assert "pending" in url

    @respx.mock
    async def test_search_by_customer_email(self) -> None:
        rest_response = _wrap_rest_response([])
        route = respx.get(f"{BASE_URL}/rest/default/V1/orders").mock(
            return_value=httpx.Response(200, json=rest_response),
        )

        inp = AdminSearchOrdersInput(customer_email="test@example.com")
        params = _build_search_params(inp)

        async with RESTClient(base_url=BASE_URL, admin_token=TOKEN) as client:
            await client.get("/V1/orders", params=params)

        url = str(route.calls[0].request.url)
        assert "customer_email" in url

    @respx.mock
    async def test_search_by_date_range(self) -> None:
        rest_response = _wrap_rest_response([])
        route = respx.get(f"{BASE_URL}/rest/default/V1/orders").mock(
            return_value=httpx.Response(200, json=rest_response),
        )

        inp = AdminSearchOrdersInput(created_from="2025-01-01", created_to="2025-06-30")
        params = _build_search_params(inp)

        async with RESTClient(base_url=BASE_URL, admin_token=TOKEN) as client:
            await client.get("/V1/orders", params=params)

        url = str(route.calls[0].request.url)
        assert "created_at" in url
        assert "2025-01-01" in url
        assert "2025-06-30" in url

    @respx.mock
    async def test_search_pagination(self) -> None:
        rest_response = _wrap_rest_response([], total_count=50)
        route = respx.get(f"{BASE_URL}/rest/default/V1/orders").mock(
            return_value=httpx.Response(200, json=rest_response),
        )

        inp = AdminSearchOrdersInput(page_size=10, current_page=3)
        params = _build_search_params(inp)

        async with RESTClient(base_url=BASE_URL, admin_token=TOKEN) as client:
            await client.get("/V1/orders", params=params)

        url = str(route.calls[0].request.url)
        assert "pageSize" in url
        assert "currentPage" in url
