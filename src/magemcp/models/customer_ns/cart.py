"""Pydantic models for cart tools."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared input fields
# ---------------------------------------------------------------------------


class CartInput(BaseModel):
    """Base input requiring a cart ID."""

    cart_id: str = Field(
        description="Guest cart ID returned by c_create_cart.",
        min_length=1,
        max_length=128,
    )
    store_scope: str = Field(
        default="default",
        description="Magento store view code.",
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    )


class AddToCartInput(CartInput):
    sku: str = Field(min_length=1, max_length=64)
    quantity: float = Field(default=1, gt=0)


class UpdateCartItemInput(CartInput):
    cart_item_uid: str = Field(min_length=1, max_length=64)
    quantity: float = Field(ge=0)


class ApplyCouponInput(CartInput):
    coupon_code: str = Field(min_length=1, max_length=128)


class SetAddressInput(CartInput):
    firstname: str = Field(min_length=1, max_length=64)
    lastname: str = Field(min_length=1, max_length=64)
    street: list[str] = Field(min_length=1)
    city: str = Field(min_length=1, max_length=64)
    region: str = Field(min_length=1, max_length=64)
    postcode: str = Field(min_length=1, max_length=16)
    country_code: str = Field(min_length=2, max_length=2)
    telephone: str = Field(min_length=1, max_length=32)


class SetShippingMethodInput(CartInput):
    carrier_code: str = Field(min_length=1, max_length=64)
    method_code: str = Field(min_length=1, max_length=64)


class SetPaymentMethodInput(CartInput):
    payment_method_code: str = Field(default="checkmo", min_length=1, max_length=64)


class SetGuestEmailInput(CartInput):
    email: str = Field(min_length=1, max_length=254)


# ---------------------------------------------------------------------------
# Output models
# ---------------------------------------------------------------------------


class MoneyAmount(BaseModel):
    value: float
    currency: str


class CartItemPrice(BaseModel):
    price: MoneyAmount


class CartProduct(BaseModel):
    sku: str
    name: str


class CartItem(BaseModel):
    uid: str
    product: CartProduct
    quantity: float
    prices: CartItemPrice | None = None


class CartPrices(BaseModel):
    grand_total: MoneyAmount | None = None
    subtotal_excluding_tax: MoneyAmount | None = None


class AppliedCoupon(BaseModel):
    code: str


class ShippingMethod(BaseModel):
    carrier_code: str
    method_code: str
    carrier_title: str | None = None
    method_title: str | None = None
    amount: MoneyAmount | None = None


class SelectedShippingMethod(BaseModel):
    carrier_code: str
    method_code: str


class CartAddress(BaseModel):
    firstname: str | None = None
    lastname: str | None = None
    street: list[str] | None = None
    city: str | None = None
    postcode: str | None = None
    country: dict[str, str] | None = None
    telephone: str | None = None


class ShippingAddress(CartAddress):
    available_shipping_methods: list[ShippingMethod] = Field(default_factory=list)
    selected_shipping_method: SelectedShippingMethod | None = None


class SelectedPaymentMethod(BaseModel):
    code: str


class Cart(BaseModel):
    id: str
    email: str | None = None
    items: list[CartItem] = Field(default_factory=list)
    prices: CartPrices | None = None
    applied_coupons: list[AppliedCoupon] | None = None
    shipping_addresses: list[ShippingAddress] = Field(default_factory=list)
    billing_address: CartAddress | None = None
    selected_payment_method: SelectedPaymentMethod | None = None


class PlaceOrderResult(BaseModel):
    order_number: str
