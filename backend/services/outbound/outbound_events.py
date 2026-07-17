"""Outbound Events — lifecycle events for outbound communication.

Separate from provider events and workflow events.
Sequence-numbered with polling support identical to provider events.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4


class OutboundEventType(str, Enum):
    DRAFT_CREATED = "draft_created"
    DRAFT_UPDATED = "draft_updated"
    DRAFT_DELETED = "draft_deleted"
    DRAFT_APPROVED = "draft_approved"
    DRAFT_REJECTED = "draft_rejected"
    DRAFT_AUTO_APPROVED = "draft_auto_approved"
    DRAFT_SENDING = "draft_sending"
    DRAFT_FAILED = "draft_failed"
    DRAFT_CANCELLED = "draft_cancelled"
    MESSAGE_SENT = "message_sent"
    MESSAGE_FAILED = "message_failed"
    MESSAGE_SCHEDULED = "message_scheduled"
    MESSAGE_CANCELLED = "message_cancelled"


class OutboundEvent:
    def __init__(
        self,
        event_type: OutboundEventType,
        provider_id: str,
        message: str = "",
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        self.id = str(uuid4())[:8]
        self.event_type = event_type
        self.provider_id = provider_id
        self.message = message
        self.metadata = metadata or {}
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.sequence = _next_seq()


_seq_counter = 0


def _next_seq() -> int:
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


_events: list[OutboundEvent] = []


def emit_event(
    event_type: OutboundEventType,
    provider_id: str,
    message: str = "",
    metadata: Optional[dict[str, Any]] = None,
) -> OutboundEvent:
    event = OutboundEvent(
        event_type=event_type,
        provider_id=provider_id,
        message=message,
        metadata=metadata,
    )
    _events.append(event)
    return event


def get_events(
    provider_id: str = "",
    after_sequence: int = 0,
    limit: int = 50,
) -> list[OutboundEvent]:
    result = [e for e in _events if e.sequence > after_sequence]
    if provider_id:
        result = [e for e in result if e.provider_id == provider_id]
    result.sort(key=lambda e: e.sequence)
    return result[-limit:]


def get_all_events() -> list[OutboundEvent]:
    return list(_events)


def clear_events(provider_id: str = "") -> None:
    global _events
    if provider_id:
        _events = [e for e in _events if e.provider_id != provider_id]
    else:
        _events = []


def latest_sequence() -> int:
    if not _events:
        return 0
    return max(e.sequence for e in _events)


def reset_events() -> None:
    global _seq_counter
    _events.clear()
    _seq_counter = 0
