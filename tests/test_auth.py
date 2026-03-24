"""Tests for the MageMCP OAuth/JWT auth module."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from magemcp.auth import (
    JWTTokenVerifier,
    build_auth_settings,
    build_token_verifier,
)


class TestBuildAuthSettings:
    def test_returns_none_when_no_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MAGEMCP_AUTH_ISSUER_URL", raising=False)
        monkeypatch.delenv("MAGEMCP_AUTH_RESOURCE_SERVER_URL", raising=False)
        assert build_auth_settings() is None

    def test_returns_none_when_only_issuer_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGEMCP_AUTH_ISSUER_URL", "https://auth.example.com")
        monkeypatch.delenv("MAGEMCP_AUTH_RESOURCE_SERVER_URL", raising=False)
        assert build_auth_settings() is None

    def test_returns_none_when_only_resource_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MAGEMCP_AUTH_ISSUER_URL", raising=False)
        monkeypatch.setenv("MAGEMCP_AUTH_RESOURCE_SERVER_URL", "https://mcp.example.com")
        assert build_auth_settings() is None

    def test_returns_auth_settings_when_both_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGEMCP_AUTH_ISSUER_URL", "https://auth.example.com")
        monkeypatch.setenv("MAGEMCP_AUTH_RESOURCE_SERVER_URL", "https://mcp.example.com")
        settings = build_auth_settings()
        assert settings is not None
        assert str(settings.issuer_url).rstrip("/") == "https://auth.example.com"
        assert str(settings.resource_server_url).rstrip("/") == "https://mcp.example.com"

    def test_required_scopes_parsed_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGEMCP_AUTH_ISSUER_URL", "https://auth.example.com")
        monkeypatch.setenv("MAGEMCP_AUTH_RESOURCE_SERVER_URL", "https://mcp.example.com")
        monkeypatch.setenv("MAGEMCP_AUTH_REQUIRED_SCOPES", "magemcp:read,magemcp:admin")
        settings = build_auth_settings()
        assert settings is not None
        assert settings.required_scopes == ["magemcp:read", "magemcp:admin"]

    def test_trailing_slash_stripped_from_urls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGEMCP_AUTH_ISSUER_URL", "https://auth.example.com/")
        monkeypatch.setenv("MAGEMCP_AUTH_RESOURCE_SERVER_URL", "https://mcp.example.com/")
        settings = build_auth_settings()
        assert settings is not None
        assert str(settings.issuer_url).rstrip("/") == "https://auth.example.com"


class TestBuildTokenVerifier:
    def test_returns_none_when_no_issuer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MAGEMCP_AUTH_ISSUER_URL", raising=False)
        assert build_token_verifier() is None

    def test_returns_verifier_when_issuer_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGEMCP_AUTH_ISSUER_URL", "https://auth.example.com")
        monkeypatch.setenv("MAGEMCP_AUTH_RESOURCE_SERVER_URL", "https://mcp.example.com")
        verifier = build_token_verifier()
        assert verifier is not None
        assert isinstance(verifier, JWTTokenVerifier)

    def test_audience_defaults_to_resource_server_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGEMCP_AUTH_ISSUER_URL", "https://auth.example.com")
        monkeypatch.setenv("MAGEMCP_AUTH_RESOURCE_SERVER_URL", "https://mcp.example.com")
        monkeypatch.delenv("MAGEMCP_AUTH_AUDIENCE", raising=False)
        verifier = build_token_verifier()
        assert verifier is not None
        assert verifier._audience == "https://mcp.example.com"

    def test_explicit_audience_overrides_resource_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGEMCP_AUTH_ISSUER_URL", "https://auth.example.com")
        monkeypatch.setenv("MAGEMCP_AUTH_RESOURCE_SERVER_URL", "https://mcp.example.com")
        monkeypatch.setenv("MAGEMCP_AUTH_AUDIENCE", "my-api-resource")
        verifier = build_token_verifier()
        assert verifier is not None
        assert verifier._audience == "my-api-resource"


class TestJWTTokenVerifier:
    def _make_payload(
        self,
        *,
        issuer: str = "https://auth.example.com",
        audience: str = "https://mcp.example.com",
        client_id: str = "test-client",
        scopes: str = "magemcp:read",
        exp_offset: int = 3600,
    ) -> dict:
        now = int(time.time())
        return {
            "iss": issuer,
            "aud": audience,
            "sub": "user-123",
            "client_id": client_id,
            "scope": scopes,
            "iat": now,
            "nbf": now,
            "exp": now + exp_offset,
        }

    @pytest.mark.asyncio
    async def test_valid_token_returns_access_token(self) -> None:
        """A valid JWT is decoded and wrapped in AccessToken."""
        import jwt as pyjwt

        verifier = JWTTokenVerifier(
            issuer_url="https://auth.example.com",
            audience="https://mcp.example.com",
        )

        payload = self._make_payload()
        # Mock the JWKS client to return the signing key
        mock_signing_key = MagicMock()
        mock_signing_key.key = "secret"  # symmetric key for testing

        mock_jwks_client = MagicMock()
        mock_jwks_client.get_signing_key_from_jwt.return_value = mock_signing_key

        token = pyjwt.encode(payload, "secret", algorithm="HS256")

        with patch.object(verifier, "_get_jwks_client", return_value=mock_jwks_client):
            # Use HS256 for the test — override algorithms
            with patch("jwt.decode", return_value=payload) as mock_decode:
                result = await verifier.verify_token(token)

        assert result is not None
        assert result.client_id == "test-client"
        assert "magemcp:read" in result.scopes

    @pytest.mark.asyncio
    async def test_invalid_token_returns_none(self) -> None:
        """An invalid token returns None without raising."""
        verifier = JWTTokenVerifier(
            issuer_url="https://auth.example.com",
            audience="https://mcp.example.com",
        )
        mock_jwks_client = MagicMock()
        mock_jwks_client.get_signing_key_from_jwt.side_effect = Exception("Invalid token")
        with patch.object(verifier, "_get_jwks_client", return_value=mock_jwks_client):
            result = await verifier.verify_token("bad.token.here")
        assert result is None

    @pytest.mark.asyncio
    async def test_scope_as_list_is_supported(self) -> None:
        """JWTs that encode scope as a list (not a space-separated string) are handled."""
        payload = self._make_payload()
        payload["scope"] = ["magemcp:read", "magemcp:admin"]

        verifier = JWTTokenVerifier(
            issuer_url="https://auth.example.com",
            audience="https://mcp.example.com",
        )
        mock_signing_key = MagicMock()
        mock_signing_key.key = "secret"
        mock_jwks_client = MagicMock()
        mock_jwks_client.get_signing_key_from_jwt.return_value = mock_signing_key

        with patch.object(verifier, "_get_jwks_client", return_value=mock_jwks_client):
            with patch("jwt.decode", return_value=payload):
                result = await verifier.verify_token("token")

        assert result is not None
        assert result.scopes == ["magemcp:read", "magemcp:admin"]

    @pytest.mark.asyncio
    async def test_azp_fallback_for_client_id(self) -> None:
        """The `azp` claim is used as client_id when `client_id` is absent."""
        payload = self._make_payload()
        del payload["client_id"]
        payload["azp"] = "azp-client"

        verifier = JWTTokenVerifier(
            issuer_url="https://auth.example.com",
            audience="https://mcp.example.com",
        )
        mock_signing_key = MagicMock()
        mock_signing_key.key = "secret"
        mock_jwks_client = MagicMock()
        mock_jwks_client.get_signing_key_from_jwt.return_value = mock_signing_key

        with patch.object(verifier, "_get_jwks_client", return_value=mock_jwks_client):
            with patch("jwt.decode", return_value=payload):
                result = await verifier.verify_token("token")

        assert result is not None
        assert result.client_id == "azp-client"

    def test_jwks_client_lazy_init(self) -> None:
        """The JWKS client is created on first use, not at construction time."""
        verifier = JWTTokenVerifier(issuer_url="https://auth.example.com")
        assert verifier._jwks_client is None
        with patch("jwt.PyJWKClient") as mock_cls:
            verifier._get_jwks_client()
        mock_cls.assert_called_once_with(
            "https://auth.example.com/.well-known/jwks.json",
            cache_jwk_set=True,
            lifespan=300,
        )
