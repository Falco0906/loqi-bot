from __future__ import annotations

import asyncio
from typing import List

from services.identity.models import Session
from services.persistence.base_repository import SupabaseRepository


class SupabaseSessionRepository(SupabaseRepository[Session]):

    @property
    def _table_name(self) -> str:
        return "sessions"

    @classmethod
    def _entity_type(cls) -> type[Session]:
        return Session

    async def find_by_user_id(self, user_id: str) -> list[Session]:
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

    async def find_active_by_user_id(self, user_id: str) -> list[Session]:
        from datetime import datetime, timezone
        client = self._client()
        if client is None:
            return []
        now = datetime.now(timezone.utc).isoformat()
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("*")
            .eq("user_id", user_id)
            .is_("revoked_at", "null")
            .gt("expires_at", now)
            .order("created_at", desc=True)
            .execute()
        )
        return [self._from_row(r) for r in (getattr(result, "data", None) or [])]

    async def revoke_all_for_user(self, user_id: str) -> int:
        client = self._client()
        if client is None:
            return 0
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .update({"revoked_at": now})
            .eq("user_id", user_id)
            .is_("revoked_at", "null")
            .execute()
        )
        return len(getattr(result, "data", None) or [])

    async def revoke_all_for_org(self, organization_id: str) -> int:
        client = self._client()
        if client is None:
            return 0
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .update({"revoked_at": now})
            .eq("organization_id", organization_id)
            .is_("revoked_at", "null")
            .execute()
        )
        return len(getattr(result, "data", None) or [])

    async def count_active_by_user_id(self, user_id: str) -> int:
        return len(await self.find_active_by_user_id(user_id))
