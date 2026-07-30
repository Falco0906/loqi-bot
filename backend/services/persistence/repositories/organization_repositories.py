from __future__ import annotations

import asyncio
import json
from typing import Any

from services.organizations.models import (
    Invitation,
    InvitationStatus,
    Membership,
    MembershipRole,
    MembershipStatus,
    Organization,
    OrganizationSettings,
    OrganizationStatus,
)
from services.organizations.repositories import (
    InvitationRepository,
    MembershipRepository,
    OrganizationRepository,
)
from services.persistence.base_repository import SupabaseRepository, _deserialize, _serialize


class SupabaseOrganizationRepository(SupabaseRepository[Organization], OrganizationRepository):

    @property
    def _table_name(self) -> str:
        return "organizations"

    @classmethod
    def _entity_type(cls) -> type[Organization]:
        return Organization

    def _to_row(self, entity: Organization) -> dict[str, Any]:
        row = _serialize(entity)
        if entity.settings is not None:
            row["settings"] = json.dumps({
                "timezone": entity.settings.timezone,
                "locale": entity.settings.locale,
                "branding": entity.settings.branding,
                "preferences": entity.settings.preferences,
                "created_at": entity.settings.created_at.isoformat() if hasattr(entity.settings.created_at, "isoformat") else entity.settings.created_at,
                "updated_at": entity.settings.updated_at.isoformat() if hasattr(entity.settings.updated_at, "isoformat") else entity.settings.updated_at,
            })
        else:
            row["settings"] = "{}"
        if entity.metadata:
            row["metadata"] = json.dumps(entity.metadata)
        else:
            row["metadata"] = "{}"
        return row

    def _from_row(self, row: dict[str, Any]) -> Organization:
        settings_raw = row.pop("settings", None)
        metadata_raw = row.pop("metadata", None)
        org = _deserialize(Organization, row)
        if metadata_raw:
            if isinstance(metadata_raw, str):
                org.metadata = json.loads(metadata_raw)
            else:
                org.metadata = dict(metadata_raw)
        if settings_raw:
            if isinstance(settings_raw, str):
                settings_data = json.loads(settings_raw)
            else:
                settings_data = dict(settings_raw)
            org.settings = OrganizationSettings(**settings_data)
        return org

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
        if row is None:
            return None
        return self._from_row(row)

    async def find_by_name(self, name: str) -> Organization | None:
        client = self._client()
        if client is None:
            return None
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("*")
            .eq("name", name)
            .is_("deleted_at", "null")
            .limit(1)
            .execute()
        )
        row = self._first(result)
        if row is None:
            return None
        return self._from_row(row)

    async def find_owned_by(self, user_id: str) -> list[Organization]:
        client = self._client()
        if client is None:
            return []
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("*")
            .eq("created_by", user_id)
            .is_("deleted_at", "null")
            .execute()
        )
        return [self._from_row(r) for r in (getattr(result, "data", None) or [])]


class SupabaseMembershipRepository(SupabaseRepository[Membership], MembershipRepository):

    @property
    def _table_name(self) -> str:
        return "memberships"

    @classmethod
    def _entity_type(cls) -> type[Membership]:
        return Membership

    async def find_by_user_and_org(self, user_id: str, organization_id: str) -> Membership | None:
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
        if row is None:
            return None
        return self._from_row(row)

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

    async def count_owners(self, organization_id: str) -> int:
        client = self._client()
        if client is None:
            return 0
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("id")
            .eq("organization_id", organization_id)
            .eq("role", "owner")
            .eq("status", "active")
            .execute()
        )
        return len(getattr(result, "data", None) or [])

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


class SupabaseInvitationRepository(SupabaseRepository[Invitation], InvitationRepository):

    @property
    def _table_name(self) -> str:
        return "invitations"

    @classmethod
    def _entity_type(cls) -> type[Invitation]:
        return Invitation

    async def find_by_org_id(self, organization_id: str) -> list[Invitation]:
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

    async def find_pending_by_email(self, email: str) -> list[Invitation]:
        client = self._client()
        if client is None:
            return []
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("*")
            .eq("email", email)
            .eq("status", "pending")
            .execute()
        )
        return [self._from_row(r) for r in (getattr(result, "data", None) or [])]

    async def find_by_token(self, token: str) -> Invitation | None:
        client = self._client()
        if client is None:
            return None
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("*")
            .eq("token", token)
            .limit(1)
            .execute()
        )
        row = self._first(result)
        if row is None:
            return None
        return self._from_row(row)
