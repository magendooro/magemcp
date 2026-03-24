"""Policy engine — rate limiting, audit logging, and tool classification."""

from __future__ import annotations

import json
import logging
import os
import time
from collections import defaultdict
from functools import wraps
from typing import Any

from magemcp.connectors.errors import MagentoRateLimitError

audit_log = logging.getLogger("magemcp.audit")


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
    ) -> None:
        """Emit a structured JSON audit log entry."""
        entry: dict[str, Any] = {
            "tool": tool_name,
            "params": {k: v for k, v in params.items() if k != "confirm"},
            "success": result.get("ok", result.get("success", False)) is True,
            "duration_ms": round(duration_ms, 1),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        if "error" in result:
            entry["error"] = result["error"]
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
    "c_add_to_cart",
    "c_update_cart_item",
    "c_apply_coupon",
    "c_set_guest_email",
    "c_set_shipping_address",
    "c_set_billing_address",
    "c_set_shipping_method",
    "c_set_payment_method",
    "c_place_order",
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


def with_policy(tool_name: str):
    """Decorator that applies rate limiting and audit logging to a tool handler."""
    _limit = int(os.getenv("MAGEMCP_RATE_LIMIT", "60"))

    def decorator(fn: Any) -> Any:
        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not _engine.check_rate_limit(tool_name, limit=_limit):
                raise MagentoRateLimitError(f"Rate limit exceeded for {tool_name}")
            t0 = time.monotonic()
            try:
                result = await fn(*args, **kwargs)
                _engine.log_action(tool_name, kwargs, {"ok": True}, (time.monotonic() - t0) * 1000)
                return result
            except Exception as e:
                _engine.log_action(tool_name, kwargs, {"error": str(e)}, (time.monotonic() - t0) * 1000)
                raise
        return wrapper
    return decorator
