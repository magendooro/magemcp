"""Tests for admin CMS tools."""

from __future__ import annotations

import json
from typing import Any

import pytest
import respx
from httpx import Response

from magemcp.connectors.errors import MagentoNotFoundError
from magemcp.tools.admin.cms import (
    _parse_page,
    admin_get_cms_page,
    admin_search_cms_pages,
    admin_update_cms_page,
)

BASE_URL = "https://magento.test"
TOKEN = "admin-token-123"
STORE_CODE = "default"


@pytest.fixture
def mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAGENTO_BASE_URL", BASE_URL)
    monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("MAGENTO_STORE_CODE", STORE_CODE)


def _make_page(
    *,
    id: int = 1,
    identifier: str = "home",
    title: str = "Home Page",
    content: str = "<p>Welcome</p>",
    is_active: bool = True,
    created_at: str = "2024-01-01 00:00:00",
) -> dict[str, Any]:
    return {
        "id": id,
        "identifier": identifier,
        "title": title,
        "content": content,
        "content_heading": "",
        "is_active": is_active,
        "page_layout": "1column",
        "meta_title": None,
        "meta_keywords": None,
        "meta_description": None,
        "created_at": created_at,
        "updated_at": "2024-06-01 00:00:00",
        "store_id": [0],
    }


def _wrap_search(items: list[dict[str, Any]], total: int | None = None) -> dict[str, Any]:
    return {"items": items, "search_criteria": {}, "total_count": total or len(items)}


# ---------------------------------------------------------------------------
# Unit — _parse_page
# ---------------------------------------------------------------------------


class TestParsePage:
    def test_basic_fields(self) -> None:
        raw = _make_page()
        page = _parse_page(raw)
        assert page["id"] == 1
        assert page["identifier"] == "home"
        assert page["title"] == "Home Page"
        assert page["content"] == "<p>Welcome</p>"
        assert page["is_active"] is True

    def test_missing_optional_fields(self) -> None:
        raw = {"id": 5, "identifier": "about"}
        page = _parse_page(raw)
        assert page["id"] == 5
        assert page["title"] is None
        assert page["content"] is None


# ---------------------------------------------------------------------------
# admin_get_cms_page
# ---------------------------------------------------------------------------


class TestGetCmsPage:
    async def test_get_by_id(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/cmsPage/1").mock(
            return_value=Response(200, json=_make_page())
        )
        result = await admin_get_cms_page(page_id=1)
        assert result["id"] == 1
        assert result["identifier"] == "home"

    async def test_get_by_identifier(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/cmsPage/search").mock(
            return_value=Response(200, json=_wrap_search([_make_page(identifier="home")]))
        )
        result = await admin_get_cms_page(identifier="home")
        assert result["identifier"] == "home"
        url = str(respx_mock.calls.last.request.url)
        assert "identifier" in url

    async def test_identifier_not_found(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/cmsPage/search").mock(
            return_value=Response(200, json=_wrap_search([]))
        )
        with pytest.raises(MagentoNotFoundError):
            await admin_get_cms_page(identifier="nonexistent")

    async def test_no_params_returns_error(self, mock_env: None) -> None:
        with pytest.raises(ValueError):
            await admin_get_cms_page()


# ---------------------------------------------------------------------------
# admin_search_cms_pages
# ---------------------------------------------------------------------------


class TestSearchCmsPages:
    async def test_title_filter_uses_like(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/cmsPage/search").mock(
            return_value=Response(200, json=_wrap_search([_make_page()]))
        )
        result = await admin_search_cms_pages(title="%Home%")
        url = str(respx_mock.calls.last.request.url)
        assert "title" in url
        assert "like" in url
        assert result["total_count"] == 1

    async def test_is_active_filter(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/cmsPage/search").mock(
            return_value=Response(200, json=_wrap_search([_make_page(is_active=True)]))
        )
        result = await admin_search_cms_pages(is_active=True)
        url = str(respx_mock.calls.last.request.url)
        assert "is_active" in url
        assert result["pages"][0]["is_active"] is True

    async def test_returns_pagination_metadata(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/cmsPage/search").mock(
            return_value=Response(200, json=_wrap_search([_make_page()], total=5))
        )
        result = await admin_search_cms_pages(page_size=10, current_page=1)
        assert result["total_count"] == 5
        assert result["page_size"] == 10
        assert "pages" in result


# ---------------------------------------------------------------------------
# admin_update_cms_page
# ---------------------------------------------------------------------------


class TestUpdateCmsPage:
    async def test_requires_confirmation(self, mock_env: None) -> None:
        result = await admin_update_cms_page(page_id=1, title="New Title")
        assert result["confirmation_required"] is True

    async def test_title_only_payload(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.put(f"{BASE_URL}/rest/{STORE_CODE}/V1/cmsPage/1").mock(
            return_value=Response(200, json=_make_page(title="New Title"))
        )
        result = await admin_update_cms_page(page_id=1, title="New Title", confirm=True)
        assert result["success"] is True
        assert "title" in result["updated_fields"]
        payload = json.loads(respx_mock.calls.last.request.content)
        assert payload["page"]["title"] == "New Title"
        assert "content" not in payload["page"]

    async def test_multiple_fields(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.put(f"{BASE_URL}/rest/{STORE_CODE}/V1/cmsPage/1").mock(
            return_value=Response(200, json=_make_page())
        )
        result = await admin_update_cms_page(
            page_id=1, title="T", content="<p>C</p>", is_active=False, confirm=True
        )
        assert result["success"] is True
        assert set(result["updated_fields"]) == {"title", "content", "is_active"}
        payload = json.loads(respx_mock.calls.last.request.content)
        assert payload["page"]["is_active"] is False

    async def test_no_fields_raises(self, mock_env: None) -> None:
        with pytest.raises(ValueError):
            await admin_update_cms_page(page_id=1, confirm=True)

    async def test_payload_wrapped_in_page_key(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.put(f"{BASE_URL}/rest/{STORE_CODE}/V1/cmsPage/1").mock(
            return_value=Response(200, json=_make_page())
        )
        await admin_update_cms_page(page_id=1, title="X", confirm=True)
        payload = json.loads(respx_mock.calls.last.request.content)
        assert "page" in payload
        assert payload["page"]["id"] == 1
