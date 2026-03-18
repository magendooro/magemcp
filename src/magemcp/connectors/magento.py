"""Magento 2 REST and GraphQL connector layer.

Async HTTP client for communicating with Magento 2 / Adobe Commerce APIs.
All Magento access in MageMCP goes through this module.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from pydantic_settings import BaseSettings

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class MagentoError(Exception):
    """Base exception for Magento API errors."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_body: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class MagentoAuthError(MagentoError):
    """401 Unauthorized — invalid or expired token."""


class MagentoNotFoundError(MagentoError):
    """404 Not Found — resource does not exist."""


class MagentoValidationError(MagentoError):
    """400 Bad Request — invalid input or search parameters."""


class MagentoRateLimitError(MagentoError):
    """429 Too Many Requests."""


class MagentoServerError(MagentoError):
    """5xx — Magento server-side failure."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_STATUS_TO_EXCEPTION: dict[int, type[MagentoError]] = {
    400: MagentoValidationError,
    401: MagentoAuthError,
    403: MagentoAuthError,
    404: MagentoNotFoundError,
    429: MagentoRateLimitError,
}


class MagentoConfig(BaseSettings):
    """Magento connection settings loaded from environment variables."""

    magento_base_url: str
    magento_token: str
    magento_store_code: str = "default"

    model_config = {"env_prefix": ""}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def _extract_error_message(response: httpx.Response) -> tuple[str, Any]:
    """Extract an error message and body from a Magento error response."""
    body: Any = None
    try:
        body = response.json()
        if isinstance(body, dict):
            # Magento REST errors use {"message": "...", "parameters": [...]}
            msg = body.get("message", "")
            params = body.get("parameters")
            if params and isinstance(params, list):
                # Magento uses %1, %2, … placeholders
                for i, param in enumerate(params, start=1):
                    msg = msg.replace(f"%{i}", str(param))
            return msg or "Unknown error", body
        return str(body), body
    except Exception:
        return response.text or "Unknown error", None


def _raise_for_status(response: httpx.Response) -> None:
    """Map Magento HTTP status codes to typed exceptions."""
    if response.is_success:
        return

    status = response.status_code
    message, body = _extract_error_message(response)

    exc_class = _STATUS_TO_EXCEPTION.get(status)
    if exc_class is None:
        exc_class = MagentoServerError if status >= 500 else MagentoError

    raise exc_class(message, status_code=status, response_body=body)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class MagentoClient:
    """Async HTTP client for Magento 2 REST and GraphQL APIs.

    Usage::

        async with MagentoClient(base_url="https://magento.test", token="abc") as m:
            order = await m.get("/V1/orders/42")
            products = await m.graphql("{ products(search: \\"shirt\\") { items { sku } } }")
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

    # -- context manager -----------------------------------------------------

    async def __aenter__(self) -> MagentoClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the underlying HTTP client (only if we created it)."""
        if self._owns_client:
            await self._client.aclose()

    # -- REST helpers --------------------------------------------------------

    def _rest_url(self, endpoint: str, *, store_code: str | None = None) -> str:
        """Build a scoped REST URL: ``/rest/{store}/V1/…``."""
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

    # -- GraphQL -------------------------------------------------------------

    async def graphql(
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

            params = MagentoClient.search_params(
                filters={
                    "status": "processing",
                    "created_at": ("2024-01-01", "gteq"),
                },
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
