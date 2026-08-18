from __future__ import annotations

import asyncio
import json
from typing import Any, Generic, TypeVar

from services.persistence.base_repository import SupabaseRepository

from .models import (
    AuditRecord,
    Campaign,
    CampaignLead,
    Company,
    ConnectedAccount,
    Draft,
    ExternalIdentity,
    Knowledge,
    KnowledgeItem,
    KnowledgeSource,
    StrategicUpdate,
    StrategicAction,
    Lead,
    LeadSignal,
    LeadSource,
    Notification,
    Plan,
    PlanFeature,
    ProviderPayload,
    Strategy,
    Subscription,
    UsageRecord,
    Workspace,
    WorkspaceCompany,
    WorkspaceLead,
    WorkspaceMember,
)

T = TypeVar("T")


class LaunchRepository(SupabaseRepository, Generic[T]):
    """Supabase-backed repository for the launch foundation entities.

    Handles JSONB columns explicitly: dataclass dicts are JSON-encoded on
    write and decoded on read, so JSON stays JSON in the database.
    """

    _json_columns: tuple[str, ...] = ()

    @classmethod
    def _entity_type(cls) -> type[T]:
        raise NotImplementedError

    def _to_row(self, entity: T) -> dict[str, Any]:
        row = super()._to_row(entity)
        for col in self._json_columns:
            val = getattr(entity, col, None)
            if val is not None:
                row[col] = json.dumps(val)
        return row

    def _from_row(self, row: dict[str, Any]) -> T:
        row = dict(row)
        for col in self._json_columns:
            val = row.get(col)
            if isinstance(val, str):
                try:
                    row[col] = json.loads(val)
                except (ValueError, TypeError):
                    pass
        return super()._from_row(row)

    # ─── shared query helpers ─────────────────────────────────────────

    # Python-keyword filter methods are exposed by postgrest with a trailing
    # underscore (is_, in_, not_, or_, and_); translate the conventional names.
    _OP_ALIASES = {
        "is": "is_",
        "in": "in_",
        "not": "not_",
        "or": "or_",
        "and": "and_",
    }

    async def _list(self, where: list[tuple[str, Any, Any]] | None = None,
                    order: str = "created_at", desc: bool = True,
                    limit: int = 1000) -> list[T]:
        client = self._client()
        if client is None:
            return []
        def _run():
            query = client.table(self._table_name).select("*")
            for col, op, val in (where or []):
                op_method = self._OP_ALIASES.get(op, op)
                query = getattr(query, op_method)(col, val)
            query = query.order(order, desc=desc).limit(limit)
            return query.execute()
        result = await asyncio.to_thread(_run)
        rows = getattr(result, "data", None) or []
        return [self._from_row(r) for r in rows]

    async def _first_where(self, where: list[tuple[str, Any, Any]], *,
                           order: str | None = None, desc: bool = False) -> T | None:
        client = self._client()
        if client is None:
            return None
        def _run():
            query = client.table(self._table_name).select("*")
            for col, op, val in where:
                op_method = self._OP_ALIASES.get(op, op)
                query = getattr(query, op_method)(col, val)
            if order:
                query = query.order(order, desc=desc)
            return query.limit(1).execute()
        result = await asyncio.to_thread(_run)
        rows = getattr(result, "data", None) or []
        return self._from_row(rows[0]) if rows else None


# ─── Identity ───────────────────────────────────────────────────────────

class ExternalIdentityRepository(LaunchRepository[ExternalIdentity]):
    _table_name = "external_identities"
    _json_columns = ("metadata",)

    @classmethod
    def _entity_type(cls) -> type[ExternalIdentity]:
        return ExternalIdentity

    async def find_by_provider_subject(self, provider: str, subject: str) -> ExternalIdentity | None:
        return await self._first_where([
            ("provider", "eq", provider),
            ("provider_subject", "eq", subject),
        ])

    async def list_for_user(self, user_id: str) -> list[ExternalIdentity]:
        return await self._list([("user_id", "eq", user_id)])


class ConnectedAccountRepository(LaunchRepository[ConnectedAccount]):
    _table_name = "connected_accounts"
    _json_columns = ("scope", "metadata")

    @classmethod
    def _entity_type(cls) -> type[ConnectedAccount]:
        return ConnectedAccount

    async def find_for_user(self, user_id: str, provider: str) -> ConnectedAccount | None:
        return await self._first_where([
            ("user_id", "eq", user_id),
            ("provider", "eq", provider),
            ("deleted_at", "is", "null"),
        ], order="created_at", desc=True)

    async def list_for_user(self, user_id: str) -> list[ConnectedAccount]:
        return await self._list([("user_id", "eq", user_id)])


# ─── Workspaces ─────────────────────────────────────────────────────────

class WorkspaceRepository(LaunchRepository[Workspace]):
    _table_name = "workspaces"
    _json_columns = ("settings", "metadata")

    @classmethod
    def _entity_type(cls) -> type[Workspace]:
        return Workspace

    def _to_row(self, entity: Workspace) -> dict[str, Any]:
        row = super()._to_row(entity)
        # ``workflow_session_id`` is provenance only (SaaS-2.3). Omit it when
        # empty so writes stay schema-cache compatible with deployments that
        # have not yet applied migration 028 (a write of a column absent from
        # the PostgREST schema cache would otherwise raise PGRST204). When set,
        # it is a valid workflow-session reference, never the workspace id.
        if not row.get("workflow_session_id"):
            row.pop("workflow_session_id", None)
        return row

    async def find_by_owner(self, user_id: str) -> Workspace | None:
        return await self._first_where([("owner_user_id", "eq", user_id)])

    async def list_for_owner(self, user_id: str) -> list[Workspace]:
        return await self._list([("owner_user_id", "eq", user_id)])

    async def find_active_by_owner(self, user_id: str) -> Workspace | None:
        """Resolve the user's canonical active workspace by durable ownership.

        This is the tenant-resolution key for SaaS-2.1: the workspace identity
        is discovered from the durable owner relationship, never from a
        workflow/web-session id.
        """
        return await self._first_where(
            [
                ("owner_user_id", "eq", user_id),
                ("deleted_at", "is", "null"),
            ],
            order="created_at",
            desc=True,
        )

    async def find_active_by_owner_and_org(
        self, user_id: str, organization_id: str,
    ) -> Workspace | None:
        return await self._first_where(
            [
                ("owner_user_id", "eq", user_id),
                ("organization_id", "eq", organization_id),
                ("deleted_at", "is", "null"),
            ],
            order="created_at",
            desc=True,
        )


class WorkspaceMemberRepository(LaunchRepository[WorkspaceMember]):
    _table_name = "workspace_members"
    _json_columns = ("metadata",)

    @classmethod
    def _entity_type(cls) -> type[WorkspaceMember]:
        return WorkspaceMember

    async def find_member(self, workspace_id: str, user_id: str) -> WorkspaceMember | None:
        return await self._first_where([
            ("workspace_id", "eq", workspace_id),
            ("user_id", "eq", user_id),
        ])

    async def list_for_workspace(self, workspace_id: str) -> list[WorkspaceMember]:
        return await self._list([("workspace_id", "eq", workspace_id)])


# ─── Companies / Leads (global) / Workspace links ────────────────────────

class CompanyRepository(LaunchRepository[Company]):
    """Global canonical companies, deduplicated by normalized domain."""

    _table_name = "companies"
    _json_columns = ("metadata",)

    @classmethod
    def _entity_type(cls) -> type[Company]:
        return Company

    async def find_by_domain(self, domain: str) -> Company | None:
        if not domain:
            return None
        return await self._first_where([("domain", "eq", domain)])


class WorkspaceCompanyRepository(LaunchRepository[WorkspaceCompany]):
    _table_name = "workspace_companies"

    @classmethod
    def _entity_type(cls) -> type[WorkspaceCompany]:
        return WorkspaceCompany

    async def find(self, workspace_id: str, company_id: str) -> WorkspaceCompany | None:
        return await self._first_where([
            ("workspace_id", "eq", workspace_id),
            ("company_id", "eq", company_id),
        ])

    async def list_for_workspace(self, workspace_id: str) -> list[WorkspaceCompany]:
        return await self._list([("workspace_id", "eq", workspace_id)])


class LeadRepository(LaunchRepository[Lead]):
    """Global canonical leads, deduplicated by normalized email."""

    _table_name = "leads"
    _json_columns = ("metadata",)

    @classmethod
    def _entity_type(cls) -> type[Lead]:
        return Lead

    async def find_by_email(self, email: str) -> Lead | None:
        if not email:
            return None
        return await self._first_where([("email", "eq", email)])


class WorkspaceLeadRepository(LaunchRepository[WorkspaceLead]):
    _table_name = "workspace_leads"
    _json_columns = ("metadata",)

    @classmethod
    def _entity_type(cls) -> type[WorkspaceLead]:
        return WorkspaceLead

    async def find_in_workspace(self, workspace_id: str, lead_id: str) -> WorkspaceLead | None:
        return await self._first_where([
            ("workspace_id", "eq", workspace_id),
            ("lead_id", "eq", lead_id),
        ])

    async def list_for_workspace(self, workspace_id: str) -> list[WorkspaceLead]:
        return await self._list([("workspace_id", "eq", workspace_id)])

    async def list_by_email(self, workspace_id: str, email: str) -> list[WorkspaceLead]:
        return await self._list([
            ("workspace_id", "eq", workspace_id),
            ("email", "eq", email),
        ])

    async def find_by_company(self, workspace_id: str, company_id: str) -> WorkspaceLead | None:
        """The workspace lead behind a company-only prospect (no person email)."""
        return await self._first_where([
            ("workspace_id", "eq", workspace_id),
            ("company_id", "eq", company_id),
        ])


class LeadSourceRepository(LaunchRepository[LeadSource]):
    _table_name = "lead_sources"
    _json_columns = ("raw_payload", "provider_metadata")

    @classmethod
    def _entity_type(cls) -> type[LeadSource]:
        return LeadSource

    async def list_for_lead(self, lead_id: str) -> list[LeadSource]:
        return await self._list([("lead_id", "eq", lead_id)])


class ProviderPayloadRepository(LaunchRepository[ProviderPayload]):
    """Immutable archive of raw provider JSON. Never updated or deleted."""

    _table_name = "provider_payloads"
    _json_columns = ("payload",)

    @classmethod
    def _entity_type(cls) -> type[ProviderPayload]:
        return ProviderPayload

    async def find(self, provider: str, entity_type: str, entity_id: str) -> ProviderPayload | None:
        return await self._first_where([
            ("provider", "eq", provider),
            ("entity_type", "eq", entity_type),
            ("entity_id", "eq", entity_id),
        ])

    async def list_for_entity(self, entity_type: str, entity_id: str) -> list[ProviderPayload]:
        return await self._list([
            ("entity_type", "eq", entity_type),
            ("entity_id", "eq", entity_id),
        ])


class LeadSignalRepository(LaunchRepository[LeadSignal]):
    _table_name = "lead_signals"
    _json_columns = ("data",)

    @classmethod
    def _entity_type(cls) -> type[LeadSignal]:
        return LeadSignal

    async def list_for_lead(self, lead_id: str) -> list[LeadSignal]:
        return await self._list([("lead_id", "eq", lead_id)])


# ─── Campaigns / Strategies / Drafts ────────────────────────────────────

class CampaignRepository(LaunchRepository[Campaign]):
    _table_name = "campaigns"
    _json_columns = ("settings", "metadata")

    @classmethod
    def _entity_type(cls) -> type[Campaign]:
        return Campaign

    async def list_for_workspace(self, workspace_id: str) -> list[Campaign]:
        return await self._list([("workspace_id", "eq", workspace_id)], order="created_at", desc=True)


class CampaignLeadRepository(LaunchRepository[CampaignLead]):
    _table_name = "campaign_leads"

    @classmethod
    def _entity_type(cls) -> type[CampaignLead]:
        return CampaignLead

    async def find_link(self, campaign_id: str, lead_id: str) -> CampaignLead | None:
        return await self._first_where([
            ("campaign_id", "eq", campaign_id),
            ("lead_id", "eq", lead_id),
        ])

    async def list_for_campaign(self, campaign_id: str) -> list[CampaignLead]:
        return await self._list([("campaign_id", "eq", campaign_id)])


class StrategyRepository(LaunchRepository[Strategy]):
    _table_name = "strategies"
    _json_columns = ("sequence", "offer", "objections", "raw")

    @classmethod
    def _entity_type(cls) -> type[Strategy]:
        return Strategy

    async def list_for_campaign(self, campaign_id: str) -> list[Strategy]:
        return await self._list([("campaign_id", "eq", campaign_id)], order="version", desc=True)

    async def current_for_campaign(self, campaign_id: str) -> Strategy | None:
        return await self._first_where([("campaign_id", "eq", campaign_id), ("is_current", "eq", True)])


class DraftRepository(LaunchRepository[Draft]):
    _table_name = "drafts"
    _json_columns = ("generation_metadata", "lead_snapshot", "metadata")

    @classmethod
    def _entity_type(cls) -> type[Draft]:
        return Draft

    async def list_for_workspace(self, workspace_id: str) -> list[Draft]:
        return await self._list([("workspace_id", "eq", workspace_id)])

    async def list_for_campaign(self, campaign_id: str) -> list[Draft]:
        return await self._list([("campaign_id", "eq", campaign_id)])


# ─── Knowledge / Notifications / Audit ─────────────────────────────────

class KnowledgeRepository(LaunchRepository[Knowledge]):
    _table_name = "knowledge"
    _json_columns = ("content",)

    @classmethod
    def _entity_type(cls) -> type[Knowledge]:
        return Knowledge

    async def find(self, owner_type: str, owner_id: str, summary_type: str) -> Knowledge | None:
        return await self._first_where([
            ("owner_type", "eq", owner_type),
            ("owner_id", "eq", owner_id),
            ("summary_type", "eq", summary_type),
        ])

    async def list_for_workspace(self, workspace_id: str) -> list[Knowledge]:
        return await self._list([("workspace_id", "eq", workspace_id)])


class KnowledgeItemRepository(LaunchRepository[KnowledgeItem]):
    """User-owned canonical Knowledge entries (PR5)."""

    _table_name = "knowledge_items"
    _json_columns = ("content", "tags")

    @classmethod
    def _entity_type(cls) -> type[KnowledgeItem]:
        return KnowledgeItem

    async def list_for_workspace(self, workspace_id: str,
                                 category: str | None = None) -> list[KnowledgeItem]:
        where = [("workspace_id", "eq", workspace_id)]
        if category:
            where.append(("category", "eq", category))
        return await self._list(where, order="updated_at", desc=True)


class KnowledgeSourceRepository(LaunchRepository[KnowledgeSource]):
    """User-owned source material (PR5)."""

    _table_name = "knowledge_sources"
    _json_columns = ("metadata",)

    @classmethod
    def _entity_type(cls) -> type[KnowledgeSource]:
        return KnowledgeSource

    async def list_for_workspace(self, workspace_id: str) -> list[KnowledgeSource]:
        return await self._list([("workspace_id", "eq", workspace_id)])


class StrategicUpdateRepository(LaunchRepository[StrategicUpdate]):
    """Supabase persistence for derived, evidence-backed updates."""

    _table_name = "strategic_updates"
    _json_columns = ("structured_analysis", "evidence", "metadata")

    @classmethod
    def _entity_type(cls) -> type[StrategicUpdate]:
        return StrategicUpdate

    async def list_for_workspace(self, workspace_id: str) -> list[StrategicUpdate]:
        return await self._list([("workspace_id", "eq", workspace_id)], order="updated_at", desc=True)

    async def find_by_pattern_key(self, workspace_id: str, pattern_key: str) -> StrategicUpdate | None:
        return await self._first_where([
            ("workspace_id", "eq", workspace_id),
            ("pattern_key", "eq", pattern_key),
        ])


class StrategicActionRepository(LaunchRepository[StrategicAction]):
    """Supabase persistence for explicit Strategic Action approvals."""

    _table_name = "strategic_actions"
    _json_columns = ("proposal", "result", "metadata")

    @classmethod
    def _entity_type(cls) -> type[StrategicAction]:
        return StrategicAction

    async def list_for_update(self, workspace_id: str, update_id: str) -> list[StrategicAction]:
        return await self._list([
            ("workspace_id", "eq", workspace_id),
            ("strategic_update_id", "eq", update_id),
        ], order="created_at", desc=True)


class NotificationRepository(LaunchRepository[Notification]):
    _table_name = "notifications"
    _json_columns = ("metadata",)

    @classmethod
    def _entity_type(cls) -> type[Notification]:
        return Notification


class AuditLogRepository(LaunchRepository[AuditRecord]):
    _table_name = "audit_log"
    _json_columns = ("before", "after", "metadata")

    @classmethod
    def _entity_type(cls) -> type[AuditRecord]:
        return AuditRecord

    async def record(self, *, workspace_id: str | None = None, user_id: str | None = None,
                     action: str, entity_type: str = "", entity_id: str = "",
                     before: dict[str, Any] | None = None,
                     after: dict[str, Any] | None = None,
                     request_id: str = "", metadata: dict[str, Any] | None = None,
                     actor_type: str = "user") -> AuditRecord | None:
        entry = AuditRecord(
            workspace_id=workspace_id,
            user_id=user_id,
            actor_type=actor_type,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before=before,
            after=after,
            request_id=request_id,
            metadata=metadata or {},
        )
        return await self.save(entry)


# ─── Billing / Usage ───────────────────────────────────────────────────

class PlanRepository(LaunchRepository[Plan]):
    _table_name = "plans"
    _json_columns = ("metadata",)

    @classmethod
    def _entity_type(cls) -> type[Plan]:
        return Plan


class PlanFeatureRepository(LaunchRepository[PlanFeature]):
    _table_name = "plan_features"
    _json_columns = ("metadata",)

    @classmethod
    def _entity_type(cls) -> type[PlanFeature]:
        return PlanFeature

    async def list_for_plan(self, plan_id: str) -> list[PlanFeature]:
        return await self._list([("plan_id", "eq", plan_id)])


class SubscriptionRepository(LaunchRepository[Subscription]):
    _table_name = "subscriptions"
    _json_columns = ("metadata",)

    @classmethod
    def _entity_type(cls) -> type[Subscription]:
        return Subscription

    async def find_active_for_org(self, organization_id: str) -> Subscription | None:
        return await self._first_where([
            ("organization_id", "eq", organization_id),
            ("status", "in", ["active", "trialing"]),
        ])


class UsageRecordRepository(LaunchRepository[UsageRecord]):
    _table_name = "usage_records"
    _json_columns = ("metadata",)

    @classmethod
    def _entity_type(cls) -> type[UsageRecord]:
        return UsageRecord

    async def record(self, *, workspace_id: str | None = None, organization_id: str = "",
                     user_id: str | None = None, feature: str, resource: str = "",
                     units: float = 1, provider: str = "", provider_cost: float = 0,
                     metadata: dict[str, Any] | None = None) -> UsageRecord | None:
        entry = UsageRecord(
            workspace_id=workspace_id,
            organization_id=organization_id,
            user_id=user_id,
            feature=feature,
            resource=resource,
            units=units,
            provider=provider,
            provider_cost=provider_cost,
            metadata=metadata or {},
        )
        return await self.save(entry)
