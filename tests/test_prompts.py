"""Tests for MageMCP MCP Prompts (T08)."""

from __future__ import annotations

import pytest


class TestPromptRegistration:
    async def test_prompts_listed(self) -> None:
        from magemcp.server import mcp

        prompts = await mcp.list_prompts()
        names = [p.name for p in prompts]
        assert "investigate_order" in names
        assert "daily_ops_briefing" in names
        assert "customer_360" in names
        assert "search_and_compare" in names
        assert "handle_return_request" in names

    async def test_prompts_have_titles(self) -> None:
        from magemcp.server import mcp

        prompts = await mcp.list_prompts()
        for p in prompts:
            assert p.title, f"Prompt '{p.name}' has no title"

    async def test_prompts_have_descriptions(self) -> None:
        from magemcp.server import mcp

        prompts = await mcp.list_prompts()
        for p in prompts:
            assert p.description, f"Prompt '{p.name}' has no description"


class TestInvestigateOrderPrompt:
    async def test_prompt_arguments(self) -> None:
        from magemcp.server import mcp

        prompts = {p.name: p for p in await mcp.list_prompts()}
        p = prompts["investigate_order"]
        arg_names = [a.name for a in (p.arguments or [])]
        assert "order_id" in arg_names

    async def test_prompt_output_contains_order_id(self) -> None:
        from magemcp.prompts import register_prompts
        from mcp.server.fastmcp import FastMCP

        _mcp = FastMCP("test-prompts")
        register_prompts(_mcp)

        result = await _mcp.get_prompt("investigate_order", {"order_id": "000000042"})
        assert result.messages
        text = result.messages[0].content.text  # type: ignore[union-attr]
        assert "000000042" in text
        assert "admin_get_order" in text

    async def test_daily_ops_briefing_no_args(self) -> None:
        from magemcp.prompts import register_prompts
        from mcp.server.fastmcp import FastMCP

        _mcp = FastMCP("test-prompts-ops")
        register_prompts(_mcp)

        result = await _mcp.get_prompt("daily_ops_briefing", {})
        assert result.messages
        text = result.messages[0].content.text  # type: ignore[union-attr]
        assert "admin_get_analytics" in text

    async def test_customer_360_contains_email(self) -> None:
        from magemcp.prompts import register_prompts
        from mcp.server.fastmcp import FastMCP

        _mcp = FastMCP("test-prompts-c360")
        register_prompts(_mcp)

        result = await _mcp.get_prompt(
            "customer_360", {"customer_email": "test@example.com"}
        )
        text = result.messages[0].content.text  # type: ignore[union-attr]
        assert "test@example.com" in text
        assert "admin_search_customers" in text

    async def test_search_and_compare_contains_query(self) -> None:
        from magemcp.prompts import register_prompts
        from mcp.server.fastmcp import FastMCP

        _mcp = FastMCP("test-prompts-search")
        register_prompts(_mcp)

        result = await _mcp.get_prompt("search_and_compare", {"query": "blue widget"})
        text = result.messages[0].content.text  # type: ignore[union-attr]
        assert "blue widget" in text
        assert "c_search_products" in text

    async def test_handle_return_contains_order(self) -> None:
        from magemcp.prompts import register_prompts
        from mcp.server.fastmcp import FastMCP

        _mcp = FastMCP("test-prompts-return")
        register_prompts(_mcp)

        result = await _mcp.get_prompt(
            "handle_return_request", {"order_id": "000000099"}
        )
        text = result.messages[0].content.text  # type: ignore[union-attr]
        assert "000000099" in text
        assert "admin_get_order" in text
