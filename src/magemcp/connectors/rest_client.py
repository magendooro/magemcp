"""Async REST client for Magento admin operations.

Requires an integration/admin bearer token for all requests.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from magemcp.connectors.errors import _raise_for_status

log = logging.getLogger(__name__)


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
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.admin_token = admin_token
        self.store_code = store_code

        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self.admin_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=timeout,
        )

    @classmethod
    def from_env(cls, **kwargs: Any) -> RESTClient:
        """Create from environment variables.

        Required: ``MAGENTO_BASE_URL``, ``MAGEMCP_ADMIN_TOKEN``
        Optional: ``MAGENTO_STORE_CODE``

        Falls back to ``MAGENTO_TOKEN`` if ``MAGEMCP_ADMIN_TOKEN`` is not set
        (backward compatibility).
        """
        base_url = os.environ.get("MAGENTO_BASE_URL", "")
        if not base_url:
            msg = "MAGENTO_BASE_URL environment variable is required"
            raise ValueError(msg)

        admin_token = os.environ.get("MAGEMCP_ADMIN_TOKEN") or os.environ.get("MAGENTO_TOKEN", "")
        if not admin_token:
            msg = "MAGEMCP_ADMIN_TOKEN environment variable is required for admin REST operations"
            raise ValueError(msg)

        return cls(
            base_url=base_url,
            admin_token=admin_token,
            store_code=os.environ.get("MAGENTO_STORE_CODE", "default"),
            **kwargs,
        )

    # -- context manager -----------------------------------------------------

    async def __aenter__(self) -> RESTClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the underlying HTTP client."""
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
