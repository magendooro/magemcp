"""Pydantic models for catalog tools (storefront + admin)."""

from __future__ import annotations

import re
from decimal import Decimal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(html: str | None) -> str | None:
    """Remove HTML tags, returning plain text or None."""
    if not html:
        return None
    return _HTML_TAG_RE.sub("", html).strip() or None


# ---------------------------------------------------------------------------
# c_search_products — Input
# ---------------------------------------------------------------------------


class CSearchProductsInput(BaseModel):
    """Search the storefront catalog."""

    search: str | None = Field(
        default=None,
        description="Free-text search query (e.g. 'blue running jacket').",
        max_length=200,
    )
    category_id: str | None = Field(
        default=None,
        description="Filter by category ID.",
        max_length=20,
    )
    price_from: float | None = Field(
        default=None,
        description="Minimum price filter.",
        ge=0,
    )
    price_to: float | None = Field(
        default=None,
        description="Maximum price filter.",
        ge=0,
    )
    in_stock_only: bool = Field(
        default=False,
        description="If true, only return products that are IN_STOCK.",
    )
    store_scope: str = Field(
        default="default",
        description="Magento store view code. Determines locale, currency, and catalog scope.",
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    page_size: int = Field(default=20, ge=1, le=50, description="Results per page. Max 50.")
    current_page: int = Field(default=1, ge=1, description="Page number (1-indexed).")
    sort_field: str = Field(
        default="relevance",
        description="Sort by: 'relevance', 'name', 'price', 'position'.",
        pattern=r"^(relevance|name|price|position)$",
    )
    sort_direction: str = Field(
        default="ASC",
        description="Sort direction: 'ASC' or 'DESC'. Ignored when sort_field is 'relevance'.",
        pattern=r"^(ASC|DESC)$",
    )


# ---------------------------------------------------------------------------
# c_search_products — Output
# ---------------------------------------------------------------------------


class PriceAmount(BaseModel):
    """A monetary value with currency."""

    value: Decimal
    currency: str


class ProductPrice(BaseModel):
    """Price information for a product."""

    regular_price: PriceAmount
    final_price: PriceAmount
    discount_amount: Decimal | None = None
    discount_percent: Decimal | None = None


class StorefrontProduct(BaseModel):
    """Product as seen on the storefront."""

    sku: str
    name: str
    url_key: str
    product_type: str  # "SimpleProduct", "ConfigurableProduct", etc.
    stock_status: str  # "IN_STOCK" or "OUT_OF_STOCK"
    min_price: ProductPrice
    max_price: ProductPrice
    image_url: str | None = None
    image_label: str | None = None
    short_description: str | None = None


class PageInfo(BaseModel):
    """GraphQL pagination info."""

    current_page: int
    page_size: int
    total_pages: int


class CSearchProductsOutput(BaseModel):
    """Paginated storefront product search results."""

    products: list[StorefrontProduct]
    total_count: int
    page_info: PageInfo


# ---------------------------------------------------------------------------
# c_get_product — Input
# ---------------------------------------------------------------------------


class CGetProductInput(BaseModel):
    """Fetch full product detail by SKU."""

    sku: str = Field(
        description="Product SKU to look up.",
        min_length=1,
        max_length=64,
    )
    store_scope: str = Field(
        default="default",
        description="Magento store view code. Determines locale, currency, and catalog scope.",
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    )


# ---------------------------------------------------------------------------
# c_get_product — Output
# ---------------------------------------------------------------------------


class MediaGalleryEntry(BaseModel):
    """A single product image from the media gallery."""

    url: str
    label: str | None = None
    position: int | None = None


class CategoryBreadcrumb(BaseModel):
    """A category with its full breadcrumb path."""

    id: str
    name: str
    url_path: str | None = None
    full_path: str  # e.g. "Women > Tops > Jackets"


class CustomAttribute(BaseModel):
    """A configurable product attribute with its available values."""

    attribute_code: str
    label: str
    values: list[str]


class CGetProductOutput(BaseModel):
    """Full product detail as seen on the storefront."""

    sku: str
    name: str
    url_key: str
    product_type: str
    meta_title: str | None = None
    meta_description: str | None = None
    stock_status: str
    description: str | None = None
    short_description: str | None = None
    min_price: ProductPrice
    max_price: ProductPrice
    images: list[MediaGalleryEntry] = Field(default_factory=list)
    categories: list[CategoryBreadcrumb] = Field(default_factory=list)
    custom_attributes: list[CustomAttribute] = Field(default_factory=list)
