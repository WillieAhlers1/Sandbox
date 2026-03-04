"""Unit tests for secrets/client.py — LocalSecretClient and resolve_dict."""

import pytest

from gcp_ml_framework.secrets.client import LocalSecretClient, make_secret_client


@pytest.fixture
def local_client(test_context):
    return LocalSecretClient(test_context)


class TestLocalSecretClient:
    def test_get_from_env(self, local_client, monkeypatch):
        monkeypatch.setenv("GML_SECRET_DB_PASSWORD", "mysecret")
        assert local_client.get("db-password") == "mysecret"

    def test_get_missing_warns(self, local_client):
        with pytest.warns(UserWarning, match="not found"):
            val = local_client.get("nonexistent-key")
        assert val == ""

    def test_get_or_default(self, local_client):
        result = local_client.get_or_default("missing-key", default="fallback")
        assert result == "fallback"

    def test_resolve_dict_plain(self, local_client):
        data = {"region": "us-central1", "count": 3}
        result = local_client.resolve_dict(data)
        assert result == data

    def test_resolve_dict_secret_ref(self, local_client, monkeypatch):
        monkeypatch.setenv("GML_SECRET_API_KEY", "abc123")
        data = {"api_key": "!secret api-key", "region": "us-central1"}
        result = local_client.resolve_dict(data)
        assert result["api_key"] == "abc123"
        assert result["region"] == "us-central1"

    def test_resolve_dict_nested(self, local_client, monkeypatch):
        monkeypatch.setenv("GML_SECRET_DB_PASS", "secret!")
        data = {"db": {"password": "!secret db-pass", "host": "localhost"}}
        result = local_client.resolve_dict(data)
        assert result["db"]["password"] == "secret!"
        assert result["db"]["host"] == "localhost"

    def test_make_secret_client_local(self, test_context):
        client = make_secret_client(test_context, local=True)
        assert isinstance(client, LocalSecretClient)
