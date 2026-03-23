"""Magento connector layer — async HTTP clients for REST and GraphQL."""

from magemcp.connectors.errors import (
    MagentoAuthError,
    MagentoError,
    MagentoNotFoundError,
    MagentoRateLimitError,
    MagentoServerError,
    MagentoValidationError,
)
from magemcp.connectors.graphql_client import GraphQLClient
from magemcp.connectors.magento import MagentoClient, MagentoConfig
from magemcp.connectors.rest_client import RESTClient

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
