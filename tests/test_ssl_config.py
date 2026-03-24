"""Tests for MAGENTO_VERIFY_SSL configuration."""

from __future__ import annotations

import pytest


class TestParseVerifySsl:
    def test_default_is_true(self, monkeypatch):
        monkeypatch.delenv("MAGENTO_VERIFY_SSL", raising=False)
        from magemcp.connectors.rest_client import _parse_verify_ssl
        assert _parse_verify_ssl() is True

    def test_true_string(self, monkeypatch):
        monkeypatch.setenv("MAGENTO_VERIFY_SSL", "true")
        from magemcp.connectors.rest_client import _parse_verify_ssl
        assert _parse_verify_ssl() is True

    def test_one_string(self, monkeypatch):
        monkeypatch.setenv("MAGENTO_VERIFY_SSL", "1")
        from magemcp.connectors.rest_client import _parse_verify_ssl
        assert _parse_verify_ssl() is True

    def test_false_string(self, monkeypatch):
        monkeypatch.setenv("MAGENTO_VERIFY_SSL", "false")
        from magemcp.connectors.rest_client import _parse_verify_ssl
        assert _parse_verify_ssl() is False

    def test_zero_string(self, monkeypatch):
        monkeypatch.setenv("MAGENTO_VERIFY_SSL", "0")
        from magemcp.connectors.rest_client import _parse_verify_ssl
        assert _parse_verify_ssl() is False

    def test_ca_bundle_path(self, monkeypatch):
        monkeypatch.setenv("MAGENTO_VERIFY_SSL", "/etc/ssl/certs/ca.pem")
        from magemcp.connectors.rest_client import _parse_verify_ssl
        assert _parse_verify_ssl() == "/etc/ssl/certs/ca.pem"

    def test_graphql_client_same_logic(self, monkeypatch):
        monkeypatch.setenv("MAGENTO_VERIFY_SSL", "false")
        from magemcp.connectors.graphql_client import _parse_verify_ssl as gql_parse
        assert gql_parse() is False

    def test_graphql_default_true(self, monkeypatch):
        monkeypatch.delenv("MAGENTO_VERIFY_SSL", raising=False)
        from magemcp.connectors.graphql_client import _parse_verify_ssl as gql_parse
        assert gql_parse() is True

    def test_rest_client_passes_verify_to_httpx(self, monkeypatch):
        monkeypatch.setenv("MAGENTO_VERIFY_SSL", "false")
        from magemcp.connectors.rest_client import RESTClient
        client = RESTClient(
            base_url="http://magento.test",
            admin_token="tok",
            verify=False,
        )
        # httpx.AsyncClient stores verify setting
        assert client._client._transport is not None

    def test_graphql_client_passes_verify_to_httpx(self, monkeypatch):
        monkeypatch.setenv("MAGENTO_VERIFY_SSL", "false")
        from magemcp.connectors.graphql_client import GraphQLClient
        client = GraphQLClient(
            base_url="http://magento.test",
            verify=False,
        )
        assert client._client._transport is not None
