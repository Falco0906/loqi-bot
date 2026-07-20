from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ProviderType(str, Enum):
    EMAIL = "email"
    GOOGLE = "google"
    MICROSOFT = "microsoft"
    GITHUB = "github"
    PASSKEYS = "passkeys"
    SAML = "saml"
    OIDC = "oidc"
    OKTA = "okta"
    AZURE_AD = "azure_ad"


@dataclass
class IdentityContext:
    user_id: str = ""
    org_id: str = ""
    session_id: str = ""
    roles: list[str] = field(default_factory=list)
    issued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > self.expires_at

    @property
    def is_authenticated(self) -> bool:
        return bool(self.user_id) and not self.is_expired


@dataclass
class ExternalIdentity:
    provider: ProviderType = ProviderType.EMAIL
    provider_user_id: str = ""
    email: str = ""
    name: str = ""
    avatar_url: str = ""
    raw_attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class AuthRequest:
    authorize_url: str = ""
    state: str = ""
    code_verifier: str = ""
    expires_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class IdentityProvider(ABC):
    @property
    @abstractmethod
    def provider_type(self) -> ProviderType:
        ...

    @abstractmethod
    async def initiate_auth(self, redirect_uri: str) -> AuthRequest:
        ...

    @abstractmethod
    async def handle_callback(self, code: str, state: str, code_verifier: str) -> ExternalIdentity:
        ...

    @abstractmethod
    async def link(self, user_id: str, external_identity: ExternalIdentity) -> bool:
        ...

    @abstractmethod
    async def unlink(self, user_id: str, provider_type: ProviderType) -> bool:
        ...
