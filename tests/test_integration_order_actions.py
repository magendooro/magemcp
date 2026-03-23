"""Integration tests for admin order actions — hit a real Magento 2 instance.

Requires MAGENTO_BASE_URL and MAGENTO_TOKEN env vars.
"""

from __future__ import annotations

import logging
import os
import uuid

import pytest

from magemcp.connectors.magento import MagentoClient

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Skip entire module when Magento is not configured
# ---------------------------------------------------------------------------

_MAGENTO_URL = os.environ.get("MAGENTO_BASE_URL", "")
_MAGENTO_TOKEN = os.environ.get("MAGENTO_TOKEN", "") or os.environ.get("MAGEMCP_ADMIN_TOKEN", "")

pytestmark = pytest.mark.skipif(
    not (_MAGENTO_URL and _MAGENTO_TOKEN),
    reason="MAGENTO_BASE_URL and MAGENTO_TOKEN env vars required for integration tests",
)


async def _discover_order_entity_id(client: MagentoClient) -> int | None:
    """Find a real order entity ID."""
    params = MagentoClient.search_params(page_size=1, sort_field="entity_id", sort_direction="DESC")
    data = await client.get("/V1/orders", params=params)
    items = data.get("items", [])
    return int(items[0]["entity_id"]) if items else None


class TestOrderActionsIntegration:
    """Integration tests for admin order actions."""

    async def test_add_comment_real(self) -> None:
        """Add a comment to a real order."""
        async with MagentoClient.from_config() as client:
            order_id = await _discover_order_entity_id(client)
        
        if order_id is None:
            pytest.skip("No orders found to test comment addition")

        from magemcp.server import mcp as server
        tools = server._tool_manager._tools
        tool_fn = tools["admin_add_order_comment"].fn

        # Use a unique comment to verify
        unique_comment = f"MageMCP Integration Test {uuid.uuid4()}"
        
        result = await tool_fn(
            order_id=order_id,
            comment=unique_comment,
            is_visible_on_front=False,
            is_customer_notified=False,
        )

        assert result["success"] is True
        assert result["comment"] == unique_comment
        log.info("Added comment to order %d: %s", order_id, unique_comment)

        # Verify via REST API
        async with MagentoClient.from_config() as client:
            data = await client.get(f"/V1/orders/{order_id}")
            history = data.get("status_histories", [])
            
            # Find our comment
            found = any(h.get("comment") == unique_comment for h in history)
            assert found, f"Comment '{unique_comment}' not found in order history"

    async def test_hold_unhold_flow(self) -> None:
        """Test hold and unhold flow (if order state allows)."""
        async with MagentoClient.from_config() as client:
            # Find an order that is NOT canceled, complete, or closed
            params = MagentoClient.search_params(
                filters={"status": "processing"},  # processing orders can usually be held
                page_size=1,
            )
            data = await client.get("/V1/orders", params=params)
            items = data.get("items", [])
            
        if not items:
            pytest.skip("No processing orders found to test hold/unhold")
            
        order_id = int(items[0]["entity_id"])
        
        from magemcp.server import mcp as server
        tools = server._tool_manager._tools
        hold_fn = tools["admin_hold_order"].fn
        unhold_fn = tools["admin_unhold_order"].fn

        # 1. Hold
        log.info("Attempting to hold order %d...", order_id)
        # First call asks for confirmation
        prompt = await hold_fn(order_id=order_id)
        assert prompt["confirmation_required"] is True
        
        # Confirm
        result = await hold_fn(order_id=order_id, confirm=True)
        assert result["success"] is True
        assert result["action"] == "held"
        
        # Verify status via REST
        async with MagentoClient.from_config() as client:
            order = await client.get(f"/V1/orders/{order_id}")
            assert order["state"] == "holded" or order["status"] == "holded"

        # 2. Unhold
        log.info("Attempting to unhold order %d...", order_id)
        prompt = await unhold_fn(order_id=order_id)
        assert prompt["confirmation_required"] is True
        
        result = await unhold_fn(order_id=order_id, confirm=True)
        assert result["success"] is True
        assert result["action"] == "unheld"

        # Verify status via REST
        async with MagentoClient.from_config() as client:
            order = await client.get(f"/V1/orders/{order_id}")
            assert order["state"] != "holded"
