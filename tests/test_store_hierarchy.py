"""Tests for admin_get_store_hierarchy tool."""

from __future__ import annotations

import pytest
import respx
import httpx


WEBSITES_URL = "http://magento.test/rest/default/V1/store/websites"
GROUPS_URL = "http://magento.test/rest/default/V1/store/storeGroups"
VIEWS_URL = "http://magento.test/rest/default/V1/store/storeViews"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("MAGENTO_BASE_URL", "http://magento.test")
    monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", "test-token")


WEBSITES = [{"id": 1, "code": "base", "name": "Main Website", "default_group_id": 1}]
GROUPS = [{"id": 1, "website_id": 1, "name": "Main Website Store", "root_category_id": 2, "default_store_id": 1, "code": "main_website_store"}]
VIEWS = [
    {"id": 1, "code": "default", "name": "Default Store View", "website_id": 1, "store_group_id": 1, "is_active": True, "sort_order": 0},
    {"id": 2, "code": "de", "name": "German", "website_id": 1, "store_group_id": 1, "is_active": True, "sort_order": 1},
]


class TestAdminGetStoreHierarchy:
    async def test_is_registered(self):
        from magemcp.server import mcp
        names = [t.name for t in await mcp.list_tools()]
        assert "admin_get_store_hierarchy" in names

    @respx.mock
    async def test_returns_hierarchy(self):
        respx.get(WEBSITES_URL).mock(return_value=httpx.Response(200, json=WEBSITES))
        respx.get(GROUPS_URL).mock(return_value=httpx.Response(200, json=GROUPS))
        respx.get(VIEWS_URL).mock(return_value=httpx.Response(200, json=VIEWS))

        from magemcp.tools.admin.store_hierarchy import admin_get_store_hierarchy
        result = await admin_get_store_hierarchy()

        assert len(result["websites"]) == 1
        assert result["websites"][0]["code"] == "base"
        assert len(result["websites"][0]["store_groups"]) == 1
        assert len(result["websites"][0]["store_groups"][0]["store_views"]) == 2

    @respx.mock
    async def test_flat_includes_all(self):
        respx.get(WEBSITES_URL).mock(return_value=httpx.Response(200, json=WEBSITES))
        respx.get(GROUPS_URL).mock(return_value=httpx.Response(200, json=GROUPS))
        respx.get(VIEWS_URL).mock(return_value=httpx.Response(200, json=VIEWS))

        from magemcp.tools.admin.store_hierarchy import admin_get_store_hierarchy
        result = await admin_get_store_hierarchy()

        assert len(result["flat"]["websites"]) == 1
        assert len(result["flat"]["store_groups"]) == 1
        assert len(result["flat"]["store_views"]) == 2

    @respx.mock
    async def test_store_view_codes_present(self):
        respx.get(WEBSITES_URL).mock(return_value=httpx.Response(200, json=WEBSITES))
        respx.get(GROUPS_URL).mock(return_value=httpx.Response(200, json=GROUPS))
        respx.get(VIEWS_URL).mock(return_value=httpx.Response(200, json=VIEWS))

        from magemcp.tools.admin.store_hierarchy import admin_get_store_hierarchy
        result = await admin_get_store_hierarchy()

        view_codes = [v["code"] for v in result["flat"]["store_views"]]
        assert "default" in view_codes
        assert "de" in view_codes

    @respx.mock
    async def test_empty_store(self):
        respx.get(WEBSITES_URL).mock(return_value=httpx.Response(200, json=[]))
        respx.get(GROUPS_URL).mock(return_value=httpx.Response(200, json=[]))
        respx.get(VIEWS_URL).mock(return_value=httpx.Response(200, json=[]))

        from magemcp.tools.admin.store_hierarchy import admin_get_store_hierarchy
        result = await admin_get_store_hierarchy()

        assert result["websites"] == []
        assert result["flat"]["websites"] == []

    @respx.mock
    async def test_makes_three_requests(self):
        respx.get(WEBSITES_URL).mock(return_value=httpx.Response(200, json=WEBSITES))
        respx.get(GROUPS_URL).mock(return_value=httpx.Response(200, json=GROUPS))
        respx.get(VIEWS_URL).mock(return_value=httpx.Response(200, json=VIEWS))

        from magemcp.tools.admin.store_hierarchy import admin_get_store_hierarchy
        await admin_get_store_hierarchy()

        called_urls = [str(c.request.url) for c in respx.calls]
        assert any("websites" in u for u in called_urls)
        assert any("storeGroups" in u for u in called_urls)
        assert any("storeViews" in u for u in called_urls)
