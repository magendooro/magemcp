"""Async GraphQL client for Magento storefront operations.

No authentication required for public catalog queries. Optional customer token
for authenticated customer-scoped operations (cart, account).
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from magemcp.connectors.errors import MagentoError, _raise_for_status

log = logging.getLogger(__name__)


class GraphQLClient:
    """Async GraphQL client for Magento storefront operations.

    Usage::

        async with GraphQLClient(base_url="http://127.0.0.1:8082") as gql:
            data = await gql.query('{ storeConfig { locale } }')

        # With customer token for authenticated operations:
        async with GraphQLClient(base_url=url, customer_token="abc") as gql:
            data = await gql.query('{ customer { firstname } }')
    """

    def __init__(
        self,
        base_url: str,
        *,
        store_code: str = "default",
        customer_token: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.store_code = store_code
        self.customer_token = customer_token

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if customer_token:
            headers["Authorization"] = f"Bearer {customer_token}"

        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=timeout,
        )

    @classmethod
    def from_env(cls, **kwargs: Any) -> GraphQLClient:
        """Create from environment variables.

        Required: ``MAGENTO_BASE_URL``
        Optional: ``MAGENTO_CUSTOMER_TOKEN``, ``MAGENTO_STORE_CODE``
        """
        base_url = os.environ.get("MAGENTO_BASE_URL", "")
        if not base_url:
            msg = "MAGENTO_BASE_URL environment variable is required"
            raise ValueError(msg)

        return cls(
            base_url=base_url,
            store_code=os.environ.get("MAGENTO_STORE_CODE", "default"),
            customer_token=os.environ.get("MAGENTO_CUSTOMER_TOKEN") or None,
            **kwargs,
        )

    # -- context manager -----------------------------------------------------

    async def __aenter__(self) -> GraphQLClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    # -- query ---------------------------------------------------------------

    async def query(
        self,
        query: str,
        *,
        variables: dict[str, Any] | None = None,
        store_code: str | None = None,
    ) -> dict[str, Any]:
        """Execute a GraphQL query against Magento.

        Returns the ``data`` portion of the response.
        Raises :class:`MagentoError` if the response contains GraphQL-level errors.
        """
        store = store_code or self.store_code
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        log.debug("GraphQL store=%s query=%s…", store, query[:80])
        response = await self._client.post(
            "/graphql",
            json=payload,
            headers={"Store": store},
        )
        _raise_for_status(response)

        result = response.json()

        if "errors" in result:
            errors = result["errors"]
            msg = errors[0].get("message", "GraphQL error") if errors else "GraphQL error"
            raise MagentoError(msg, response_body=result)

        return result.get("data", result)
