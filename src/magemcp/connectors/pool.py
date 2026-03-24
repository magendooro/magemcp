"""Shared connector singletons for connection pooling.

The module-level REST and GraphQL client instances are initialised once
(typically by the FastMCP lifespan) and reused across all tool calls.

Lifecycle:
  - ``init()`` — create and store both singletons
  - ``close()`` — close both singletons and clear references
  - ``get_rest()`` / ``get_graphql()`` — return the current singleton (or None)

When a singleton is available, ``RESTClient.from_env()`` and
``GraphQLClient.from_env()`` return a *borrowed* wrapper whose
``__aexit__`` is a no-op — the underlying ``httpx.AsyncClient`` is not
closed per-call, preserving the connection pool.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from magemcp.connectors.rest_client import RESTClient
    from magemcp.connectors.graphql_client import GraphQLClient

log = logging.getLogger(__name__)

_rest: RESTClient | None = None
_graphql: GraphQLClient | None = None


def get_rest() -> RESTClient | None:
    """Return the shared REST client, or *None* if not initialised."""
    return _rest


def get_graphql() -> GraphQLClient | None:
    """Return the shared GraphQL client, or *None* if not initialised."""
    return _graphql


async def init() -> None:
    """Create and store both singletons from environment variables."""
    global _rest, _graphql

    from magemcp.connectors.rest_client import RESTClient
    from magemcp.connectors.graphql_client import GraphQLClient

    _rest = RESTClient.from_env()
    _graphql = GraphQLClient.from_env()
    log.info("Connection pool initialised (REST + GraphQL).")


async def close() -> None:
    """Close both singletons and clear references."""
    global _rest, _graphql

    if _rest is not None:
        await _rest.close()
        _rest = None
    if _graphql is not None:
        await _graphql.close()
        _graphql = None
    log.info("Connection pool closed.")
