"""Shared audit context — ContextVar so connectors can attach HTTP details to the active tool entry.

This is a leaf module (no internal imports) to avoid circular dependencies:
  engine.py   → audit_context.py
  rest_client → audit_context.py
  graphql_client → audit_context.py
"""

from __future__ import annotations

import json
from contextvars import ContextVar
from typing import Any


# Set by with_policy at the start of each tool invocation.
# While the tool is executing, connectors read this and append their HTTP call
# details to entry["http_calls"], so the final audit entry contains a full
# record of every request sent to Magento during that tool call.
current_entry: ContextVar[dict[str, Any] | None] = ContextVar(
    "magemcp_audit_entry", default=None
)


def truncate_for_audit(value: Any, max_chars: int = 2000) -> Any:
    """Reduce a value to fit within the audit log size budget.

    Keeps the structure (dict / list) for small payloads so the audit log
    remains machine-readable.  Falls back to a truncated JSON string for
    very large values.
    """
    if value is None:
        return None
    try:
        encoded = json.dumps(value)
    except (TypeError, ValueError):
        encoded = str(value)
    if len(encoded) <= max_chars:
        return value
    # Try to produce a smaller but still structured representation.
    if isinstance(value, dict):
        shrunk: dict[str, Any] = {}
        for k, v in value.items():
            if isinstance(v, str) and len(v) > 500:
                shrunk[k] = v[:500] + f"…[{len(v) - 500} chars]"
            elif isinstance(v, list) and len(v) > 5:
                shrunk[k] = v[:5] + [f"…[{len(v) - 5} more]"]
            else:
                shrunk[k] = v
        return shrunk
    if isinstance(value, list) and len(value) > 5:
        return value[:5] + [f"…[{len(value) - 5} more]"]
    # Last resort: raw JSON string, truncated.
    return encoded[:max_chars] + "…"
