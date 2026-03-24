"""Tests for c_get_store_config tool."""

from __future__ import annotations

from typing import Any

import httpx
import respx

from magemcp.connectors.graphql_client import GraphQLClient

BASE_URL = "https://magento.test"


def _make_store_config(
    *,
    store_code: str = "default",
    store_name: str = "Default Store View",
    locale: str = "en_US",
    base_currency_code: str = "USD",
    default_display_currency_code: str = "USD",
    timezone: str = "America/Chicago",
    weight_unit: str = "lbs",
    base_url: str = "https://magento.test/",
    base_link_url: str = "https://magento.test/",
    base_media_url: str = "https://magento.test/media/",
    product_url_suffix: str = ".html",
    category_url_suffix: str = ".html",
    cms_home_page: str = "home",
    copyright: str = "Copyright 2025",
    **extra: Any,
) -> dict[str, Any]:
    return {
        "store_code": store_code,
        "store_name": store_name,
        "locale": locale,
        "base_currency_code": base_currency_code,
        "default_display_currency_code": default_display_currency_code,
        "timezone": timezone,
        "weight_unit": weight_unit,
        "base_url": base_url,
        "base_link_url": base_link_url,
        "base_media_url": base_media_url,
        "catalog_default_sort_by": "position",
        "grid_per_page": 12,
        "list_per_page": 10,
        "product_url_suffix": product_url_suffix,
        "category_url_suffix": category_url_suffix,
        "title_prefix": None,
        "title_suffix": None,
        "default_title": None,
        "default_description": None,
        "head_includes": None,
        "cms_home_page": cms_home_page,
        "cms_no_route": "no-route",
        "copyright": copyright,
        **extra,
    }


class TestStoreConfig:
    @respx.mock
    async def test_returns_locale(self) -> None:
        config = _make_store_config(locale="fr_FR")
        gql_response = {"data": {"storeConfig": config}}
        respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        async with GraphQLClient(base_url=BASE_URL) as client:
            data = await client.query("{ storeConfig { locale } }")

        assert data["storeConfig"]["locale"] == "fr_FR"

    @respx.mock
    async def test_returns_currency(self) -> None:
        config = _make_store_config(base_currency_code="EUR")
        gql_response = {"data": {"storeConfig": config}}
        respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        async with GraphQLClient(base_url=BASE_URL) as client:
            data = await client.query("{ storeConfig { base_currency_code } }")

        assert data["storeConfig"]["base_currency_code"] == "EUR"

    @respx.mock
    async def test_returns_urls(self) -> None:
        config = _make_store_config(
            base_url="https://shop.example.com/",
            product_url_suffix=".html",
        )
        gql_response = {"data": {"storeConfig": config}}
        respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        async with GraphQLClient(base_url=BASE_URL) as client:
            data = await client.query("{ storeConfig { base_url product_url_suffix } }")

        assert data["storeConfig"]["base_url"] == "https://shop.example.com/"
        assert data["storeConfig"]["product_url_suffix"] == ".html"

    @respx.mock
    async def test_store_header_sent(self) -> None:
        gql_response = {"data": {"storeConfig": _make_store_config()}}
        route = respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        async with GraphQLClient(base_url=BASE_URL) as client:
            await client.query("{ storeConfig { locale } }", store_code="fr")

        assert route.calls[0].request.headers["store"] == "fr"

    @respx.mock
    async def test_tool_function_returns_config(self) -> None:
        """c_get_store_config tool function fetches and returns storeConfig dict."""
        import os
        config = _make_store_config(locale="de_DE", base_currency_code="EUR")
        gql_response = {"data": {"storeConfig": config}}
        respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        from magemcp.tools.customer.store_config import _cache, c_get_store_config

        _cache._store.clear()  # ensure no cache hit

        os.environ["MAGENTO_BASE_URL"] = BASE_URL

        result = await c_get_store_config(store_scope="default")
        assert result["locale"] == "de_DE"
        assert result["base_currency_code"] == "EUR"

    @respx.mock
    async def test_tool_function_caches_result(self) -> None:
        """Second call with same store_scope returns cached result without HTTP request."""
        import os
        config = _make_store_config()
        gql_response = {"data": {"storeConfig": config}}
        route = respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        from magemcp.tools.customer.store_config import _cache, c_get_store_config

        _cache._store.clear()
        os.environ["MAGENTO_BASE_URL"] = BASE_URL

        await c_get_store_config(store_scope="cache_test")
        await c_get_store_config(store_scope="cache_test")
        assert route.call_count == 1  # second call used cache

    @respx.mock
    async def test_all_fields_present(self) -> None:
        config = _make_store_config()
        gql_response = {"data": {"storeConfig": config}}
        respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        async with GraphQLClient(base_url=BASE_URL) as client:
            data = await client.query("{ storeConfig { store_code } }")

        sc = data["storeConfig"]
        assert sc["store_code"] == "default"
        assert sc["store_name"] == "Default Store View"
        assert sc["timezone"] == "America/Chicago"
        assert sc["cms_home_page"] == "home"
        assert sc["copyright"] == "Copyright 2025"
