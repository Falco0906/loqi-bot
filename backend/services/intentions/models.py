from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class IntentionType(str, Enum):
    """Every intention Loqi can have.  No free-form intention types."""
    ASK_USER = "ask_user"
    RECOMMEND_ACTION = "recommend_action"
    FOLLOW_UP = "follow_up"
    WAIT = "wait"
    NOTIFY = "notify"
    AUTO_HANDLE = "auto_handle"
    ESCALATE = "escalate"
    IGNORE = "ignore"


class PriorityLevel(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class LifecycleStatus(str, Enum):
    CREATED = "created"
    ACTIVE = "active"
    COMPLETED = "completed"
    DISMISSED = "dismissed"
    EXPIRED = "expired"


class ReasonCode(str, Enum):
    """Every intention has exactly one reason code.  No free-form strings."""
    CAMPAIGN_READY = "campaign_ready"
    CAMPAIGN_BLOCKED = "campaign_blocked"
    DRAFT_REVIEW_REQUIRED = "draft_review_required"
    NEW_REPLY_RECEIVED = "new_reply_received"
    FOLLOW_UP_DUE = "follow_up_due"
    MEETING_PENDING = "meeting_pending"
    NEW_LEADS_FOUND = "new_leads_found"
    LOW_CONFIDENCE = "low_confidence"
    PROVIDER_FAILURE = "provider_failure"
    USER_INPUT_REQUIRED = "user_input_required"
    CALENDAR_CONFLICT = "calendar_conflict"
    DOCUMENT_UPDATED = "document_updated"
    PREFERENCE_LEARNED = "preference_learned"
    INSIGHT_GENERATED = "insight_generated"
    SYNC_COMPLETED = "sync_completed"
    RESEARCH_COMPLETED = "research_completed"
    OUTREACH_PENDING = "outreach_pending"
    SIGNAL_DETECTED = "signal_detected"
    CAMPAIGN_HEALTH_CHANGED = "campaign_health_changed"
    WORKSPACE_HEALTH_CHANGED = "workspace_health_changed"


@dataclass
class Evidence:
    """Structured evidence explaining why an intention exists."""
    reason_code: ReasonCode
    confidence: float = 0.0
    source: str = ""
    detail: str = ""
    related_events: list[str] = field(default_factory=list)
    signals: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason_code": self.reason_code.value,
            "confidence": round(self.confidence, 2),
            "source": self.source,
            "detail": self.detail,
            "related_events": self.related_events,
            "signals": self.signals,
        }


@dataclass
class Intention:
    """A single intention — what Loqi should do next.

    Intentions are:
        - deterministic (never created by LLMs)
        - strongly typed (no free-form types or reasons)
        - evidence-backed
        - lifecycle-managed
        - priority-ordered
    """
    id: str
    workspace_id: str
    type: IntentionType
    priority: PriorityLevel
    confidence: float
    status: LifecycleStatus
    reason_code: ReasonCode
    blocking: bool
    created_at: str
    updated_at: str
    expires_at: str = ""
    related_campaign: str = ""
    related_lead: str = ""
    related_provider: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    evidence: list[Evidence] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "type": self.type.value,
            "priority": self.priority.value,
            "confidence": round(self.confidence, 2),
            "status": self.status.value,
            "reason_code": self.reason_code.value,
            "blocking": self.blocking,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
            "related_campaign": self.related_campaign,
            "related_lead": self.related_lead,
            "related_provider": self.related_provider,
            "metadata": self.metadata,
            "evidence": [e.to_dict() for e in self.evidence],
        }

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()


# ── Helpers for constructing intentions ──────────────────────────

def intention_id(workspace_id: str, reason_code: ReasonCode, suffix: str = "") -> str:
    import hashlib, time
    raw = f"{workspace_id}::{reason_code.value}::{suffix or str(time.time())}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
