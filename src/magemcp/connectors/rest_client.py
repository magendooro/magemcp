"""Async REST client for Magento admin operations.

Requires an integration/admin bearer token for all requests.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from magemcp.audit_context import current_entry as _current_audit_entry
from magemcp.audit_context import truncate_for_audit
from magemcp.connectors.errors import _raise_for_status

log = logging.getLogger(__name__)


def _record_http_mutation(
    method: str,
    url: str,
    body: Any,
    response: "httpx.Response",
) -> None:
    """Append a Magento HTTP call to the active audit entry (if any).

    Only called for state-changing requests (POST / PUT / DELETE) so read-only
    GET calls don't flood the audit log.
    """
    entry = _current_audit_entry.get()
    if entry is None:
        return
    try:
        resp_body = response.json()
    except Exception:
        resp_body = None
    entry["http_calls"].append({
        "method": method,
        "url": url,
        "body": truncate_for_audit(body),
        "status": response.status_code,
        "response": truncate_for_audit(resp_body),
    })


def _parse_verify_ssl() -> bool | str:
    """Parse MAGENTO_VERIFY_SSL env var.

    - unset / 'true' / '1' → True (default — verify using system CAs)
    - 'false' / '0'        → False (disable verification; logs a warning)
    - any other value      → treated as a path to a CA bundle / cert file
    """
    raw = os.environ.get("MAGENTO_VERIFY_SSL", "true").strip().lower()
    if raw in ("false", "0"):
        return False
    if raw in ("true", "1"):
        return True
    return raw  # path to CA bundle


class RESTClient:
    """Async REST client for Magento admin operations.

    Usage::

        async with RESTClient(base_url="http://127.0.0.1:8082", admin_token="abc") as rest:
            order = await rest.get("/V1/orders/42")
    """

    def __init__(
        self,
        base_url: str,
        admin_token: str,
        *,
        store_code: str = "default",
        timeout: float = 30.0,
        verify: bool | str = True,
        _owned: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.admin_token = admin_token
        self.store_code = store_code
        self._owned = _owned  # False for borrowed pool references

        if verify is False:
            log.warning("SSL verification disabled for REST client (MAGENTO_VERIFY_SSL=false)")

        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self.admin_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=timeout,
            verify=verify,
        )

    @classmethod
    def from_env(cls, **kwargs: Any) -> RESTClient:
        """Create from environment variables.

        Required: ``MAGENTO_BASE_URL``, ``MAGEMCP_ADMIN_TOKEN``
        Optional: ``MAGENTO_STORE_CODE``

        Falls back to ``MAGENTO_TOKEN`` if ``MAGEMCP_ADMIN_TOKEN`` is not set
        (backward compatibility).

        When a shared pool client is available (initialised via
        ``magemcp.connectors.pool.init()``), returns a *borrowed* reference to
        it instead of creating a new client.  The borrowed reference's
        ``close()`` method is a no-op so the pool is not torn down per call.
        """
        from magemcp.connectors.pool import get_rest

        pooled = get_rest()
        if pooled is not None:
            # Return a borrowed wrapper: same underlying httpx client, no-op close.
            borrowed = cls.__new__(cls)
            borrowed.base_url = pooled.base_url
            borrowed.admin_token = pooled.admin_token
            borrowed.store_code = pooled.store_code
            borrowed._client = pooled._client
            borrowed._owned = False
            return borrowed

        base_url = os.environ.get("MAGENTO_BASE_URL", "")
        if not base_url:
            msg = "MAGENTO_BASE_URL environment variable is required"
            raise ValueError(msg)

        admin_token = os.environ.get("MAGEMCP_ADMIN_TOKEN") or os.environ.get("MAGENTO_TOKEN", "")
        if not admin_token:
            msg = "MAGEMCP_ADMIN_TOKEN environment variable is required for admin REST operations"
            raise ValueError(msg)

        verify = _parse_verify_ssl()
        return cls(
            base_url=base_url,
            admin_token=admin_token,
            store_code=os.environ.get("MAGENTO_STORE_CODE", "default"),
            verify=verify,
            **kwargs,
        )

    # -- context manager -----------------------------------------------------

    async def __aenter__(self) -> RESTClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the underlying HTTP client (no-op for borrowed pool references)."""
        if self._owned:
            await self._client.aclose()

    # -- URL builder ---------------------------------------------------------

    def _rest_url(self, endpoint: str, *, store_code: str | None = None) -> str:
        """Build a scoped REST URL: ``/rest/{store}/V1/…``."""
        store = store_code or self.store_code
        if not endpoint.startswith("/"):
            endpoint = f"/{endpoint}"
        return f"/rest/{store}{endpoint}"

    # -- HTTP methods --------------------------------------------------------

    async def get(
        self,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        store_code: str | None = None,
    ) -> Any:
        """``GET`` against the Magento REST API."""
        url = self._rest_url(endpoint, store_code=store_code)
        log.debug("GET %s params=%s", url, params)
        response = await self._client.get(url, params=params)
        _raise_for_status(response)
        return response.json()

    async def post(
        self,
        endpoint: str,
        *,
        json: Any = None,
        store_code: str | None = None,
    ) -> Any:
        """``POST`` against the Magento REST API."""
        url = self._rest_url(endpoint, store_code=store_code)
        log.debug("POST %s", url)
        response = await self._client.post(url, json=json)
        _raise_for_status(response)
        _record_http_mutation("POST", f"{self.base_url}{url}", json, response)
        return response.json()

    async def put(
        self,
        endpoint: str,
        *,
        json: Any = None,
        store_code: str | None = None,
    ) -> Any:
        """``PUT`` against the Magento REST API."""
        url = self._rest_url(endpoint, store_code=store_code)
        log.debug("PUT %s", url)
        response = await self._client.put(url, json=json)
        _raise_for_status(response)
        _record_http_mutation("PUT", f"{self.base_url}{url}", json, response)
        return response.json()

    async def delete(
        self,
        endpoint: str,
        *,
        store_code: str | None = None,
    ) -> Any:
        """``DELETE`` against the Magento REST API."""
        url = self._rest_url(endpoint, store_code=store_code)
        log.debug("DELETE %s", url)
        response = await self._client.delete(url)
        _raise_for_status(response)
        _record_http_mutation("DELETE", f"{self.base_url}{url}", None, response)
        return response.json()

    # -- searchCriteria builder ----------------------------------------------

    @staticmethod
    def search_params(
        filters: dict[str, Any] | None = None,
        *,
        page_size: int = 20,
        current_page: int = 1,
        sort_field: str | None = None,
        sort_direction: str = "ASC",
    ) -> dict[str, str]:
        """Build Magento ``searchCriteria`` query parameters.

        *filters* is a dict mapping field names to either a plain value
        (uses ``eq`` condition) or a ``(value, condition_type)`` tuple::

            params = RESTClient.search_params(
                filters={"status": "processing"},
                page_size=10,
            )
            orders = await client.get("/V1/orders", params=params)
        """
        params: dict[str, str] = {
            "searchCriteria[pageSize]": str(page_size),
            "searchCriteria[currentPage]": str(current_page),
        }

        if filters:
            for idx, (field, value) in enumerate(filters.items()):
                if isinstance(value, tuple):
                    val, condition = value
                else:
                    val, condition = value, "eq"
                prefix = f"searchCriteria[filterGroups][{idx}][filters][0]"
                params[f"{prefix}[field]"] = field
                params[f"{prefix}[value]"] = str(val)
                params[f"{prefix}[conditionType]"] = condition

        if sort_field:
            params["searchCriteria[sortOrders][0][field]"] = sort_field
            params["searchCriteria[sortOrders][0][direction]"] = sort_direction

        return params
