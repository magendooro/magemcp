"""Tests for admin confirmation helpers (needs_confirmation, elicit_confirmation)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from magemcp.tools.admin._confirmation import elicit_confirmation, needs_confirmation


# ---------------------------------------------------------------------------
# needs_confirmation (synchronous two-call helper)
# ---------------------------------------------------------------------------


class TestNeedsConfirmation:
    def test_returns_prompt_by_default(self) -> None:
        result = needs_confirmation("cancel order 1", "1")
        assert result is not None
        assert result["confirmation_required"] is True
        assert "cancel order 1" in result["action"]
        assert result["entity"] == "1"

    def test_confirm_true_returns_none(self) -> None:
        assert needs_confirmation("cancel order 1", "1", confirm=True) is None

    def test_skip_env_var_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGEMCP_SKIP_CONFIRMATION", "true")
        assert needs_confirmation("cancel order 1", "1") is None

    def test_skip_env_var_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGEMCP_SKIP_CONFIRMATION", "TRUE")
        assert needs_confirmation("cancel order 1", "1") is None

    def test_message_includes_action(self) -> None:
        result = needs_confirmation("do something irreversible", "42")
        assert result is not None
        assert "do something irreversible" in result["message"]


# ---------------------------------------------------------------------------
# elicit_confirmation — bypass paths
# ---------------------------------------------------------------------------


class TestElicitConfirmationBypass:
    async def test_confirm_true_returns_none(self) -> None:
        result = await elicit_confirmation(None, "cancel order 1", "1", confirm=True)
        assert result is None

    async def test_skip_env_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGEMCP_SKIP_CONFIRMATION", "true")
        result = await elicit_confirmation(None, "cancel order 1", "1")
        assert result is None

    async def test_no_ctx_returns_two_call_prompt(self) -> None:
        result = await elicit_confirmation(None, "cancel order 1", "1")
        assert result is not None
        assert result["confirmation_required"] is True
        assert result["entity"] == "1"
        assert "cancel order 1" in result["action"]


# ---------------------------------------------------------------------------
# elicit_confirmation — MCP elicitation path (ctx is not None)
# ---------------------------------------------------------------------------


class _ConfirmData(BaseModel):
    confirmed: bool


class TestElicitConfirmationWithCtx:
    def _make_ctx(self, elicit_return: object) -> MagicMock:
        ctx = MagicMock()
        ctx.elicit = AsyncMock(return_value=elicit_return)
        return ctx

    async def test_accepted_confirmed_returns_none(self) -> None:
        from mcp.server.elicitation import AcceptedElicitation

        ctx = self._make_ctx(AcceptedElicitation(data=_ConfirmData(confirmed=True)))
        result = await elicit_confirmation(ctx, "cancel order 1", "1")
        assert result is None

    async def test_accepted_not_confirmed_returns_declined(self) -> None:
        from mcp.server.elicitation import AcceptedElicitation

        ctx = self._make_ctx(AcceptedElicitation(data=_ConfirmData(confirmed=False)))
        result = await elicit_confirmation(ctx, "cancel order 1", "1")
        assert result is not None
        assert result.get("declined") is True
        assert result["confirmation_required"] is False
        assert "declined" in result["message"].lower() or "Action declined" in result["message"]

    async def test_declined_elicitation_falls_back_to_two_call(self) -> None:
        from mcp.server.elicitation import DeclinedElicitation

        ctx = self._make_ctx(DeclinedElicitation())
        result = await elicit_confirmation(ctx, "cancel order 1", "1")
        # Declined (not accepted) → fall back to two-call pattern
        assert result is not None
        assert result["confirmation_required"] is True
        assert result["entity"] == "1"

    async def test_cancelled_elicitation_falls_back_to_two_call(self) -> None:
        from mcp.server.elicitation import CancelledElicitation

        ctx = self._make_ctx(CancelledElicitation())
        result = await elicit_confirmation(ctx, "cancel order 1", "1")
        assert result is not None
        assert result["confirmation_required"] is True

    async def test_elicit_exception_falls_back_to_two_call(self) -> None:
        ctx = MagicMock()
        ctx.elicit = AsyncMock(side_effect=NotImplementedError("client unsupported"))
        result = await elicit_confirmation(ctx, "cancel order 1", "1")
        assert result is not None
        assert result["confirmation_required"] is True
        assert result["entity"] == "1"

    async def test_elicit_called_with_action_and_entity(self) -> None:
        from mcp.server.elicitation import AcceptedElicitation

        ctx = self._make_ctx(AcceptedElicitation(data=_ConfirmData(confirmed=True)))
        await elicit_confirmation(ctx, "hold order 99", "99")
        ctx.elicit.assert_called_once()
        call_kwargs = ctx.elicit.call_args
        msg = call_kwargs.kwargs.get("message", "") or (call_kwargs.args[0] if call_kwargs.args else "")
        assert "hold order 99" in msg
        assert "99" in msg
