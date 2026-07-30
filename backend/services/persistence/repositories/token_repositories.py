from __future__ import annotations

import asyncio
from typing import List

from services.identity.models import (
    PasswordResetRequest,
    RefreshToken,
    VerificationToken,
)
from services.identity.repositories.token_repositories import (
    PasswordResetRepository,
    RefreshTokenRepository,
    VerificationTokenRepository,
)
from services.persistence.base_repository import SupabaseRepository


class SupabaseVerificationTokenRepository(
    SupabaseRepository[VerificationToken], VerificationTokenRepository
):

    @property
    def _table_name(self) -> str:
        return "verification_tokens"

    @classmethod
    def _entity_type(cls) -> type[VerificationToken]:
        return VerificationToken

    async def find_valid_by_target_and_purpose(
        self, target: str, purpose: str,
    ) -> VerificationToken | None:
        from datetime import datetime, timezone
        client = self._client()
        if client is None:
            return None
        now = datetime.now(timezone.utc).isoformat()
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("*")
            .eq("target", target)
            .eq("purpose", purpose)
            .is_("used_at", "null")
            .gt("expires_at", now)
            .limit(1)
            .execute()
        )
        row = self._first(result)
        if row is None:
            return None
        return self._from_row(row)

    async def find_by_target(self, target: str) -> list[VerificationToken]:
        client = self._client()
        if client is None:
            return []
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("*")
            .eq("target", target)
            .order("created_at", desc=True)
            .execute()
        )
        return [self._from_row(r) for r in (getattr(result, "data", None) or [])]

    async def find_by_hash(self, token_hash: str) -> VerificationToken | None:
        client = self._client()
        if client is None:
            return None
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("*")
            .eq("token_hash", token_hash)
            .limit(1)
            .execute()
        )
        row = self._first(result)
        if row is None:
            return None
        return self._from_row(row)

    async def invalidate_all_for_target(self, target: str) -> int:
        from datetime import datetime, timezone
        client = self._client()
        if client is None:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .update({"used_at": now})
            .eq("target", target)
            .is_("used_at", "null")
            .execute()
        )
        return len(getattr(result, "data", None) or [])


class SupabaseRefreshTokenRepository(
    SupabaseRepository[RefreshToken], RefreshTokenRepository
):

    @property
    def _table_name(self) -> str:
        return "refresh_tokens"

    @classmethod
    def _entity_type(cls) -> type[RefreshToken]:
        return RefreshToken

    async def find_active_by_session_id(self, session_id: str) -> RefreshToken | None:
        from datetime import datetime, timezone
        client = self._client()
        if client is None:
            return None
        now = datetime.now(timezone.utc).isoformat()
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("*")
            .eq("session_id", session_id)
            .is_("revoked_at", "null")
            .gt("expires_at", now)
            .limit(1)
            .execute()
        )
        row = self._first(result)
        if row is None:
            return None
        return self._from_row(row)

    async def find_by_family(self, family: str) -> list[RefreshToken]:
        client = self._client()
        if client is None:
            return []
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("*")
            .eq("family", family)
            .order("sequence", desc=True)
            .execute()
        )
        return [self._from_row(r) for r in (getattr(result, "data", None) or [])]

    async def revoke_all_for_session(self, session_id: str) -> int:
        from datetime import datetime, timezone
        client = self._client()
        if client is None:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .update({"revoked_at": now})
            .eq("session_id", session_id)
            .is_("revoked_at", "null")
            .execute()
        )
        return len(getattr(result, "data", None) or [])

    async def revoke_all_for_user(self, user_id: str, session_ids: list[str]) -> int:
        if not session_ids:
            return 0
        from datetime import datetime, timezone
        client = self._client()
        if client is None:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .update({"revoked_at": now})
            .in_("session_id", session_ids)
            .is_("revoked_at", "null")
            .execute()
        )
        return len(getattr(result, "data", None) or [])

    async def revoke_family(self, family: str) -> int:
        from datetime import datetime, timezone
        client = self._client()
        if client is None:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .update({"revoked_at": now})
            .eq("family", family)
            .is_("revoked_at", "null")
            .execute()
        )
        return len(getattr(result, "data", None) or [])

    async def find_by_hash(self, token_hash: str) -> RefreshToken | None:
        client = self._client()
        if client is None:
            return None
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("*")
            .eq("token_hash", token_hash)
            .limit(1)
            .execute()
        )
        row = self._first(result)
        if row is None:
            return None
        return self._from_row(row)


class SupabasePasswordResetRepository(
    SupabaseRepository[PasswordResetRequest], PasswordResetRepository
):

    @property
    def _table_name(self) -> str:
        return "password_reset_requests"

    @classmethod
    def _entity_type(cls) -> type[PasswordResetRequest]:
        return PasswordResetRequest

    async def find_valid_by_user_id(self, user_id: str) -> PasswordResetRequest | None:
        from datetime import datetime, timezone
        client = self._client()
        if client is None:
            return None
        now = datetime.now(timezone.utc).isoformat()
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("*")
            .eq("user_id", user_id)
            .is_("used_at", "null")
            .gt("expires_at", now)
            .limit(1)
            .execute()
        )
        row = self._first(result)
        if row is None:
            return None
        return self._from_row(row)

    async def invalidate_all_for_user(self, user_id: str) -> int:
        from datetime import datetime, timezone
        client = self._client()
        if client is None:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .update({"used_at": now})
            .eq("user_id", user_id)
            .is_("used_at", "null")
            .execute()
        )
        return len(getattr(result, "data", None) or [])
