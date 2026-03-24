"""Tests for the enriched audit log — trace_id, HTTP call capture, before/after state."""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest
import respx
from httpx import Response

from magemcp.policy.engine import (
    PolicyEngine,
    clear_audit_log,
    get_audit_log,
    with_policy,
)

BASE_URL = "https://magento.test"
STORE_CODE = "default"


@pytest.fixture(autouse=True)
def clear_buffer() -> None:
    """Ensure a clean audit buffer before every test."""
    clear_audit_log()


@pytest.fixture
def mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAGENTO_BASE_URL", BASE_URL)
    monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", "test-token")
    monkeypatch.setenv("MAGENTO_STORE_CODE", STORE_CODE)


# ---------------------------------------------------------------------------
# log_action — backward-compatible format + new fields
# ---------------------------------------------------------------------------


class TestLogActionEnrichedFormat:
    def test_result_included_in_entry(self, caplog: pytest.LogCaptureFixture) -> None:
        """log_action includes the actual result payload in the audit entry."""
        engine = PolicyEngine()
        with caplog.at_level(logging.INFO, logger="magemcp.audit"):
            engine.log_action(
                tool_name="admin_update_product",
                params={"sku": "24-MB01", "price": 39.99},
                result={"success": True, "sku": "24-MB01", "updated_fields": ["price"]},
                duration_ms=200.0,
            )

        entry = json.loads(caplog.records[0].message)
        assert entry["success"] is True
        assert "result" in entry
        assert entry["result"]["sku"] == "24-MB01"
        assert "price" in entry["result"]["updated_fields"]

    def test_trace_id_included_when_provided(self, caplog: pytest.LogCaptureFixture) -> None:
        engine = PolicyEngine()
        with caplog.at_level(logging.INFO, logger="magemcp.audit"):
            engine.log_action(
                "admin_get_order",
                {"increment_id": "000000001"},
                {"success": True},
                50.0,
                trace_id="abc123def456",
                tool_class="read",
            )

        entry = json.loads(caplog.records[0].message)
        assert entry["trace_id"] == "abc123def456"
        assert entry["tool_class"] == "read"

    def test_http_calls_included_when_provided(self, caplog: pytest.LogCaptureFixture) -> None:
        engine = PolicyEngine()
        http_calls = [
            {
                "method": "PUT",
                "url": "http://magento.test/rest/default/V1/products/24-MB01",
                "body": {"product": {"price": 39.99}},
                "status": 200,
                "response": {"sku": "24-MB01", "price": 39.99},
            }
        ]
        with caplog.at_level(logging.INFO, logger="magemcp.audit"):
            engine.log_action(
                "admin_update_product",
                {"sku": "24-MB01"},
                {"success": True},
                120.0,
                http_calls=http_calls,
            )

        entry = json.loads(caplog.records[0].message)
        assert "http_calls" in entry
        assert entry["http_calls"][0]["method"] == "PUT"
        assert entry["http_calls"][0]["status"] == 200

    def test_no_http_calls_key_when_empty(self, caplog: pytest.LogCaptureFixture) -> None:
        """http_calls is omitted (not an empty list) when nothing was captured."""
        engine = PolicyEngine()
        with caplog.at_level(logging.INFO, logger="magemcp.audit"):
            engine.log_action("admin_get_order", {}, {"success": True}, 10.0)

        entry = json.loads(caplog.records[0].message)
        assert "http_calls" not in entry

    def test_entry_appended_to_buffer(self) -> None:
        engine = PolicyEngine()
        engine.log_action("admin_get_order", {"x": 1}, {"success": True}, 5.0)
        entries = get_audit_log(limit=10)
        assert len(entries) == 1
        assert entries[0]["tool"] == "admin_get_order"

    def test_buffer_newest_first(self) -> None:
        engine = PolicyEngine()
        engine.log_action("tool_a", {}, {"success": True}, 1.0)
        engine.log_action("tool_b", {}, {"success": True}, 1.0)
        entries = get_audit_log()
        assert entries[0]["tool"] == "tool_b"
        assert entries[1]["tool"] == "tool_a"


# ---------------------------------------------------------------------------
# get_audit_log filtering
# ---------------------------------------------------------------------------


class TestGetAuditLog:
    def test_filter_by_tool(self) -> None:
        engine = PolicyEngine()
        engine.log_action("admin_get_order", {}, {"success": True}, 1.0)
        engine.log_action("admin_update_product", {}, {"success": True}, 1.0)
        engine.log_action("admin_get_order", {}, {"success": True}, 1.0)

        filtered = get_audit_log(tool_filter="admin_get_order")
        assert len(filtered) == 2
        assert all(e["tool"] == "admin_get_order" for e in filtered)

    def test_filter_by_classification(self) -> None:
        engine = PolicyEngine()
        engine.log_action("admin_get_order", {}, {"success": True}, 1.0,
                          tool_class="read")
        engine.log_action("admin_update_product", {}, {"success": True}, 1.0,
                          tool_class="write")

        write_entries = get_audit_log(classification_filter="write")
        assert len(write_entries) == 1
        assert write_entries[0]["tool"] == "admin_update_product"

    def test_limit_respected(self) -> None:
        engine = PolicyEngine()
        for i in range(10):
            engine.log_action(f"tool_{i}", {}, {"success": True}, 1.0)

        entries = get_audit_log(limit=3)
        assert len(entries) == 3

    def test_clear_audit_log_empties_buffer(self) -> None:
        engine = PolicyEngine()
        engine.log_action("admin_get_order", {}, {"success": True}, 1.0)
        clear_audit_log()
        assert get_audit_log() == []


# ---------------------------------------------------------------------------
# with_policy — trace_id and HTTP call capture
# ---------------------------------------------------------------------------


class TestWithPolicyAudit:
    async def test_trace_id_in_audit_entry(self, caplog: pytest.LogCaptureFixture) -> None:
        """Each with_policy invocation gets a unique trace_id in the audit entry."""
        async def my_tool() -> dict:
            return {"success": True}

        wrapped = with_policy("_test_trace_tool")(my_tool)
        with caplog.at_level(logging.INFO, logger="magemcp.audit"):
            await wrapped()

        audit_records = [r for r in caplog.records if r.name == "magemcp.audit"]
        entry = json.loads(audit_records[0].message)
        assert "trace_id" in entry
        assert len(entry["trace_id"]) == 16  # uuid4().hex[:16]

    async def test_tool_class_in_audit_entry(self, caplog: pytest.LogCaptureFixture) -> None:
        """tool_class is included in every audit entry."""
        async def my_tool() -> dict:
            return {"success": True}

        wrapped = with_policy("admin_update_product")(my_tool)
        with caplog.at_level(logging.INFO, logger="magemcp.audit"):
            await wrapped()

        audit_records = [r for r in caplog.records if r.name == "magemcp.audit"]
        entry = json.loads(audit_records[0].message)
        assert entry["tool_class"] == "write"

    async def test_actual_result_in_audit_entry(self, caplog: pytest.LogCaptureFixture) -> None:
        """The real tool result (not just {'ok': True}) is logged."""
        async def my_tool(order_id: int) -> dict:
            return {"success": True, "order_id": order_id, "status": "cancelled"}

        wrapped = with_policy("_test_result_tool")(my_tool)
        with caplog.at_level(logging.INFO, logger="magemcp.audit"):
            await wrapped(order_id=42)

        entry = json.loads(
            [r for r in caplog.records if r.name == "magemcp.audit"][0].message
        )
        assert entry["result"]["order_id"] == 42
        assert entry["result"]["status"] == "cancelled"

    async def test_two_calls_have_distinct_trace_ids(self) -> None:
        """Each tool invocation produces a distinct trace_id."""
        async def my_tool() -> dict:
            return {"success": True}

        wrapped = with_policy("_test_trace_distinct")(my_tool)
        await wrapped()
        await wrapped()

        entries = get_audit_log(tool_filter="_test_trace_distinct")
        assert len(entries) == 2
        assert entries[0]["trace_id"] != entries[1]["trace_id"]


# ---------------------------------------------------------------------------
# HTTP call capture — REST mutations
# ---------------------------------------------------------------------------


class TestHttpCallCapture:
    async def test_rest_put_captured_in_audit(
        self, mock_env: None, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A REST PUT inside a with_policy-wrapped tool is captured in http_calls."""
        from magemcp.tools.admin.products import admin_update_product

        wrapped = with_policy("admin_update_product")(admin_update_product)
        with respx.mock:
            respx.put(f"{BASE_URL}/rest/{STORE_CODE}/V1/products/24-MB01").mock(
                return_value=Response(200, json={
                    "sku": "24-MB01", "price": 39.99, "custom_attributes": []
                })
            )
            with caplog.at_level(logging.INFO, logger="magemcp.audit"):
                await wrapped(sku="24-MB01", price=39.99, confirm=True)

        audit_records = [r for r in caplog.records if r.name == "magemcp.audit"]
        entry = json.loads(audit_records[0].message)
        assert "http_calls" in entry
        call = entry["http_calls"][0]
        assert call["method"] == "PUT"
        assert "V1/products/24-MB01" in call["url"]
        assert call["status"] == 200
        assert call["body"]["product"]["price"] == 39.99

    async def test_rest_post_captured_in_audit(
        self, mock_env: None, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A REST POST (order action) is captured in http_calls."""
        from magemcp.tools.admin.order_actions import admin_cancel_order

        wrapped = with_policy("admin_cancel_order")(admin_cancel_order)
        with respx.mock:
            respx.post(f"{BASE_URL}/rest/{STORE_CODE}/V1/orders/42/cancel").mock(
                return_value=Response(200, json=True)
            )
            with caplog.at_level(logging.INFO, logger="magemcp.audit"):
                await wrapped(order_id=42, confirm=True)

        audit_records = [r for r in caplog.records if r.name == "magemcp.audit"]
        entry = json.loads(audit_records[0].message)
        assert "http_calls" in entry
        call = entry["http_calls"][0]
        assert call["method"] == "POST"
        assert "cancel" in call["url"]

    async def test_read_only_tool_has_no_http_calls(
        self, mock_env: None, caplog: pytest.LogCaptureFixture
    ) -> None:
        """GET-only tools produce no http_calls in the audit entry (reads are not audit-logged)."""
        from magemcp.tools.admin.search_orders import admin_search_orders

        wrapped = with_policy("admin_search_orders")(admin_search_orders)
        with respx.mock:
            respx.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/orders").mock(
                return_value=Response(200, json={"items": [], "total_count": 0})
            )
            with caplog.at_level(logging.INFO, logger="magemcp.audit"):
                await wrapped(status="pending")

        audit_records = [r for r in caplog.records if r.name == "magemcp.audit"]
        entry = json.loads(audit_records[0].message)
        # GETs are not recorded — http_calls should be absent (no mutations)
        assert "http_calls" not in entry


# ---------------------------------------------------------------------------
# GraphQL mutation capture
# ---------------------------------------------------------------------------


class TestGraphQLMutationCapture:
    async def test_graphql_mutation_captured(
        self, mock_env: None, caplog: pytest.LogCaptureFixture
    ) -> None:
        """GraphQL mutations are captured in http_calls with query summary."""
        from magemcp.tools.customer.initiate_return import c_initiate_return

        mock_response = {
            "data": {
                "requestReturn": {
                    "return": {
                        "uid": "NQ==",
                        "number": "000000001",
                        "status": "PENDING",
                        "created_at": "2025-01-01",
                        "items": [{"uid": "MQ==", "quantity": 1.0,
                                   "request_quantity": 1.0, "status": "PENDING"}],
                    }
                }
            }
        }
        wrapped = with_policy("c_initiate_return")(c_initiate_return)
        with respx.mock:
            respx.post(f"{BASE_URL}/graphql").mock(
                return_value=Response(200, json=mock_response)
            )
            with caplog.at_level(logging.INFO, logger="magemcp.audit"):
                await wrapped(
                    order_uid="UID",
                    contact_email="test@test.com",
                    items=[{"order_item_uid": "MQ==", "quantity_to_return": 1.0}],
                    confirm=True,
                )

        audit_records = [r for r in caplog.records if r.name == "magemcp.audit"]
        entry = json.loads(audit_records[0].message)
        assert "http_calls" in entry
        call = entry["http_calls"][0]
        assert call["method"] == "POST"
        assert call["url"] == "/graphql"
        assert "mutation" in call["query"].lower()
        assert call["status"] == 200


# ---------------------------------------------------------------------------
# Before/after state in admin_update_product
# ---------------------------------------------------------------------------


class TestBeforeAfterState:
    async def test_after_state_always_present(
        self, mock_env: None, respx_mock: respx.MockRouter
    ) -> None:
        """after-state is always included in the result (from PUT response)."""
        from magemcp.tools.admin.products import admin_update_product

        respx_mock.put(f"{BASE_URL}/rest/{STORE_CODE}/V1/products/24-MB01").mock(
            return_value=Response(200, json={
                "sku": "24-MB01",
                "price": 39.99,
                "custom_attributes": [],
            })
        )
        result = await admin_update_product(sku="24-MB01", price=39.99, confirm=True)

        assert result["success"] is True
        assert "after" in result
        assert result["after"]["price"] == 39.99

    async def test_before_state_with_env_flag(
        self, mock_env: None, respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """before-state is fetched when MAGEMCP_AUDIT_BEFORE_STATE=true."""
        monkeypatch.setenv("MAGEMCP_AUDIT_BEFORE_STATE", "true")

        from magemcp.tools.admin.products import admin_update_product

        # Mock GET for before-state
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/products/24-MB01").mock(
            return_value=Response(200, json={
                "sku": "24-MB01",
                "price": 29.99,
                "custom_attributes": [
                    {"attribute_code": "special_price", "value": None},
                ],
            })
        )
        # Mock PUT for the update
        respx_mock.put(f"{BASE_URL}/rest/{STORE_CODE}/V1/products/24-MB01").mock(
            return_value=Response(200, json={
                "sku": "24-MB01",
                "price": 39.99,
                "custom_attributes": [],
            })
        )

        result = await admin_update_product(sku="24-MB01", price=39.99, confirm=True)

        assert result["success"] is True
        assert "before" in result
        assert result["before"]["price"] == 29.99
        assert "after" in result
        assert result["after"]["price"] == 39.99

    async def test_special_price_in_payload(
        self, mock_env: None, respx_mock: respx.MockRouter
    ) -> None:
        """special_price is sent as a custom_attribute in the PUT payload."""
        import json as _json

        from magemcp.tools.admin.products import admin_update_product

        respx_mock.put(f"{BASE_URL}/rest/{STORE_CODE}/V1/products/24-MB01").mock(
            return_value=Response(200, json={
                "sku": "24-MB01",
                "price": 29.99,
                "custom_attributes": [
                    {"attribute_code": "special_price", "value": "19.99"},
                ],
            })
        )
        result = await admin_update_product(sku="24-MB01", special_price=19.99, confirm=True)

        payload = _json.loads(respx_mock.calls.last.request.content)
        ca = payload["product"]["custom_attributes"]
        special = next((a for a in ca if a["attribute_code"] == "special_price"), None)
        assert special is not None
        assert special["value"] == "19.99"
        assert "special_price" in result["updated_fields"]
        assert result["after"].get("special_price") == "19.99"

    async def test_special_price_with_dates(
        self, mock_env: None, respx_mock: respx.MockRouter
    ) -> None:
        """special_price_from and special_price_to are included in the payload."""
        import json as _json

        from magemcp.tools.admin.products import admin_update_product

        respx_mock.put(f"{BASE_URL}/rest/{STORE_CODE}/V1/products/24-MB01").mock(
            return_value=Response(200, json={
                "sku": "24-MB01",
                "price": 29.99,
                "custom_attributes": [
                    {"attribute_code": "special_price", "value": "19.99"},
                    {"attribute_code": "special_from_date", "value": "2026-03-24"},
                    {"attribute_code": "special_to_date", "value": "2026-03-31"},
                ],
            })
        )
        result = await admin_update_product(
            sku="24-MB01",
            special_price=19.99,
            special_price_from="2026-03-24",
            special_price_to="2026-03-31",
            confirm=True,
        )

        payload = _json.loads(respx_mock.calls.last.request.content)
        ca = {a["attribute_code"]: a["value"] for a in payload["product"]["custom_attributes"]}
        assert ca["special_price"] == "19.99"
        assert ca["special_from_date"] == "2026-03-24"
        assert ca["special_to_date"] == "2026-03-31"
        assert "special_from_date" in result["updated_fields"]
        assert "special_to_date" in result["updated_fields"]


# ---------------------------------------------------------------------------
# audit_context — ContextVar isolation between concurrent calls
# ---------------------------------------------------------------------------


class TestAuditContextIsolation:
    async def test_concurrent_calls_have_independent_contexts(self) -> None:
        """Two concurrent tool invocations don't share audit contexts."""
        import asyncio

        from magemcp.audit_context import current_entry

        call_log: list[str] = []

        async def tool_a() -> dict:
            ctx = current_entry.get()
            assert ctx is not None
            await asyncio.sleep(0)  # yield to allow concurrent execution
            call_log.append(f"a:{id(ctx)}")
            return {"tool": "a"}

        async def tool_b() -> dict:
            ctx = current_entry.get()
            assert ctx is not None
            await asyncio.sleep(0)
            call_log.append(f"b:{id(ctx)}")
            return {"tool": "b"}

        wrapped_a = with_policy("_test_iso_a")(tool_a)
        wrapped_b = with_policy("_test_iso_b")(tool_b)

        await asyncio.gather(wrapped_a(), wrapped_b())

        # Each call should have logged with a distinct context object
        assert len(call_log) == 2
        ids = [entry.split(":")[1] for entry in call_log]
        assert ids[0] != ids[1], "Context objects should be distinct per call"
