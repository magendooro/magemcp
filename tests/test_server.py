"""Smoke test — server module imports and MCP instance exists."""

from magemcp.server import mcp


def test_mcp_instance_exists() -> None:
    assert mcp is not None
    assert mcp.name == "MageMCP"
