from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import Context


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
        "message": f"This will {action}. Call again with confirm=True to proceed.",
    }


async def elicit_confirmation(
    ctx: Context | None,
    action: str,
    entity_id: str,
    confirm: bool = False,
) -> dict[str, Any] | None:
    """Attempt MCP elicitation for confirmation; fall back to two-call pattern.

    Returns None if the action may proceed, or a dict that should be returned to the caller
    if the action should be blocked (pending confirmation or user declined).
    """
    if confirm or os.getenv("MAGEMCP_SKIP_CONFIRMATION", "").lower() == "true":
        return None

    # Try MCP elicitation if we have a context
    if ctx is not None:
        try:
            from pydantic import BaseModel

            class ConfirmSchema(BaseModel):
                confirmed: bool

            result = await ctx.elicit(
                message=f"Confirm: {action}? (entity: {entity_id})",
                schema=ConfirmSchema,
            )

            from mcp.server.elicitation import AcceptedElicitation, DeclinedElicitation

            if isinstance(result, AcceptedElicitation) and result.data.confirmed:
                return None  # Proceed
            if isinstance(result, AcceptedElicitation) and not result.data.confirmed:
                return {"confirmation_required": False, "declined": True, "action": action,
                        "message": "Action declined by user."}
            # Declined or cancelled elicitation → fall back to two-call pattern
        except Exception:
            # Client doesn't support elicitation — fall back to two-call pattern
            pass

    return {
        "confirmation_required": True,
        "action": action,
        "entity": entity_id,
        "message": f"This will {action}. Call again with confirm=True to proceed.",
    }
