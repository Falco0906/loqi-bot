"""Provider Events — lifecycle events for communication providers.

Mission Control later consumes these events.
Separate from workflow events and conversation timeline events.
"""

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from services.communication.provider_models import ProviderEventType



class ProviderEvent:
    """A single provider lifecycle event."""

    def __init__(
        self,
        event_type: ProviderEventType,
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


_events: list[ProviderEvent] = []


def emit_event(
    event_type: ProviderEventType,
    provider_id: str,
    message: str = "",
    metadata: Optional[dict[str, Any]] = None,
) -> ProviderEvent:
    """Emit a provider event."""
    event = ProviderEvent(
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
) -> list[ProviderEvent]:
    """Get events, optionally filtered by provider and sequence."""
    result = [e for e in _events if e.sequence > after_sequence]
    if provider_id:
        result = [e for e in result if e.provider_id == provider_id]
    result.sort(key=lambda e: e.sequence)
    return result[-limit:]


def get_all_events() -> list[ProviderEvent]:
    """Get all events."""
    return list(_events)


def clear_events(provider_id: str = "") -> None:
    """Clear events, optionally for a specific provider."""
    global _events
    if provider_id:
        _events = [e for e in _events if e.provider_id != provider_id]
    else:
        _events = []


def latest_sequence() -> int:
    """Get the latest sequence number."""
    if not _events:
        return 0
    return max(e.sequence for e in _events)


def reset_events() -> None:
    """Reset all events and sequence counter (for testing)."""
    global _seq_counter
    _events.clear()
    _seq_counter = 0
