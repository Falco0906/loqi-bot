from __future__ import annotations

import base64
from abc import ABC, abstractmethod
from typing import Any


class AuthStrategy(ABC):
    """Abstract authentication strategy.

    Implementations produce headers to inject into an HTTP request.
    """

    @abstractmethod
    def apply(self, credentials: dict[str, str]) -> dict[str, str]:
        """Return headers to inject into the request.

        Args:
            credentials: A dict of credential field values from
                         a CredentialInstance or AdapterContext.

        Returns:
            Headers to merge into the HTTP request.
        """


class NoAuth(AuthStrategy):
    """No authentication. Returns empty headers."""

    def apply(self, credentials: dict[str, str] | None = None) -> dict[str, str]:
        return {}


class ApiKeyAuth(AuthStrategy):
    """API key authentication via a custom header.

    Credential fields used:
        - api_key:      The API key value (required).
        - header_name:  The header name (default: "X-API-Key").
    """

    def apply(self, credentials: dict[str, str]) -> dict[str, str]:
        api_key = credentials.get("api_key", "")
        header_name = credentials.get("header_name", "X-API-Key")
        return {header_name: api_key}


class BearerTokenAuth(AuthStrategy):
    """Bearer token authentication via Authorization header.

    Credential fields used:
        - token:         The bearer token value (required).
        - token_type:    Token type prefix (default: "Bearer").
    """

    def apply(self, credentials: dict[str, str]) -> dict[str, str]:
        token = credentials.get("token", credentials.get("access_token", ""))
        token_type = credentials.get("token_type", "Bearer")
        return {"Authorization": f"{token_type} {token}"}


class BasicAuth(AuthStrategy):
    """HTTP Basic authentication via Authorization header.

    Credential fields used:
        - username:  The username (required).
        - password:  The password (required).
    """

    def apply(self, credentials: dict[str, str]) -> dict[str, str]:
        username = credentials.get("username", "")
        password = credentials.get("password", "")
        raw = f"{username}:{password}"
        encoded = base64.b64encode(raw.encode()).decode()
        return {"Authorization": f"Basic {encoded}"}


class CustomHeaderAuth(AuthStrategy):
    """Custom header authentication.

    Credential fields used:
        - header_name:   The header name (required).
        - header_value:  The header value (required).
    """

    def apply(self, credentials: dict[str, str]) -> dict[str, str]:
        header_name = credentials.get("header_name", "")
        header_value = credentials.get("header_value", "")
        return {header_name: header_value}


_AUTH_STRATEGY_REGISTRY: dict[str, type[AuthStrategy]] = {
    "no_auth": NoAuth,
    "api_key": ApiKeyAuth,
    "bearer_token": BearerTokenAuth,
    "basic_auth": BasicAuth,
    "custom_header": CustomHeaderAuth,
}


def get_auth_strategy(auth_type: str) -> AuthStrategy:
    """Look up and instantiate an auth strategy by type name."""
    cls = _AUTH_STRATEGY_REGISTRY.get(auth_type)
    if cls is None:
        raise ValueError(
            f"Unknown auth type {auth_type!r}. "
            f"Available: {', '.join(sorted(_AUTH_STRATEGY_REGISTRY))}"
        )
    return cls()


def resolve_auth(
    credentials: dict[str, Any],
) -> tuple[AuthStrategy, dict[str, str]]:
    """Resolve an auth strategy and credential values from a credentials dict.

    The credentials dict should contain an ``auth_type`` key matching
    one of the registered strategy names.  The remaining keys are passed
    to the strategy's ``apply()`` method.

    Returns:
        A tuple of ``(strategy, credential_values)`` where
        ``credential_values`` is the credentials dict with ``auth_type``
        removed.
    """
    auth_type = credentials.get("auth_type", "no_auth") or "no_auth"
    strategy = get_auth_strategy(auth_type)
    creds = {k: v for k, v in credentials.items() if k != "auth_type"}
    return strategy, creds
