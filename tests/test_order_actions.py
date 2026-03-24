"""Tests for admin order action tools."""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest
import respx
from httpx import Response

from magemcp.tools.admin.order_actions import (
    admin_add_order_comment,
    admin_cancel_order,
    admin_create_invoice,
    admin_create_shipment,
    admin_hold_order,
    admin_send_order_email,
    admin_unhold_order,
)

BASE_URL = "https://magento.test"
TOKEN = "admin-token-123"
STORE_CODE = "default"


@pytest.fixture
def mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set up environment variables for RESTClient.from_env()."""
    monkeypatch.setenv("MAGENTO_BASE_URL", BASE_URL)
    monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("MAGENTO_STORE_CODE", STORE_CODE)


@pytest.mark.asyncio
async def test_cancel_requires_confirmation(mock_env: None) -> None:
    """Test that cancel requests confirmation by default."""
    result = await admin_cancel_order(order_id=123)
    assert result["confirmation_required"] is True
    assert "cancel" in result["action"]
    assert result["entity"] == "123"


@pytest.mark.asyncio
async def test_cancel_with_confirmation(mock_env: None, respx_mock: respx.MockRouter) -> None:
    """Test that cancel proceeds when confirmed."""
    respx_mock.post(f"{BASE_URL}/rest/{STORE_CODE}/V1/orders/123/cancel").mock(
        return_value=Response(200, json=True)
    )

    result = await admin_cancel_order(order_id=123, confirm=True)
    assert result["success"] is True
    assert result["action"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_skip_confirmation_env(mock_env: None, respx_mock: respx.MockRouter) -> None:
    """Test that MAGEMCP_SKIP_CONFIRMATION env var bypasses confirmation."""
    with patch.dict(os.environ, {"MAGEMCP_SKIP_CONFIRMATION": "true"}):
        respx_mock.post(f"{BASE_URL}/rest/{STORE_CODE}/V1/orders/123/cancel").mock(
            return_value=Response(200, json=True)
        )

        result = await admin_cancel_order(order_id=123)
        assert result["success"] is True


@pytest.mark.asyncio
async def test_hold_order(mock_env: None, respx_mock: respx.MockRouter) -> None:
    """Test hold order."""
    respx_mock.post(f"{BASE_URL}/rest/{STORE_CODE}/V1/orders/123/hold").mock(
        return_value=Response(200, json=True)
    )

    result = await admin_hold_order(order_id=123, confirm=True)
    assert result["success"] is True
    assert result["action"] == "held"


@pytest.mark.asyncio
async def test_unhold_order(mock_env: None, respx_mock: respx.MockRouter) -> None:
    """Test unhold order."""
    respx_mock.post(f"{BASE_URL}/rest/{STORE_CODE}/V1/orders/123/unhold").mock(
        return_value=Response(200, json=True)
    )

    result = await admin_unhold_order(order_id=123, confirm=True)
    assert result["success"] is True
    assert result["action"] == "unheld"


@pytest.mark.asyncio
async def test_add_comment(mock_env: None, respx_mock: respx.MockRouter) -> None:
    """Test adding a comment."""
    respx_mock.post(f"{BASE_URL}/rest/{STORE_CODE}/V1/orders/123/comments").mock(
        return_value=Response(200, json=True)
    )

    result = await admin_add_order_comment(
        order_id=123,
        comment="Test comment",
        is_visible_on_front=True,
        status="processing",
    )

    assert result["success"] is True
    assert result["comment"] == "Test comment"

    # Verify payload
    request = respx_mock.calls.last.request
    payload = json.loads(request.content)
    assert payload["statusHistory"]["comment"] == "Test comment"
    assert payload["statusHistory"]["is_visible_on_front"] == 1
    assert payload["statusHistory"]["is_customer_notified"] == 0
    assert payload["statusHistory"]["status"] == "processing"


@pytest.mark.asyncio
async def test_create_invoice_requires_confirmation(mock_env: None) -> None:
    """Invoice creation requires confirmation — irreversible."""
    result = await admin_create_invoice(order_id=123)
    assert result["confirmation_required"] is True
    assert "invoice" in result["action"]


@pytest.mark.asyncio
async def test_create_invoice(mock_env: None, respx_mock: respx.MockRouter) -> None:
    """Test creating an invoice with confirm=True."""
    respx_mock.post(f"{BASE_URL}/rest/{STORE_CODE}/V1/order/123/invoice").mock(
        return_value=Response(200, json="INV-001")
    )

    result = await admin_create_invoice(order_id=123, capture=True, confirm=True)
    assert result["success"] is True
    assert result["invoice_id"] == "INV-001"

    request = respx_mock.calls.last.request
    payload = json.loads(request.content)
    assert payload["capture"] is True


@pytest.mark.asyncio
async def test_create_shipment_requires_confirmation(mock_env: None) -> None:
    """Shipment creation requires confirmation — irreversible."""
    result = await admin_create_shipment(order_id=123)
    assert result["confirmation_required"] is True
    assert "shipment" in result["action"]


@pytest.mark.asyncio
async def test_create_shipment_with_tracking(
    mock_env: None, respx_mock: respx.MockRouter,
) -> None:
    """Test creating shipment with tracking and confirm=True."""
    respx_mock.post(f"{BASE_URL}/rest/{STORE_CODE}/V1/order/123/ship").mock(
        return_value=Response(200, json="SHIP-001")
    )

    result = await admin_create_shipment(
        order_id=123,
        tracking_number="TRACK123",
        carrier_code="ups",
        title="UPS Ground",
        confirm=True,
    )

    assert result["success"] is True
    assert result["shipment_id"] == "SHIP-001"

    request = respx_mock.calls.last.request
    payload = json.loads(request.content)
    assert payload["tracks"][0]["track_number"] == "TRACK123"
    assert payload["tracks"][0]["carrier_code"] == "ups"


@pytest.mark.asyncio
async def test_create_shipment_without_tracking(
    mock_env: None, respx_mock: respx.MockRouter,
) -> None:
    """Test creating shipment without tracking (confirmed)."""
    respx_mock.post(f"{BASE_URL}/rest/{STORE_CODE}/V1/order/123/ship").mock(
        return_value=Response(200, json="SHIP-002")
    )

    await admin_create_shipment(order_id=123, confirm=True)

    request = respx_mock.calls.last.request
    payload = json.loads(request.content)
    assert "tracks" not in payload


@pytest.mark.asyncio
async def test_send_order_email(mock_env: None, respx_mock: respx.MockRouter) -> None:
    """Test sending order email."""
    respx_mock.post(f"{BASE_URL}/rest/{STORE_CODE}/V1/orders/123/emails").mock(
        return_value=Response(200, json=True)
    )

    result = await admin_send_order_email(order_id=123)
    assert result["success"] is True


@pytest.mark.asyncio
async def test_hold_requires_confirmation(mock_env: None) -> None:
    result = await admin_hold_order(order_id=123, confirm=False)
    assert result.get("confirmation_required") is True
    assert "hold" in result["action"]


@pytest.mark.asyncio
async def test_unhold_requires_confirmation(mock_env: None) -> None:
    result = await admin_unhold_order(order_id=123, confirm=False)
    assert result.get("confirmation_required") is True
    assert "unhold" in result["action"]


@pytest.mark.asyncio
async def test_add_comment_with_idempotency_key(
    mock_env: None, respx_mock: respx.MockRouter,
) -> None:
    respx_mock.post(f"{BASE_URL}/rest/{STORE_CODE}/V1/orders/123/comments").mock(
        return_value=Response(200, json=True)
    )
    result = await admin_add_order_comment(
        order_id=123, comment="Test", idempotency_key="idem-001"
    )
    assert result["success"] is True
    # Second call with same key should return replay
    result2 = await admin_add_order_comment(
        order_id=123, comment="Test", idempotency_key="idem-001"
    )
    assert result2.get("idempotent_replay") is True


@pytest.mark.asyncio
async def test_create_invoice_with_idempotency_key(
    mock_env: None, respx_mock: respx.MockRouter,
) -> None:
    respx_mock.post(f"{BASE_URL}/rest/{STORE_CODE}/V1/order/123/invoice").mock(
        return_value=Response(200, json="INV-099")
    )
    result = await admin_create_invoice(
        order_id=123, confirm=True, idempotency_key="inv-001"
    )
    assert result["success"] is True
    result2 = await admin_create_invoice(
        order_id=123, confirm=True, idempotency_key="inv-001"
    )
    assert result2.get("idempotent_replay") is True


@pytest.mark.asyncio
async def test_create_shipment_with_idempotency_key(
    mock_env: None, respx_mock: respx.MockRouter,
) -> None:
    respx_mock.post(f"{BASE_URL}/rest/{STORE_CODE}/V1/order/123/ship").mock(
        return_value=Response(200, json="SHIP-099")
    )
    result = await admin_create_shipment(
        order_id=123, confirm=True, idempotency_key="ship-001"
    )
    assert result["success"] is True
    result2 = await admin_create_shipment(
        order_id=123, confirm=True, idempotency_key="ship-001"
    )
    assert result2.get("idempotent_replay") is True


@pytest.mark.asyncio
async def test_send_email_with_idempotency_key(
    mock_env: None, respx_mock: respx.MockRouter,
) -> None:
    respx_mock.post(f"{BASE_URL}/rest/{STORE_CODE}/V1/orders/123/emails").mock(
        return_value=Response(200, json=True)
    )
    result = await admin_send_order_email(order_id=123, idempotency_key="email-001")
    assert result["success"] is True
    result2 = await admin_send_order_email(order_id=123, idempotency_key="email-001")
    assert result2.get("idempotent_replay") is True