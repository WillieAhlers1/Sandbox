"""
GCP Secret Manager client.

Secrets are referenced by short key names in config/YAML as:
    !secret my-api-key

At runtime, `SecretManagerClient.resolve()` maps:
    my-api-key  →  {secret_prefix}-my-api-key  →  fetches latest version from Secret Manager

Secret names follow the convention:
    {namespace}-{key}   e.g. dsci-churn-pred-main-db-password

This keeps secrets branch-namespaced so DEV/STAGE/PROD each maintain
independent secret values under the same logical key name.
"""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gcp_ml_framework.context import MLContext


class SecretManagerClient:
    """
    Thin wrapper around the GCP Secret Manager SDK.

    Handles:
    - Key → namespaced secret name derivation
    - Version fetching (always latest)
    - In-process cache (secrets don't change mid-run)

    Usage:
        client = SecretManagerClient(context)
        value = client.get("db-password")
        # fetches secret "dsci-churn-pred-main-db-password" from Secret Manager
    """

    def __init__(self, context: "MLContext") -> None:
        self._context = context
        self._project = context.secret_project_id
        self._prefix = context.secret_prefix
        self._cache: dict[str, str] = {}

    def _secret_resource_name(self, key: str) -> str:
        """Build the full Secret Manager resource path for a short key."""
        secret_id = f"{self._prefix}-{key}"
        return f"projects/{self._project}/secrets/{secret_id}/versions/latest"

    def get(self, key: str) -> str:
        """
        Retrieve the latest version of a secret by short key name.

        Results are cached in memory for the lifetime of this client instance.
        Raises RuntimeError if the secret does not exist or cannot be accessed.
        """
        if key in self._cache:
            return self._cache[key]

        try:
            from google.cloud import secretmanager  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "google-cloud-secret-manager is required. "
                "Install it with: pip install google-cloud-secret-manager"
            ) from exc

        client = secretmanager.SecretManagerServiceClient()
        resource = self._secret_resource_name(key)

        try:
            response = client.access_secret_version(request={"name": resource})
            value = response.payload.data.decode("utf-8")
        except Exception as exc:
            raise RuntimeError(
                f"Failed to retrieve secret '{key}' "
                f"(resource: {resource}): {exc}"
            ) from exc

        self._cache[key] = value
        return value

    def get_or_default(self, key: str, default: str = "") -> str:
        """Like get(), but returns `default` instead of raising on missing secret."""
        try:
            return self.get(key)
        except RuntimeError:
            return default

    def resolve_dict(self, data: dict) -> dict:
        """
        Recursively walk a dict and resolve any string value prefixed with '!secret '.

        Usage:
            raw = {"db_url": "!secret db-url", "region": "us-central1"}
            resolved = client.resolve_dict(raw)
            # {"db_url": "<actual-secret-value>", "region": "us-central1"}
        """
        result = {}
        for k, v in data.items():
            if isinstance(v, str) and v.startswith("!secret "):
                secret_key = v[len("!secret "):].strip()
                result[k] = self.get(secret_key)
            elif isinstance(v, dict):
                result[k] = self.resolve_dict(v)
            else:
                result[k] = v
        return result

    def clear_cache(self) -> None:
        self._cache.clear()


class LocalSecretClient:
    """
    Drop-in replacement for SecretManagerClient used in local development.

    Reads secrets from environment variables instead of Secret Manager:
        GML_SECRET_{KEY_UPPER}=value

    Falls back to an empty string with a warning if not set.
    """

    def __init__(self, context: "MLContext") -> None:
        self._context = context

    def get(self, key: str) -> str:
        import os

        env_var = f"GML_SECRET_{key.upper().replace('-', '_')}"
        value = os.environ.get(env_var)
        if value is None:
            import warnings

            warnings.warn(
                f"Local secret '{key}' not found in env var {env_var}. "
                "Set it or use a real SecretManagerClient.",
                stacklevel=2,
            )
            return ""
        return value

    def get_or_default(self, key: str, default: str = "") -> str:
        import os

        env_var = f"GML_SECRET_{key.upper().replace('-', '_')}"
        return os.environ.get(env_var, default)

    def resolve_dict(self, data: dict) -> dict:
        result = {}
        for k, v in data.items():
            if isinstance(v, str) and v.startswith("!secret "):
                secret_key = v[len("!secret "):].strip()
                result[k] = self.get(secret_key)
            elif isinstance(v, dict):
                result[k] = self.resolve_dict(v)
            else:
                result[k] = v
        return result

    def clear_cache(self) -> None:
        pass


def make_secret_client(context: "MLContext", local: bool = False):
    """Factory: returns LocalSecretClient in local mode, SecretManagerClient otherwise."""
    if local:
        return LocalSecretClient(context)
    return SecretManagerClient(context)
