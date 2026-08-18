from __future__ import annotations

import asyncio
from typing import Any

from services.identity.models import Membership, Organization
from services.identity.repositories.membership_repository import MembershipRepository
from services.identity.repositories.organization_repository import OrganizationRepository
from services.persistence.base_repository import (
    SupabaseRepository,
    _deserialize,
    _serialize,
)


class SupabaseIdentityOrganizationRepository(
    SupabaseRepository[Organization], OrganizationRepository
):

    @property
    def _table_name(self) -> str:
        return "organizations"

    @classmethod
    def _entity_type(cls) -> type[Organization]:
        return Organization

    def _to_row(self, entity: Organization) -> dict[str, Any]:
        # The durable `organizations` table stores the creator as `created_by`;
        # the identity model calls it `owner_id`. All other columns default.
        row = _serialize(entity)
        row["created_by"] = row.pop("owner_id", "")
        return row

    def _from_row(self, row: dict[str, Any]) -> Organization:
        row = dict(row)
        if "created_by" in row and "owner_id" not in row:
            row["owner_id"] = row.pop("created_by")
        return _deserialize(Organization, row)

    async def find_by_slug(self, slug: str) -> Organization | None:
        client = self._client()
        if client is None:
            return None
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("*")
            .eq("slug", slug)
            .is_("deleted_at", "null")
            .limit(1)
            .execute()
        )
        row = self._first(result)
        return None if row is None else self._from_row(row)

    async def find_by_owner_id(self, owner_id: str) -> list[Organization]:
        client = self._client()
        if client is None:
            return []
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("*")
            .eq("created_by", owner_id)
            .is_("deleted_at", "null")
            .execute()
        )
        return [self._from_row(r) for r in (getattr(result, "data", None) or [])]


class SupabaseIdentityMembershipRepository(
    SupabaseRepository[Membership], MembershipRepository
):

    @property
    def _table_name(self) -> str:
        return "memberships"

    @classmethod
    def _entity_type(cls) -> type[Membership]:
        return Membership

    def _to_row(self, entity: Membership) -> dict[str, Any]:
        # The durable `memberships` table stores the membership timestamp as
        # `joined_at`; the identity model calls it `invited_at` and keeps
        # `accepted_at` (not persisted by this schema). Status/role map 1:1.
        row = _serialize(entity)
        if "invited_at" in row:
            row["joined_at"] = row.pop("invited_at")
        row.pop("accepted_at", None)
        return row

    def _from_row(self, row: dict[str, Any]) -> Membership:
        row = dict(row)
        if "joined_at" in row and "invited_at" not in row:
            row["invited_at"] = row.pop("joined_at")
        row.setdefault("accepted_at", None)
        return _deserialize(Membership, row)

    async def find_by_user_and_org(
        self, user_id: str, organization_id: str,
    ) -> Membership | None:
        client = self._client()
        if client is None:
            return None
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("*")
            .eq("user_id", user_id)
            .eq("organization_id", organization_id)
            .limit(1)
            .execute()
        )
        row = self._first(result)
        return None if row is None else self._from_row(row)

    async def find_by_user_id(self, user_id: str) -> list[Membership]:
        client = self._client()
        if client is None:
            return []
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("*")
            .eq("user_id", user_id)
            .execute()
        )
        return [self._from_row(r) for r in (getattr(result, "data", None) or [])]

    async def find_by_org_id(self, organization_id: str) -> list[Membership]:
        client = self._client()
        if client is None:
            return []
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("*")
            .eq("organization_id", organization_id)
            .execute()
        )
        return [self._from_row(r) for r in (getattr(result, "data", None) or [])]

    async def find_active_by_user_id(self, user_id: str) -> list[Membership]:
        client = self._client()
        if client is None:
            return []
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("*")
            .eq("user_id", user_id)
            .eq("status", "active")
            .execute()
        )
        return [self._from_row(r) for r in (getattr(result, "data", None) or [])]