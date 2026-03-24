"""Tests for admin_search_quotes tool."""

from __future__ import annotations

import pytest
import respx
import httpx


SEARCH_URL = "http://magento.test/rest/default/V1/carts/search"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("MAGENTO_BASE_URL", "http://magento.test")
    monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", "test-token")


def _quote(**kwargs):
    defaults = {
        "id": 1,
        "customer_email": "buyer@example.com",
        "customer_firstname": "Jane",
        "customer_lastname": "Doe",
        "items_count": 2,
        "items_qty": 3.0,
        "grand_total": 149.99,
        "base_grand_total": 149.99,
        "currency": {"quote_currency_code": "USD"},
        "store_id": 1,
        "is_active": True,
        "is_virtual": False,
        "created_at": "2026-03-01 10:00:00",
        "updated_at": "2026-03-20 15:30:00",
    }
    return {**defaults, **kwargs}


class TestAdminSearchQuotes:
    async def test_is_registered(self):
        from magemcp.server import mcp
        names = [t.name for t in await mcp.list_tools()]
        assert "admin_search_quotes" in names

    @respx.mock
    async def test_returns_quotes(self):
        respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={
            "items": [_quote()],
            "total_count": 1,
        }))
        from magemcp.tools.admin.quotes import admin_search_quotes
        result = await admin_search_quotes()
        assert result["total_count"] == 1
        assert len(result["quotes"]) == 1
        assert result["quotes"][0]["customer_email"] == "buyer@example.com"
        assert result["quotes"][0]["grand_total"] == 149.99

    @respx.mock
    async def test_filter_by_email(self):
        respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={
            "items": [_quote(customer_email="test@test.com")],
            "total_count": 1,
        }))
        from magemcp.tools.admin.quotes import admin_search_quotes
        result = await admin_search_quotes(customer_email="%test%")
        request = respx.calls[0].request
        assert "customer_email" in str(request.url)

    @respx.mock
    async def test_filter_is_active(self):
        respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={
            "items": [_quote(is_active=True)],
            "total_count": 1,
        }))
        from magemcp.tools.admin.quotes import admin_search_quotes
        result = await admin_search_quotes(is_active=True)
        request = respx.calls[0].request
        assert "is_active" in str(request.url)

    @respx.mock
    async def test_filter_min_grand_total(self):
        respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={
            "items": [_quote(grand_total=200.0)],
            "total_count": 1,
        }))
        from magemcp.tools.admin.quotes import admin_search_quotes
        result = await admin_search_quotes(min_grand_total=100.0)
        request = respx.calls[0].request
        assert "grand_total" in str(request.url)
        assert "gteq" in str(request.url)

    @respx.mock
    async def test_filter_updated_from_natural_language(self):
        respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={
            "items": [],
            "total_count": 0,
        }))
        from magemcp.tools.admin.quotes import admin_search_quotes
        result = await admin_search_quotes(updated_from="last week")
        request = respx.calls[0].request
        assert "updated_at" in str(request.url)

    @respx.mock
    async def test_empty_results(self):
        respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={
            "items": [],
            "total_count": 0,
        }))
        from magemcp.tools.admin.quotes import admin_search_quotes
        result = await admin_search_quotes()
        assert result["total_count"] == 0
        assert result["quotes"] == []

    @respx.mock
    async def test_pagination(self):
        respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={
            "items": [_quote()],
            "total_count": 50,
        }))
        from magemcp.tools.admin.quotes import admin_search_quotes
        result = await admin_search_quotes(page_size=10, current_page=2)
        assert result["page_size"] == 10
        assert result["current_page"] == 2

    @respx.mock
    async def test_currency_parsed(self):
        respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={
            "items": [_quote(currency={"quote_currency_code": "EUR"})],
            "total_count": 1,
        }))
        from magemcp.tools.admin.quotes import admin_search_quotes
        result = await admin_search_quotes()
        assert result["quotes"][0]["currency_code"] == "EUR"
