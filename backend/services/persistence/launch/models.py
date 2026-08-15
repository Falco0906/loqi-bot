from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid4())


# ─── Identity ─────────────────────────────────────────────────────────────

@dataclass
class ExternalIdentity:
    id: str = field(default_factory=_new_id)
    user_id: str = ""
    provider: str = ""
    provider_subject: str = ""
    email: str = ""
    username: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    last_verified_at: datetime | None = None
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    deleted_at: datetime | None = None


@dataclass
class ConnectedAccount:
    id: str = field(default_factory=_new_id)
    user_id: str = ""
    provider: str = ""
    account_id: str = ""
    display_name: str = ""
    email: str = ""
    access_token: str = ""
    refresh_token: str = ""
    token_type: str = "bearer"
    token_expires_at: datetime | None = None
    status: str = "active"
    scope: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    last_synced_at: datetime | None = None
    version: int = 1
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    deleted_at: datetime | None = None


# ─── Organizations / Workspaces ──────────────────────────────────────────

@dataclass
class Workspace:
    id: str = field(default_factory=_new_id)
    organization_id: str = ""
    name: str = ""
    slug: str = ""
    owner_user_id: str = ""
    created_by: str = ""
    updated_by: str = ""
    status: str = "active"
    settings: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    version: int = 1
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    deleted_at: datetime | None = None


@dataclass
class WorkspaceMember:
    id: str = field(default_factory=_new_id)
    workspace_id: str = ""
    user_id: str = ""
    role: str = "member"
    status: str = "active"
    joined_at: datetime = field(default_factory=_now)
    invited_by: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    deleted_at: datetime | None = None


# ─── Companies / Leads ───────────────────────────────────────────────────

@dataclass
class Company:
    """Globally canonical company, deduplicated once per normalized domain."""

    id: str = field(default_factory=_new_id)
    canonical_id: str = ""
    domain: str = ""
    name: str = ""
    website: str = ""
    linkedin_url: str = ""
    industry: str = ""
    employee_count: int | None = None
    revenue_band: str = ""
    country: str = ""
    city: str = ""
    location: str = ""
    description: str = ""
    source_provider: str = ""
    created_by: str = ""
    updated_by: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    last_synced_at: datetime | None = None
    version: int = 1
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    deleted_at: datetime | None = None


@dataclass
class WorkspaceCompany:
    """Association + discovery provenance between a workspace and a global company."""

    id: str = field(default_factory=_new_id)
    workspace_id: str = ""
    company_id: str = ""
    source: str = ""
    created_by: str = ""
    created_at: datetime = field(default_factory=_now)
    deleted_at: datetime | None = None


@dataclass
class Lead:
    """Globally canonical person, deduplicated once per normalized email."""

    id: str = field(default_factory=_new_id)
    canonical_id: str = ""
    email: str = ""
    first_name: str = ""
    last_name: str = ""
    title: str = ""
    phone: str = ""
    linkedin_url: str = ""
    source_provider: str = ""
    created_by: str = ""
    updated_by: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    last_synced_at: datetime | None = None
    version: int = 1
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    deleted_at: datetime | None = None


@dataclass
class WorkspaceLead:
    """Workspace-scoped context for a global lead: company link + acquisition state."""

    id: str = field(default_factory=_new_id)
    workspace_id: str = ""
    lead_id: str = ""
    company_id: str | None = None
    email: str = ""
    first_name: str = ""
    last_name: str = ""
    title: str = ""
    phone: str = ""
    linkedin_url: str = ""
    lead_status: str = "new"
    research_status: str = "not_researched"
    verification_status: str = "unverified"
    confidence: float = 0
    source: str = ""
    created_by: str = ""
    updated_by: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    last_synced_at: datetime | None = None
    version: int = 1
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    deleted_at: datetime | None = None


@dataclass
class LeadSource:
    id: str = field(default_factory=_new_id)
    lead_id: str = ""
    provider: str = ""
    provider_lead_id: str = ""
    job_id: str | None = None
    rank: int = 0
    retrieved_at: datetime = field(default_factory=_now)
    cost: float = 0
    raw_payload: dict[str, Any] = field(default_factory=dict)
    provider_metadata: dict[str, Any] = field(default_factory=dict)
    payload_id: str = ""
    created_at: datetime = field(default_factory=_now)


@dataclass
class ProviderPayload:
    """Immutable archive of raw provider JSON (Apollo/PDL/Hunter/Clay...).

    Append-only: never updated or deleted, so archived fields can be
    re-parsed and backfilled without re-querying the provider.
    """

    id: str = field(default_factory=_new_id)
    provider: str = ""
    entity_type: str = "lead"  # "lead" | "company"
    entity_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    retrieved_at: datetime = field(default_factory=_now)
    created_at: datetime = field(default_factory=_now)


@dataclass
class LeadSignal:
    id: str = field(default_factory=_new_id)
    lead_id: str = ""
    company_id: str | None = None
    signal_type: str = ""
    label: str = ""
    strength: float = 0
    source: str = ""
    detected_at: datetime = field(default_factory=_now)
    data: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_now)


# ─── Campaigns / Strategies / Drafts ────────────────────────────────────

@dataclass
class Campaign:
    id: str = field(default_factory=_new_id)
    workspace_id: str = ""
    organization_id: str = ""
    name: str = ""
    objective: str = ""
    status: str = "planning"
    search_query: str = ""
    discovery_id: str = ""
    settings: dict[str, Any] = field(default_factory=dict)
    created_by: str = ""
    updated_by: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    version: int = 1
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    archived_at: datetime | None = None
    deleted_at: datetime | None = None


@dataclass
class CampaignLead:
    id: str = field(default_factory=_new_id)
    campaign_id: str = ""
    lead_id: str = ""
    status: str = "added"
    added_by: str = ""
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    deleted_at: datetime | None = None


@dataclass
class Strategy:
    id: str = field(default_factory=_new_id)
    campaign_id: str = ""
    version: int = 1
    is_current: bool = True
    objective: str = ""
    audience: str = ""
    channel: str = ""
    messaging_angle: str = ""
    sequence: list[str] = field(default_factory=list)
    tone: str = ""
    persona: str = ""
    offer: dict[str, Any] = field(default_factory=dict)
    objections: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    generated_at: datetime = field(default_factory=_now)
    generated_by: str = ""
    model_used: str = ""
    created_at: datetime = field(default_factory=_now)


@dataclass
class Draft:
    id: str = field(default_factory=_new_id)
    workspace_id: str = ""
    campaign_id: str | None = None
    lead_id: str | None = None
    provider: str = ""
    subject: str = ""
    body: str = ""
    preview: str = ""
    status: str = "pending"
    tone: str = ""
    length: str = ""
    generation_model: str = ""
    generation_version: str = ""
    prompt_hash: str = ""
    generation_metadata: dict[str, Any] = field(default_factory=dict)
    lead_snapshot: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_by: str = ""
    updated_by: str = ""
    version: int = 1
    approved_at: datetime | None = None
    sent_at: datetime | None = None
    reply_state: str = ""
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    deleted_at: datetime | None = None


# ─── Knowledge / Notifications / Audit ──────────────────────────────────

class KnowledgeCategory(str, Enum):
    """User Knowledge sections (PR5)."""

    COMPANY = "company"
    ICP = "icp"
    MESSAGING = "messaging"
    SALES_OFFER = "sales_offer"


class KnowledgeItemSourceType(str, Enum):
    """Provenance of a Knowledge item — agents must not treat generated
    information as user-provided fact."""

    USER_INPUT = "user_input"
    UPLOADED_DOCUMENT = "uploaded_document"
    IMPORTED_SOURCE = "imported_source"
    SYSTEM_GENERATED = "system_generated"


class KnowledgeSourceType(str, Enum):
    """Provenance of source material."""

    USER_INPUT = "user_input"
    UPLOADED_DOCUMENT = "uploaded_document"
    IMPORTED_SOURCE = "imported_source"
    SYSTEM_GENERATED = "system_generated"


@dataclass
class KnowledgeItem:
    """User-owned canonical Knowledge entry.

    ``content`` holds structured fields per category (e.g. company:
    {"products": [...], "competitors": [...]}). ``tags`` aids filtering.
    """

    id: str = field(default_factory=_new_id)
    workspace_id: str = ""
    category: str = ""
    title: str = ""
    summary: str = ""
    content: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    source_type: str = "user_input"
    source_id: str = ""
    created_by: str = ""
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    deleted_at: datetime | None = None


@dataclass
class KnowledgeSource:
    """Source material that future agents can retrieve.

    ``content`` holds text/notes directly; ``reference`` preserves a
    reference to externally stored file bytes rather than duplicating them.
    """

    id: str = field(default_factory=_new_id)
    workspace_id: str = ""
    title: str = ""
    source_type: str = "user_input"
    content: str = ""
    reference: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_by: str = ""
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    deleted_at: datetime | None = None


@dataclass
class StrategicUpdate:
    """Durable evidence-backed interpretation of observed workspace activity."""

    id: str = field(default_factory=_new_id)
    workspace_id: str = ""
    pattern_key: str = ""
    title: str = ""
    summary: str = ""
    update_type: str = "performance"
    status: str = "active"
    confidence: str = "low"
    observed_at: datetime = field(default_factory=_now)
    observation: str = ""
    interpretation: str = ""
    recommendation: str = ""
    structured_analysis: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    archived_at: datetime | None = None
    deleted_at: datetime | None = None


@dataclass
class StrategicAction:
    """Explicitly approved operational action derived from a Strategic Update."""

    id: str = field(default_factory=_new_id)
    workspace_id: str = ""
    strategic_update_id: str = ""
    action_type: str = ""
    status: str = "proposed"
    proposal: dict[str, Any] = field(default_factory=dict)
    created_by: str = ""
    created_at: datetime = field(default_factory=_now)
    approved_at: datetime | None = None
    executed_at: datetime | None = None
    dismissed_at: datetime | None = None
    error: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: datetime = field(default_factory=_now)
    deleted_at: datetime | None = None


@dataclass
class Knowledge:
    id: str = field(default_factory=_new_id)
    workspace_id: str = ""
    owner_type: str = ""
    owner_id: str = ""
    summary_type: str = ""
    title: str = ""
    content: dict[str, Any] = field(default_factory=dict)
    source_event: str = ""
    created_by: str = ""
    version: int = 1
    generated_at: datetime = field(default_factory=_now)
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    deleted_at: datetime | None = None


@dataclass
class Notification:
    id: str = field(default_factory=_new_id)
    user_id: str = ""
    workspace_id: str | None = None
    type: str = "info"
    title: str = ""
    body: str = ""
    read: bool = False
    read_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_now)
    deleted_at: datetime | None = None


@dataclass
class AuditRecord:
    id: str = field(default_factory=_new_id)
    workspace_id: str | None = None
    user_id: str | None = None
    actor_type: str = "user"
    action: str = ""
    entity_type: str = ""
    entity_id: str = ""
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    request_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_now)


# ─── Billing / Usage ────────────────────────────────────────────────────

@dataclass
class Plan:
    id: str = field(default_factory=_new_id)
    code: str = ""
    name: str = ""
    description: str = ""
    billing_interval: str = "monthly"
    currency: str = "usd"
    price: int = 0
    is_active: bool = True
    sort_order: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    deleted_at: datetime | None = None


@dataclass
class PlanFeature:
    id: str = field(default_factory=_new_id)
    plan_id: str = ""
    feature: str = ""
    value: str = ""
    unit: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_now)


@dataclass
class Subscription:
    id: str = field(default_factory=_new_id)
    organization_id: str = ""
    workspace_id: str | None = None
    plan_id: str | None = None
    status: str = "incomplete"
    trial_ends_at: datetime | None = None
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False
    canceled_at: datetime | None = None
    provider: str = ""
    provider_subscription_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    version: int = 1
    last_synced_at: datetime | None = None
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)


@dataclass
class UsageRecord:
    id: str = field(default_factory=_new_id)
    workspace_id: str | None = None
    organization_id: str = ""
    user_id: str | None = None
    feature: str = ""
    resource: str = ""
    units: float = 1
    provider: str = ""
    provider_cost: float = 0
    external_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=_now)
    created_at: datetime = field(default_factory=_now)
