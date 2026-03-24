"""Tests for the policy engine — rate limiting, audit logging, tool classification."""

from __future__ import annotations

import json
import logging
import os
import time
from unittest.mock import patch

import pytest

from magemcp.connectors.errors import MagentoRateLimitError
from magemcp.policy.engine import (
    DESTRUCTIVE_TOOLS,
    PolicyEngine,
    READ_TOOLS,
    WRITE_TOOLS,
    _engine,
    _is_tool_allowed,
    classify_tool,
    with_policy,
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


# ---------------------------------------------------------------------------
# with_policy decorator
# ---------------------------------------------------------------------------


class TestWithPolicy:
    async def test_passes_through_result(self) -> None:
        """with_policy calls the wrapped function and returns its result."""
        async def my_tool(x: int) -> dict:
            return {"value": x * 2}

        wrapped = with_policy("test_tool_pass")(my_tool)
        result = await wrapped(x=5)
        assert result == {"value": 10}

    async def test_raises_rate_limit_error(self) -> None:
        """with_policy raises MagentoRateLimitError when rate limit is exceeded."""
        tool_name = "test_tool_rate_limit_xyz"
        limit = int(os.getenv("MAGEMCP_RATE_LIMIT", "60"))
        # Fill the sliding-window counter directly to trigger the limit
        _engine._rate_counters[tool_name] = [time.time()] * limit

        async def my_tool() -> dict:
            return {"ok": True}

        wrapped = with_policy(tool_name)(my_tool)
        with pytest.raises(MagentoRateLimitError):
            await wrapped()

    async def test_audit_log_on_success(self, caplog: pytest.LogCaptureFixture) -> None:
        """with_policy emits an audit log entry on successful tool call."""
        async def my_tool(order_id: str) -> dict:
            return {"found": True}

        wrapped = with_policy("test_tool_audit")(my_tool)
        with caplog.at_level(logging.INFO, logger="magemcp.audit"):
            await wrapped(order_id="000001")

        audit_records = [r for r in caplog.records if r.name == "magemcp.audit"]
        assert audit_records, "Expected audit log entry"
        entry = json.loads(audit_records[0].message)
        assert entry["tool"] == "test_tool_audit"

    async def test_audit_log_on_exception(self, caplog: pytest.LogCaptureFixture) -> None:
        """with_policy logs errors and re-raises the exception."""
        async def bad_tool() -> dict:
            raise ValueError("something went wrong")

        wrapped = with_policy("test_tool_error")(bad_tool)
        with caplog.at_level(logging.INFO, logger="magemcp.audit"):
            with pytest.raises(ValueError, match="something went wrong"):
                await wrapped()

        audit_records = [r for r in caplog.records if r.name == "magemcp.audit"]
        assert audit_records
        entry = json.loads(audit_records[0].message)
        assert entry["tool"] == "test_tool_error"
        assert "something went wrong" in entry.get("error", "")


# ---------------------------------------------------------------------------
# Tool allowlist (MAGEMCP_ALLOWED_TOOLS)
# ---------------------------------------------------------------------------


class TestToolAllowlist:
    def test_all_allowed_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MAGEMCP_ALLOWED_TOOLS", raising=False)
        assert _is_tool_allowed("admin_cancel_order") is True
        assert _is_tool_allowed("c_search_products") is True

    def test_all_allowed_when_env_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGEMCP_ALLOWED_TOOLS", "")
        assert _is_tool_allowed("admin_get_order") is True

    def test_allowed_tool_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGEMCP_ALLOWED_TOOLS", "admin_get_order,c_search_products")
        assert _is_tool_allowed("admin_get_order") is True
        assert _is_tool_allowed("c_search_products") is True

    def test_blocked_tool_denied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGEMCP_ALLOWED_TOOLS", "admin_get_order")
        assert _is_tool_allowed("admin_cancel_order") is False

    def test_whitespace_in_list_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGEMCP_ALLOWED_TOOLS", " admin_get_order , c_search_products ")
        assert _is_tool_allowed("admin_get_order") is True
        assert _is_tool_allowed("c_search_products") is True

    async def test_blocked_tool_raises_in_with_policy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAGEMCP_ALLOWED_TOOLS", "admin_get_order")

        async def my_tool() -> dict:
            return {"ok": True}

        wrapped = with_policy("admin_cancel_order")(my_tool)
        with pytest.raises(ValueError, match="MAGEMCP_ALLOWED_TOOLS"):
            await wrapped()


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


class TestMetrics:
    async def test_call_count_increments(self) -> None:
        from magemcp.policy.engine import _metrics, get_metrics, with_policy
        tool_name = "_test_metrics_calls_xyz"
        _metrics.pop(tool_name, None)

        async def my_tool() -> dict:
            return {"ok": True}

        wrapped = with_policy(tool_name)(my_tool)
        await wrapped()
        await wrapped()

        snap = get_metrics()
        assert snap[tool_name]["calls"] == 2

    async def test_error_count_increments(self) -> None:
        from magemcp.policy.engine import _metrics, get_metrics, with_policy
        tool_name = "_test_metrics_errors_xyz"
        _metrics.pop(tool_name, None)

        async def bad_tool() -> dict:
            raise RuntimeError("oops")

        wrapped = with_policy(tool_name)(bad_tool)
        with pytest.raises(RuntimeError):
            await wrapped()

        snap = get_metrics()
        assert snap[tool_name]["errors"] == 1

    async def test_rate_limit_hit_counted(self) -> None:
        from magemcp.policy.engine import _engine, _metrics, get_metrics, with_policy
        tool_name = "_test_metrics_rl_xyz"
        _metrics.pop(tool_name, None)
        limit = int(os.getenv("MAGEMCP_RATE_LIMIT", "60"))
        _engine._rate_counters[tool_name] = [time.time()] * limit

        async def my_tool() -> dict:
            return {"ok": True}

        wrapped = with_policy(tool_name)(my_tool)
        with pytest.raises(Exception):
            await wrapped()

        snap = get_metrics()
        assert snap[tool_name]["rate_limit_hits"] == 1

    def test_get_metrics_returns_all_registered(self) -> None:
        from magemcp.policy.engine import get_metrics, with_policy
        tool_name = "_test_metrics_list_xyz"

        async def my_tool() -> dict:
            return {}

        with_policy(tool_name)(my_tool)
        snap = get_metrics()
        assert tool_name in snap
        assert "calls" in snap[tool_name]
        assert "errors" in snap[tool_name]
        assert "avg_duration_ms" in snap[tool_name]
