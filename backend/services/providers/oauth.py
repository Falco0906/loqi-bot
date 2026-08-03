from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol


@dataclass
class OAuthToken:
    access_token: str
    refresh_token: str | None = None
    expires_at: float | None = None
    scope: str = ""
    token_type: str = "Bearer"
    provider_id: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() >= self.expires_at - 60

    @property
    def is_expiring_soon(self, buffer_seconds: int = 300) -> bool:
        if self.expires_at is None:
            return False
        return time.time() >= self.expires_at - buffer_seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "scope": self.scope,
            "token_type": self.token_type,
            "provider_id": self.provider_id,
        }


class OAuthTokenStore(ABC):
    """Persistent storage for OAuth tokens.

    Implementations may back onto Supabase, in-memory dict, or filesystem.
    Tokens must never leak into business logic — only this store handles them.
    """

    @abstractmethod
    async def get(self, provider_id: str, user_id: str = "") -> OAuthToken | None:
        ...

    @abstractmethod
    async def store(self, provider_id: str, token: OAuthToken, user_id: str = "") -> None:
        ...

    @abstractmethod
    async def delete(self, provider_id: str, user_id: str = "") -> None:
        ...

    @abstractmethod
    async def list_for_provider(self, provider_id: str) -> list[OAuthToken]:
        ...


class InMemoryTokenStore(OAuthTokenStore):
    """In-memory token store for development/testing.

    Tokens are lost on process restart.
    Not suitable for production.
    """

    def __init__(self) -> None:
        self._tokens: dict[str, OAuthToken] = {}

    def _key(self, provider_id: str, user_id: str) -> str:
        return f"{provider_id}::{user_id}" if user_id else provider_id

    async def get(self, provider_id: str, user_id: str = "") -> OAuthToken | None:
        return self._tokens.get(self._key(provider_id, user_id))

    async def store(self, provider_id: str, token: OAuthToken, user_id: str = "") -> None:
        self._tokens[self._key(provider_id, user_id)] = token

    async def delete(self, provider_id: str, user_id: str = "") -> None:
        self._tokens.pop(self._key(provider_id, user_id), None)

    async def list_for_provider(self, provider_id: str) -> list[OAuthToken]:
        prefix = f"{provider_id}::"
        return [v for k, v in self._tokens.items() if k == provider_id or k.startswith(prefix)]


class OAuthFlow(ABC):
    """OAuth2 authorization code flow.

    Each provider (Google, Microsoft, etc.) implements its own flow.
    The rest of the application never touches authorization URLs or codes directly.
    """

    @property
    @abstractmethod
    def provider_id(self) -> str:
        ...

    @abstractmethod
    def authorization_url(self, state: str, redirect_uri: str = "") -> str:
        ...

    @abstractmethod
    async def exchange_code(self, code: str, redirect_uri: str = "") -> OAuthToken:
        ...

    @abstractmethod
    async def refresh_token(self, token: OAuthToken) -> OAuthToken:
        ...

    @abstractmethod
    async def revoke_token(self, token: OAuthToken) -> None:
        ...


class TokenRefreshError(Exception):
    """Raised when token refresh fails (e.g., refresh token expired)."""
    pass


class TokenManager:
    """Handles automatic token refresh and lifecycle.

    Wraps an OAuthFlow and OAuthTokenStore.
    Callers request tokens by provider_id — TokenManager handles refresh transparently.
    """

    def __init__(
        self,
        flow: OAuthFlow,
        store: OAuthTokenStore,
    ) -> None:
        self._flow = flow
        self._store = store

    async def get_valid_token(self, provider_id: str, user_id: str = "") -> OAuthToken:
        token = await self._store.get(provider_id, user_id)
        if token is None:
            raise TokenRefreshError(f"No token found for provider '{provider_id}'")

        if token.is_expired or token.is_expiring_soon:
            if token.refresh_token:
                try:
                    token = await self._flow.refresh_token(token)
                    await self._store.store(provider_id, token, user_id)
                except Exception as e:
                    raise TokenRefreshError(
                        f"Failed to refresh token for '{provider_id}': {e}"
                    ) from e
            else:
                raise TokenRefreshError(
                    f"Token for '{provider_id}' expired and no refresh_token available"
                )

        return token

    async def store_token(self, provider_id: str, token: OAuthToken, user_id: str = "") -> None:
        await self._store.store(provider_id, token, user_id)

    async def delete_token(self, provider_id: str, user_id: str = "") -> None:
        await self._store.delete(provider_id, user_id)

    @property
    def flow(self) -> OAuthFlow:
        return self._flow
