"""Pydantic models for customer tools — including PII-redacted DTOs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Shared sub-models
# ---------------------------------------------------------------------------


class CustomerAddress(BaseModel):
    """A customer address record as returned by the Magento REST API."""

    id: int | None = None
    firstname: str | None = None
    lastname: str | None = None
    street: list[str] = Field(default_factory=list)
    city: str | None = None
    region: str | None = None
    region_code: str | None = None
    postcode: str | None = None
    country_id: str | None = None
    telephone: str | None = None
    default_billing: bool = False
    default_shipping: bool = False


class CustomerSummary(BaseModel):
    """Lean customer record returned by admin_search_customers."""

    customer_id: int
    email: str | None = None
    firstname: str | None = None
    lastname: str | None = None
    group_id: int | None = None
    store_id: int | None = None
    website_id: int | None = None
    created_at: str | None = None
    is_active: bool = True


# ---------------------------------------------------------------------------
# c_get_customer — Input
# ---------------------------------------------------------------------------


class CGetCustomerInput(BaseModel):
    """Fetch a customer by internal ID or email address.

    At least one of ``customer_id`` or ``email`` must be provided.
    """

    customer_id: int | None = Field(
        default=None,
        description="Magento internal customer ID.",
        gt=0,
    )
    email: str | None = Field(
        default=None,
        description="Customer email address (requires website_id for uniqueness).",
        max_length=254,
    )
    website_id: int = Field(
        default=1,
        description="Website ID scope for email lookup (Magento customers are unique per website).",
        ge=0,
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
            "PII exposure level. 'redacted' (default) masks email, name, and addresses. "
            "'full' returns unmasked data (requires authorization)."
        ),
    )

    @model_validator(mode="after")
    def _require_id_or_email(self) -> CGetCustomerInput:
        if self.customer_id is None and not self.email:
            msg = "At least one of 'customer_id' or 'email' must be provided."
            raise ValueError(msg)
        return self


# ---------------------------------------------------------------------------
# c_get_customer — Output
# ---------------------------------------------------------------------------


class CGetCustomerOutput(BaseModel):
    """Customer support view — redacted by default per CLAUDE.md spec.

    Exposes customer group, account dates, and order summary.
    PII (email, name, DOB, addresses) is masked unless pii_mode=full.
    """

    customer_id: int
    group_id: int | None = None
    store_id: int | None = None
    website_id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None

    # PII fields (redacted by default)
    firstname: str | None = None
    lastname: str | None = None
    email: str | None = None
    dob: str | None = None

    # Non-PII metadata
    gender: int | None = None
    is_active: bool = True
    default_billing_id: str | None = None
    default_shipping_id: str | None = None

    # Extended fields (admin view)
    addresses: list[CustomerAddress] = Field(default_factory=list)
    custom_attributes: dict[str, Any] = Field(default_factory=dict)
    extension_attributes: dict[str, Any] = Field(default_factory=dict)

    pii_mode: str = "redacted"
