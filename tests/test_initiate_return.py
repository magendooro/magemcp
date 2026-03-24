"""Tests for c_initiate_return tool."""

from __future__ import annotations

import json
from typing import Any

import pytest
import respx
from httpx import Response

from magemcp.tools.customer.initiate_return import c_initiate_return

BASE_URL = "https://magento.test"
STORE_CODE = "default"


@pytest.fixture
def mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAGENTO_BASE_URL", BASE_URL)
    monkeypatch.setenv("MAGENTO_STORE_CODE", STORE_CODE)


_RETURN_RESPONSE: dict[str, Any] = {
    "data": {
        "requestReturn": {
            "return": {
                "uid": "NQ==",
                "number": "000000001",
                "status": "PENDING",
                "created_at": "2025-01-01 10:00:00",
                "items": [
                    {
                        "uid": "MQ==",
                        "quantity": 1.0,
                        "request_quantity": 1.0,
                        "status": "PENDING",
                    }
                ],
            }
        }
    }
}

_ITEMS = [{"order_item_uid": "MQ==", "quantity_to_return": 1.0}]


class TestInitiateReturn:
    async def test_requires_confirmation(self, mock_env: None) -> None:
        result = await c_initiate_return(
            order_uid="abc123",
            contact_email="customer@example.com",
            items=_ITEMS,
        )
        assert result["confirmation_required"] is True

    async def test_empty_items_raises(self, mock_env: None) -> None:
        with pytest.raises(ValueError):
            await c_initiate_return(
                order_uid="abc123",
                contact_email="customer@example.com",
                items=[],
                confirm=True,
            )

    async def test_successful_return(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.post(f"{BASE_URL}/graphql").mock(
            return_value=Response(200, json=_RETURN_RESPONSE)
        )
        result = await c_initiate_return(
            order_uid="abc123",
            contact_email="customer@example.com",
            items=_ITEMS,
            confirm=True,
        )
        assert result["success"] is True
        assert result["uid"] == "NQ=="
        assert result["number"] == "000000001"
        assert result["status"] == "PENDING"
        assert len(result["items"]) == 1

    async def test_mutation_payload_structure(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.post(f"{BASE_URL}/graphql").mock(
            return_value=Response(200, json=_RETURN_RESPONSE)
        )
        await c_initiate_return(
            order_uid="ORDER-UID",
            contact_email="test@example.com",
            items=[{"order_item_uid": "ITEM-UID", "quantity_to_return": 2.0}],
            confirm=True,
        )
        payload = json.loads(respx_mock.calls.last.request.content)
        variables = payload["variables"]["input"]
        assert variables["order_uid"] == "ORDER-UID"
        assert variables["contact_email"] == "test@example.com"
        assert variables["items"][0]["order_item_uid"] == "ITEM-UID"
        assert variables["items"][0]["quantity_to_return"] == 2.0

    async def test_comment_included_when_provided(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.post(f"{BASE_URL}/graphql").mock(
            return_value=Response(200, json=_RETURN_RESPONSE)
        )
        await c_initiate_return(
            order_uid="UID",
            contact_email="test@test.com",
            items=_ITEMS,
            comment="Item was damaged on arrival",
            confirm=True,
        )
        payload = json.loads(respx_mock.calls.last.request.content)
        assert payload["variables"]["input"]["comment_text"] == "Item was damaged on arrival"

    async def test_comment_omitted_when_not_provided(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.post(f"{BASE_URL}/graphql").mock(
            return_value=Response(200, json=_RETURN_RESPONSE)
        )
        await c_initiate_return(
            order_uid="UID",
            contact_email="test@test.com",
            items=_ITEMS,
            confirm=True,
        )
        payload = json.loads(respx_mock.calls.last.request.content)
        assert "comment_text" not in payload["variables"]["input"]

    async def test_multiple_items(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.post(f"{BASE_URL}/graphql").mock(
            return_value=Response(200, json=_RETURN_RESPONSE)
        )
        await c_initiate_return(
            order_uid="UID",
            contact_email="test@test.com",
            items=[
                {"order_item_uid": "ITEM-1", "quantity_to_return": 1.0},
                {"order_item_uid": "ITEM-2", "quantity_to_return": 2.0},
            ],
            confirm=True,
        )
        payload = json.loads(respx_mock.calls.last.request.content)
        items = payload["variables"]["input"]["items"]
        assert len(items) == 2
        assert items[1]["quantity_to_return"] == 2.0

    async def test_idempotency_key_replays(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.post(f"{BASE_URL}/graphql").mock(
            return_value=Response(200, json=_RETURN_RESPONSE)
        )
        result = await c_initiate_return(
            order_uid="UID",
            contact_email="test@test.com",
            items=_ITEMS,
            confirm=True,
            idempotency_key="ret-idem-001",
        )
        assert result["success"] is True

        result2 = await c_initiate_return(
            order_uid="UID",
            contact_email="test@test.com",
            items=_ITEMS,
            confirm=True,
            idempotency_key="ret-idem-001",
        )
        assert result2.get("idempotent_replay") is True

    async def test_is_registered(self) -> None:
        from magemcp.server import mcp
        tool_names = [t.name for t in await mcp.list_tools()]
        assert "c_initiate_return" in tool_names
