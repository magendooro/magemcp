"""Tests for the policy engine — rate limiting, audit logging, tool classification."""

from __future__ import annotations

import json
import logging
from unittest.mock import patch

import pytest

from magemcp.policy.engine import (
    DESTRUCTIVE_TOOLS,
    READ_TOOLS,
    WRITE_TOOLS,
    PolicyEngine,
    classify_tool,
)


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


class TestRateLimit:
    def test_allows_within_limit(self) -> None:
        engine = PolicyEngine()
        for _ in range(5):
            assert engine.check_rate_limit("admin_get_order", limit=5, window=60) is True

    def test_blocks_over_limit(self) -> None:
        engine = PolicyEngine()
        for _ in range(5):
            engine.check_rate_limit("admin_cancel_order", limit=5, window=60)
        # 6th call should be blocked
        assert engine.check_rate_limit("admin_cancel_order", limit=5, window=60) is False

    def test_window_expires(self) -> None:
        engine = PolicyEngine()
        # Fill up the limit
        for _ in range(3):
            engine.check_rate_limit("admin_get_order", limit=3, window=60)
        assert engine.check_rate_limit("admin_get_order", limit=3, window=60) is False

        # Backdate all recorded calls to outside the window
        engine._rate_counters["admin_get_order"] = [t - 61 for t in engine._rate_counters["admin_get_order"]]

        # Should be allowed again
        assert engine.check_rate_limit("admin_get_order", limit=3, window=60) is True

    def test_counters_are_per_tool(self) -> None:
        engine = PolicyEngine()
        for _ in range(3):
            engine.check_rate_limit("tool_a", limit=3, window=60)
        # tool_a is at limit, tool_b should be unaffected
        assert engine.check_rate_limit("tool_a", limit=3, window=60) is False
        assert engine.check_rate_limit("tool_b", limit=3, window=60) is True

    def test_exact_limit_boundary(self) -> None:
        """Exactly at limit is blocked; one below is allowed."""
        engine = PolicyEngine()
        for _ in range(9):
            engine.check_rate_limit("tool_x", limit=10, window=60)
        assert engine.check_rate_limit("tool_x", limit=10, window=60) is True  # 10th call allowed
        assert engine.check_rate_limit("tool_x", limit=10, window=60) is False  # 11th blocked


# ---------------------------------------------------------------------------
# Audit log format
# ---------------------------------------------------------------------------


class TestAuditLogFormat:
    def test_log_format(self, caplog: pytest.LogCaptureFixture) -> None:
        """Verify the audit log entry is valid JSON with required fields."""
        engine = PolicyEngine()

        with caplog.at_level(logging.INFO, logger="magemcp.audit"):
            engine.log_action(
                tool_name="admin_get_order",
                params={"increment_id": "000000001", "store_scope": "default"},
                result={"success": True, "order_id": 42},
                duration_ms=123.4,
            )

        assert caplog.records, "Expected at least one log record"
        entry = json.loads(caplog.records[0].message)

        assert entry["tool"] == "admin_get_order"
        assert entry["params"]["increment_id"] == "000000001"
        assert entry["success"] is True
        assert entry["duration_ms"] == 123.4
        assert "timestamp" in entry
        # Timestamp format: 2024-01-01T00:00:00Z
        assert entry["timestamp"].endswith("Z")
        assert "T" in entry["timestamp"]

    def test_confirm_param_excluded(self, caplog: pytest.LogCaptureFixture) -> None:
        """'confirm' is stripped from logged params (security hygiene)."""
        engine = PolicyEngine()

        with caplog.at_level(logging.INFO, logger="magemcp.audit"):
            engine.log_action(
                tool_name="admin_cancel_order",
                params={"order_id": 99, "confirm": True, "store_scope": "default"},
                result={"success": True},
                duration_ms=50.0,
            )

        entry = json.loads(caplog.records[0].message)
        assert "confirm" not in entry["params"]
        assert entry["params"]["order_id"] == 99

    def test_failed_action_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """success=False is logged correctly for failed tool calls."""
        engine = PolicyEngine()

        with caplog.at_level(logging.INFO, logger="magemcp.audit"):
            engine.log_action(
                tool_name="admin_get_order",
                params={"increment_id": "NOTFOUND"},
                result={"error": "Order not found"},
                duration_ms=10.0,
            )

        entry = json.loads(caplog.records[0].message)
        assert entry["success"] is False


# ---------------------------------------------------------------------------
# Tool classification
# ---------------------------------------------------------------------------


class TestToolClassification:
    def test_destructive_tools(self) -> None:
        assert "admin_cancel_order" in DESTRUCTIVE_TOOLS
        assert "admin_delete_product" in DESTRUCTIVE_TOOLS

    def test_write_tools(self) -> None:
        expected = {
            "admin_create_invoice",
            "admin_create_shipment",
            "admin_add_order_comment",
            "admin_update_product",
            "admin_update_cms_page",
            "admin_update_inventory",
            "admin_generate_coupons",
            "admin_send_order_email",
            "c_place_order",
        }
        assert expected <= WRITE_TOOLS

    def test_read_tools_is_open_set(self) -> None:
        """READ_TOOLS is empty — read is the default for anything not classified."""
        assert READ_TOOLS == frozenset()

    def test_classify_tool_destructive(self) -> None:
        assert classify_tool("admin_cancel_order") == "destructive"
        assert classify_tool("admin_delete_product") == "destructive"

    def test_classify_tool_write(self) -> None:
        assert classify_tool("admin_create_invoice") == "write"
        assert classify_tool("admin_update_product") == "write"
        assert classify_tool("c_place_order") == "write"

    def test_classify_tool_read(self) -> None:
        assert classify_tool("admin_get_order") == "read"
        assert classify_tool("admin_search_products") == "read"
        assert classify_tool("c_search_products") == "read"
        assert classify_tool("c_get_product") == "read"
        assert classify_tool("unknown_tool") == "read"

    def test_no_overlap_between_sets(self) -> None:
        """A tool cannot be in both DESTRUCTIVE_TOOLS and WRITE_TOOLS."""
        overlap = DESTRUCTIVE_TOOLS & WRITE_TOOLS
        assert overlap == frozenset(), f"Overlap found: {overlap}"
