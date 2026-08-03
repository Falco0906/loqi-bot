from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class EventType(str, Enum):
    """Every meaningful occurrence in Loqi maps to one of these types.

    Categories follow the RFC architecture:
      Business   — campaign lifecycle, goal changes
      Outreach   — lead, draft, send lifecycle
      Inbox      — message analysis, reply handling
      Knowledge  — learned preferences, insights, memory
      User       — user-initiated actions and feedback
      System     — provider events, sync, errors
    """

    # ── Business ──
    CAMPAIGN_CREATED = "campaign_created"
    CAMPAIGN_STATUS_CHANGED = "campaign_status_changed"
    CAMPAIGN_UPDATED = "campaign_updated"
    CAMPAIGN_ARCHIVED = "campaign_archived"
    GOAL_SET = "goal_set"
    GOAL_UPDATED = "goal_updated"

    # ── Outreach ──
    LEAD_DISCOVERED = "lead_discovered"
    LEAD_SELECTED = "lead_selected"
    DRAFT_GENERATED = "draft_generated"
    DRAFT_UPDATED = "draft_updated"
    DRAFT_APPROVED = "draft_approved"
    DRAFT_REJECTED = "draft_rejected"
    DRAFT_SENT = "draft_sent"
    DRAFT_SCHEDULED = "draft_scheduled"
    DRAFT_FAILED = "draft_failed"

    # ── Inbox ──
    MESSAGE_RECEIVED = "message_received"
    REPLY_CLASSIFIED = "reply_classified"
    REPLY_AUTO_HANDLED = "reply_auto_handled"
    CONVERSATION_ESCALATED = "conversation_escalated"

    # ── Knowledge ──
    PREFERENCE_LEARNED = "preference_learned"
    ICP_UPDATED = "icp_updated"
    INSIGHT_GENERATED = "insight_generated"
    MEMORY_CONSOLIDATED = "memory_consolidated"

    # ── User ──
    BRIEFING_VIEWED = "briefing_viewed"
    RECOMMENDATION_ACTIONED = "recommendation_actioned"
    RECOMMENDATION_DISMISSED = "recommendation_dismissed"
    TELL_LOQI_INSTRUCTION = "tell_loqi_instruction"

    # ── System ──
    PROVIDER_CONNECTED = "provider_connected"
    PROVIDER_DISCONNECTED = "provider_disconnected"
    SYNC_COMPLETED = "sync_completed"
    RESEARCH_COMPLETED = "research_completed"
    ERROR_OCCURRED = "error_occurred"

    # ── Workflows ──
    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_PROGRESS = "workflow_progress"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"
    WORKFLOW_PAUSED = "workflow_paused"
    WORKFLOW_RESUMED = "workflow_resumed"
    WORKFLOW_CANCELLED = "workflow_cancelled"
    WORKFLOW_WAITING_APPROVAL = "workflow_waiting_approval"
    WORKFLOW_APPROVED = "workflow_approved"


@dataclass
class WorkspaceEvent:
    """An immutable record of something that happened in Loqi.

    Events are the source of truth.  The World Model projects current
    state by replaying events in sequence order.  Events are never
    mutated or deleted — only superseded by newer events.
    """

    id: str = field(default_factory=lambda: uuid4().hex[:16])
    type: EventType = EventType.SYNC_COMPLETED
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    session_id: str = ""
    actor: str = "system"
    data: dict[str, Any] = field(default_factory=dict)
    sequence: int = 0
    parent_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "timestamp": self.timestamp.isoformat(),
            "session_id": self.session_id,
            "actor": self.actor,
            "data": self.data,
            "sequence": self.sequence,
            "parent_id": self.parent_id,
        }
