"""Shared exception hierarchy for Magento API errors."""

from __future__ import annotations

from typing import Any

import httpx


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


_STATUS_TO_EXCEPTION: dict[int, type[MagentoError]] = {
    400: MagentoValidationError,
    401: MagentoAuthError,
    403: MagentoAuthError,
    404: MagentoNotFoundError,
    429: MagentoRateLimitError,
}


def _extract_error_message(response: httpx.Response) -> tuple[str, Any]:
    """Extract an error message and body from a Magento error response."""
    body: Any = None
    try:
        body = response.json()
        if isinstance(body, dict):
            msg = body.get("message", "")
            params = body.get("parameters")
            if params and isinstance(params, list):
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
