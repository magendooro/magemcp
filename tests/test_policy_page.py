"""Tests for c_get_policy_page tool."""

from __future__ import annotations

import httpx
import pytest
import respx

from magemcp.connectors.errors import MagentoNotFoundError
from magemcp.tools.customer.policy_page import c_get_policy_page

BASE_URL = "https://magento.test"


def _gql_response(page: dict | None) -> dict:
    return {"data": {"cmsPage": page}}


@pytest.fixture
def mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAGENTO_BASE_URL", BASE_URL)


class TestCGetPolicyPage:
    async def test_returns_page_content(
        self, mock_env: None, respx_mock: respx.MockRouter,
    ) -> None:
        page = {
            "identifier": "privacy-policy",
            "title": "Privacy Policy",
            "content": "<p>We respect your privacy.</p>",
            "content_heading": "Privacy Policy",
            "meta_title": "Privacy Policy | Store",
            "meta_description": "Our privacy policy",
            "meta_keywords": None,
            "url_key": "privacy-policy",
        }
        respx_mock.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=_gql_response(page))
        )

        result = await c_get_policy_page("privacy-policy")
        assert result["identifier"] == "privacy-policy"
        assert result["title"] == "Privacy Policy"
        assert "privacy" in result["content"].lower()

    async def test_raises_not_found_when_page_missing(
        self, mock_env: None, respx_mock: respx.MockRouter,
    ) -> None:
        respx_mock.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=_gql_response(None))
        )

        with pytest.raises(MagentoNotFoundError, match="privacy-policy"):
            await c_get_policy_page("privacy-policy")

    async def test_store_scope_sent_as_header(
        self, mock_env: None, respx_mock: respx.MockRouter,
    ) -> None:
        page = {
            "identifier": "returns",
            "title": "Returns",
            "content": "<p>Returns policy.</p>",
            "content_heading": None,
            "meta_title": None,
            "meta_description": None,
            "meta_keywords": None,
            "url_key": "returns",
        }
        route = respx_mock.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=_gql_response(page))
        )

        await c_get_policy_page("returns", store_scope="fr")
        assert route.calls[0].request.headers.get("store") == "fr"

    async def test_identifier_sent_as_graphql_variable(
        self, mock_env: None, respx_mock: respx.MockRouter,
    ) -> None:
        import json

        page = {
            "identifier": "about-us",
            "title": "About Us",
            "content": "<p>About us.</p>",
            "content_heading": None,
            "meta_title": None,
            "meta_description": None,
            "meta_keywords": None,
            "url_key": "about-us",
        }
        route = respx_mock.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=_gql_response(page))
        )

        await c_get_policy_page("about-us")
        body = json.loads(route.calls[0].request.content)
        assert body["variables"]["identifier"] == "about-us"

    async def test_all_fields_returned(
        self, mock_env: None, respx_mock: respx.MockRouter,
    ) -> None:
        page = {
            "identifier": "terms",
            "title": "Terms and Conditions",
            "content": "<p>Terms.</p>",
            "content_heading": "T&C",
            "meta_title": "Terms | Store",
            "meta_description": "Our terms",
            "meta_keywords": "terms, conditions",
            "url_key": "terms-and-conditions",
        }
        respx_mock.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=_gql_response(page))
        )

        result = await c_get_policy_page("terms")
        for field in ("identifier", "title", "content", "content_heading",
                      "meta_title", "meta_description", "meta_keywords", "url_key"):
            assert field in result

    async def test_is_registered(self) -> None:
        from magemcp.server import mcp
        names = [t.name for t in await mcp.list_tools()]
        assert "c_get_policy_page" in names
