"""Tests for admin_get_customer tool."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from magemcp.connectors.magento import MagentoClient, MagentoNotFoundError
from magemcp.connectors.errors import MagentoNotFoundError as RestNotFoundError
from magemcp.models.customer import CGetCustomerInput, CGetCustomerOutput
from magemcp.tools.admin.get_customer import parse_customer, _parse_address, admin_get_customer

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
# parse_customer — admin always returns full data
# ---------------------------------------------------------------------------


class TestParseCustomerFull:
    def test_basic_full(self) -> None:
        raw = _make_rest_customer()
        result = parse_customer(raw)

        assert result.customer_id == 42
        assert result.group_id == 1
        assert result.pii_mode == "full"

        # Full PII — not masked
        assert result.email == "jane.doe@example.com"
        assert result.firstname == "Jane"
        assert result.lastname == "Doe"
        assert result.dob == "1990-05-15"

        # Non-PII should be present
        assert result.created_at == "2025-01-10 08:00:00"
        assert result.gender == 2
        assert result.default_billing_id == "10"
        assert result.default_shipping_id == "11"

    def test_missing_optional_fields(self) -> None:
        raw = _make_rest_customer(default_billing=None, default_shipping=None, dob=None)
        result = parse_customer(raw)
        assert result.default_billing_id is None
        assert result.default_shipping_id is None
        assert result.dob is None


# ---------------------------------------------------------------------------
# Admin tool returns full PII — explicit verification
# ---------------------------------------------------------------------------


class TestAdminGetCustomerReturnsFullData:
    def test_email_not_masked(self) -> None:
        raw = _make_rest_customer(email="jane.doe@example.com")
        result = parse_customer(raw)
        assert result.email == "jane.doe@example.com"
        assert "***" not in (result.email or "")

    def test_firstname_not_masked(self) -> None:
        raw = _make_rest_customer(firstname="Jane")
        result = parse_customer(raw)
        assert result.firstname == "Jane"

    def test_lastname_not_masked(self) -> None:
        raw = _make_rest_customer(lastname="Doe")
        result = parse_customer(raw)
        assert result.lastname == "Doe"

    def test_dob_not_masked(self) -> None:
        raw = _make_rest_customer(dob="1990-05-15")
        result = parse_customer(raw)
        assert result.dob == "1990-05-15"
        assert result.dob != "***"


# ---------------------------------------------------------------------------
# End-to-end tool invocation (mocked REST)
# ---------------------------------------------------------------------------


class TestToolEndToEnd:
    @respx.mock
    async def test_get_customer_by_id(self) -> None:
        """Fetch by customer ID — admin returns full data."""
        customer = _make_rest_customer()
        route = respx.get(f"{BASE_URL}/rest/default/V1/customers/42").mock(
            return_value=httpx.Response(200, json=customer),
        )

        async with MagentoClient(base_url=BASE_URL, token=TOKEN) as client:
            data = await client.get("/V1/customers/42")

        result = parse_customer(data)
        assert result.customer_id == 42
        assert result.email == "jane.doe@example.com"
        assert result.firstname == "Jane"
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

        result = parse_customer(items[0])
        assert result.customer_id == 42
        assert result.email == "jane.doe@example.com"
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


# ---------------------------------------------------------------------------
# Output serialization
# ---------------------------------------------------------------------------


class TestOutputSerialization:
    def test_model_dump_json(self) -> None:
        """Verify that the output serializes cleanly to JSON-compatible dict."""
        raw = _make_rest_customer()
        result = parse_customer(raw)
        dumped = result.model_dump(mode="json")

        assert isinstance(dumped, dict)
        assert dumped["customer_id"] == 42
        assert dumped["pii_mode"] == "full"
        assert dumped["email"] == "jane.doe@example.com"
        assert dumped["firstname"] == "Jane"
        assert dumped["lastname"] == "Doe"
        assert dumped["dob"] == "1990-05-15"
        assert dumped["group_id"] == 1
        assert dumped["created_at"] == "2025-01-10 08:00:00"


# ---------------------------------------------------------------------------
# _parse_address
# ---------------------------------------------------------------------------


class TestParseAddress:
    def test_full_address(self) -> None:
        raw = {
            "id": 10,
            "firstname": "Jane",
            "lastname": "Doe",
            "street": ["123 Main St", "Apt 4"],
            "city": "Springfield",
            "region": {"region": "Illinois", "region_code": "IL"},
            "postcode": "62701",
            "country_id": "US",
            "telephone": "555-1234",
            "default_billing": True,
            "default_shipping": False,
        }
        addr = _parse_address(raw)
        assert addr.id == 10
        assert addr.firstname == "Jane"
        assert addr.street == ["123 Main St", "Apt 4"]
        assert addr.city == "Springfield"
        assert addr.region == "Illinois"
        assert addr.region_code == "IL"
        assert addr.postcode == "62701"
        assert addr.country_id == "US"
        assert addr.telephone == "555-1234"
        assert addr.default_billing is True
        assert addr.default_shipping is False

    def test_region_as_string(self) -> None:
        raw = {
            "id": 11,
            "firstname": "John",
            "lastname": "Smith",
            "street": ["1 Oak Ave"],
            "city": "Portland",
            "region": "Oregon",
            "postcode": "97201",
            "country_id": "US",
            "telephone": None,
            "default_billing": False,
            "default_shipping": True,
        }
        addr = _parse_address(raw)
        assert addr.region == "Oregon"
        assert addr.region_code is None

    def test_minimal_address(self) -> None:
        raw = {"id": 1}
        addr = _parse_address(raw)
        assert addr.id == 1
        assert addr.street == []
        assert addr.default_billing is False
        assert addr.default_shipping is False


# ---------------------------------------------------------------------------
# Tool function (module-level)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAGENTO_BASE_URL", BASE_URL)
    monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", TOKEN)


class TestToolFunction:
    async def test_get_by_id(
        self, mock_env: None, respx_mock: respx.MockRouter,
    ) -> None:
        customer = _make_rest_customer()
        respx_mock.get(f"{BASE_URL}/rest/default/V1/customers/42").mock(
            return_value=httpx.Response(200, json=customer)
        )
        result = await admin_get_customer(customer_id=42)
        assert result["customer_id"] == 42
        assert result["email"] == "jane.doe@example.com"

    async def test_get_by_email(
        self, mock_env: None, respx_mock: respx.MockRouter,
    ) -> None:
        customer = _make_rest_customer()
        respx_mock.get(f"{BASE_URL}/rest/default/V1/customers/search").mock(
            return_value=httpx.Response(200, json=_wrap_search_response([customer]))
        )
        result = await admin_get_customer(email="jane.doe@example.com")
        assert result["customer_id"] == 42

    async def test_not_found_by_email(
        self, mock_env: None, respx_mock: respx.MockRouter,
    ) -> None:
        respx_mock.get(f"{BASE_URL}/rest/default/V1/customers/search").mock(
            return_value=httpx.Response(200, json=_wrap_search_response([]))
        )
        with pytest.raises(RestNotFoundError):
            await admin_get_customer(email="nobody@example.com")

    async def test_store_scope_in_url(
        self, mock_env: None, respx_mock: respx.MockRouter,
    ) -> None:
        customer = _make_rest_customer()
        route = respx_mock.get(f"{BASE_URL}/rest/fr/V1/customers/42").mock(
            return_value=httpx.Response(200, json=customer)
        )
        await admin_get_customer(customer_id=42, store_scope="fr")
        assert route.called

    async def test_addresses_parsed(
        self, mock_env: None, respx_mock: respx.MockRouter,
    ) -> None:
        customer = _make_rest_customer()
        customer["addresses"] = [{
            "id": 10,
            "firstname": "Jane",
            "lastname": "Doe",
            "street": ["1 Main St"],
            "city": "Portland",
            "region": {"region": "Oregon", "region_code": "OR"},
            "postcode": "97201",
            "country_id": "US",
            "telephone": "555-9999",
            "default_billing": True,
            "default_shipping": True,
        }]
        respx_mock.get(f"{BASE_URL}/rest/default/V1/customers/42").mock(
            return_value=httpx.Response(200, json=customer)
        )
        result = await admin_get_customer(customer_id=42)
        assert len(result["addresses"]) == 1
        assert result["addresses"][0]["city"] == "Portland"
