"""Tests for magemcp.utils.idempotency — IdempotencyStore."""

from __future__ import annotations

import time

import pytest

from magemcp.utils.idempotency import IdempotencyStore


class TestIdempotencyStoreBasics:
    def test_miss_returns_none(self) -> None:
        store = IdempotencyStore()
        assert store.get("tool", "key-1") is None

    def test_set_and_get(self) -> None:
        store = IdempotencyStore()
        store.set("tool", "key-1", {"order_id": 42, "success": True})
        result = store.get("tool", "key-1")
        assert result == {"order_id": 42, "success": True}

    def test_different_tools_are_isolated(self) -> None:
        store = IdempotencyStore()
        store.set("tool_a", "shared-key", {"tool": "a"})
        store.set("tool_b", "shared-key", {"tool": "b"})
        assert store.get("tool_a", "shared-key")["tool"] == "a"
        assert store.get("tool_b", "shared-key")["tool"] == "b"

    def test_len(self) -> None:
        store = IdempotencyStore()
        store.set("tool", "k1", {"x": 1})
        store.set("tool", "k2", {"x": 2})
        assert len(store) == 2

    def test_clear(self) -> None:
        store = IdempotencyStore()
        store.set("tool", "key-1", {"x": 1})
        store.clear()
        assert store.get("tool", "key-1") is None
        assert len(store) == 0

    def test_overwrite(self) -> None:
        store = IdempotencyStore()
        store.set("tool", "k", {"v": 1})
        store.set("tool", "k", {"v": 2})
        assert store.get("tool", "k") == {"v": 2}


class TestIdempotencyStoreTTL:
    def test_expired_entry_returns_none(self) -> None:
        store = IdempotencyStore(ttl=60)
        store.set("tool", "k", {"x": 1})
        # Backdate the stored expiry
        raw_key = store._key("tool", "k")
        value, _ = store._cache._store[raw_key]
        store._cache._store[raw_key] = (value, time.monotonic() - 1)
        assert store.get("tool", "k") is None

    def test_short_ttl_expires(self) -> None:
        store = IdempotencyStore(ttl=0.001)
        store.set("tool", "k", {"x": 1})
        time.sleep(0.01)
        assert store.get("tool", "k") is None


class TestIdempotencyInOrderActions:
    async def test_cancel_replay(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGENTO_BASE_URL", "https://magento.test")
        monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", "token")

        from magemcp.utils.idempotency import idempotency_store
        from magemcp.tools.admin.order_actions import admin_cancel_order

        idempotency_store.clear()
        # Seed the store so no HTTP call is made
        idempotency_store.set(
            "admin_cancel_order", "idem-key-1",
            {"success": True, "order_id": 99, "action": "cancelled"},
        )
        result = await admin_cancel_order(order_id=99, confirm=True, idempotency_key="idem-key-1")
        assert result["idempotent_replay"] is True
        assert result["success"] is True

    async def test_cancel_stores_on_first_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGENTO_BASE_URL", "https://magento.test")
        monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", "token")

        import respx
        import httpx
        from magemcp.utils.idempotency import idempotency_store
        from magemcp.tools.admin.order_actions import admin_cancel_order

        idempotency_store.clear()
        with respx.mock:
            respx.post("https://magento.test/rest/default/V1/orders/5/cancel").mock(
                return_value=httpx.Response(200, json=True)
            )
            result = await admin_cancel_order(
                order_id=5, confirm=True, idempotency_key="idem-key-2"
            )

        assert result["success"] is True
        assert "idempotent_replay" not in result
        # Now the store should have it
        stored = idempotency_store.get("admin_cancel_order", "idem-key-2")
        assert stored is not None
        assert stored["order_id"] == 5

    async def test_invoice_replay(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGENTO_BASE_URL", "https://magento.test")
        monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", "token")

        from magemcp.utils.idempotency import idempotency_store
        from magemcp.tools.admin.order_actions import admin_create_invoice

        idempotency_store.clear()
        idempotency_store.set(
            "admin_create_invoice", "inv-idem-1",
            {"success": True, "order_id": 7, "invoice_id": 42},
        )
        result = await admin_create_invoice(order_id=7, confirm=True, idempotency_key="inv-idem-1")
        assert result["idempotent_replay"] is True
        assert result["invoice_id"] == 42

    async def test_shipment_replay(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGENTO_BASE_URL", "https://magento.test")
        monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", "token")

        from magemcp.utils.idempotency import idempotency_store
        from magemcp.tools.admin.order_actions import admin_create_shipment

        idempotency_store.clear()
        idempotency_store.set(
            "admin_create_shipment", "ship-idem-1",
            {"success": True, "order_id": 8, "shipment_id": 55},
        )
        result = await admin_create_shipment(order_id=8, confirm=True, idempotency_key="ship-idem-1")
        assert result["idempotent_replay"] is True
        assert result["shipment_id"] == 55

    async def test_comment_replay(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGENTO_BASE_URL", "https://magento.test")
        monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", "token")

        from magemcp.utils.idempotency import idempotency_store
        from magemcp.tools.admin.order_actions import admin_add_order_comment

        idempotency_store.clear()
        idempotency_store.set(
            "admin_add_order_comment", "comment-idem-1",
            {"success": True, "order_id": 10, "comment": "test"},
        )
        result = await admin_add_order_comment(
            order_id=10, comment="different text", idempotency_key="comment-idem-1"
        )
        assert result["idempotent_replay"] is True
        assert result["comment"] == "test"  # original stored value

    async def test_email_replay(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGENTO_BASE_URL", "https://magento.test")
        monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", "token")

        from magemcp.utils.idempotency import idempotency_store
        from magemcp.tools.admin.order_actions import admin_send_order_email

        idempotency_store.clear()
        idempotency_store.set(
            "admin_send_order_email", "email-idem-1",
            {"success": True, "order_id": 11, "action": "email_sent"},
        )
        result = await admin_send_order_email(order_id=11, idempotency_key="email-idem-1")
        assert result["idempotent_replay"] is True

    async def test_coupons_replay(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGENTO_BASE_URL", "https://magento.test")
        monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", "token")

        from magemcp.utils.idempotency import idempotency_store
        from magemcp.tools.admin.promotions import admin_generate_coupons

        idempotency_store.clear()
        idempotency_store.set(
            "admin_generate_coupons", "coupon-idem-1",
            {"success": True, "rule_id": 3, "generated": 2, "coupon_codes": ["AAA", "BBB"]},
        )
        result = await admin_generate_coupons(rule_id=3, confirm=True, idempotency_key="coupon-idem-1")
        assert result["idempotent_replay"] is True
        assert result["coupon_codes"] == ["AAA", "BBB"]

    async def test_no_idempotency_key_skips_store(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without an idempotency_key, the store is never consulted."""
        monkeypatch.setenv("MAGENTO_BASE_URL", "https://magento.test")
        monkeypatch.setenv("MAGEMCP_ADMIN_TOKEN", "token")

        import respx
        import httpx
        from magemcp.utils.idempotency import idempotency_store
        from magemcp.tools.admin.order_actions import admin_send_order_email

        idempotency_store.clear()
        with respx.mock:
            respx.post("https://magento.test/rest/default/V1/orders/20/emails").mock(
                return_value=httpx.Response(200, json=True)
            )
            result = await admin_send_order_email(order_id=20)

        assert result["success"] is True
        assert "idempotent_replay" not in result
        assert len(idempotency_store) == 0
