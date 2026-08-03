from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# ── Business Context ──


@dataclass
class Goal:
    description: str = ""
    active: bool = True
    created_at: str = ""


@dataclass
class Preference:
    key: str = ""
    value: str = ""
    confidence: float = 0.5
    source: str = ""


@dataclass
class BusinessContext:
    icp: str = ""
    goals: list[Goal] = field(default_factory=list)
    preferences: list[Preference] = field(default_factory=list)
    product_description: str = ""
    constraints: list[str] = field(default_factory=list)


# ── Pipeline State ──


@dataclass
class CampaignState:
    id: str = ""
    name: str = ""
    status: str = "planning"
    lead_count: int = 0
    pending_drafts: int = 0
    approved_drafts: int = 0
    created_at: str = ""
    updated_at: str = ""


@dataclass
class LeadState:
    id: str = ""
    name: str = ""
    company: str = ""
    title: str = ""
    email: str = ""
    campaign_id: str = ""
    status: str = "pending"


@dataclass
class DraftState:
    id: str = ""
    campaign_id: str = ""
    lead_id: str = ""
    subject: str = ""
    body_preview: str = ""
    status: str = "pending"
    tone: str = ""
    length: str = ""
    created_at: str = ""


@dataclass
class PipelineState:
    campaigns: list[CampaignState] = field(default_factory=list)
    leads: list[LeadState] = field(default_factory=list)
    drafts: list[DraftState] = field(default_factory=list)


# ── Relationship State ──


@dataclass
class ConversationSummary:
    id: str = ""
    external_thread_id: str = ""
    contact_name: str = ""
    subject: str = ""
    summary: str = ""
    stage: str = ""
    needs_attention: bool = False
    last_message_at: str = ""
    message_count: int = 0


@dataclass
class ContactState:
    id: str = ""
    name: str = ""
    email: str = ""
    company: str = ""
    title: str = ""
    conversation_count: int = 0
    last_contact_at: str = ""


@dataclass
class OutcomeState:
    id: str = ""
    campaign_id: str = ""
    lead_id: str = ""
    action: str = ""
    result: str = ""
    occurred_at: str = ""


@dataclass
class RelationshipState:
    conversations: list[ConversationSummary] = field(default_factory=list)
    contacts: list[ContactState] = field(default_factory=list)
    outcomes: list[OutcomeState] = field(default_factory=list)


# ── System State ──


@dataclass
class ProviderState:
    id: str = ""
    provider_type: str = ""
    status: str = "disconnected"
    email: str = ""
    last_sync_at: str = ""


@dataclass
class JobState:
    id: str = ""
    type: str = ""
    status: str = "queued"
    progress: float = 0.0
    started_at: str = ""


@dataclass
class SystemState:
    providers: list[ProviderState] = field(default_factory=list)
    jobs: list[JobState] = field(default_factory=list)


# ── Delta ──


@dataclass
class WorkspaceDelta:
    """What changed between two points in time.

    Produced by WorldModelStore.compute_delta() and consumed by the
    Reasoning Layer to power "while you were away" briefings.

    ``event_range`` records ``(first_sequence, last_sequence)`` of the
    events that produced this delta, enabling idempotent re-computation.
    ``first_visit`` is True when the session has no prior acknowledgement.
    """

    new_campaigns: list[CampaignState] = field(default_factory=list)
    changed_campaigns: list[CampaignState] = field(default_factory=list)
    new_drafts: list[DraftState] = field(default_factory=list)
    scheduled_drafts: list[DraftState] = field(default_factory=list)
    sent_outreach: list[DraftState] = field(default_factory=list)
    new_leads: list[LeadState] = field(default_factory=list)
    new_providers: list[ProviderState] = field(default_factory=list)
    new_conversations: list[ConversationSummary] = field(default_factory=list)
    escalated_conversations: list[ConversationSummary] = field(default_factory=list)
    completed_jobs: list[JobState] = field(default_factory=list)
    learned_preferences: list[Preference] = field(default_factory=list)
    new_insights: list[str] = field(default_factory=list)
    event_count: int = 0
    event_range: tuple[int, int] = (0, 0)
    first_visit: bool = False

    def is_empty(self) -> bool:
        return self.event_count == 0


# ── Top-level State ──


@dataclass
class WorkspaceState:
    """The unified representation of everything Loqi knows about a session.

    This is a projection of the event log.  Every field is derived by
    replaying WorkspaceEvents in sequence order.

    In Phase 1 this type was defined but not used as the source of
    truth.  Phase 2 wired event publishing so the event log is now
    the operational record.  Phase 3+ will migrate each reader to
    derive data from this state instead of the legacy dicts.
    """

    session_id: str = ""
    business_context: BusinessContext = field(default_factory=BusinessContext)
    pipeline: PipelineState = field(default_factory=PipelineState)
    relationships: RelationshipState = field(default_factory=RelationshipState)
    system: SystemState = field(default_factory=SystemState)
    version: int = 1
    projected_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
