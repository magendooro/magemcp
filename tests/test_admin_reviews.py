"""Tests for admin product review tools."""

from __future__ import annotations

import pytest
import respx
import httpx


BASE = "http://magento.test"
REVIEW_SEARCH_URL = f"{BASE}/rest/default/V1/products/review"
REVIEW_URL = f"{BASE}/rest/default/V1/reviews/42"
REVIEWS_PUT_URL = f"{BASE}/rest/default/V1/reviews/42"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("MAGENTO_BASE_URL", BASE)
    monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", "test-token")


def _review(**kwargs):
    defaults = {
        "id": 1,
        "entity_pk_value": "MH01",
        "status_id": 1,
        "title": "Great product",
        "detail": "Really happy with this purchase.",
        "nickname": "JohnD",
        "ratings": [{"rating_name": "Rating", "percent": 80, "value": 4}],
        "created_at": "2026-03-01 12:00:00",
        "store_id": 1,
    }
    return {**defaults, **kwargs}


class TestAdminGetProductReviews:
    async def test_is_registered(self):
        from magemcp.server import mcp
        names = [t.name for t in await mcp.list_tools()]
        assert "admin_get_product_reviews" in names

    @respx.mock
    async def test_returns_reviews(self):
        respx.get(REVIEW_SEARCH_URL).mock(return_value=httpx.Response(200, json={
            "items": [_review()],
            "total_count": 1,
        }))
        from magemcp.tools.admin.reviews import admin_get_product_reviews
        result = await admin_get_product_reviews(sku="MH01")
        assert result["total_count"] == 1
        assert result["sku"] == "MH01"
        assert result["reviews"][0]["title"] == "Great product"
        assert result["reviews"][0]["status"] == "approved"

    @respx.mock
    async def test_status_filter(self):
        respx.get(REVIEW_SEARCH_URL).mock(return_value=httpx.Response(200, json={
            "items": [_review(status_id=2)],
            "total_count": 1,
        }))
        from magemcp.tools.admin.reviews import admin_get_product_reviews
        result = await admin_get_product_reviews(sku="MH01", status_id=2)
        request = respx.calls[0].request
        assert "status_id" in str(request.url)
        assert result["reviews"][0]["status"] == "pending"

    @respx.mock
    async def test_ratings_parsed(self):
        respx.get(REVIEW_SEARCH_URL).mock(return_value=httpx.Response(200, json={
            "items": [_review()],
            "total_count": 1,
        }))
        from magemcp.tools.admin.reviews import admin_get_product_reviews
        result = await admin_get_product_reviews(sku="MH01")
        assert len(result["reviews"][0]["ratings"]) == 1
        assert result["reviews"][0]["ratings"][0]["value"] == 4

    @respx.mock
    async def test_empty_results(self):
        respx.get(REVIEW_SEARCH_URL).mock(return_value=httpx.Response(200, json={
            "items": [],
            "total_count": 0,
        }))
        from magemcp.tools.admin.reviews import admin_get_product_reviews
        result = await admin_get_product_reviews(sku="MH99")
        assert result["reviews"] == []


class TestAdminGetReview:
    async def test_is_registered(self):
        from magemcp.server import mcp
        names = [t.name for t in await mcp.list_tools()]
        assert "admin_get_review" in names

    @respx.mock
    async def test_returns_review(self):
        respx.get(REVIEW_URL).mock(return_value=httpx.Response(200, json=_review(id=42)))
        from magemcp.tools.admin.reviews import admin_get_review
        result = await admin_get_review(review_id=42)
        assert result["id"] == 42
        assert result["title"] == "Great product"

    @respx.mock
    async def test_not_found_raises(self):
        respx.get(REVIEW_URL).mock(return_value=httpx.Response(200, json={}))
        from magemcp.tools.admin.reviews import admin_get_review
        from magemcp.connectors.errors import MagentoNotFoundError
        with pytest.raises(MagentoNotFoundError):
            await admin_get_review(review_id=42)


class TestAdminModerateReview:
    async def test_is_registered(self):
        from magemcp.server import mcp
        names = [t.name for t in await mcp.list_tools()]
        assert "admin_moderate_review" in names

    async def test_requires_confirmation(self):
        from magemcp.tools.admin.reviews import admin_moderate_review
        result = await admin_moderate_review(review_id=42, status_id=1, confirm=False)
        assert "confirm" in result or "confirmation" in str(result).lower()

    @respx.mock
    async def test_approves_with_confirm(self):
        respx.put(REVIEWS_PUT_URL).mock(return_value=httpx.Response(200, json={}))
        from magemcp.tools.admin.reviews import admin_moderate_review
        result = await admin_moderate_review(review_id=42, status_id=1, confirm=True)
        assert result["success"] is True
        assert result["status"] == "approved"

    async def test_invalid_status_raises(self):
        from magemcp.tools.admin.reviews import admin_moderate_review
        with pytest.raises(ValueError, match="status_id"):
            await admin_moderate_review(review_id=42, status_id=99, confirm=True)
