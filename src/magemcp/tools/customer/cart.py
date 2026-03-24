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


async def c_create_cart(
    store_scope: str = "default",
) -> dict[str, Any]:
    """Create a guest cart."""
    log.info("c_create_cart store=%s", store_scope)
    async with GraphQLClient.from_env() as client:
        data = await client.query(CREATE_CART_MUTATION, store_code=store_scope)
    cart_id = data["createGuestCart"]["cart"]["id"]
    return {"cart_id": cart_id}


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
        raise MagentoError(user_errors[0]["message"])

    return _parse_cart(result["cart"])


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
        raise MagentoError(errors[0]["message"])

    order = result["order"]
    return PlaceOrderResult(order_number=order["order_number"]).model_dump(mode="json")


def register_cart_tools(mcp: FastMCP) -> None:
    """Register all cart tools on the given MCP server."""
    mcp.tool(
        name="c_create_cart",
        title="Create Cart",
        description=(
            "Start a new guest checkout session by creating an empty cart. "
            "Must be called first before any other cart operation. "
            "Returns a cart_id (opaque string) used by all subsequent c_* cart tools."
        ),
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
    )(c_create_cart)

    mcp.tool(
        name="c_get_cart",
        title="Get Cart",
        description=(
            "Read the current state of a cart: line items with SKU/qty/price, "
            "grand_total, subtotal, applied coupon codes, shipping address with available shipping methods, "
            "selected shipping method, and selected payment method. "
            "Use after any mutation to confirm the cart state before proceeding."
        ),
        annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    )(c_get_cart)

    mcp.tool(
        name="c_add_to_cart",
        title="Add to Cart",
        description=(
            "Add a product to the cart by SKU. Use c_search_products or c_get_product to obtain the SKU first. "
            "quantity defaults to 1. Returns the full updated cart state. "
            "Raises an error if the SKU is out of stock or not purchasable as a guest."
        ),
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
    )(c_add_to_cart)

    mcp.tool(
        name="c_update_cart_item",
        title="Update Cart Item",
        description=(
            "Change the quantity of a cart line item, or remove it entirely. "
            "cart_item_uid comes from the items[].uid field in c_get_cart response. "
            "Set quantity=0 to remove the item from the cart. Returns updated cart state."
        ),
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
    )(c_update_cart_item)

    mcp.tool(
        name="c_apply_coupon",
        title="Apply Coupon",
        description=(
            "Apply a coupon code to the cart to activate a discount. "
            "Use admin_search_sales_rules to find valid coupon codes if needed. "
            "Returns updated cart with applied_coupons and recalculated prices."
        ),
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
    )(c_apply_coupon)

    mcp.tool(
        name="c_set_guest_email",
        title="Set Guest Email",
        description=(
            "Set the contact email for a guest checkout. "
            "Required step before c_place_order — Magento will not place the order without it. "
            "Should be called after adding items and before setting addresses."
        ),
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
    )(c_set_guest_email)

    mcp.tool(
        name="c_set_shipping_address",
        title="Set Shipping Address",
        description=(
            "Set the delivery address on the cart. "
            "street is a list of address lines (e.g. ['123 Main St', 'Apt 4']). "
            "country_code is ISO 3166-1 alpha-2 (e.g. 'US', 'DE'). "
            "Returns available_shipping_methods with carrier_code, method_code, and price — "
            "use these values with c_set_shipping_method."
        ),
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
    )(c_set_shipping_address)

    mcp.tool(
        name="c_set_billing_address",
        title="Set Billing Address",
        description=(
            "Set the billing address on the cart. "
            "Required before c_place_order. Often the same as the shipping address. "
            "Same field format as c_set_shipping_address (street list, ISO country_code)."
        ),
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
    )(c_set_billing_address)

    mcp.tool(
        name="c_set_shipping_method",
        title="Set Shipping Method",
        description=(
            "Select a shipping method for the cart. "
            "carrier_code and method_code come from available_shipping_methods returned by c_set_shipping_address "
            "(e.g. carrier_code='flatrate', method_code='flatrate'). "
            "Must be called after c_set_shipping_address and before c_place_order."
        ),
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
    )(c_set_shipping_method)

    mcp.tool(
        name="c_set_payment_method",
        title="Set Payment Method",
        description=(
            "Select a payment method for the cart. "
            "payment_method_code defaults to 'checkmo' (check/money order). "
            "Other common codes: 'free' (zero-total orders), 'purchaseorder'. "
            "Must be called after addresses and shipping are set, before c_place_order."
        ),
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
    )(c_set_payment_method)

    mcp.tool(
        name="c_place_order",
        title="Place Order",
        description=(
            "Submit the cart as a confirmed order. "
            "All prerequisites must be complete: items added, guest email set, "
            "shipping address set, shipping method selected, billing address set, payment method set. "
            "Returns order_number (the customer-facing increment ID, e.g. '000000042'). "
            "This is irreversible — use admin_cancel_order if the order needs to be cancelled after placement."
        ),
        annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True},
    )(c_place_order)
