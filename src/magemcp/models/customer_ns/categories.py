"""Pydantic models for the c_get_categories tool."""

from __future__ import annotations

from pydantic import BaseModel, Field

from magemcp.models.catalog import PageInfo


# ---------------------------------------------------------------------------
# c_get_categories — Input
# ---------------------------------------------------------------------------


class CGetCategoriesInput(BaseModel):
    """Fetch categories with optional filters."""

    parent_id: str | None = Field(
        default=None,
        description="Filter by parent category UID. Returns only children of this category.",
    )
    name: str | None = Field(
        default=None,
        description="Filter by category name (exact match).",
        max_length=200,
    )
    include_in_menu: bool | None = Field(
        default=None,
        description="Filter by menu visibility. True = only menu items, False = only hidden.",
    )
    store_scope: str = Field(
        default="default",
        description="Magento store view code.",
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    page_size: int = Field(default=20, ge=1, le=50)
    current_page: int = Field(default=1, ge=1)


# ---------------------------------------------------------------------------
# c_get_categories — Output
# ---------------------------------------------------------------------------


class CategoryNode(BaseModel):
    """A single category with optional nested children (up to 3 levels)."""

    uid: str
    name: str
    url_key: str | None = None
    url_path: str | None = None
    position: int | None = None
    level: int | None = None
    product_count: int = 0
    include_in_menu: bool = True
    children: list[CategoryNode] = Field(default_factory=list)


CategoryNode.model_rebuild()


class CGetCategoriesOutput(BaseModel):
    """Paginated category tree response."""

    categories: list[CategoryNode]
    total_count: int
    page_info: PageInfo
