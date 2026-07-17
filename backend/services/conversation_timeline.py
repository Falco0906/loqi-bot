"""Conversation Timeline — structured event log for a conversation.

Events are separate from workflow events.
They represent conversation-level occurrences.
"""

from datetime import datetime, timezone
from typing import Optional
from services.conversation_models import ConversationTimelineEvent, TimelineEventType


_timelines: dict[str, list[ConversationTimelineEvent]] = {}


def create_event(
    conversation_id: str,
    event_type: TimelineEventType,
    message: str,
    metadata: Optional[dict] = None,
) -> ConversationTimelineEvent:
    """Create a timeline event for a conversation."""
    event = ConversationTimelineEvent(
        event_type=event_type,
        message=message,
        timestamp=datetime.now(timezone.utc).isoformat(),
        metadata=metadata or {},
    )
    if conversation_id not in _timelines:
        _timelines[conversation_id] = []
    _timelines[conversation_id].append(event)
    return event


def get_events(conversation_id: str) -> list[ConversationTimelineEvent]:
    """Get all timeline events for a conversation, ordered by timestamp."""
    return _timelines.get(conversation_id, [])


def get_all_events() -> dict[str, list[ConversationTimelineEvent]]:
    """Get all timeline events across all conversations."""
    return dict(_timelines)


def clear_events(conversation_id: str) -> None:
    """Clear all events for a conversation."""
    _timelines.pop(conversation_id, None)


def clear_all() -> None:
    """Clear all events."""
    _timelines.clear()
