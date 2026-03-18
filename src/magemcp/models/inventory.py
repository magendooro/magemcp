"""Pydantic models for inventory tools."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# c_get_inventory — Input
# ---------------------------------------------------------------------------


class CGetInventoryInput(BaseModel):
    """Check salable quantity for one or more SKUs."""

    skus: list[str] = Field(
        description="Product SKU(s) to check inventory for.",
        min_length=1,
        max_length=50,
    )
    stock_id: int = Field(
        default=1,
        description="Magento stock ID (default stock = 1).",
        gt=0,
    )
    store_scope: str = Field(
        default="default",
        description="Magento store view code.",
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    )


# ---------------------------------------------------------------------------
# c_get_inventory — Output
# ---------------------------------------------------------------------------


class SkuInventory(BaseModel):
    """Inventory result for a single SKU."""

    sku: str
    salable_quantity: float
    is_salable: bool
    stock_id: int
    error: str | None = None


class CGetInventoryOutput(BaseModel):
    """Inventory check results for one or more SKUs."""

    items: list[SkuInventory]
    stock_id: int
