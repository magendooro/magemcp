"""Tests for c_get_categories tool."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from magemcp.connectors.errors import MagentoError
from magemcp.connectors.graphql_client import GraphQLClient
from magemcp.models.customer_ns.categories import (
    CategoryNode,
    CGetCategoriesInput,
    CGetCategoriesOutput,
)
from magemcp.tools.customer.get_categories import (
    _build_variables,
    _parse_category_node,
    _parse_response,
)

BASE_URL = "https://magento.test"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_category(
    *,
    uid: str = "MQ==",
    name: str = "Default Category",
    url_key: str | None = "default-category",
    url_path: str | None = "default-category",
    position: int = 1,
    level: int = 1,
    product_count: int = 0,
    include_in_menu: bool = True,
    children: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a mock GraphQL category item."""
    return {
        "uid": uid,
        "name": name,
        "url_key": url_key,
        "url_path": url_path,
        "position": position,
        "level": level,
        "product_count": product_count,
        "include_in_menu": include_in_menu,
        "children": children or [],
    }


def _make_gql_response(
    items: list[dict[str, Any]] | None = None,
    total_count: int | None = None,
    current_page: int = 1,
    page_size: int = 20,
    total_pages: int = 1,
) -> dict[str, Any]:
    """Build a complete GraphQL categories response (the 'data' portion)."""
    if items is None:
        items = [_make_category()]
    if total_count is None:
        total_count = len(items)
    return {
        "categories": {
            "items": items,
            "total_count": total_count,
            "page_info": {
                "current_page": current_page,
                "page_size": page_size,
                "total_pages": total_pages,
            },
        },
    }


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_defaults(self) -> None:
        inp = CGetCategoriesInput()
        assert inp.parent_id is None
        assert inp.name is None
        assert inp.include_in_menu is None
        assert inp.store_scope == "default"
        assert inp.page_size == 20
        assert inp.current_page == 1

    def test_with_parent_id(self) -> None:
        inp = CGetCategoriesInput(parent_id="MQ==")
        assert inp.parent_id == "MQ=="

    def test_with_name(self) -> None:
        inp = CGetCategoriesInput(name="Jackets")
        assert inp.name == "Jackets"

    def test_with_include_in_menu(self) -> None:
        inp = CGetCategoriesInput(include_in_menu=True)
        assert inp.include_in_menu is True

    def test_invalid_store_scope(self) -> None:
        with pytest.raises(Exception):
            CGetCategoriesInput(store_scope="INVALID!")

    def test_page_size_max(self) -> None:
        with pytest.raises(Exception):
            CGetCategoriesInput(page_size=51)

    def test_page_size_min(self) -> None:
        with pytest.raises(Exception):
            CGetCategoriesInput(page_size=0)

    def test_name_max_length(self) -> None:
        with pytest.raises(Exception):
            CGetCategoriesInput(name="x" * 201)


# ---------------------------------------------------------------------------
# _build_variables
# ---------------------------------------------------------------------------


class TestBuildVariables:
    def test_minimal(self) -> None:
        inp = CGetCategoriesInput()
        variables = _build_variables(inp)
        assert variables == {"pageSize": 20, "currentPage": 1}
        assert "filters" not in variables

    def test_with_parent_id(self) -> None:
        inp = CGetCategoriesInput(parent_id="MQ==")
        variables = _build_variables(inp)
        assert variables["filters"]["parent_id"] == {"eq": "MQ=="}

    def test_with_name(self) -> None:
        inp = CGetCategoriesInput(name="Jackets")
        variables = _build_variables(inp)
        assert variables["filters"]["name"] == {"match": "Jackets"}

    def test_with_include_in_menu_true(self) -> None:
        inp = CGetCategoriesInput(include_in_menu=True)
        variables = _build_variables(inp)
        assert variables["filters"]["include_in_menu"] == {"eq": True}

    def test_with_include_in_menu_false(self) -> None:
        inp = CGetCategoriesInput(include_in_menu=False)
        variables = _build_variables(inp)
        assert variables["filters"]["include_in_menu"] == {"eq": False}

    def test_combined_filters(self) -> None:
        inp = CGetCategoriesInput(parent_id="MQ==", name="Tops", include_in_menu=True)
        variables = _build_variables(inp)
        assert "parent_id" in variables["filters"]
        assert "name" in variables["filters"]
        assert "include_in_menu" in variables["filters"]

    def test_pagination(self) -> None:
        inp = CGetCategoriesInput(page_size=5, current_page=3)
        variables = _build_variables(inp)
        assert variables["pageSize"] == 5
        assert variables["currentPage"] == 3


# ---------------------------------------------------------------------------
# _parse_category_node
# ---------------------------------------------------------------------------


class TestParseCategoryNode:
    def test_basic(self) -> None:
        raw = _make_category(uid="MQ==", name="Women", level=2, product_count=42)
        node = _parse_category_node(raw)
        assert node.uid == "MQ=="
        assert node.name == "Women"
        assert node.level == 2
        assert node.product_count == 42
        assert node.children == []

    def test_with_children(self) -> None:
        raw = _make_category(
            uid="1",
            name="Women",
            children=[
                _make_category(uid="2", name="Tops", level=3),
                _make_category(uid="3", name="Bottoms", level=3),
            ],
        )
        node = _parse_category_node(raw)
        assert len(node.children) == 2
        assert node.children[0].name == "Tops"
        assert node.children[1].name == "Bottoms"

    def test_nested_children_3_levels(self) -> None:
        """Verify 3-level deep nesting parses correctly."""
        raw = _make_category(
            uid="1",
            name="Root",
            level=1,
            children=[
                _make_category(
                    uid="2",
                    name="Women",
                    level=2,
                    children=[
                        _make_category(
                            uid="3",
                            name="Tops",
                            level=3,
                            children=[
                                _make_category(uid="4", name="Jackets", level=4, product_count=15),
                            ],
                        ),
                    ],
                ),
            ],
        )
        node = _parse_category_node(raw)
        assert node.name == "Root"
        assert node.children[0].name == "Women"
        assert node.children[0].children[0].name == "Tops"
        assert node.children[0].children[0].children[0].name == "Jackets"
        assert node.children[0].children[0].children[0].product_count == 15

    def test_missing_optional_fields(self) -> None:
        raw = {"uid": "X", "name": "Minimal"}
        node = _parse_category_node(raw)
        assert node.uid == "X"
        assert node.name == "Minimal"
        assert node.url_key is None
        assert node.url_path is None
        assert node.position is None
        assert node.level is None
        assert node.product_count == 0
        assert node.include_in_menu is True
        assert node.children == []


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------


class TestParseResponse:
    def test_basic_response(self) -> None:
        data = _make_gql_response(
            items=[
                _make_category(uid="1", name="Women"),
                _make_category(uid="2", name="Men"),
                _make_category(uid="3", name="Gear"),
            ],
            total_count=3,
        )
        result = _parse_response(data)
        assert len(result.categories) == 3
        assert result.total_count == 3
        assert result.page_info.current_page == 1

    def test_empty_categories(self) -> None:
        data = _make_gql_response(items=[], total_count=0)
        result = _parse_response(data)
        assert result.categories == []
        assert result.total_count == 0

    def test_pagination_info(self) -> None:
        data = _make_gql_response(
            total_count=15,
            current_page=2,
            page_size=5,
            total_pages=3,
        )
        result = _parse_response(data)
        assert result.page_info.current_page == 2
        assert result.page_info.page_size == 5
        assert result.page_info.total_pages == 3

    def test_with_nested_children(self) -> None:
        data = _make_gql_response(
            items=[
                _make_category(
                    uid="1",
                    name="Women",
                    children=[
                        _make_category(uid="2", name="Tops", children=[
                            _make_category(uid="3", name="Jackets"),
                        ]),
                        _make_category(uid="4", name="Bottoms"),
                    ],
                ),
            ],
        )
        result = _parse_response(data)
        assert len(result.categories) == 1
        women = result.categories[0]
        assert women.name == "Women"
        assert len(women.children) == 2
        assert women.children[0].name == "Tops"
        assert len(women.children[0].children) == 1
        assert women.children[0].children[0].name == "Jackets"


# ---------------------------------------------------------------------------
# End-to-end tool invocation (mocked GraphQL)
# ---------------------------------------------------------------------------


class TestToolEndToEnd:
    @respx.mock
    async def test_get_root_categories(self) -> None:
        """Mock GraphQL response with 3 top-level categories with children."""
        gql_response = {
            "data": _make_gql_response(
                items=[
                    _make_category(uid="1", name="Women", product_count=100, children=[
                        _make_category(uid="10", name="Tops", level=3),
                    ]),
                    _make_category(uid="2", name="Men", product_count=80),
                    _make_category(uid="3", name="Gear", product_count=50),
                ],
                total_count=3,
            ),
        }
        route = respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        async with GraphQLClient(base_url=BASE_URL) as client:
            data = await client.query(
                "query { categories { items { uid name } } }",
                store_code="default",
            )

        result = _parse_response(data)
        assert len(result.categories) == 3
        assert result.categories[0].name == "Women"
        assert result.categories[0].children[0].name == "Tops"
        assert route.called
        assert route.calls[0].request.headers["store"] == "default"

    @respx.mock
    async def test_filter_by_parent_id(self) -> None:
        """Verify parent_id filter is sent in variables."""
        gql_response = {"data": _make_gql_response(items=[], total_count=0)}
        route = respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        inp = CGetCategoriesInput(parent_id="MQ==")
        variables = _build_variables(inp)

        async with GraphQLClient(base_url=BASE_URL) as client:
            await client.query(
                "query($filters: CategoryFilterInput) { categories(filters: $filters) { items { uid } } }",
                variables=variables,
            )

        assert route.called
        assert b'"parent_id"' in route.calls[0].request.content

    @respx.mock
    async def test_include_in_menu_filter(self) -> None:
        """Verify include_in_menu filter works."""
        menu_cats = [
            _make_category(uid="1", name="Women", include_in_menu=True),
            _make_category(uid="2", name="Men", include_in_menu=True),
        ]
        gql_response = {"data": _make_gql_response(items=menu_cats, total_count=2)}
        respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        async with GraphQLClient(base_url=BASE_URL) as client:
            data = await client.query(
                "query { categories { items { uid name include_in_menu } } }",
            )

        result = _parse_response(data)
        assert all(c.include_in_menu for c in result.categories)

    @respx.mock
    async def test_graphql_error_propagates(self) -> None:
        gql_response = {"errors": [{"message": "Category query error"}]}
        respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        async with GraphQLClient(base_url=BASE_URL) as client:
            with pytest.raises(MagentoError, match="Category query error"):
                await client.query("{ categories { items { uid } } }")


# ---------------------------------------------------------------------------
# Output serialization
# ---------------------------------------------------------------------------


class TestOutputSerialization:
    def test_model_dump_json(self) -> None:
        data = _make_gql_response(
            items=[
                _make_category(
                    uid="1",
                    name="Women",
                    product_count=42,
                    children=[
                        _make_category(uid="2", name="Tops", product_count=20),
                    ],
                ),
            ],
        )
        result = _parse_response(data)
        dumped = result.model_dump(mode="json")

        assert isinstance(dumped, dict)
        assert isinstance(dumped["categories"], list)
        assert dumped["categories"][0]["uid"] == "1"
        assert dumped["categories"][0]["name"] == "Women"
        assert dumped["categories"][0]["product_count"] == 42
        assert len(dumped["categories"][0]["children"]) == 1
        assert dumped["categories"][0]["children"][0]["name"] == "Tops"
        assert dumped["total_count"] == 1
        assert dumped["page_info"]["current_page"] == 1
