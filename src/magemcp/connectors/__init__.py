"""Magento connector layer — async HTTP clients for REST and GraphQL."""

from magemcp.connectors.magento import (
    MagentoAuthError,
    MagentoClient,
    MagentoConfig,
    MagentoError,
    MagentoNotFoundError,
    MagentoRateLimitError,
    MagentoServerError,
    MagentoValidationError,
)

__all__ = [
    "MagentoAuthError",
    "MagentoClient",
    "MagentoConfig",
    "MagentoError",
    "MagentoNotFoundError",
    "MagentoRateLimitError",
    "MagentoServerError",
    "MagentoValidationError",
]
