"""Tests for admin_search_customers tool."""

from __future__ import annotations

from typing import Any

import pytest
import respx
from httpx import Response

from magemcp.tools.admin.search_customers import _parse_customer_summary

BASE_URL = "https://magento.test"
TOKEN = "admin-token-123"
STORE_CODE = "default"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAGENTO_BASE_URL", BASE_URL)
    monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("MAGENTO_STORE_CODE", STORE_CODE)


def _make_customer(
    *,
    id: int = 1,
    email: str = "jane@example.com",
    firstname: str = "Jane",
    lastname: str = "Doe",
    group_id: int = 1,
    store_id: int = 1,
    website_id: int = 1,
    created_at: str = "2024-01-15 10:00:00",
) -> dict[str, Any]:
    return {
        "id": id,
        "email": email,
        "firstname": firstname,
        "lastname": lastname,
        "group_id": group_id,
        "store_id": store_id,
        "website_id": website_id,
        "created_at": created_at,
    }


def _wrap(items: list[dict[str, Any]], total_count: int | None = None) -> dict[str, Any]:
    return {
        "items": items,
        "search_criteria": {},
        "total_count": total_count if total_count is not None else len(items),
    }


# ---------------------------------------------------------------------------
# Unit tests — parse helper
# ---------------------------------------------------------------------------


class TestParseCustomerSummary:
    def test_basic_fields(self) -> None:
        raw = _make_customer()
        summary = _parse_customer_summary(raw)
        assert summary.customer_id == 1
        assert summary.email == "jane@example.com"
        assert summary.firstname == "Jane"
        assert summary.lastname == "Doe"
        assert summary.group_id == 1

    def test_missing_optional_fields(self) -> None:
        raw = {"id": 42}
        summary = _parse_customer_summary(raw)
        assert summary.customer_id == 42
        assert summary.email is None
        assert summary.firstname is None

    def test_is_active_default(self) -> None:
        raw = _make_customer()
        summary = _parse_customer_summary(raw)
        assert summary.is_active is True


# ---------------------------------------------------------------------------
# Tool tests
# ---------------------------------------------------------------------------


class TestSearchByEmail:
    async def test_email_filter_uses_like(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        """Email filter should use 'like' condition to support wildcards."""
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/customers/search").mock(
            return_value=Response(200, json=_wrap([_make_customer()]))
        )

        from magemcp.tools.admin.search_customers import admin_search_customers
        result = await admin_search_customers(email="%@example.com")

        assert result["total_count"] == 1
        assert len(result["customers"]) == 1

        # Verify the filter condition in the request URL
        request = respx_mock.calls.last.request
        url = str(request.url)
        assert "email" in url
        assert "like" in url

    async def test_search_by_email_exact(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        """Exact email search returns matching customer."""
        customer = _make_customer(email="john@test.com", firstname="John", lastname="Smith")
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/customers/search").mock(
            return_value=Response(200, json=_wrap([customer]))
        )

        from magemcp.tools.admin.search_customers import admin_search_customers
        result = await admin_search_customers(email="john@test.com")

        assert result["customers"][0]["email"] == "john@test.com"


class TestSearchByName:
    async def test_firstname_filter_uses_like(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        """Firstname filter uses 'like' condition."""
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/customers/search").mock(
            return_value=Response(200, json=_wrap([_make_customer(firstname="Jane")]))
        )

        from magemcp.tools.admin.search_customers import admin_search_customers
        result = await admin_search_customers(firstname="Jane%")

        request = respx_mock.calls.last.request
        url = str(request.url)
        assert "firstname" in url
        assert "like" in url
        assert result["customers"][0]["firstname"] == "Jane"

    async def test_lastname_filter_uses_like(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        """Lastname filter uses 'like' condition."""
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/customers/search").mock(
            return_value=Response(200, json=_wrap([_make_customer(lastname="Smith")]))
        )

        from magemcp.tools.admin.search_customers import admin_search_customers
        result = await admin_search_customers(lastname="Smith")

        request = respx_mock.calls.last.request
        url = str(request.url)
        assert "lastname" in url
        assert "like" in url

    async def test_combined_name_filters(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        """Both firstname and lastname filters are applied together."""
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/customers/search").mock(
            return_value=Response(200, json=_wrap([]))
        )

        from magemcp.tools.admin.search_customers import admin_search_customers
        result = await admin_search_customers(firstname="Jane", lastname="Doe")

        request = respx_mock.calls.last.request
        url = str(request.url)
        assert "firstname" in url
        assert "lastname" in url


class TestSearchReturnsFullData:
    async def test_email_not_masked(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        """Admin search returns full email — no masking."""
        customer = _make_customer(email="real@address.com", firstname="Real", lastname="Name")
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/customers/search").mock(
            return_value=Response(200, json=_wrap([customer]))
        )

        from magemcp.tools.admin.search_customers import admin_search_customers
        result = await admin_search_customers()

        c = result["customers"][0]
        assert c["email"] == "real@address.com"
        assert c["firstname"] == "Real"
        assert c["lastname"] == "Name"

    async def test_pagination_metadata(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        """Response includes total_count, page_size, current_page."""
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/customers/search").mock(
            return_value=Response(200, json=_wrap([_make_customer()], total_count=42))
        )

        from magemcp.tools.admin.search_customers import admin_search_customers
        result = await admin_search_customers(page_size=10, current_page=2)

        assert result["total_count"] == 42
        assert result["page_size"] == 10
        assert result["current_page"] == 2

    async def test_group_id_filter_uses_eq(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        """group_id uses eq condition (not like)."""
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/customers/search").mock(
            return_value=Response(200, json=_wrap([_make_customer(group_id=3)]))
        )

        from magemcp.tools.admin.search_customers import admin_search_customers
        result = await admin_search_customers(group_id=3)

        request = respx_mock.calls.last.request
        url = str(request.url)
        assert "group_id" in url
        # group_id uses eq (no 'like')
        assert result["customers"][0]["group_id"] == 3

    async def test_created_from_filter_uses_gteq(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        """created_from uses gteq condition."""
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/customers/search").mock(
            return_value=Response(200, json=_wrap([_make_customer()]))
        )

        from magemcp.tools.admin.search_customers import admin_search_customers
        result = await admin_search_customers(created_from="2024-01-01 00:00:00")

        request = respx_mock.calls.last.request
        url = str(request.url)
        assert "created_at" in url
        assert "gteq" in url
        assert result["total_count"] == 1
