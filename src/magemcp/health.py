"""Health check endpoint for MageMCP.

Exposed at ``GET /health`` when running with the streamable-http transport.
Returns a JSON response with server status and a summary of registered tools.
"""

from __future__ import annotations

import os
import time
from typing import Any

_started_at = time.time()


def get_health(tool_count: int) -> dict[str, Any]:
    """Build the health-check response payload."""
    return {
        "status": "ok",
        "uptime_seconds": round(time.time() - _started_at, 1),
        "tool_count": tool_count,
        "base_url_configured": bool(os.environ.get("MAGENTO_BASE_URL")),
        "admin_token_configured": bool(
            os.environ.get("MAGEMCP_ADMIN_TOKEN") or os.environ.get("MAGENTO_TOKEN")
        ),
    }
