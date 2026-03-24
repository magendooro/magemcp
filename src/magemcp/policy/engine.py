"""Policy engine — rate limiting, audit logging, and tool classification."""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections import defaultdict, deque
from functools import wraps
from typing import Any

from magemcp.audit_context import current_entry as _current_audit_entry
from magemcp.audit_context import truncate_for_audit
from magemcp.connectors.errors import MagentoRateLimitError

audit_log = logging.getLogger("magemcp.audit")


class _ToolMetrics:
    """Simple in-process per-tool call/error/latency counters."""

    __slots__ = ("calls", "errors", "rate_limit_hits", "total_duration_ms")

    def __init__(self) -> None:
        self.calls: int = 0
        self.errors: int = 0
        self.rate_limit_hits: int = 0
        self.total_duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        avg = round(self.total_duration_ms / self.calls, 1) if self.calls else 0
        return {
            "calls": self.calls,
            "errors": self.errors,
            "rate_limit_hits": self.rate_limit_hits,
            "avg_duration_ms": avg,
        }


# Module-level metrics registry
_metrics: dict[str, _ToolMetrics] = {}

# ---------------------------------------------------------------------------
# In-memory rolling audit buffer
# ---------------------------------------------------------------------------

_AUDIT_BUFFER_SIZE = 500
_audit_buffer: deque[dict[str, Any]] = deque(maxlen=_AUDIT_BUFFER_SIZE)


def get_audit_log(
    limit: int = 50,
    tool_filter: str | None = None,
    classification_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Return recent audit entries, newest first, with optional filters.

    Args:
        limit: Maximum number of entries to return (default 50, max 500).
        tool_filter: Only return entries for this tool name.
        classification_filter: Only return entries with this tool_class
            ('read', 'write', or 'destructive').
    """
    entries = list(_audit_buffer)
    entries.reverse()  # newest first
    if tool_filter:
        entries = [e for e in entries if e.get("tool") == tool_filter]
    if classification_filter:
        entries = [e for e in entries if e.get("tool_class") == classification_filter]
    return entries[: min(limit, _AUDIT_BUFFER_SIZE)]


def clear_audit_log() -> None:
    """Clear the in-memory audit buffer (useful in tests)."""
    _audit_buffer.clear()


def get_metrics() -> dict[str, dict[str, Any]]:
    """Return a snapshot of per-tool metrics."""
    return {name: m.to_dict() for name, m in _metrics.items()}


class PolicyEngine:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._rate_counters: dict[str, list[float]] = defaultdict(list)

    def check_rate_limit(self, tool_name: str, limit: int = 60, window: int = 60) -> bool:
        """Check if tool is within rate limit. Returns True if allowed, False if blocked."""
        now = time.time()
        calls = self._rate_counters[tool_name]
        calls[:] = [t for t in calls if t > now - window]
        if len(calls) >= limit:
            return False
        calls.append(now)
        return True

    def log_action(
        self,
        tool_name: str,
        params: dict[str, Any],
        result: dict[str, Any],
        duration_ms: float,
        *,
        trace_id: str | None = None,
        tool_class: str | None = None,
        http_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        """Emit a structured JSON audit log entry and append it to the in-memory buffer.

        The ``result`` dict is included in the entry (truncated if large) so that
        reports can show what was actually returned — not just whether the call
        succeeded.  For write tools the tool implementation may include ``before``
        and ``after`` keys in the result to capture field-level state changes.

        New optional kwargs (populated by ``with_policy``):
          trace_id       — 16-char hex ID linking this entry to its HTTP sub-calls.
          tool_class     — 'read', 'write', or 'destructive'.
          http_calls     — list of Magento HTTP call details captured during execution.
        """
        success = result.get("ok", result.get("success", False)) is True
        entry: dict[str, Any] = {
            "tool": tool_name,
            "params": {k: v for k, v in params.items() if k != "confirm"},
            "success": success,
            "duration_ms": round(duration_ms, 1),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        if trace_id:
            entry["trace_id"] = trace_id
        if tool_class:
            entry["tool_class"] = tool_class
        if "error" in result:
            entry["error"] = result["error"]
        # Always include the result so the audit log shows what was returned.
        # Exclude internal meta keys that duplicate other fields.
        result_payload = {
            k: v for k, v in result.items()
            if k not in ("ok",)
        }
        if result_payload:
            entry["result"] = truncate_for_audit(result_payload)
        if http_calls:
            entry["http_calls"] = http_calls
        _audit_buffer.append(entry)
        audit_log.info(json.dumps(entry))


# ---------------------------------------------------------------------------
# Tool classification
# ---------------------------------------------------------------------------

DESTRUCTIVE_TOOLS: frozenset[str] = frozenset({
    "admin_cancel_order",
    "admin_delete_product",
})

WRITE_TOOLS: frozenset[str] = frozenset({
    "admin_create_invoice",
    "admin_create_shipment",
    "admin_add_order_comment",
    "admin_hold_order",
    "admin_unhold_order",
    "admin_update_product",
    "admin_update_cms_page",
    "admin_update_inventory",
    "admin_generate_coupons",
    "admin_send_order_email",
    "admin_bulk_inventory_update",
    "admin_bulk_catalog_update",
    "c_add_to_cart",
    "c_update_cart_item",
    "c_apply_coupon",
    "c_set_guest_email",
    "c_set_shipping_address",
    "c_set_billing_address",
    "c_set_shipping_method",
    "c_set_payment_method",
    "c_place_order",
    "c_initiate_return",
})

# READ_TOOLS is the open set — anything not in DESTRUCTIVE_TOOLS or WRITE_TOOLS
READ_TOOLS: frozenset[str] = frozenset()


def classify_tool(tool_name: str) -> str:
    """Return 'destructive', 'write', or 'read' for a given tool name."""
    if tool_name in DESTRUCTIVE_TOOLS:
        return "destructive"
    if tool_name in WRITE_TOOLS:
        return "write"
    return "read"


# ---------------------------------------------------------------------------
# Module-level engine singleton + with_policy decorator
# ---------------------------------------------------------------------------

_engine = PolicyEngine()


def _is_tool_allowed(tool_name: str) -> bool:
    """Return True if the tool is permitted by MAGEMCP_ALLOWED_TOOLS.

    If the env var is unset or empty, all tools are allowed.
    Otherwise only tools whose names appear in the comma-separated list are allowed.
    """
    allowed_env = os.getenv("MAGEMCP_ALLOWED_TOOLS", "").strip()
    if not allowed_env:
        return True
    allowed = {t.strip() for t in allowed_env.split(",") if t.strip()}
    return tool_name in allowed


def with_policy(tool_name: str):
    """Decorator that applies rate limiting, tool allowlist, audit logging, and metrics.

    Each invocation receives a unique ``trace_id``.  A mutable audit context dict
    (containing ``http_calls: []``) is set on a ContextVar before the tool runs.
    Connector-level code (REST/GraphQL clients) appends their HTTP call details
    to this dict, so the final audit entry contains a complete picture of every
    Magento request made during the tool invocation.
    """
    _limit = int(os.getenv("MAGEMCP_RATE_LIMIT", "60"))
    _tool_class = classify_tool(tool_name)
    if tool_name not in _metrics:
        _metrics[tool_name] = _ToolMetrics()

    def decorator(fn: Any) -> Any:
        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            m = _metrics[tool_name]
            if not _is_tool_allowed(tool_name):
                raise ValueError(
                    f"Tool '{tool_name}' is not in MAGEMCP_ALLOWED_TOOLS."
                )
            if not _engine.check_rate_limit(tool_name, limit=_limit):
                m.rate_limit_hits += 1
                raise MagentoRateLimitError(f"Rate limit exceeded for {tool_name}")

            # Establish an audit context for this invocation.
            # Connectors will append HTTP call details to entry["http_calls"].
            trace_id = uuid.uuid4().hex[:16]
            audit_ctx: dict[str, Any] = {"http_calls": []}
            token = _current_audit_entry.set(audit_ctx)

            t0 = time.monotonic()
            m.calls += 1
            try:
                result = await fn(*args, **kwargs)
                duration = (time.monotonic() - t0) * 1000
                m.total_duration_ms += duration
                _engine.log_action(
                    tool_name, kwargs, result, duration,
                    trace_id=trace_id,
                    tool_class=_tool_class,
                    http_calls=audit_ctx["http_calls"] or None,
                )
                return result
            except BaseException as e:
                duration = (time.monotonic() - t0) * 1000
                m.total_duration_ms += duration
                import asyncio
                if isinstance(e, asyncio.CancelledError):
                    raise
                m.errors += 1
                _engine.log_action(
                    tool_name, kwargs, {"error": str(e)}, duration,
                    trace_id=trace_id,
                    tool_class=_tool_class,
                    http_calls=audit_ctx["http_calls"] or None,
                )
                raise
            finally:
                _current_audit_entry.reset(token)
        return wrapper
    return decorator
