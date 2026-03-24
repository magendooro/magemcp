"""MageMCP OAuth/JWT token verification for HTTP transport.

Implements the MCP 2025-03-26 Authorization specification using JWT bearer tokens
validated against an external OAuth authorization server's JWKS endpoint.

Environment variables
---------------------
MAGEMCP_AUTH_ISSUER_URL          OAuth issuer (e.g. https://auth.example.com/realms/mcp)
MAGEMCP_AUTH_RESOURCE_SERVER_URL This server's URL (e.g. https://mcp.example.com)
MAGEMCP_AUTH_AUDIENCE            Expected JWT `aud` claim (defaults to resource server URL)
MAGEMCP_AUTH_REQUIRED_SCOPES     Comma-separated required scopes (e.g. magemcp:read,magemcp:admin)

When MAGEMCP_AUTH_ISSUER_URL and MAGEMCP_AUTH_RESOURCE_SERVER_URL are both set the MCP server
requires a valid JWT bearer token on all HTTP transport requests. Stdio transport is unaffected.

If either variable is absent auth is disabled (all requests are unauthenticated) — appropriate
for stdio-only deployments and trusted internal networks.
"""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)


def _issuer_url() -> str:
    return os.getenv("MAGEMCP_AUTH_ISSUER_URL", "").rstrip("/")


def _resource_server_url() -> str:
    return os.getenv("MAGEMCP_AUTH_RESOURCE_SERVER_URL", "").rstrip("/")


def _audience() -> str | None:
    explicit = os.getenv("MAGEMCP_AUTH_AUDIENCE", "")
    return explicit or (_resource_server_url() or None)


def _required_scopes() -> list[str]:
    raw = os.getenv("MAGEMCP_AUTH_REQUIRED_SCOPES", "")
    return [s.strip() for s in raw.split(",") if s.strip()]


def build_auth_settings() -> Any | None:
    """Return an AuthSettings instance if auth env vars are configured, else None.

    Returns None when MAGEMCP_AUTH_ISSUER_URL or MAGEMCP_AUTH_RESOURCE_SERVER_URL
    is absent — which disables auth entirely (suitable for stdio and trusted deployments).
    """
    issuer = _issuer_url()
    resource = _resource_server_url()
    if not issuer or not resource:
        return None

    from mcp.server.auth.settings import AuthSettings

    scopes = _required_scopes() or None
    log.info("MCP OAuth enabled: issuer=%s resource=%s required_scopes=%s", issuer, resource, scopes)
    return AuthSettings(
        issuer_url=issuer,  # type: ignore[arg-type]
        resource_server_url=resource,  # type: ignore[arg-type]
        required_scopes=scopes,
    )


class JWTTokenVerifier:
    """Validates JWT bearer tokens using the OAuth server's JWKS endpoint.

    The JWKS URL is derived as ``{issuer_url}/.well-known/jwks.json`` (standard OIDC).
    Keys are cached for 5 minutes (PyJWT default) to avoid hitting the JWKS endpoint on
    every request.
    """

    def __init__(
        self,
        issuer_url: str,
        audience: str | None = None,
        leeway: int = 10,
    ) -> None:
        self._issuer = issuer_url.rstrip("/")
        self._audience = audience
        self._leeway = leeway
        self._jwks_client: Any | None = None  # lazy init

    def _get_jwks_client(self) -> Any:
        if self._jwks_client is None:
            from jwt import PyJWKClient

            jwks_uri = f"{self._issuer}/.well-known/jwks.json"
            log.debug("Initialising JWKS client: %s", jwks_uri)
            self._jwks_client = PyJWKClient(jwks_uri, cache_jwk_set=True, lifespan=300)
        return self._jwks_client

    async def verify_token(self, token: str) -> Any | None:
        """Verify a JWT bearer token.

        Returns an ``AccessToken`` on success, ``None`` if the token is invalid.
        Never raises — all exceptions are caught and logged at DEBUG level.
        """
        try:
            import jwt as pyjwt
            from mcp.server.auth.provider import AccessToken

            client = self._get_jwks_client()
            signing_key = client.get_signing_key_from_jwt(token)

            options: dict[str, Any] = {
                "verify_exp": True,
                "verify_nbf": True,
                "verify_iss": True,
                "verify_aud": self._audience is not None,
            }
            decode_kwargs: dict[str, Any] = {
                "algorithms": ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"],
                "issuer": self._issuer,
                "leeway": self._leeway,
                "options": options,
            }
            if self._audience:
                decode_kwargs["audience"] = self._audience

            payload = pyjwt.decode(token, signing_key.key, **decode_kwargs)

            # Extract scopes — OAuth servers encode them as space-separated string or list
            scope_claim = payload.get("scope", payload.get("scp", ""))
            if isinstance(scope_claim, list):
                scopes = scope_claim
            else:
                scopes = scope_claim.split() if scope_claim else []

            client_id: str = payload.get("client_id", payload.get("azp", payload.get("sub", "")))

            return AccessToken(
                token=token,
                client_id=client_id,
                scopes=scopes,
                expires_at=payload.get("exp"),
            )

        except Exception as exc:
            log.debug("JWT verification failed: %s", exc)
            return None


def build_token_verifier() -> JWTTokenVerifier | None:
    """Return a JWTTokenVerifier if auth is configured, else None."""
    issuer = _issuer_url()
    if not issuer:
        return None
    audience = _audience()
    return JWTTokenVerifier(issuer_url=issuer, audience=audience)
