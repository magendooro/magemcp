"""Tests for admin promotions tools."""

from __future__ import annotations

import json
from typing import Any

import pytest
import respx
from httpx import Response

from magemcp.tools.admin.promotions import (
    _parse_rule_summary,
    admin_generate_coupons,
    admin_get_sales_rule,
    admin_search_sales_rules,
)

BASE_URL = "https://magento.test"
TOKEN = "admin-token-123"
STORE_CODE = "default"


@pytest.fixture
def mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAGENTO_BASE_URL", BASE_URL)
    monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("MAGENTO_STORE_CODE", STORE_CODE)


def _make_rule(
    *,
    rule_id: int = 1,
    name: str = "Summer Sale 20% Off",
    is_active: bool = True,
    coupon_type: int = 2,
    coupon_code: str = "SUMMER20",
    discount_amount: float = 20.0,
    simple_action: str = "by_percent",
    from_date: str = "2024-06-01",
    to_date: str | None = "2024-08-31",
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "name": name,
        "description": "20% off all items",
        "is_active": is_active,
        "coupon_type": coupon_type,
        "coupon_code": coupon_code,
        "uses_per_coupon": 0,
        "uses_per_customer": 1,
        "discount_amount": discount_amount,
        "simple_action": simple_action,
        "from_date": from_date,
        "to_date": to_date,
        "website_ids": [1],
        "customer_group_ids": [0, 1, 2],
        "stop_rules_processing": False,
        "sort_order": 0,
        "discount_qty": None,
        "discount_step": 0,
        "apply_to_shipping": False,
        "times_used": 42,
        "conditions": {"type": "Magento\\SalesRule\\Model\\Rule\\Condition\\Combine"},
        "actions": {"type": "Magento\\SalesRule\\Model\\Rule\\Condition\\Product\\Combine"},
        "store_labels": [],
    }


def _wrap_search(items: list[dict[str, Any]], total: int | None = None) -> dict[str, Any]:
    return {"items": items, "search_criteria": {}, "total_count": total or len(items)}


# ---------------------------------------------------------------------------
# Unit — _parse_rule_summary
# ---------------------------------------------------------------------------


class TestParseRuleSummary:
    def test_basic_fields(self) -> None:
        raw = _make_rule()
        summary = _parse_rule_summary(raw)
        assert summary["rule_id"] == 1
        assert summary["name"] == "Summer Sale 20% Off"
        assert summary["is_active"] is True
        assert summary["coupon_code"] == "SUMMER20"
        assert summary["discount_amount"] == 20.0
        assert summary["simple_action"] == "by_percent"

    def test_missing_optional_fields(self) -> None:
        raw = {"rule_id": 99}
        summary = _parse_rule_summary(raw)
        assert summary["rule_id"] == 99
        assert summary["name"] is None
        assert summary["coupon_code"] is None
        assert summary["website_ids"] == []


# ---------------------------------------------------------------------------
# admin_search_sales_rules
# ---------------------------------------------------------------------------


class TestSearchSalesRules:
    async def test_name_filter_uses_like(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/salesRules/search").mock(
            return_value=Response(200, json=_wrap_search([_make_rule()]))
        )
        result = await admin_search_sales_rules(name="%Summer%")
        url = str(respx_mock.calls.last.request.url)
        assert "name" in url
        assert "like" in url
        assert result["total_count"] == 1
        assert result["rules"][0]["name"] == "Summer Sale 20% Off"

    async def test_is_active_filter(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/salesRules/search").mock(
            return_value=Response(200, json=_wrap_search([_make_rule(is_active=True)]))
        )
        result = await admin_search_sales_rules(is_active=True)
        url = str(respx_mock.calls.last.request.url)
        assert "is_active" in url
        assert result["rules"][0]["is_active"] is True

    async def test_returns_pagination_metadata(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/salesRules/search").mock(
            return_value=Response(200, json=_wrap_search([_make_rule()], total=15))
        )
        result = await admin_search_sales_rules(page_size=5)
        assert result["total_count"] == 15
        assert "rules" in result

    async def test_coupon_type_filter(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/salesRules/search").mock(
            return_value=Response(200, json=_wrap_search([_make_rule(coupon_type=3)]))
        )
        result = await admin_search_sales_rules(coupon_type=3)
        url = str(respx_mock.calls.last.request.url)
        assert "coupon_type" in url
        assert result["rules"][0]["coupon_type"] == 3


# ---------------------------------------------------------------------------
# admin_get_sales_rule
# ---------------------------------------------------------------------------


class TestGetSalesRule:
    async def test_returns_full_detail(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/salesRules/1").mock(
            return_value=Response(200, json=_make_rule())
        )
        result = await admin_get_sales_rule(rule_id=1)
        assert result["rule_id"] == 1
        assert result["name"] == "Summer Sale 20% Off"
        # Full detail includes conditions/actions
        assert "conditions" in result
        assert "actions" in result
        assert result["times_used"] == 42

    async def test_not_found_returns_error(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        from magemcp.connectors.errors import MagentoNotFoundError
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/salesRules/9999").mock(
            return_value=Response(404, json={"message": "No such entity"})
        )
        with pytest.raises(MagentoNotFoundError):
            await admin_get_sales_rule(rule_id=9999)

    async def test_empty_response_raises_not_found(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        from magemcp.connectors.errors import MagentoNotFoundError
        respx_mock.get(f"{BASE_URL}/rest/{STORE_CODE}/V1/salesRules/42").mock(
            return_value=Response(200, json={})
        )
        with pytest.raises(MagentoNotFoundError):
            await admin_get_sales_rule(rule_id=42)


# ---------------------------------------------------------------------------
# admin_generate_coupons
# ---------------------------------------------------------------------------


class TestGenerateCoupons:
    async def test_requires_confirmation(self, mock_env: None) -> None:
        result = await admin_generate_coupons(rule_id=1, quantity=5)
        assert result["confirmation_required"] is True
        assert "1" in result["entity"]

    async def test_payload_structure(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        codes = ["ABC123XYZ456", "DEF456UVW789"]
        respx_mock.post(f"{BASE_URL}/rest/{STORE_CODE}/V1/coupons/generate").mock(
            return_value=Response(200, json=codes)
        )
        result = await admin_generate_coupons(
            rule_id=1, quantity=2, length=12, format="alphanum", confirm=True
        )
        assert result["success"] is True
        assert result["rule_id"] == 1
        assert result["generated"] == 2
        assert result["coupon_codes"] == codes

        payload = json.loads(respx_mock.calls.last.request.content)
        spec = payload["couponSpec"]
        assert spec["rule_id"] == 1
        assert spec["qty"] == 2
        assert spec["length"] == 12
        assert spec["format"] == "alphanum"

    async def test_default_quantity_and_format(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.post(f"{BASE_URL}/rest/{STORE_CODE}/V1/coupons/generate").mock(
            return_value=Response(200, json=["SINGLECODE1"])
        )
        result = await admin_generate_coupons(rule_id=2, confirm=True)
        assert result["generated"] == 1
        payload = json.loads(respx_mock.calls.last.request.content)
        assert payload["couponSpec"]["qty"] == 1
        assert payload["couponSpec"]["format"] == "alphanum"

    async def test_idempotency_key_stores_and_replays(self, mock_env: None, respx_mock: respx.MockRouter) -> None:
        respx_mock.post(f"{BASE_URL}/rest/{STORE_CODE}/V1/coupons/generate").mock(
            return_value=Response(200, json=["IDEM-CODE-1"])
        )
        result = await admin_generate_coupons(
            rule_id=3, confirm=True, idempotency_key="gen-001"
        )
        assert result["success"] is True
        assert result["coupon_codes"] == ["IDEM-CODE-1"]

        # Second call with same key should return replay without hitting API
        result2 = await admin_generate_coupons(
            rule_id=3, confirm=True, idempotency_key="gen-001"
        )
        assert result2.get("idempotent_replay") is True
