"""Tests for the health check endpoint."""

from __future__ import annotations

import os
import time

import pytest

from magemcp.health import get_health


class TestGetHealth:
    def test_status_ok(self) -> None:
        result = get_health(tool_count=10)
        assert result["status"] == "ok"

    def test_tool_count(self) -> None:
        result = get_health(tool_count=42)
        assert result["tool_count"] == 42

    def test_uptime_non_negative(self) -> None:
        result = get_health(tool_count=0)
        assert result["uptime_seconds"] >= 0

    def test_base_url_configured_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGENTO_BASE_URL", "https://magento.test")
        result = get_health(tool_count=0)
        assert result["base_url_configured"] is True

    def test_base_url_configured_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MAGENTO_BASE_URL", raising=False)
        result = get_health(tool_count=0)
        assert result["base_url_configured"] is False

    def test_admin_token_configured_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", "sometoken")
        result = get_health(tool_count=0)
        assert result["admin_token_configured"] is True

    def test_admin_token_falls_back_to_magento_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MAGEMCP_ADMIN_TOKEN", raising=False)
        monkeypatch.setenv("MAGENTO_TOKEN", "legacy-token")
        result = get_health(tool_count=0)
        assert result["admin_token_configured"] is True

    def test_admin_token_configured_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MAGEMCP_ADMIN_TOKEN", raising=False)
        monkeypatch.delenv("MAGENTO_TOKEN", raising=False)
        result = get_health(tool_count=0)
        assert result["admin_token_configured"] is False


class TestHealthRoute:
    async def test_route_registered(self) -> None:
        from magemcp.server import mcp

        route_paths = [r.path for r in mcp._custom_starlette_routes]
        assert "/health" in route_paths
