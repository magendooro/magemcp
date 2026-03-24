from __future__ import annotations

import os
from typing import Any


def needs_confirmation(action: str, entity_id: str, confirm: bool = False) -> dict[str, Any] | None:
    """Return a confirmation prompt dict if confirmation is required, None if the action may proceed.

    Pass confirm=True on the second call to proceed.
    Set MAGEMCP_SKIP_CONFIRMATION=true to bypass for automated pipelines.
    """
    if confirm or os.getenv("MAGEMCP_SKIP_CONFIRMATION", "").lower() == "true":
        return None
    return {
        "confirmation_required": True,
        "action": action,
        "entity": entity_id,
        "message": f"This will {action} order {entity_id}. Call again with confirm=True to proceed.",
    }
