"""Conversation timeline models.

Every event in a conversation's lifecycle is recorded as a timeline entry.
Timeline events are ordered and immutable.
"""

from __future__ import annotations
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class TimelineEventType(str, Enum):
    CAMPAIGN_CREATED = "campaign_created"
    DRAFT_GENERATED = "draft_generated"
    EMAIL_SENT = "email_sent"
    EMAIL_DELIVERED = "email_delivered"
    EMAIL_OPENED = "email_opened"
    EMAIL_BOUNCED = "email_bounced"
    REPLY_RECEIVED = "reply_received"
    REPLY_CLASSIFIED = "reply_classified"
    FOLLOW_UP_SUGGESTED = "follow_up_suggested"
    FOLLOW_UP_READY = "follow_up_ready"
    FOLLOW_UP_SENT = "follow_up_sent"
    MEETING_BOOKED = "meeting_booked"
    STATUS_CHANGED = "status_changed"
    SUMMARY_UPDATED = "summary_updated"
    NOTE_ADDED = "note_added"
    CLOSED_WON = "closed_won"
    CLOSED_LOST = "closed_lost"


class TimelineEvent:
    """A single immutable event in a conversation's timeline."""

    def __init__(
        self,
        event_id: str = "",
        conversation_id: str = "",
        event_type: TimelineEventType = TimelineEventType.EMAIL_SENT,
        title: str = "",
        description: str = "",
        timestamp: Optional[datetime] = None,
        actor: str = "",
        metadata: dict = None,
    ):
        self.event_id = event_id or str(uuid.uuid4())
        self.conversation_id = conversation_id
        self.event_type = event_type
        self.title = title
        self.description = description
        self.timestamp = timestamp or datetime.now(timezone.utc)
        self.actor = actor
        self.metadata = metadata or {}

    def to_dict(self) -> dict:
        now = datetime.now(timezone.utc)
        return {
            "event_id": self.event_id,
            "conversation_id": self.conversation_id,
            "event_type": self.event_type.value,
            "title": self.title,
            "description": self.description,
            "timestamp": self.timestamp.isoformat() if self.timestamp else now.isoformat(),
            "actor": self.actor,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TimelineEvent:
        ts = data.get("timestamp")
        if ts and isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                ts = datetime.now(timezone.utc)
        else:
            ts = datetime.now(timezone.utc)
        type_val = data.get("event_type", "email_sent")
        try:
            etype = TimelineEventType(type_val)
        except ValueError:
            etype = TimelineEventType.EMAIL_SENT
        return cls(
            event_id=data.get("event_id", ""),
            conversation_id=data.get("conversation_id", ""),
            event_type=etype,
            title=data.get("title", ""),
            description=data.get("description", ""),
            timestamp=ts,
            actor=data.get("actor", ""),
            metadata=data.get("metadata", {}),
        )


def build_timeline_event(
    conversation_id: str,
    event_type: TimelineEventType,
    title: str,
    description: str = "",
    actor: str = "",
    metadata: dict = None,
) -> TimelineEvent:
    """Convenience factory for creating timeline events."""
    return TimelineEvent(
        conversation_id=conversation_id,
        event_type=event_type,
        title=title,
        description=description,
        actor=actor,
        metadata=metadata or {},
    )
