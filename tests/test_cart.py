"""Tests for cart tools."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from magemcp.connectors.errors import MagentoError
from magemcp.connectors.graphql_client import GraphQLClient
from magemcp.models.customer_ns.cart import (
    AddToCartInput,
    ApplyCouponInput,
    Cart,
    CartInput,
    SetAddressInput,
    SetGuestEmailInput,
    SetPaymentMethodInput,
    SetShippingMethodInput,
    UpdateCartItemInput,
)

BASE_URL = "https://magento.test"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_cart_item(
    *,
    uid: str = "MQ==",
    sku: str = "SKU1",
    name: str = "Test Product",
    quantity: float = 1,
    price: float = 29.99,
    currency: str = "USD",
) -> dict[str, Any]:
    return {
        "uid": uid,
        "product": {"sku": sku, "name": name},
        "quantity": quantity,
        "prices": {"price": {"value": price, "currency": currency}},
    }


def _make_cart(
    *,
    cart_id: str = "abc123",
    email: str | None = None,
    items: list[dict[str, Any]] | None = None,
    grand_total: float = 0,
    subtotal: float = 0,
    currency: str = "USD",
    applied_coupons: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "id": cart_id,
        "email": email,
        "items": items or [],
        "prices": {
            "grand_total": {"value": grand_total, "currency": currency},
            "subtotal_excluding_tax": {"value": subtotal, "currency": currency},
        },
        "applied_coupons": applied_coupons,
        "shipping_addresses": [],
        "billing_address": None,
        "selected_payment_method": None,
    }


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_cart_input_valid(self) -> None:
        inp = CartInput(cart_id="abc123")
        assert inp.cart_id == "abc123"
        assert inp.store_scope == "default"

    def test_cart_input_empty_id_rejected(self) -> None:
        with pytest.raises(Exception):
            CartInput(cart_id="")

    def test_add_to_cart_input(self) -> None:
        inp = AddToCartInput(cart_id="abc", sku="SKU1", quantity=2)
        assert inp.sku == "SKU1"
        assert inp.quantity == 2

    def test_add_to_cart_zero_quantity_rejected(self) -> None:
        with pytest.raises(Exception):
            AddToCartInput(cart_id="abc", sku="SKU1", quantity=0)

    def test_update_cart_item_zero_quantity_allowed(self) -> None:
        """Quantity=0 means remove."""
        inp = UpdateCartItemInput(cart_id="abc", cart_item_uid="MQ==", quantity=0)
        assert inp.quantity == 0

    def test_apply_coupon_input(self) -> None:
        inp = ApplyCouponInput(cart_id="abc", coupon_code="SAVE10")
        assert inp.coupon_code == "SAVE10"

    def test_set_address_input(self) -> None:
        inp = SetAddressInput(
            cart_id="abc", firstname="Jane", lastname="Doe",
            street=["123 Main St"], city="Austin", region="TX",
            postcode="78701", country_code="US", telephone="5551234",
        )
        assert inp.firstname == "Jane"
        assert inp.country_code == "US"

    def test_set_shipping_method_input(self) -> None:
        inp = SetShippingMethodInput(
            cart_id="abc", carrier_code="flatrate", method_code="flatrate",
        )
        assert inp.carrier_code == "flatrate"

    def test_set_payment_default(self) -> None:
        inp = SetPaymentMethodInput(cart_id="abc")
        assert inp.payment_method_code == "checkmo"

    def test_set_guest_email_input(self) -> None:
        inp = SetGuestEmailInput(cart_id="abc", email="test@example.com")
        assert inp.email == "test@example.com"


# ---------------------------------------------------------------------------
# Cart model parsing
# ---------------------------------------------------------------------------


class TestCartModel:
    def test_empty_cart(self) -> None:
        raw = _make_cart()
        cart = Cart(**raw)
        assert cart.id == "abc123"
        assert cart.items == []
        assert cart.prices is not None
        assert cart.prices.grand_total is not None
        assert cart.prices.grand_total.value == 0

    def test_cart_with_items(self) -> None:
        raw = _make_cart(
            items=[
                _make_cart_item(uid="1", sku="SKU1", quantity=2, price=10.0),
                _make_cart_item(uid="2", sku="SKU2", quantity=1, price=20.0),
            ],
            grand_total=40.0,
            subtotal=40.0,
        )
        cart = Cart(**raw)
        assert len(cart.items) == 2
        assert cart.items[0].product.sku == "SKU1"
        assert cart.items[0].quantity == 2
        assert cart.items[1].product.sku == "SKU2"

    def test_cart_with_coupon(self) -> None:
        raw = _make_cart(applied_coupons=[{"code": "SAVE10"}])
        cart = Cart(**raw)
        assert cart.applied_coupons is not None
        assert cart.applied_coupons[0].code == "SAVE10"

    def test_cart_serialization(self) -> None:
        raw = _make_cart(
            items=[_make_cart_item()],
            grand_total=29.99,
            subtotal=29.99,
            email="test@example.com",
        )
        cart = Cart(**raw)
        dumped = cart.model_dump(mode="json")
        assert dumped["id"] == "abc123"
        assert dumped["email"] == "test@example.com"
        assert len(dumped["items"]) == 1
        assert dumped["items"][0]["product"]["sku"] == "SKU1"
        assert dumped["prices"]["grand_total"]["value"] == 29.99


# ---------------------------------------------------------------------------
# Tool end-to-end (mocked GraphQL)
# ---------------------------------------------------------------------------


class TestToolEndToEnd:
    @respx.mock
    async def test_create_cart(self) -> None:
        """createGuestCart returns cart_id."""
        gql_response = {
            "data": {"createGuestCart": {"cart": {"id": "new-cart-id-123"}}},
        }
        route = respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        async with GraphQLClient(base_url=BASE_URL) as client:
            data = await client.query("mutation { createGuestCart { cart { id } } }")

        assert data["createGuestCart"]["cart"]["id"] == "new-cart-id-123"
        assert route.called

    @respx.mock
    async def test_add_to_cart(self) -> None:
        """addProductsToCart sends SKU and qty, returns updated cart."""
        cart = _make_cart(
            items=[_make_cart_item(sku="SKU1", quantity=2, price=15.0)],
            grand_total=30.0,
            subtotal=30.0,
        )
        gql_response = {
            "data": {"addProductsToCart": {"cart": cart, "user_errors": []}},
        }
        route = respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        async with GraphQLClient(base_url=BASE_URL) as client:
            data = await client.query(
                "mutation($cartId: String!, $cartItems: [CartItemInput!]!) { "
                "addProductsToCart(cartId: $cartId, cartItems: $cartItems) { "
                "cart { id items { uid } } user_errors { code message } } }",
                variables={
                    "cartId": "abc123",
                    "cartItems": [{"sku": "SKU1", "quantity": 2}],
                },
            )

        result = data["addProductsToCart"]
        assert result["user_errors"] == []
        parsed = Cart(**result["cart"])
        assert len(parsed.items) == 1
        assert parsed.items[0].product.sku == "SKU1"
        assert route.called
        assert b'"sku"' in route.calls[0].request.content

    @respx.mock
    async def test_get_cart_with_items(self) -> None:
        """Get cart with 2 items, verify parsing."""
        cart = _make_cart(
            items=[
                _make_cart_item(uid="1", sku="SKU1", name="Product A", quantity=1, price=10.0),
                _make_cart_item(uid="2", sku="SKU2", name="Product B", quantity=3, price=20.0),
            ],
            grand_total=70.0,
            subtotal=70.0,
        )
        gql_response = {"data": {"cart": cart}}
        respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        async with GraphQLClient(base_url=BASE_URL) as client:
            data = await client.query(
                "query($cartId: String!) { cart(cart_id: $cartId) { id items { uid } } }",
                variables={"cartId": "abc123"},
            )

        parsed = Cart(**data["cart"])
        assert len(parsed.items) == 2
        assert parsed.items[0].product.sku == "SKU1"
        assert parsed.items[1].quantity == 3
        assert parsed.prices is not None
        assert parsed.prices.grand_total is not None
        assert parsed.prices.grand_total.value == 70.0

    @respx.mock
    async def test_update_cart_item_quantity(self) -> None:
        """updateCartItems sends item UID and new quantity."""
        cart = _make_cart(
            items=[_make_cart_item(uid="MQ==", sku="SKU1", quantity=5)],
        )
        gql_response = {"data": {"updateCartItems": {"cart": cart}}}
        route = respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        async with GraphQLClient(base_url=BASE_URL) as client:
            data = await client.query(
                "mutation { updateCartItems(input: {}) { cart { id } } }",
                variables={
                    "cartId": "abc123",
                    "items": [{"cart_item_uid": "MQ==", "quantity": 5}],
                },
            )

        parsed = Cart(**data["updateCartItems"]["cart"])
        assert parsed.items[0].quantity == 5
        assert route.called

    @respx.mock
    async def test_apply_coupon(self) -> None:
        """applyCouponToCart sends coupon code."""
        cart = _make_cart(applied_coupons=[{"code": "SAVE10"}])
        gql_response = {"data": {"applyCouponToCart": {"cart": cart}}}
        route = respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        async with GraphQLClient(base_url=BASE_URL) as client:
            data = await client.query(
                "mutation { applyCouponToCart(input: {}) { cart { id } } }",
                variables={"cartId": "abc123", "couponCode": "SAVE10"},
            )

        parsed = Cart(**data["applyCouponToCart"]["cart"])
        assert parsed.applied_coupons is not None
        assert parsed.applied_coupons[0].code == "SAVE10"
        assert b'"SAVE10"' in route.calls[0].request.content

    @respx.mock
    async def test_place_order(self) -> None:
        """placeOrder returns order_number."""
        gql_response = {
            "data": {
                "placeOrder": {
                    "order": {"order_number": "000000042"},
                    "errors": [],
                },
            },
        }
        route = respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        async with GraphQLClient(base_url=BASE_URL) as client:
            data = await client.query(
                "mutation($cartId: String!) { placeOrder(input: {cart_id: $cartId}) { "
                "order { order_number } errors { code message } } }",
                variables={"cartId": "abc123"},
            )

        result = data["placeOrder"]
        assert result["order"]["order_number"] == "000000042"
        assert result["errors"] == []
        assert route.called

    @respx.mock
    async def test_add_invalid_sku_returns_error(self) -> None:
        """addProductsToCart with invalid SKU returns user_errors."""
        cart = _make_cart()
        gql_response = {
            "data": {
                "addProductsToCart": {
                    "cart": cart,
                    "user_errors": [
                        {"code": "PRODUCT_NOT_FOUND", "message": "Could not find a product with SKU \"NOPE\""},
                    ],
                },
            },
        }
        respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        async with GraphQLClient(base_url=BASE_URL) as client:
            data = await client.query(
                "mutation { addProductsToCart(cartId: $cartId, cartItems: $items) { "
                "cart { id } user_errors { code message } } }",
                variables={"cartId": "abc123", "cartItems": [{"sku": "NOPE", "quantity": 1}]},
            )

        errors = data["addProductsToCart"]["user_errors"]
        assert len(errors) == 1
        assert errors[0]["code"] == "PRODUCT_NOT_FOUND"

    @respx.mock
    async def test_store_scope_sent_as_header(self) -> None:
        """Verify Store header is sent for cart operations."""
        gql_response = {"data": {"createGuestCart": {"cart": {"id": "x"}}}}
        route = respx.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json=gql_response),
        )

        async with GraphQLClient(base_url=BASE_URL) as client:
            await client.query(
                "mutation { createGuestCart { cart { id } } }",
                store_code="fr",
            )

        assert route.calls[0].request.headers["store"] == "fr"


# ---------------------------------------------------------------------------
# Tool functions (module-level)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAGENTO_BASE_URL", BASE_URL)


from magemcp.tools.customer.cart import (
    c_create_cart,
    c_get_cart,
    c_add_to_cart,
    c_update_cart_item,
    c_apply_coupon,
    c_set_guest_email,
    c_set_shipping_address,
    c_set_billing_address,
    c_set_shipping_method,
    c_set_payment_method,
    c_place_order,
)


class TestCartToolFunctions:
    async def test_c_create_cart(
        self, mock_env: None, respx_mock: respx.MockRouter,
    ) -> None:
        respx_mock.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json={"data": {
                "createGuestCart": {"cart": {"id": "NEW123"}}
            }})
        )
        result = await c_create_cart()
        assert result["cart_id"] == "NEW123"

    async def test_c_get_cart(
        self, mock_env: None, respx_mock: respx.MockRouter,
    ) -> None:
        cart = _make_cart(cart_id="abc123", items=[_make_cart_item()])
        respx_mock.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json={"data": {"cart": cart}})
        )
        result = await c_get_cart("abc123")
        assert result["id"] == "abc123"
        assert len(result["items"]) == 1

    async def test_c_add_to_cart(
        self, mock_env: None, respx_mock: respx.MockRouter,
    ) -> None:
        cart = _make_cart(cart_id="abc123", items=[_make_cart_item(sku="WJ12")])
        respx_mock.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json={"data": {
                "addProductsToCart": {"cart": cart, "user_errors": []}
            }})
        )
        result = await c_add_to_cart("abc123", "WJ12")
        assert result["id"] == "abc123"
        assert result["items"][0]["product"]["sku"] == "WJ12"

    async def test_c_add_to_cart_user_error_raises(
        self, mock_env: None, respx_mock: respx.MockRouter,
    ) -> None:
        respx_mock.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json={"data": {
                "addProductsToCart": {
                    "cart": _make_cart(),
                    "user_errors": [{"code": "PRODUCT_NOT_FOUND", "message": "SKU not found"}],
                }
            }})
        )
        with pytest.raises(MagentoError, match="SKU not found"):
            await c_add_to_cart("abc123", "NOPE")

    async def test_c_update_cart_item(
        self, mock_env: None, respx_mock: respx.MockRouter,
    ) -> None:
        cart = _make_cart()
        respx_mock.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json={"data": {
                "updateCartItems": {"cart": cart}
            }})
        )
        result = await c_update_cart_item("abc123", "ITEM_UID", quantity=2)
        assert result["id"] == "abc123"

    async def test_c_update_cart_item_remove(
        self, mock_env: None, respx_mock: respx.MockRouter,
    ) -> None:
        cart = _make_cart()
        respx_mock.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json={"data": {
                "removeItemFromCart": {"cart": cart}
            }})
        )
        result = await c_update_cart_item("abc123", "ITEM_UID", quantity=0)
        assert result["id"] == "abc123"

    async def test_c_apply_coupon(
        self, mock_env: None, respx_mock: respx.MockRouter,
    ) -> None:
        cart = _make_cart(applied_coupons=[{"code": "SAVE10"}])
        respx_mock.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json={"data": {
                "applyCouponToCart": {"cart": cart}
            }})
        )
        result = await c_apply_coupon("abc123", "SAVE10")
        assert result["applied_coupons"][0]["code"] == "SAVE10"

    async def test_c_set_guest_email(
        self, mock_env: None, respx_mock: respx.MockRouter,
    ) -> None:
        respx_mock.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json={"data": {
                "setGuestEmailOnCart": {"cart": {"email": "guest@example.com"}}
            }})
        )
        result = await c_set_guest_email("abc123", "guest@example.com")
        assert result["email"] == "guest@example.com"

    async def test_c_set_shipping_address(
        self, mock_env: None, respx_mock: respx.MockRouter,
    ) -> None:
        cart = _make_cart()
        respx_mock.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json={"data": {
                "setShippingAddressesOnCart": {"cart": cart}
            }})
        )
        result = await c_set_shipping_address(
            "abc123", "Jane", "Doe", ["1 Main St"], "Portland", "OR", "97201", "US", "555-1234"
        )
        assert result["id"] == "abc123"

    async def test_c_set_billing_address(
        self, mock_env: None, respx_mock: respx.MockRouter,
    ) -> None:
        cart = _make_cart()
        respx_mock.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json={"data": {
                "setBillingAddressOnCart": {"cart": cart}
            }})
        )
        result = await c_set_billing_address(
            "abc123", "Jane", "Doe", ["1 Main St"], "Portland", "OR", "97201", "US", "555-1234"
        )
        assert result["id"] == "abc123"

    async def test_c_set_shipping_method(
        self, mock_env: None, respx_mock: respx.MockRouter,
    ) -> None:
        cart = _make_cart()
        respx_mock.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json={"data": {
                "setShippingMethodsOnCart": {"cart": cart}
            }})
        )
        result = await c_set_shipping_method("abc123", "flatrate", "flatrate")
        assert result["id"] == "abc123"

    async def test_c_set_payment_method(
        self, mock_env: None, respx_mock: respx.MockRouter,
    ) -> None:
        cart = _make_cart()
        respx_mock.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json={"data": {
                "setPaymentMethodOnCart": {"cart": cart}
            }})
        )
        result = await c_set_payment_method("abc123")
        assert result["id"] == "abc123"

    async def test_c_place_order(
        self, mock_env: None, respx_mock: respx.MockRouter,
    ) -> None:
        respx_mock.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json={"data": {
                "placeOrder": {
                    "order": {"order_number": "000000042"},
                    "errors": [],
                }
            }})
        )
        result = await c_place_order("abc123")
        assert result["order_number"] == "000000042"

    async def test_c_place_order_error_raises(
        self, mock_env: None, respx_mock: respx.MockRouter,
    ) -> None:
        respx_mock.post(f"{BASE_URL}/graphql").mock(
            return_value=httpx.Response(200, json={"data": {
                "placeOrder": {
                    "order": None,
                    "errors": [{"code": "UNABLE_TO_PLACE_ORDER", "message": "Cart is empty"}],
                }
            }})
        )
        with pytest.raises(MagentoError, match="Cart is empty"):
            await c_place_order("abc123")

    async def test_parse_cart_helper(
        self, mock_env: None, respx_mock: respx.MockRouter,
    ) -> None:
        from magemcp.tools.customer.cart import _parse_cart, _address_variables, SetAddressInput
        cart = _make_cart(cart_id="test-id")
        result = _parse_cart(cart)
        assert result["id"] == "test-id"

    async def test_address_variables_helper(
        self, mock_env: None, respx_mock: respx.MockRouter,
    ) -> None:
        from magemcp.tools.customer.cart import _address_variables, SetAddressInput
        inp = SetAddressInput(
            cart_id="x", firstname="Jane", lastname="Doe",
            street=["1 Main St"], city="Portland", region="OR",
            postcode="97201", country_code="US", telephone="555-0000",
        )
        variables = _address_variables(inp)
        assert variables["firstname"] == "Jane"
        assert variables["street"] == ["1 Main St"]
