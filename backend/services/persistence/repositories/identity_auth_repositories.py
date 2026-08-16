from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from services.identity.models import (
    EmailIdentity,
    PasswordCredential,
    RegistrationSession,
    RegistrationSessionStatus,
)
from services.identity.repositories.email_identity_repository import (
    EmailIdentityRepository,
)
from services.identity.repositories.password_credential_repository import (
    PasswordCredentialRepository,
)
from services.identity.repositories.registration_session_repository import (
    RegistrationSessionRepository,
)
from services.identity.models.oauth_session import OAuthSession
from services.identity.repositories.oauth_session_repository import (
    OAuthSessionRepository,
)
from services.persistence.base_repository import SupabaseRepository


class SupabaseEmailIdentityRepository(
    SupabaseRepository[EmailIdentity], EmailIdentityRepository
):

    @property
    def _table_name(self) -> str:
        return "email_identities"

    @classmethod
    def _entity_type(cls) -> type[EmailIdentity]:
        return EmailIdentity

    async def find_by_email(self, email: str) -> EmailIdentity | None:
        client = self._client()
        if client is None:
            return None
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("*")
            .eq("email", email)
            .limit(1)
            .execute()
        )
        return self._first(result)

    async def find_by_user_id(self, user_id: str) -> list[EmailIdentity]:
        client = self._client()
        if client is None:
            return []
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        return [self._from_row(r) for r in (getattr(result, "data", None) or [])]

    async def find_primary_by_user_id(self, user_id: str) -> EmailIdentity | None:
        client = self._client()
        if client is None:
            return None
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("*")
            .eq("user_id", user_id)
            .eq("is_primary", True)
            .limit(1)
            .execute()
        )
        return self._first(result)


class SupabasePasswordCredentialRepository(
    SupabaseRepository[PasswordCredential], PasswordCredentialRepository
):

    @property
    def _table_name(self) -> str:
        return "password_credentials"

    @classmethod
    def _entity_type(cls) -> type[PasswordCredential]:
        return PasswordCredential

    async def find_by_user_id(self, user_id: str) -> PasswordCredential | None:
        client = self._client()
        if client is None:
            return None
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("*")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        return self._first(result)


class SupabaseRegistrationSessionRepository(
    SupabaseRepository[RegistrationSession], RegistrationSessionRepository
):

    @property
    def _table_name(self) -> str:
        return "registration_sessions"

    @classmethod
    def _entity_type(cls) -> type[RegistrationSession]:
        return RegistrationSession

    async def find_pending_by_email(self, email: str) -> list[RegistrationSession]:
        client = self._client()
        if client is None:
            return []
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("*")
            .eq("email", email)
            .eq("status", RegistrationSessionStatus.PENDING.value)
            .order("created_at", desc=True)
            .execute()
        )
        return [self._from_row(r) for r in (getattr(result, "data", None) or [])]

    async def expire_stale(self) -> int:
        client = self._client()
        if client is None:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        stale = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("id")
            .eq("status", RegistrationSessionStatus.PENDING.value)
            .lt("expires_at", now)
            .execute()
        )
        count = 0
        for row in getattr(stale, "data", None) or []:
            await asyncio.to_thread(
                lambda: client.table(self._table_name)
                .update({"status": RegistrationSessionStatus.EXPIRED.value})
                .eq("id", row.get("id"))
                .execute()
            )
            count += 1
        return count

class SupabaseOAuthSessionRepository(
    SupabaseRepository[OAuthSession], OAuthSessionRepository
):

    @property
    def _table_name(self) -> str:
        return "oauth_sessions"

    @classmethod
    def _entity_type(cls) -> type[OAuthSession]:
        return OAuthSession

    async def find_by_state(self, state: str) -> OAuthSession | None:
        client = self._client()
        if client is None:
            return None
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("*")
            .eq("state", state)
            .limit(1)
            .execute()
        )
        return self._first(result)
