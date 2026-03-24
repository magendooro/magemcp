"""Tests for MCP completion (autocomplete) handler."""

from __future__ import annotations

import pytest

from mcp.types import Completion, CompletionArgument, PromptReference, ResourceTemplateReference


class TestCompletionsRegistered:
    def test_completions_capability_enabled(self):
        """Server has a completion handler registered."""
        from magemcp.server import mcp
        # If a completion handler is registered, the MCP server should have it
        from mcp.types import CompleteRequest
        assert CompleteRequest in mcp._mcp_server.request_handlers


class TestStaticCompletions:
    async def test_order_status_prefix(self):
        from magemcp.completions import handle_completion
        ref = PromptReference(type="ref/prompt", name="some_prompt")
        arg = CompletionArgument(name="status", value="pend")
        result = await handle_completion(ref, arg)
        assert result is not None
        assert any("pending" in v for v in result.values)

    async def test_metric_completion(self):
        from magemcp.completions import handle_completion
        ref = PromptReference(type="ref/prompt", name="some_prompt")
        arg = CompletionArgument(name="metric", value="rev")
        result = await handle_completion(ref, arg)
        assert result is not None
        assert "revenue" in result.values

    async def test_group_by_completion(self):
        from magemcp.completions import handle_completion
        ref = PromptReference(type="ref/prompt", name="daily_ops_briefing")
        arg = CompletionArgument(name="group_by", value="m")
        result = await handle_completion(ref, arg)
        assert result is not None
        assert "month" in result.values

    async def test_no_match_returns_none(self):
        from magemcp.completions import handle_completion
        ref = PromptReference(type="ref/prompt", name="some_prompt")
        arg = CompletionArgument(name="unknown_arg_xyz", value="foo")
        result = await handle_completion(ref, arg)
        assert result is None

    async def test_order_status_empty_partial_returns_all(self):
        from magemcp.completions import handle_completion
        ref = PromptReference(type="ref/prompt", name="some_prompt")
        arg = CompletionArgument(name="status", value="")
        result = await handle_completion(ref, arg)
        assert result is not None
        assert len(result.values) > 0


class TestResourceTemplateCompletions:
    async def test_product_sku_routes_to_search(self, monkeypatch):
        from magemcp.completions import handle_completion, _complete_sku
        calls = []

        async def mock_complete(partial: str):
            calls.append(partial)
            return ["MH01", "MH02"]

        monkeypatch.setattr("magemcp.completions._complete_sku", mock_complete)
        ref = ResourceTemplateReference(type="ref/resource", uri="magento://product/{sku}")
        arg = CompletionArgument(name="sku", value="MH")
        result = await handle_completion(ref, arg)
        assert calls == ["MH"]
        assert result is not None
        assert "MH01" in result.values

    async def test_cms_identifier_routes_to_search(self, monkeypatch):
        from magemcp.completions import handle_completion

        async def mock_complete(partial: str):
            return ["about-us", "privacy-policy"]

        monkeypatch.setattr("magemcp.completions._complete_cms_identifier", mock_complete)
        ref = ResourceTemplateReference(type="ref/resource", uri="magento://cms/{identifier}")
        arg = CompletionArgument(name="identifier", value="about")
        result = await handle_completion(ref, arg)
        assert result is not None
        assert "about-us" in result.values


class TestPromptCompletions:
    async def test_investigate_order_order_id(self, monkeypatch):
        from magemcp.completions import handle_completion

        async def mock_complete(partial: str):
            return ["000000001", "000000002"]

        monkeypatch.setattr("magemcp.completions._complete_order_id", mock_complete)
        ref = PromptReference(type="ref/prompt", name="investigate_order")
        arg = CompletionArgument(name="order_id", value="000")
        result = await handle_completion(ref, arg)
        assert result is not None
        assert "000000001" in result.values

    async def test_handle_return_request_order_increment_id(self, monkeypatch):
        from magemcp.completions import handle_completion

        async def mock_complete(partial: str):
            return ["100000042"]

        monkeypatch.setattr("magemcp.completions._complete_order_id", mock_complete)
        ref = PromptReference(type="ref/prompt", name="handle_return_request")
        arg = CompletionArgument(name="order_increment_id", value="1000")
        result = await handle_completion(ref, arg)
        assert result is not None
        assert "100000042" in result.values

    async def test_customer_360_email_returns_empty(self):
        from magemcp.completions import handle_completion
        ref = PromptReference(type="ref/prompt", name="customer_360")
        arg = CompletionArgument(name="email", value="test")
        result = await handle_completion(ref, arg)
        assert result is not None
        assert result.values == []

    async def test_search_and_compare_query_returns_empty(self):
        from magemcp.completions import handle_completion
        ref = PromptReference(type="ref/prompt", name="search_and_compare")
        arg = CompletionArgument(name="query", value="shirt")
        result = await handle_completion(ref, arg)
        assert result is not None
        assert result.values == []

    async def test_coupon_format_completion(self):
        from magemcp.completions import handle_completion
        ref = PromptReference(type="ref/prompt", name="generate_coupon")
        arg = CompletionArgument(name="format", value="al")
        result = await handle_completion(ref, arg)
        assert result is not None
        assert "alphanum" in result.values or "alpha" in result.values

    async def test_order_resource_template_completion(self, monkeypatch):
        from magemcp.completions import handle_completion

        async def mock_complete(partial: str):
            return ["000000099"]

        monkeypatch.setattr("magemcp.completions._complete_order_id", mock_complete)
        ref = ResourceTemplateReference(type="ref/resource", uri="magento://order/{increment_id}")
        arg = CompletionArgument(name="increment_id", value="0000")
        result = await handle_completion(ref, arg)
        assert result is not None
        assert "000000099" in result.values


# ---------------------------------------------------------------------------
# Dynamic completion functions (exercises _complete_sku, _complete_order_id,
# _complete_cms_identifier via respx mocks)
# ---------------------------------------------------------------------------


BASE_URL = "https://magento.test"
TOKEN = "admin-token-123"


@pytest.fixture
def mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAGENTO_BASE_URL", BASE_URL)
    monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", TOKEN)


class TestDynamicCompletions:
    import respx as _respx_module
    import httpx as _httpx_module

    async def test_complete_sku_returns_matching_skus(
        self, mock_env: None, respx_mock,
    ) -> None:
        respx_mock.get(f"{BASE_URL}/rest/default/V1/products").mock(
            return_value=__import__("httpx").Response(200, json={
                "items": [
                    {"sku": "MH01-XS-Black"},
                    {"sku": "MH01-S-Black"},
                ],
                "total_count": 2,
            })
        )
        from magemcp.completions import _complete_sku
        result = await _complete_sku("MH01")
        assert "MH01-XS-Black" in result
        assert "MH01-S-Black" in result

    async def test_complete_sku_returns_empty_on_error(
        self, mock_env: None, respx_mock,
    ) -> None:
        respx_mock.get(f"{BASE_URL}/rest/default/V1/products").mock(
            return_value=__import__("httpx").Response(500, text="error")
        )
        from magemcp.completions import _complete_sku
        result = await _complete_sku("X")
        assert result == []

    async def test_complete_order_id_returns_matching_ids(
        self, mock_env: None, respx_mock,
    ) -> None:
        respx_mock.get(f"{BASE_URL}/rest/default/V1/orders").mock(
            return_value=__import__("httpx").Response(200, json={
                "items": [
                    {"increment_id": "000000042"},
                    {"increment_id": "000000043"},
                ],
                "total_count": 2,
            })
        )
        from magemcp.completions import _complete_order_id
        result = await _complete_order_id("00000004")
        assert "000000042" in result
        assert "000000043" in result

    async def test_complete_order_id_returns_empty_on_error(
        self, mock_env: None, respx_mock,
    ) -> None:
        respx_mock.get(f"{BASE_URL}/rest/default/V1/orders").mock(
            return_value=__import__("httpx").Response(401, text="Unauthorized")
        )
        from magemcp.completions import _complete_order_id
        result = await _complete_order_id("1")
        assert result == []

    async def test_complete_cms_identifier_returns_matching(
        self, mock_env: None, respx_mock,
    ) -> None:
        respx_mock.get(f"{BASE_URL}/rest/default/V1/cmsPage/search").mock(
            return_value=__import__("httpx").Response(200, json={
                "items": [
                    {"identifier": "privacy-policy"},
                    {"identifier": "privacy-notice"},
                ],
                "total_count": 2,
            })
        )
        from magemcp.completions import _complete_cms_identifier
        result = await _complete_cms_identifier("privacy")
        assert "privacy-policy" in result

    async def test_complete_sku_empty_partial(
        self, mock_env: None, respx_mock,
    ) -> None:
        """Empty partial triggers a request without sku filter."""
        route = respx_mock.get(f"{BASE_URL}/rest/default/V1/products").mock(
            return_value=__import__("httpx").Response(200, json={"items": [], "total_count": 0})
        )
        from magemcp.completions import _complete_sku
        await _complete_sku("")
        assert route.called
