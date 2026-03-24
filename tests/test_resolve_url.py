"""Tests for c_resolve_url tool."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from magemcp.connectors.errors import MagentoError, MagentoNotFoundError
from magemcp.connectors.graphql_client import GraphQLClient
from magemcp.tools.customer.resolve_url import CResolveUrlInput, _parse_route

BASE_URL = "https://magento.test"


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_valid_url(self) -> None:
        inp = CResolveUrlInput(url="blue-jacket.html")
        assert inp.url == "blue-jacket.html"
        assert inp.store_scope == "default"

    def test_empty_url_rejected(self) -> None:
        with pytest.raises(Exception):
            CResolveUrlInput(url="")

    def test_url_too_long(self) -> None:
        with pytest.raises(Exception):
            CResolveUrlInput(url="x" * 513)

    def test_invalid_store_scope(self) -> None:
        with pytest.raises(Exception):
            CResolveUrlInput(url="test.html", store_scope="INVALID!")


# ---------------------------------------------------------------------------
# _parse_route
# ---------------------------------------------------------------------------


class TestParseRoute:
    def test_simple_product(self) -> None:
        route = {"__typename": "SimpleProduct", "sku": "SKU1", "name": "Blue Jacket", "url_key": "blue-jacket"}
        result = _parse_route(route)
        assert result["type"] == "SimpleProduct"
        assert result["sku"] == "SKU1"
        assert result["name"] == "Blue Jacket"
        assert result["url_key"] == "blue-jacket"

    def test_configurable_product(self) -> None:
        route = {"__typename": "ConfigurableProduct", "sku": "WJ12", "name": "Jacket", "url_key": "jacket"}
        result = _parse_route(route)
        assert result["type"] == "ConfigurableProduct"
        assert result["sku"] == "WJ12"

    def test_bundle_product(self) -> None:
        route = {"__typename": "BundleProduct", "sku": "BDL1", "name": "Bundle", "url_key": "bundle"}
        result = _parse_route(route)
        assert result["type"] == "BundleProduct"
        assert result["sku"] == "BDL1"

    def test_category_tree(self) -> None:
        route = {"__typename": "CategoryTree", "uid": "MQ==", "name": "Women", "url_key": "women", "url_path": "women"}
        result = _parse_route(route)
        assert result["type"] == "CategoryTree"
        assert result["uid"] == "MQ=="
        assert result["name"] == "Women"
        assert result["url_path"] == "women"

    def test_cms_page(self) -> None:
        route = {"__typename": "CmsPage", "identifier": "about-us", "title": "About Us", "url_key": "about-us"}
        result = _parse_route(route)
        assert result["type"] == "CmsPage"
        assert result["identifier"] == "about-us"
        assert result["title"] == "About Us"

    def test_null_route(self) -> None:
        with pytest.raises(MagentoNotFoundError):
            _parse_route(None)

    def test_unknown_type(self) -> None:
        route = {"__typename": "FutureType", "id": "123"}
        result = _parse_route(route)
        assert result["type"] == "FutureType"
        assert result["raw"] == route


# ---------------------------------------------------------------------------
# End-to-end (mocked GraphQL)
# ---------------------------------------------------------------------------


class TestToolEndToEnd:
    @respx.mock
    async def test_resolve_product_url(self) -> None:
        gql_response = {
            "data": {
                "route": {
                    "__typename": "SimpleProduct",
                    "sku": "SKU1",
                    "name": "Blue Jacket",
                    "url_key": "blue-jacket",
                },
            },
        }
        route = respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        async with GraphQLClient(base_url=BASE_URL) as client:
            data = await client.query(
                "query($url: String!) { route(url: $url) { __typename ... on SimpleProduct { sku name url_key } } }",
                variables={"url": "blue-jacket.html"},
            )

        result = _parse_route(data["route"])
        assert result["type"] == "SimpleProduct"
        assert result["sku"] == "SKU1"
        assert route.called

    @respx.mock
    async def test_resolve_category_url(self) -> None:
        gql_response = {
            "data": {
                "route": {
                    "__typename": "CategoryTree",
                    "uid": "MQ==",
                    "name": "Women",
                    "url_key": "women",
                    "url_path": "women",
                },
            },
        }
        respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        async with GraphQLClient(base_url=BASE_URL) as client:
            data = await client.query(
                "query($url: String!) { route(url: $url) { __typename ... on CategoryTree { uid name } } }",
                variables={"url": "women.html"},
            )

        result = _parse_route(data["route"])
        assert result["type"] == "CategoryTree"
        assert result["uid"] == "MQ=="

    @respx.mock
    async def test_resolve_cms_page_url(self) -> None:
        gql_response = {
            "data": {
                "route": {
                    "__typename": "CmsPage",
                    "identifier": "about-us",
                    "title": "About Us",
                    "url_key": "about-us",
                },
            },
        }
        respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        async with GraphQLClient(base_url=BASE_URL) as client:
            data = await client.query(
                "query($url: String!) { route(url: $url) { __typename ... on CmsPage { identifier title } } }",
                variables={"url": "about-us"},
            )

        result = _parse_route(data["route"])
        assert result["type"] == "CmsPage"
        assert result["identifier"] == "about-us"

    @respx.mock
    async def test_resolve_invalid_url(self) -> None:
        gql_response = {"data": {"route": None}}
        respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        async with GraphQLClient(base_url=BASE_URL) as client:
            data = await client.query(
                "query($url: String!) { route(url: $url) { __typename } }",
                variables={"url": "nonexistent-page-xyz"},
            )

        with pytest.raises(MagentoNotFoundError):
            _parse_route(data["route"])

    @respx.mock
    async def test_store_header_sent(self) -> None:
        gql_response = {"data": {"route": None}}
        route = respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        async with GraphQLClient(base_url=BASE_URL) as client:
            await client.query(
                "query($url: String!) { route(url: $url) { __typename } }",
                variables={"url": "test"},
                store_code="fr",
            )

        assert route.calls[0].request.headers["store"] == "fr"
