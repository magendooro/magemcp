"""Async GraphQL client for Magento storefront operations.

No authentication required for public catalog queries. Optional customer token
for authenticated customer-scoped operations (cart, account).
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from magemcp.audit_context import current_entry as _current_audit_entry
from magemcp.audit_context import truncate_for_audit
from magemcp.connectors.errors import MagentoError, _raise_for_status

log = logging.getLogger(__name__)


def _is_mutation(query: str) -> bool:
    """Return True if this is a GraphQL mutation (not a read query)."""
    stripped = query.strip()
    return stripped.startswith("mutation") or "mutation " in stripped


def _record_graphql_mutation(
    query: str,
    variables: dict[str, Any] | None,
    response: "httpx.Response",
) -> None:
    """Append a GraphQL mutation call to the active audit entry (if any)."""
    entry = _current_audit_entry.get()
    if entry is None:
        return
    try:
        resp_body = response.json()
    except Exception:
        resp_body = None
    # Trim the query for readability — first line is usually the operation name
    query_summary = query.strip()[:300] + ("…" if len(query.strip()) > 300 else "")
    entry["http_calls"].append({
        "method": "POST",
        "url": "/graphql",
        "query": query_summary,
        "variables": truncate_for_audit(variables),
        "status": response.status_code,
        "response": truncate_for_audit(resp_body),
    })


def _parse_verify_ssl() -> bool | str:
    """Parse MAGENTO_VERIFY_SSL env var — same semantics as rest_client."""
    raw = os.environ.get("MAGENTO_VERIFY_SSL", "true").strip().lower()
    if raw in ("false", "0"):
        return False
    if raw in ("true", "1"):
        return True
    return raw


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
        verify: bool | str = True,
        _owned: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.store_code = store_code
        self.customer_token = customer_token
        self._owned = _owned  # False for borrowed pool references

        if verify is False:
            log.warning("SSL verification disabled for GraphQL client (MAGENTO_VERIFY_SSL=false)")

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
            verify=verify,
        )

    @classmethod
    def from_env(cls, **kwargs: Any) -> GraphQLClient:
        """Create from environment variables.

        Required: ``MAGENTO_BASE_URL``
        Optional: ``MAGENTO_CUSTOMER_TOKEN``, ``MAGENTO_STORE_CODE``

        When a shared pool client is available (initialised via
        ``magemcp.connectors.pool.init()``), returns a *borrowed* reference to
        it instead of creating a new client.  The borrowed reference's
        ``close()`` method is a no-op so the pool is not torn down per call.

        Note: the pooled client does not carry a customer token (it is the
        anonymous/guest client).  Pass ``customer_token=`` explicitly to bypass
        the pool for authenticated customer operations.
        """
        from magemcp.connectors.pool import get_graphql

        if not kwargs.get("customer_token"):
            pooled = get_graphql()
            if pooled is not None:
                borrowed = cls.__new__(cls)
                borrowed.base_url = pooled.base_url
                borrowed.store_code = pooled.store_code
                borrowed.customer_token = None
                borrowed._client = pooled._client
                borrowed._owned = False
                return borrowed

        base_url = os.environ.get("MAGENTO_BASE_URL", "")
        if not base_url:
            msg = "MAGENTO_BASE_URL environment variable is required"
            raise ValueError(msg)

        # Extract customer_token from kwargs (if provided explicitly) to avoid
        # passing it twice when building the instance.
        customer_token = kwargs.pop("customer_token", None) or os.environ.get("MAGENTO_CUSTOMER_TOKEN") or None

        verify = _parse_verify_ssl()
        return cls(
            base_url=base_url,
            store_code=os.environ.get("MAGENTO_STORE_CODE", "default"),
            customer_token=customer_token,
            verify=verify,
            **kwargs,
        )

    # -- context manager -----------------------------------------------------

    async def __aenter__(self) -> GraphQLClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the underlying HTTP client (no-op for borrowed pool references)."""
        if self._owned:
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

        if _is_mutation(query):
            _record_graphql_mutation(query, variables, response)

        result = response.json()

        if "errors" in result:
            errors = result["errors"]
            msg = errors[0].get("message", "GraphQL error") if errors else "GraphQL error"
            raise MagentoError(msg, response_body=result)

        return result.get("data", result)
