"""Pydantic models for admin product tools."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ProductSummary(BaseModel):
    """Lean product record returned by admin_search_products."""

    sku: str
    name: str | None = None
    price: float | None = None
    status: int | None = None
    visibility: int | None = None
    type_id: str | None = None
    weight: float | None = None
    created_at: str | None = None
    updated_at: str | None = None


class MediaGalleryEntry(BaseModel):
    id: int | None = None
    media_type: str | None = None
    label: str | None = None
    position: int | None = None
    disabled: bool = False
    types: list[str] = Field(default_factory=list)
    file: str | None = None


class StockItem(BaseModel):
    qty: float | None = None
    is_in_stock: bool | None = None
    manage_stock: bool | None = None
    min_sale_qty: float | None = None
    max_sale_qty: float | None = None


class TierPrice(BaseModel):
    customer_group_id: int | None = None
    qty: float | None = None
    value: float | None = None
    extension_attributes: dict[str, Any] = Field(default_factory=dict)


class ProductOption(BaseModel):
    option_id: int | None = None
    title: str | None = None
    type: str | None = None
    is_require: bool = False
    values: list[dict[str, Any]] = Field(default_factory=list)


class ProductDetail(BaseModel):
    """Full product record returned by admin_get_product."""

    sku: str
    name: str | None = None
    attribute_set_id: int | None = None
    price: float | None = None
    status: int | None = None
    visibility: int | None = None
    type_id: str | None = None
    weight: float | None = None
    created_at: str | None = None
    updated_at: str | None = None

    # Descriptions
    description: str | None = None
    short_description: str | None = None
    meta_title: str | None = None
    meta_description: str | None = None
    meta_keyword: str | None = None
    url_key: str | None = None

    # Media
    media_gallery: list[MediaGalleryEntry] = Field(default_factory=list)

    # Stock
    stock: StockItem | None = None

    # Pricing
    tier_prices: list[TierPrice] = Field(default_factory=list)

    # Options (customizable)
    options: list[ProductOption] = Field(default_factory=list)

    # Category IDs
    category_ids: list[int] = Field(default_factory=list)

    # Raw custom_attributes (flattened)
    custom_attributes: dict[str, Any] = Field(default_factory=dict)

    # Extension attributes (configurable links, bundle, etc.)
    extension_attributes: dict[str, Any] = Field(default_factory=dict)
