"""Pydantic models for order tools — including PII-redacted DTOs."""

from __future__ import annotations

import re
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# PII mode
# ---------------------------------------------------------------------------


class PiiMode(str, Enum):
    """Controls how much PII is included in order responses."""

    redacted = "redacted"
    full = "full"


# ---------------------------------------------------------------------------
# PII masking helpers
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"^([^@])[^@]*@([^.])[^.]*(\..+)$")


def mask_email(email: str | None) -> str | None:
    """Mask an email address: ``j***@e***.com``."""
    if not email:
        return None
    m = _EMAIL_RE.match(email)
    if not m:
        return "***@***.***"
    return f"{m.group(1)}***@{m.group(2)}***{m.group(3)}"


def mask_phone(phone: str | None) -> str | None:
    """Mask a phone number, keeping the last 4 digits."""
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if len(digits) <= 4:
        return "***"
    return f"***-***-{digits[-4:]}"


def mask_name(first: str | None, last: str | None) -> str:
    """Return masked name as first initial + last initial."""
    fi = (first or "?")[0].upper()
    li = (last or "?")[0].upper()
    return f"{fi}. {li}."


def mask_street(street: list[str] | None) -> list[str] | None:
    """Replace street lines with a redacted placeholder."""
    if not street:
        return None
    return ["[REDACTED]"]


# ---------------------------------------------------------------------------
# c_get_order — Input
# ---------------------------------------------------------------------------


class CGetOrderInput(BaseModel):
    """Fetch an order by its customer-facing increment ID."""

    increment_id: str = Field(
        description="Customer-facing order number (e.g. '000000001').",
        min_length=1,
        max_length=32,
    )
    store_scope: str = Field(
        default="default",
        description="Magento store view code.",
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    pii_mode: Literal["redacted", "full"] = Field(
        default="redacted",
        description=(
            "PII exposure level. 'redacted' (default) masks customer email, phone, "
            "names, and addresses. 'full' returns unmasked data (requires authorization)."
        ),
    )


# ---------------------------------------------------------------------------
# c_get_order — Output sub-models
# ---------------------------------------------------------------------------


class OrderAddress(BaseModel):
    """Billing or shipping address (may be redacted)."""

    city: str | None = None
    region: str | None = None
    postcode: str | None = None
    country_id: str | None = None
    street: list[str] | None = None
    telephone: str | None = None
    firstname: str | None = None
    lastname: str | None = None


class OrderItem(BaseModel):
    """A single line item on the order."""

    sku: str
    name: str
    qty_ordered: float
    price: float
    row_total: float


class ShipmentSummary(BaseModel):
    """Summary of a shipment on the order."""

    tracks: list[ShipmentTrack] = Field(default_factory=list)


class ShipmentTrack(BaseModel):
    """A tracking number for a shipment."""

    track_number: str
    carrier_code: str | None = None
    title: str | None = None


# Fix forward reference
ShipmentSummary.model_rebuild()


class StatusHistoryEntry(BaseModel):
    """An entry from the order's status history / comments."""

    comment: str | None = None
    status: str | None = None
    created_at: str | None = None
    is_customer_notified: bool = False
    is_visible_on_front: bool = False


# ---------------------------------------------------------------------------
# c_get_order — Output
# ---------------------------------------------------------------------------


class CGetOrderOutput(BaseModel):
    """Full admin order view — no PII redaction.

    Contains increment ID, status, totals, fulfillment state, shipment summary,
    status history, payment info, and invoice/credit memo references.
    """

    increment_id: str
    state: str
    status: str
    created_at: str
    updated_at: str | None = None

    # Customer
    customer_name: str
    customer_email: str | None = None

    # Totals
    grand_total: float
    subtotal: float
    tax_amount: float
    discount_amount: float
    shipping_amount: float
    currency_code: str | None = None
    total_qty_ordered: float

    # Items
    items: list[OrderItem] = Field(default_factory=list)

    # Addresses
    billing_address: OrderAddress | None = None
    shipping_address: OrderAddress | None = None

    # Fulfillment
    shipping_method: str | None = None
    shipments: list[ShipmentSummary] = Field(default_factory=list)

    # Status history
    status_history: list[StatusHistoryEntry] = Field(default_factory=list)

    # Payment
    payment_method: str | None = None
    payment_additional: list[str] = Field(default_factory=list)

    # References
    invoice_ids: list[int] = Field(default_factory=list)
    credit_memo_ids: list[int] = Field(default_factory=list)

    pii_mode: str = "redacted"


# ---------------------------------------------------------------------------
# Order summary (for search results)
# ---------------------------------------------------------------------------


class OrderSummary(BaseModel):
    """Lightweight order summary for search results."""

    increment_id: str
    state: str
    status: str
    created_at: str
    grand_total: float
    currency_code: str | None = None
    total_qty_ordered: float
    customer_name: str
    customer_email: str | None = None
    total_items: int = 0
