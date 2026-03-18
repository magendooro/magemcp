"""Tests for c_get_customer tool."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from magemcp.connectors.magento import MagentoClient, MagentoNotFoundError
from magemcp.models.customer import CGetCustomerInput, CGetCustomerOutput
from magemcp.tools.get_customer import parse_customer

BASE_URL = "https://magento.test"
TOKEN = "test-token-123"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_rest_customer(
    *,
    customer_id: int = 42,
    group_id: int = 1,
    store_id: int = 1,
    website_id: int = 1,
    created_at: str = "2025-01-10 08:00:00",
    updated_at: str = "2025-06-15 12:00:00",
    email: str = "jane.doe@example.com",
    firstname: str = "Jane",
    lastname: str = "Doe",
    dob: str | None = "1990-05-15",
    gender: int = 2,
    default_billing: str | None = "10",
    default_shipping: str | None = "11",
) -> dict[str, Any]:
    """Build a mock Magento REST customer response."""
    return {
        "id": customer_id,
        "group_id": group_id,
        "store_id": store_id,
        "website_id": website_id,
        "created_at": created_at,
        "updated_at": updated_at,
        "email": email,
        "firstname": firstname,
        "lastname": lastname,
        "dob": dob,
        "gender": gender,
        "default_billing": default_billing,
        "default_shipping": default_shipping,
    }


def _wrap_search_response(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Wrap customer items in the REST search response envelope."""
    return {
        "items": items,
        "search_criteria": {},
        "total_count": len(items),
    }


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_valid_by_id(self) -> None:
        inp = CGetCustomerInput(customer_id=42)
        assert inp.customer_id == 42
        assert inp.email is None
        assert inp.store_scope == "default"
        assert inp.pii_mode == "redacted"

    def test_valid_by_email(self) -> None:
        inp = CGetCustomerInput(email="jane@example.com")
        assert inp.email == "jane@example.com"
        assert inp.customer_id is None

    def test_valid_both(self) -> None:
        inp = CGetCustomerInput(customer_id=42, email="jane@example.com")
        assert inp.customer_id == 42
        assert inp.email == "jane@example.com"

    def test_neither_id_nor_email_rejected(self) -> None:
        with pytest.raises(Exception):
            CGetCustomerInput()

    def test_invalid_customer_id_zero(self) -> None:
        with pytest.raises(Exception):
            CGetCustomerInput(customer_id=0)

    def test_invalid_customer_id_negative(self) -> None:
        with pytest.raises(Exception):
            CGetCustomerInput(customer_id=-1)

    def test_full_pii_mode(self) -> None:
        inp = CGetCustomerInput(customer_id=1, pii_mode="full")
        assert inp.pii_mode == "full"

    def test_invalid_pii_mode(self) -> None:
        with pytest.raises(Exception):
            CGetCustomerInput(customer_id=1, pii_mode="partial")  # type: ignore[arg-type]

    def test_invalid_store_scope(self) -> None:
        with pytest.raises(Exception):
            CGetCustomerInput(customer_id=1, store_scope="INVALID!")

    def test_website_id_default(self) -> None:
        inp = CGetCustomerInput(email="jane@example.com")
        assert inp.website_id == 1

    def test_custom_website_id(self) -> None:
        inp = CGetCustomerInput(email="jane@example.com", website_id=2)
        assert inp.website_id == 2


# ---------------------------------------------------------------------------
# parse_customer — redacted mode
# ---------------------------------------------------------------------------


class TestParseCustomerRedacted:
    def test_basic_redacted(self) -> None:
        raw = _make_rest_customer()
        result = parse_customer(raw, redact=True)

        assert result.customer_id == 42
        assert result.group_id == 1
        assert result.pii_mode == "redacted"

        # PII should be masked
        assert result.email == "j***@e***.com"
        assert result.firstname == "J."
        assert result.lastname == "D."
        assert result.dob == "***"

        # Non-PII should be present
        assert result.created_at == "2025-01-10 08:00:00"
        assert result.gender == 2
        assert result.default_billing_id == "10"
        assert result.default_shipping_id == "11"

    def test_no_dob_redacted(self) -> None:
        raw = _make_rest_customer(dob=None)
        result = parse_customer(raw, redact=True)
        assert result.dob is None

    def test_missing_name_redacted(self) -> None:
        raw = _make_rest_customer(firstname=None, lastname=None)  # type: ignore[arg-type]
        result = parse_customer(raw, redact=True)
        assert result.firstname == "?."
        assert result.lastname == "?."


# ---------------------------------------------------------------------------
# parse_customer — full mode
# ---------------------------------------------------------------------------


class TestParseCustomerFull:
    def test_basic_full(self) -> None:
        raw = _make_rest_customer()
        result = parse_customer(raw, redact=False)

        assert result.pii_mode == "full"
        assert result.email == "jane.doe@example.com"
        assert result.firstname == "Jane"
        assert result.lastname == "Doe"
        assert result.dob == "1990-05-15"

    def test_missing_optional_fields(self) -> None:
        raw = _make_rest_customer(default_billing=None, default_shipping=None, dob=None)
        result = parse_customer(raw, redact=False)
        assert result.default_billing_id is None
        assert result.default_shipping_id is None
        assert result.dob is None


# ---------------------------------------------------------------------------
# End-to-end tool invocation (mocked REST)
# ---------------------------------------------------------------------------


class TestToolEndToEnd:
    @respx.mock
    async def test_get_customer_by_id_redacted(self) -> None:
        """Fetch by customer ID with redacted PII."""
        customer = _make_rest_customer()
        route = respx.get(f"{BASE_URL}/rest/default/V1/customers/42").mock(
            return_value=httpx.Response(200, json=customer),
        )

        async with MagentoClient(base_url=BASE_URL, token=TOKEN) as client:
            data = await client.get("/V1/customers/42")

        result = parse_customer(data, redact=True)
        assert result.customer_id == 42
        assert result.email == "j***@e***.com"
        assert result.firstname == "J."
        assert route.called

    @respx.mock
    async def test_get_customer_by_email(self) -> None:
        """Fetch by email via search endpoint."""
        customer = _make_rest_customer()
        search_response = _wrap_search_response([customer])
        route = respx.get(f"{BASE_URL}/rest/default/V1/customers/search").mock(
            return_value=httpx.Response(200, json=search_response),
        )

        async with MagentoClient(base_url=BASE_URL, token=TOKEN) as client:
            params = MagentoClient.search_params(
                filters={"email": "jane.doe@example.com", "website_id": 1},
                page_size=1,
            )
            data = await client.get("/V1/customers/search", params=params)

        items = data.get("items") or []
        assert len(items) == 1

        result = parse_customer(items[0], redact=True)
        assert result.customer_id == 42
        assert result.email == "j***@e***.com"
        assert route.called

    @respx.mock
    async def test_get_customer_store_scope(self) -> None:
        """Verify store scope is sent in the REST URL."""
        customer = _make_rest_customer()
        route = respx.get(f"{BASE_URL}/rest/fr/V1/customers/42").mock(
            return_value=httpx.Response(200, json=customer),
        )

        async with MagentoClient(base_url=BASE_URL, token=TOKEN) as client:
            await client.get("/V1/customers/42", store_code="fr")

        assert route.called

    @respx.mock
    async def test_customer_not_found_by_email(self) -> None:
        """Empty search results means customer not found."""
        search_response = _wrap_search_response([])
        respx.get(f"{BASE_URL}/rest/default/V1/customers/search").mock(
            return_value=httpx.Response(200, json=search_response),
        )

        async with MagentoClient(base_url=BASE_URL, token=TOKEN) as client:
            params = MagentoClient.search_params(
                filters={"email": "nobody@example.com", "website_id": 1},
                page_size=1,
            )
            data = await client.get("/V1/customers/search", params=params)

        items = data.get("items") or []
        assert items == []

    @respx.mock
    async def test_customer_not_found_by_id_404(self) -> None:
        """404 from direct ID lookup raises MagentoNotFoundError."""
        respx.get(f"{BASE_URL}/rest/default/V1/customers/999").mock(
            return_value=httpx.Response(
                404, json={"message": "No such entity with customerId = 999"},
            ),
        )

        async with MagentoClient(base_url=BASE_URL, token=TOKEN) as client:
            with pytest.raises(MagentoNotFoundError, match="No such entity"):
                await client.get("/V1/customers/999")

    @respx.mock
    async def test_get_customer_full_pii(self) -> None:
        """Full PII mode returns unmasked data."""
        customer = _make_rest_customer()
        respx.get(f"{BASE_URL}/rest/default/V1/customers/42").mock(
            return_value=httpx.Response(200, json=customer),
        )

        async with MagentoClient(base_url=BASE_URL, token=TOKEN) as client:
            data = await client.get("/V1/customers/42")

        result = parse_customer(data, redact=False)
        assert result.email == "jane.doe@example.com"
        assert result.firstname == "Jane"
        assert result.lastname == "Doe"


# ---------------------------------------------------------------------------
# Output serialization
# ---------------------------------------------------------------------------


class TestOutputSerialization:
    def test_model_dump_json(self) -> None:
        """Verify that the output serializes cleanly to JSON-compatible dict."""
        raw = _make_rest_customer()
        result = parse_customer(raw, redact=True)
        dumped = result.model_dump(mode="json")

        assert isinstance(dumped, dict)
        assert dumped["customer_id"] == 42
        assert dumped["pii_mode"] == "redacted"
        assert dumped["email"] == "j***@e***.com"
        assert dumped["firstname"] == "J."
        assert dumped["lastname"] == "D."
        assert dumped["dob"] == "***"
        assert dumped["group_id"] == 1
        assert dumped["created_at"] == "2025-01-10 08:00:00"
