"""Tests for admin_get_order tool."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from magemcp.connectors.magento import MagentoClient, MagentoNotFoundError
from magemcp.models.order import (
    CGetOrderInput,
    mask_email,
    mask_name,
    mask_phone,
    mask_street,
)
from magemcp.tools.admin.get_order import (
    _extract_shipping_address,
    _extract_shipping_method,
    _parse_address,
    _parse_items,
    _parse_shipments,
    _parse_status_history,
    parse_order,
)

BASE_URL = "https://magento.test"
TOKEN = "test-token-123"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_rest_order(
    *,
    increment_id: str = "000000001",
    entity_id: int = 1,
    state: str = "processing",
    status: str = "processing",
    created_at: str = "2025-06-15 10:30:00",
    updated_at: str = "2025-06-15 11:00:00",
    customer_email: str = "jane.doe@example.com",
    customer_firstname: str = "Jane",
    customer_lastname: str = "Doe",
    grand_total: float = 129.99,
    subtotal: float = 109.99,
    tax_amount: float = 10.00,
    discount_amount: float = 0.0,
    shipping_amount: float = 10.00,
    order_currency_code: str = "USD",
    total_qty_ordered: float = 2.0,
    shipping_description: str = "Flat Rate - Fixed",
    items: list[dict[str, Any]] | None = None,
    billing_address: dict[str, Any] | None = None,
    status_histories: list[dict[str, Any]] | None = None,
    shipping_assignments: list[dict[str, Any]] | None = None,
    shipments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a mock Magento REST order response."""
    if items is None:
        items = [
            {
                "sku": "WJ12-M-Blue",
                "name": "Stellar Running Jacket",
                "qty_ordered": 1,
                "price": 89.99,
                "row_total": 89.99,
                "parent_item_id": None,
            },
            {
                "sku": "WT03-S-Red",
                "name": "Training Top",
                "qty_ordered": 1,
                "price": 20.00,
                "row_total": 20.00,
                "parent_item_id": None,
            },
        ]

    if billing_address is None:
        billing_address = {
            "firstname": "Jane",
            "lastname": "Doe",
            "street": ["123 Main St", "Apt 4"],
            "city": "Austin",
            "region": "Texas",
            "postcode": "78701",
            "country_id": "US",
            "telephone": "512-555-1234",
        }

    if status_histories is None:
        status_histories = [
            {
                "comment": "Order placed via web.",
                "status": "pending",
                "created_at": "2025-06-15 10:30:00",
                "is_customer_notified": True,
                "is_visible_on_front": True,
            },
        ]

    shipping_addr = {
        "firstname": "Jane",
        "lastname": "Doe",
        "street": ["123 Main St", "Apt 4"],
        "city": "Austin",
        "region": "Texas",
        "postcode": "78701",
        "country_id": "US",
        "telephone": "512-555-1234",
    }

    if shipping_assignments is None:
        shipping_assignments = [
            {
                "shipping": {
                    "address": shipping_addr,
                    "method": "flatrate_flatrate",
                },
                "items": items,
            },
        ]

    ext: dict[str, Any] = {"shipping_assignments": shipping_assignments}
    if shipments is not None:
        ext["shipments"] = shipments

    return {
        "entity_id": entity_id,
        "increment_id": increment_id,
        "state": state,
        "status": status,
        "created_at": created_at,
        "updated_at": updated_at,
        "customer_email": customer_email,
        "customer_firstname": customer_firstname,
        "customer_lastname": customer_lastname,
        "grand_total": grand_total,
        "subtotal": subtotal,
        "tax_amount": tax_amount,
        "discount_amount": discount_amount,
        "shipping_amount": shipping_amount,
        "order_currency_code": order_currency_code,
        "total_qty_ordered": total_qty_ordered,
        "shipping_description": shipping_description,
        "items": items,
        "billing_address": billing_address,
        "status_histories": status_histories,
        "extension_attributes": ext,
        "payment": {
            "method": "checkmo",
            "additional_information": ["Check / Money order"],
        },
    }


def _wrap_rest_response(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Wrap order items in the REST search response envelope."""
    return {
        "items": items,
        "search_criteria": {},
        "total_count": len(items),
    }


# ---------------------------------------------------------------------------
# PII masking helpers (still tested — they live in models/order.py)
# ---------------------------------------------------------------------------


class TestMaskEmail:
    def test_standard_email(self) -> None:
        assert mask_email("jane.doe@example.com") == "j***@e***.com"

    def test_short_email(self) -> None:
        assert mask_email("a@b.co") == "a***@b***.co"

    def test_none(self) -> None:
        assert mask_email(None) is None

    def test_empty(self) -> None:
        assert mask_email("") is None

    def test_malformed(self) -> None:
        assert mask_email("notanemail") == "***@***.***"


class TestMaskPhone:
    def test_standard_phone(self) -> None:
        assert mask_phone("512-555-1234") == "***-***-1234"

    def test_international(self) -> None:
        assert mask_phone("+1 (512) 555-1234") == "***-***-1234"

    def test_short_number(self) -> None:
        assert mask_phone("1234") == "***"

    def test_none(self) -> None:
        assert mask_phone(None) is None

    def test_empty(self) -> None:
        assert mask_phone("") is None


class TestMaskName:
    def test_standard(self) -> None:
        assert mask_name("Jane", "Doe") == "J. D."

    def test_none_first(self) -> None:
        assert mask_name(None, "Doe") == "?. D."

    def test_none_last(self) -> None:
        assert mask_name("Jane", None) == "J. ?."

    def test_both_none(self) -> None:
        assert mask_name(None, None) == "?. ?."


class TestMaskStreet:
    def test_standard(self) -> None:
        assert mask_street(["123 Main St", "Apt 4"]) == ["[REDACTED]"]

    def test_none(self) -> None:
        assert mask_street(None) is None

    def test_empty(self) -> None:
        assert mask_street([]) is None


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_valid_input(self) -> None:
        inp = CGetOrderInput(increment_id="000000001")
        assert inp.increment_id == "000000001"
        assert inp.store_scope == "default"

    def test_empty_increment_id_rejected(self) -> None:
        with pytest.raises(Exception):
            CGetOrderInput(increment_id="")

    def test_increment_id_too_long(self) -> None:
        with pytest.raises(Exception):
            CGetOrderInput(increment_id="x" * 33)

    def test_invalid_store_scope(self) -> None:
        with pytest.raises(Exception):
            CGetOrderInput(increment_id="000000001", store_scope="INVALID!")


# ---------------------------------------------------------------------------
# _parse_address (admin — always full)
# ---------------------------------------------------------------------------


class TestParseAddress:
    def test_full_address(self) -> None:
        raw = {
            "firstname": "Jane",
            "lastname": "Doe",
            "street": ["123 Main St"],
            "city": "Austin",
            "region": "Texas",
            "postcode": "78701",
            "country_id": "US",
            "telephone": "512-555-1234",
        }
        result = _parse_address(raw)
        assert result is not None
        assert result.street == ["123 Main St"]
        assert result.telephone == "512-555-1234"
        assert result.firstname == "Jane"
        assert result.lastname == "Doe"
        assert result.city == "Austin"
        assert result.country_id == "US"

    def test_none_input(self) -> None:
        assert _parse_address(None) is None


# ---------------------------------------------------------------------------
# _parse_items
# ---------------------------------------------------------------------------


class TestParseItems:
    def test_basic_items(self) -> None:
        raw = [
            {"sku": "SKU1", "name": "Item 1", "qty_ordered": 2, "price": 10.0, "row_total": 20.0},
            {"sku": "SKU2", "name": "Item 2", "qty_ordered": 1, "price": 5.0, "row_total": 5.0},
        ]
        items = _parse_items(raw)
        assert len(items) == 2
        assert items[0].sku == "SKU1"
        assert items[1].row_total == 5.0

    def test_child_items_skipped(self) -> None:
        raw = [
            {"sku": "PARENT", "name": "Configurable", "qty_ordered": 1, "price": 50.0, "row_total": 50.0, "parent_item_id": None},
            {"sku": "CHILD-M", "name": "Configurable - M", "qty_ordered": 1, "price": 50.0, "row_total": 50.0, "parent_item_id": 1},
        ]
        items = _parse_items(raw)
        assert len(items) == 1
        assert items[0].sku == "PARENT"

    def test_empty(self) -> None:
        assert _parse_items([]) == []


# ---------------------------------------------------------------------------
# _parse_shipments
# ---------------------------------------------------------------------------


class TestParseShipments:
    def test_with_tracks(self) -> None:
        order = {
            "extension_attributes": {
                "shipments": [
                    {
                        "tracks": [
                            {"track_number": "1Z999AA10", "carrier_code": "ups", "title": "UPS Ground"},
                        ],
                    },
                ],
            },
        }
        shipments = _parse_shipments(order)
        assert len(shipments) == 1
        assert shipments[0].tracks[0].track_number == "1Z999AA10"
        assert shipments[0].tracks[0].carrier_code == "ups"

    def test_no_shipments(self) -> None:
        order: dict[str, Any] = {"extension_attributes": {}}
        assert _parse_shipments(order) == []

    def test_no_extension_attributes(self) -> None:
        order: dict[str, Any] = {}
        assert _parse_shipments(order) == []


# ---------------------------------------------------------------------------
# _parse_status_history
# ---------------------------------------------------------------------------


class TestParseStatusHistory:
    def test_returns_all_entries(self) -> None:
        """Admin view returns all status history entries."""
        raw = [
            {"comment": f"Comment {i}", "status": "processing", "created_at": f"2025-06-1{i}"}
            for i in range(5)
        ]
        result = _parse_status_history(raw)
        assert len(result) == 5
        assert result[0].comment == "Comment 0"

    def test_empty(self) -> None:
        assert _parse_status_history([]) == []

    def test_parses_fields(self) -> None:
        raw = [
            {
                "comment": "Shipped",
                "status": "complete",
                "created_at": "2025-06-16 08:00:00",
                "is_customer_notified": True,
                "is_visible_on_front": False,
            },
        ]
        result = _parse_status_history(raw)
        assert result[0].comment == "Shipped"
        assert result[0].status == "complete"
        assert result[0].is_customer_notified is True
        assert result[0].is_visible_on_front is False


# ---------------------------------------------------------------------------
# _extract_shipping_method
# ---------------------------------------------------------------------------


class TestExtractShippingMethod:
    def test_present(self) -> None:
        order = {"shipping_description": "Flat Rate - Fixed"}
        assert _extract_shipping_method(order) == "Flat Rate - Fixed"

    def test_missing(self) -> None:
        assert _extract_shipping_method({}) is None

    def test_empty_string(self) -> None:
        assert _extract_shipping_method({"shipping_description": ""}) is None


# ---------------------------------------------------------------------------
# _extract_shipping_address
# ---------------------------------------------------------------------------


class TestExtractShippingAddress:
    def test_present(self) -> None:
        order = _make_rest_order()
        addr = _extract_shipping_address(order)
        assert addr is not None
        assert addr["city"] == "Austin"

    def test_no_assignments(self) -> None:
        order = {"extension_attributes": {"shipping_assignments": []}}
        assert _extract_shipping_address(order) is None

    def test_no_ext(self) -> None:
        assert _extract_shipping_address({}) is None


# ---------------------------------------------------------------------------
# parse_order — admin always returns full data
# ---------------------------------------------------------------------------


class TestParseOrderFull:
    def test_basic_full(self) -> None:
        order = _make_rest_order()
        result = parse_order(order)

        assert result.increment_id == "000000001"
        assert result.state == "processing"
        assert result.status == "processing"
        assert result.pii_mode == "full"

        # Full PII — not masked
        assert result.customer_name == "Jane Doe"
        assert result.customer_email == "jane.doe@example.com"

        # Totals
        assert result.grand_total == 129.99
        assert result.subtotal == 109.99
        assert result.currency_code == "USD"

        # Items
        assert len(result.items) == 2
        assert result.items[0].sku == "WJ12-M-Blue"

        # Addresses — full data
        assert result.billing_address is not None
        assert result.billing_address.street == ["123 Main St", "Apt 4"]
        assert result.billing_address.telephone == "512-555-1234"
        assert result.billing_address.firstname == "Jane"

        assert result.shipping_address is not None
        assert result.shipping_address.street == ["123 Main St", "Apt 4"]

    def test_shipping_method(self) -> None:
        order = _make_rest_order()
        result = parse_order(order)
        assert result.shipping_method == "Flat Rate - Fixed"

    def test_missing_customer_name(self) -> None:
        order = _make_rest_order(customer_firstname=None, customer_lastname=None)  # type: ignore[arg-type]
        result = parse_order(order)
        assert result.customer_name == "Unknown"

    def test_payment_info(self) -> None:
        order = _make_rest_order()
        result = parse_order(order)
        assert result.payment_method == "checkmo"
        assert result.payment_additional == ["Check / Money order"]

    def test_invoice_and_credit_memo_ids(self) -> None:
        order = _make_rest_order()
        # Add invoices and credit memos to extension_attributes
        order["extension_attributes"]["invoices"] = [
            {"entity_id": 1}, {"entity_id": 2},
        ]
        order["extension_attributes"]["credit_memos"] = [
            {"entity_id": 10},
        ]
        result = parse_order(order)
        assert result.invoice_ids == [1, 2]
        assert result.credit_memo_ids == [10]

    def test_no_payment(self) -> None:
        order = _make_rest_order()
        del order["payment"]
        result = parse_order(order)
        assert result.payment_method is None
        assert result.payment_additional == []


# ---------------------------------------------------------------------------
# Admin tool returns full PII — explicit verification
# ---------------------------------------------------------------------------


class TestAdminGetOrderReturnsFullPii:
    def test_email_not_masked(self) -> None:
        order = _make_rest_order(customer_email="jane.doe@example.com")
        result = parse_order(order)
        assert result.customer_email == "jane.doe@example.com"
        assert "***" not in (result.customer_email or "")

    def test_name_not_masked(self) -> None:
        order = _make_rest_order(customer_firstname="Jane", customer_lastname="Doe")
        result = parse_order(order)
        assert result.customer_name == "Jane Doe"

    def test_phone_not_masked(self) -> None:
        order = _make_rest_order()
        result = parse_order(order)
        assert result.billing_address is not None
        assert result.billing_address.telephone == "512-555-1234"

    def test_address_not_masked(self) -> None:
        order = _make_rest_order()
        result = parse_order(order)
        assert result.billing_address is not None
        assert result.billing_address.street == ["123 Main St", "Apt 4"]
        assert result.billing_address.firstname == "Jane"
        assert result.billing_address.lastname == "Doe"


# ---------------------------------------------------------------------------
# parse_order — with shipments
# ---------------------------------------------------------------------------


class TestParseOrderWithShipments:
    def test_shipment_tracks(self) -> None:
        order = _make_rest_order(
            shipments=[
                {
                    "tracks": [
                        {"track_number": "1Z999AA10", "carrier_code": "ups", "title": "UPS Ground"},
                    ],
                },
            ],
        )
        result = parse_order(order)
        assert len(result.shipments) == 1
        assert result.shipments[0].tracks[0].track_number == "1Z999AA10"


# ---------------------------------------------------------------------------
# End-to-end tool invocation (mocked REST)
# ---------------------------------------------------------------------------


class TestToolEndToEnd:
    @respx.mock
    async def test_get_order_full(self) -> None:
        """Full tool invocation — admin always returns full data."""
        order = _make_rest_order()
        rest_response = _wrap_rest_response([order])
        route = respx.get(f"{BASE_URL}/rest/default/V1/orders").mock(
            return_value=httpx.Response(200, json=rest_response),
        )

        async with MagentoClient(base_url=BASE_URL, token=TOKEN) as client:
            params = MagentoClient.search_params(
                filters={"increment_id": "000000001"},
                page_size=1,
            )
            data = await client.get("/V1/orders", params=params)

        items = data.get("items") or []
        assert len(items) == 1

        result = parse_order(items[0])
        assert result.increment_id == "000000001"
        assert result.customer_email == "jane.doe@example.com"
        assert result.customer_name == "Jane Doe"
        assert result.billing_address is not None
        assert result.billing_address.firstname == "Jane"
        assert route.called

    @respx.mock
    async def test_get_order_store_scope(self) -> None:
        """Verify store scope is sent in the REST URL."""
        order = _make_rest_order()
        rest_response = _wrap_rest_response([order])
        route = respx.get(f"{BASE_URL}/rest/fr/V1/orders").mock(
            return_value=httpx.Response(200, json=rest_response),
        )

        async with MagentoClient(base_url=BASE_URL, token=TOKEN) as client:
            await client.get(
                "/V1/orders",
                params=MagentoClient.search_params(
                    filters={"increment_id": "000000001"}, page_size=1,
                ),
                store_code="fr",
            )

        assert route.called

    @respx.mock
    async def test_order_not_found(self) -> None:
        """Empty items list means order not found."""
        rest_response = _wrap_rest_response([])
        respx.get(f"{BASE_URL}/rest/default/V1/orders").mock(
            return_value=httpx.Response(200, json=rest_response),
        )

        async with MagentoClient(base_url=BASE_URL, token=TOKEN) as client:
            data = await client.get(
                "/V1/orders",
                params=MagentoClient.search_params(
                    filters={"increment_id": "NOPE"}, page_size=1,
                ),
            )

        items = data.get("items") or []
        assert items == []

    @respx.mock
    async def test_401_raises(self) -> None:
        """401 should raise MagentoAuthError."""
        from magemcp.connectors.magento import MagentoAuthError

        respx.get(f"{BASE_URL}/rest/default/V1/orders").mock(
            return_value=httpx.Response(
                401, json={"message": "Consumer is not authorized"},
            ),
        )

        async with MagentoClient(base_url=BASE_URL, token=TOKEN) as client:
            with pytest.raises(MagentoAuthError, match="Consumer is not authorized"):
                await client.get(
                    "/V1/orders",
                    params=MagentoClient.search_params(
                        filters={"increment_id": "000000001"}, page_size=1,
                    ),
                )


# ---------------------------------------------------------------------------
# Output serialization
# ---------------------------------------------------------------------------


class TestOutputSerialization:
    def test_model_dump_json(self) -> None:
        """Verify that the output serializes cleanly to JSON-compatible dict."""
        order = _make_rest_order(
            shipments=[
                {"tracks": [{"track_number": "1Z999", "carrier_code": "ups", "title": "UPS"}]},
            ],
        )
        result = parse_order(order)
        dumped = result.model_dump(mode="json")

        assert isinstance(dumped, dict)
        assert dumped["increment_id"] == "000000001"
        assert dumped["pii_mode"] == "full"
        assert dumped["customer_name"] == "Jane Doe"
        assert dumped["customer_email"] == "jane.doe@example.com"
        assert isinstance(dumped["items"], list)
        assert len(dumped["items"]) == 2
        assert dumped["items"][0]["sku"] == "WJ12-M-Blue"
        assert dumped["billing_address"]["street"] == ["123 Main St", "Apt 4"]
        assert len(dumped["shipments"]) == 1
        assert dumped["shipments"][0]["tracks"][0]["track_number"] == "1Z999"
