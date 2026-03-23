"""Backward-compatible wrapper — re-exports from split clients.

Existing code importing ``MagentoClient`` from this module will continue to work.
New code should import ``GraphQLClient`` or ``RESTClient`` directly.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from pydantic_settings import BaseSettings

from magemcp.connectors.errors import (
    MagentoAuthError,
    MagentoError,
    MagentoNotFoundError,
    MagentoRateLimitError,
    MagentoServerError,
    MagentoValidationError,
    _raise_for_status,
)
from magemcp.connectors.graphql_client import GraphQLClient
from magemcp.connectors.rest_client import RESTClient

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration (kept here for backward compat)
# ---------------------------------------------------------------------------


class MagentoConfig(BaseSettings):
    """Magento connection settings loaded from environment variables."""

    magento_base_url: str
    magento_token: str
    magento_store_code: str = "default"

    model_config = {"env_prefix": ""}


# ---------------------------------------------------------------------------
# Legacy unified client — wraps both RESTClient and GraphQLClient
# ---------------------------------------------------------------------------


class MagentoClient:
    """Backward-compatible async client wrapping both REST and GraphQL.

    New code should use :class:`RESTClient` or :class:`GraphQLClient` directly.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        store_code: str = "default",
        *,
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.store_code = store_code

        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=timeout,
        )

    @classmethod
    def from_config(cls, config: MagentoConfig | None = None, **kwargs: Any) -> MagentoClient:
        """Create a client from a :class:`MagentoConfig`.

        Reads env vars if *config* is ``None``.
        """
        if config is None:
            config = MagentoConfig()  # type: ignore[call-arg]
        return cls(
            base_url=config.magento_base_url,
            token=config.magento_token,
            store_code=config.magento_store_code,
            **kwargs,
        )

    async def __aenter__(self) -> MagentoClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _rest_url(self, endpoint: str, *, store_code: str | None = None) -> str:
        store = store_code or self.store_code
        if not endpoint.startswith("/"):
            endpoint = f"/{endpoint}"
        return f"/rest/{store}{endpoint}"

    async def get(
        self,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        store_code: str | None = None,
    ) -> Any:
        url = self._rest_url(endpoint, store_code=store_code)
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
        url = self._rest_url(endpoint, store_code=store_code)
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
        url = self._rest_url(endpoint, store_code=store_code)
        response = await self._client.put(url, json=json)
        _raise_for_status(response)
        return response.json()

    async def graphql(
        self,
        query: str,
        *,
        variables: dict[str, Any] | None = None,
        store_code: str | None = None,
    ) -> dict[str, Any]:
        store = store_code or self.store_code
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

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

    @staticmethod
    def search_params(
        filters: dict[str, Any] | None = None,
        *,
        page_size: int = 20,
        current_page: int = 1,
        sort_field: str | None = None,
        sort_direction: str = "ASC",
    ) -> dict[str, str]:
        return RESTClient.search_params(
            filters=filters,
            page_size=page_size,
            current_page=current_page,
            sort_field=sort_field,
            sort_direction=sort_direction,
        )


__all__ = [
    "GraphQLClient",
    "MagentoAuthError",
    "MagentoClient",
    "MagentoConfig",
    "MagentoError",
    "MagentoNotFoundError",
    "MagentoRateLimitError",
    "MagentoServerError",
    "MagentoValidationError",
    "RESTClient",
]
