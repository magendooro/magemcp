"""Cart tools — guest cart operations via Magento GraphQL."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from magemcp.connectors.errors import MagentoError
from magemcp.connectors.graphql_client import GraphQLClient
from magemcp.models.customer_ns.cart import (
    AddToCartInput,
    ApplyCouponInput,
    Cart,
    CartInput,
    PlaceOrderResult,
    SetAddressInput,
    SetGuestEmailInput,
    SetPaymentMethodInput,
    SetShippingMethodInput,
    UpdateCartItemInput,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GraphQL fragments / queries
# ---------------------------------------------------------------------------

CART_FIELDS = """
    id
    email
    items {
      uid
      product { sku name }
      quantity
      prices { price { value currency } }
    }
    prices {
      grand_total { value currency }
      subtotal_excluding_tax { value currency }
    }
    applied_coupons { code }
    shipping_addresses {
      firstname lastname street city postcode
      country { code }
      telephone
      available_shipping_methods {
        carrier_code method_code carrier_title method_title
        amount { value currency }
      }
      selected_shipping_method { carrier_code method_code }
    }
    billing_address {
      firstname lastname street city postcode
      country { code }
      telephone
    }
    selected_payment_method { code }
"""

CREATE_CART_MUTATION = """
mutation { createGuestCart { cart { id } } }
"""

GET_CART_QUERY = """
query($cartId: String!) {
  cart(cart_id: $cartId) {
    """ + CART_FIELDS + """
  }
}
"""

ADD_TO_CART_MUTATION = """
mutation($cartId: String!, $cartItems: [CartItemInput!]!) {
  addProductsToCart(cartId: $cartId, cartItems: $cartItems) {
    cart {
      """ + CART_FIELDS + """
    }
    user_errors { code message }
  }
}
"""

UPDATE_CART_ITEMS_MUTATION = """
mutation($cartId: String!, $items: [CartItemUpdateInput!]!) {
  updateCartItems(input: {cart_id: $cartId, cart_items: $items}) {
    cart {
      """ + CART_FIELDS + """
    }
  }
}
"""

REMOVE_ITEM_MUTATION = """
mutation($cartId: String!, $itemUid: ID!) {
  removeItemFromCart(input: {cart_id: $cartId, cart_item_uid: $itemUid}) {
    cart {
      """ + CART_FIELDS + """
    }
  }
}
"""

APPLY_COUPON_MUTATION = """
mutation($cartId: String!, $couponCode: String!) {
  applyCouponToCart(input: {cart_id: $cartId, coupon_code: $couponCode}) {
    cart {
      """ + CART_FIELDS + """
    }
  }
}
"""

SET_GUEST_EMAIL_MUTATION = """
mutation($cartId: String!, $email: String!) {
  setGuestEmailOnCart(input: {cart_id: $cartId, email: $email}) {
    cart { email }
  }
}
"""

SET_SHIPPING_ADDRESS_MUTATION = """
mutation($cartId: String!, $address: CartAddressInput!) {
  setShippingAddressesOnCart(input: {
    cart_id: $cartId,
    shipping_addresses: [{address: $address}]
  }) {
    cart {
      shipping_addresses {
        firstname lastname street city postcode
        country { code }
        telephone
        available_shipping_methods {
          carrier_code method_code carrier_title method_title
          amount { value currency }
        }
      }
    }
  }
}
"""

SET_BILLING_ADDRESS_MUTATION = """
mutation($cartId: String!, $address: CartAddressInput!) {
  setBillingAddressOnCart(input: {
    cart_id: $cartId,
    billing_address: {address: $address}
  }) {
    cart {
      billing_address { firstname lastname street city postcode country { code } telephone }
    }
  }
}
"""

SET_SHIPPING_METHOD_MUTATION = """
mutation($cartId: String!, $carrierCode: String!, $methodCode: String!) {
  setShippingMethodsOnCart(input: {
    cart_id: $cartId,
    shipping_methods: [{carrier_code: $carrierCode, method_code: $methodCode}]
  }) {
    cart {
      shipping_addresses {
        selected_shipping_method { carrier_code method_code }
      }
    }
  }
}
"""

SET_PAYMENT_METHOD_MUTATION = """
mutation($cartId: String!, $code: String!) {
  setPaymentMethodOnCart(input: {
    cart_id: $cartId,
    payment_method: {code: $code}
  }) {
    cart { selected_payment_method { code } }
  }
}
"""

PLACE_ORDER_MUTATION = """
mutation($cartId: String!) {
  placeOrder(input: {cart_id: $cartId}) {
    order { order_number }
    errors { code message }
  }
}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_cart(raw: dict[str, Any]) -> dict[str, Any]:
    """Parse raw cart response into Cart model and dump."""
    return Cart(**raw).model_dump(mode="json")


def _address_variables(inp: SetAddressInput) -> dict[str, Any]:
    """Build address variables for GraphQL mutations."""
    return {
        "firstname": inp.firstname,
        "lastname": inp.lastname,
        "street": inp.street,
        "city": inp.city,
        "region": inp.region,
        "postcode": inp.postcode,
        "country_code": inp.country_code,
        "telephone": inp.telephone,
    }


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_cart_tools(mcp: FastMCP) -> None:
    """Register all cart tools on the given MCP server."""

    # -- c_create_cart -------------------------------------------------------

    @mcp.tool(
        name="c_create_cart",
        description="Create an empty guest cart. Returns the cart ID for subsequent operations.",
        annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
    )
    async def c_create_cart(
        store_scope: str = "default",
    ) -> dict[str, Any]:
        """Create a guest cart."""
        log.info("c_create_cart store=%s", store_scope)
        async with GraphQLClient.from_env() as client:
            data = await client.query(CREATE_CART_MUTATION, store_code=store_scope)
        cart_id = data["createGuestCart"]["cart"]["id"]
        return {"cart_id": cart_id}

    # -- c_get_cart ----------------------------------------------------------

    @mcp.tool(
        name="c_get_cart",
        description=(
            "Get cart contents including items, prices, applied coupons, "
            "addresses, and selected shipping/payment methods."
        ),
        annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": True},
    )
    async def c_get_cart(
        cart_id: str,
        store_scope: str = "default",
    ) -> dict[str, Any]:
        """Get cart contents."""
        inp = CartInput(cart_id=cart_id, store_scope=store_scope)
        log.info("c_get_cart cart_id=%s store=%s", inp.cart_id, inp.store_scope)
        async with GraphQLClient.from_env() as client:
            data = await client.query(
                GET_CART_QUERY,
                variables={"cartId": inp.cart_id},
                store_code=inp.store_scope,
            )
        return _parse_cart(data["cart"])

    # -- c_add_to_cart -------------------------------------------------------

    @mcp.tool(
        name="c_add_to_cart",
        description="Add a product to the cart by SKU. Returns updated cart.",
        annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
    )
    async def c_add_to_cart(
        cart_id: str,
        sku: str,
        quantity: float = 1,
        store_scope: str = "default",
    ) -> dict[str, Any]:
        """Add a product to cart."""
        inp = AddToCartInput(
            cart_id=cart_id, sku=sku, quantity=quantity, store_scope=store_scope,
        )
        log.info("c_add_to_cart cart=%s sku=%s qty=%s", inp.cart_id, inp.sku, inp.quantity)
        async with GraphQLClient.from_env() as client:
            data = await client.query(
                ADD_TO_CART_MUTATION,
                variables={
                    "cartId": inp.cart_id,
                    "cartItems": [{"sku": inp.sku, "quantity": inp.quantity}],
                },
                store_code=inp.store_scope,
            )

        result = data["addProductsToCart"]
        user_errors = result.get("user_errors") or []
        if user_errors:
            return {"error": user_errors[0]["message"], "code": user_errors[0].get("code")}

        return _parse_cart(result["cart"])

    # -- c_update_cart_item --------------------------------------------------

    @mcp.tool(
        name="c_update_cart_item",
        description="Update item quantity in the cart. Set quantity=0 to remove the item.",
        annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
    )
    async def c_update_cart_item(
        cart_id: str,
        cart_item_uid: str,
        quantity: float,
        store_scope: str = "default",
    ) -> dict[str, Any]:
        """Update cart item quantity or remove it."""
        inp = UpdateCartItemInput(
            cart_id=cart_id, cart_item_uid=cart_item_uid,
            quantity=quantity, store_scope=store_scope,
        )
        log.info(
            "c_update_cart_item cart=%s item=%s qty=%s",
            inp.cart_id, inp.cart_item_uid, inp.quantity,
        )

        async with GraphQLClient.from_env() as client:
            if inp.quantity == 0:
                data = await client.query(
                    REMOVE_ITEM_MUTATION,
                    variables={"cartId": inp.cart_id, "itemUid": inp.cart_item_uid},
                    store_code=inp.store_scope,
                )
                return _parse_cart(data["removeItemFromCart"]["cart"])

            data = await client.query(
                UPDATE_CART_ITEMS_MUTATION,
                variables={
                    "cartId": inp.cart_id,
                    "items": [{"cart_item_uid": inp.cart_item_uid, "quantity": inp.quantity}],
                },
                store_code=inp.store_scope,
            )
        return _parse_cart(data["updateCartItems"]["cart"])

    # -- c_apply_coupon ------------------------------------------------------

    @mcp.tool(
        name="c_apply_coupon",
        description="Apply a coupon code to the cart. Returns updated cart with discounts.",
        annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
    )
    async def c_apply_coupon(
        cart_id: str,
        coupon_code: str,
        store_scope: str = "default",
    ) -> dict[str, Any]:
        """Apply coupon to cart."""
        inp = ApplyCouponInput(
            cart_id=cart_id, coupon_code=coupon_code, store_scope=store_scope,
        )
        log.info("c_apply_coupon cart=%s code=%s", inp.cart_id, inp.coupon_code)
        async with GraphQLClient.from_env() as client:
            data = await client.query(
                APPLY_COUPON_MUTATION,
                variables={"cartId": inp.cart_id, "couponCode": inp.coupon_code},
                store_code=inp.store_scope,
            )
        return _parse_cart(data["applyCouponToCart"]["cart"])

    # -- c_set_guest_email ---------------------------------------------------

    @mcp.tool(
        name="c_set_guest_email",
        description="Set the guest email on the cart (required before placing order).",
        annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
    )
    async def c_set_guest_email(
        cart_id: str,
        email: str,
        store_scope: str = "default",
    ) -> dict[str, Any]:
        """Set guest email on cart."""
        inp = SetGuestEmailInput(cart_id=cart_id, email=email, store_scope=store_scope)
        log.info("c_set_guest_email cart=%s", inp.cart_id)
        async with GraphQLClient.from_env() as client:
            data = await client.query(
                SET_GUEST_EMAIL_MUTATION,
                variables={"cartId": inp.cart_id, "email": inp.email},
                store_code=inp.store_scope,
            )
        return {"email": data["setGuestEmailOnCart"]["cart"]["email"]}

    # -- c_set_shipping_address ----------------------------------------------

    @mcp.tool(
        name="c_set_shipping_address",
        description=(
            "Set the shipping address on the cart. "
            "Returns available shipping methods for the address."
        ),
        annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
    )
    async def c_set_shipping_address(
        cart_id: str,
        firstname: str,
        lastname: str,
        street: list[str],
        city: str,
        region: str,
        postcode: str,
        country_code: str,
        telephone: str,
        store_scope: str = "default",
    ) -> dict[str, Any]:
        """Set shipping address on cart."""
        inp = SetAddressInput(
            cart_id=cart_id, firstname=firstname, lastname=lastname,
            street=street, city=city, region=region, postcode=postcode,
            country_code=country_code, telephone=telephone, store_scope=store_scope,
        )
        log.info("c_set_shipping_address cart=%s", inp.cart_id)
        async with GraphQLClient.from_env() as client:
            data = await client.query(
                SET_SHIPPING_ADDRESS_MUTATION,
                variables={"cartId": inp.cart_id, "address": _address_variables(inp)},
                store_code=inp.store_scope,
            )
        return data["setShippingAddressesOnCart"]["cart"]

    # -- c_set_billing_address -----------------------------------------------

    @mcp.tool(
        name="c_set_billing_address",
        description="Set the billing address on the cart.",
        annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
    )
    async def c_set_billing_address(
        cart_id: str,
        firstname: str,
        lastname: str,
        street: list[str],
        city: str,
        region: str,
        postcode: str,
        country_code: str,
        telephone: str,
        store_scope: str = "default",
    ) -> dict[str, Any]:
        """Set billing address on cart."""
        inp = SetAddressInput(
            cart_id=cart_id, firstname=firstname, lastname=lastname,
            street=street, city=city, region=region, postcode=postcode,
            country_code=country_code, telephone=telephone, store_scope=store_scope,
        )
        log.info("c_set_billing_address cart=%s", inp.cart_id)
        async with GraphQLClient.from_env() as client:
            data = await client.query(
                SET_BILLING_ADDRESS_MUTATION,
                variables={"cartId": inp.cart_id, "address": _address_variables(inp)},
                store_code=inp.store_scope,
            )
        return data["setBillingAddressOnCart"]["cart"]

    # -- c_set_shipping_method -----------------------------------------------

    @mcp.tool(
        name="c_set_shipping_method",
        description="Set the shipping method on the cart (e.g., flatrate/flatrate).",
        annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
    )
    async def c_set_shipping_method(
        cart_id: str,
        carrier_code: str,
        method_code: str,
        store_scope: str = "default",
    ) -> dict[str, Any]:
        """Set shipping method on cart."""
        inp = SetShippingMethodInput(
            cart_id=cart_id, carrier_code=carrier_code,
            method_code=method_code, store_scope=store_scope,
        )
        log.info("c_set_shipping_method cart=%s %s/%s", inp.cart_id, inp.carrier_code, inp.method_code)
        async with GraphQLClient.from_env() as client:
            data = await client.query(
                SET_SHIPPING_METHOD_MUTATION,
                variables={
                    "cartId": inp.cart_id,
                    "carrierCode": inp.carrier_code,
                    "methodCode": inp.method_code,
                },
                store_code=inp.store_scope,
            )
        return data["setShippingMethodsOnCart"]["cart"]

    # -- c_set_payment_method ------------------------------------------------

    @mcp.tool(
        name="c_set_payment_method",
        description="Set the payment method on the cart (default: checkmo).",
        annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
    )
    async def c_set_payment_method(
        cart_id: str,
        payment_method_code: str = "checkmo",
        store_scope: str = "default",
    ) -> dict[str, Any]:
        """Set payment method on cart."""
        inp = SetPaymentMethodInput(
            cart_id=cart_id, payment_method_code=payment_method_code,
            store_scope=store_scope,
        )
        log.info("c_set_payment_method cart=%s code=%s", inp.cart_id, inp.payment_method_code)
        async with GraphQLClient.from_env() as client:
            data = await client.query(
                SET_PAYMENT_METHOD_MUTATION,
                variables={"cartId": inp.cart_id, "code": inp.payment_method_code},
                store_code=inp.store_scope,
            )
        return data["setPaymentMethodOnCart"]["cart"]

    # -- c_place_order -------------------------------------------------------

    @mcp.tool(
        name="c_place_order",
        description=(
            "Place the order. Requires cart to have items, addresses, shipping method, "
            "payment method, and guest email set. Returns the order number."
        ),
        annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True},
    )
    async def c_place_order(
        cart_id: str,
        store_scope: str = "default",
    ) -> dict[str, Any]:
        """Place the order."""
        inp = CartInput(cart_id=cart_id, store_scope=store_scope)
        log.info("c_place_order cart=%s", inp.cart_id)
        async with GraphQLClient.from_env() as client:
            data = await client.query(
                PLACE_ORDER_MUTATION,
                variables={"cartId": inp.cart_id},
                store_code=inp.store_scope,
            )

        result = data["placeOrder"]
        errors = result.get("errors") or []
        if errors:
            return {"error": errors[0]["message"], "code": errors[0].get("code")}

        order = result["order"]
        return PlaceOrderResult(order_number=order["order_number"]).model_dump(mode="json")
