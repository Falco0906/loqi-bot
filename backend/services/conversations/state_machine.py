"""Conversation state machine.

Explicit state transitions for the conversation lifecycle.
Extend by adding new (from_state, to_state) pairs to ALLOWED_TRANSITIONS.
"""

from __future__ import annotations
from services.conversations.conversation_models import ConversationStatus


ALLOWED_TRANSITIONS: dict[ConversationStatus, set[ConversationStatus]] = {
    ConversationStatus.NEW: {
        ConversationStatus.SENT,
        ConversationStatus.BOUNCED,
        ConversationStatus.CLOSED_LOST,
    },
    ConversationStatus.SENT: {
        ConversationStatus.DELIVERED,
        ConversationStatus.BOUNCED,
        ConversationStatus.REPLIED,
        ConversationStatus.OPENED,
        ConversationStatus.INTERESTED,
        ConversationStatus.FOLLOW_UP_PENDING,
        ConversationStatus.CLOSED_LOST,
    },
    ConversationStatus.DELIVERED: {
        ConversationStatus.OPENED,
        ConversationStatus.REPLIED,
        ConversationStatus.BOUNCED,
        ConversationStatus.FOLLOW_UP_PENDING,
    },
    ConversationStatus.OPENED: {
        ConversationStatus.REPLIED,
        ConversationStatus.FOLLOW_UP_PENDING,
        ConversationStatus.INTERESTED,
        ConversationStatus.CLOSED_LOST,
    },
    ConversationStatus.REPLIED: {
        ConversationStatus.SENT,
        ConversationStatus.FOLLOW_UP_PENDING,
        ConversationStatus.INTERESTED,
        ConversationStatus.MEETING_BOOKED,
        ConversationStatus.CLOSED_LOST,
        ConversationStatus.FOLLOW_UP_READY,
    },
    ConversationStatus.FOLLOW_UP_PENDING: {
        ConversationStatus.FOLLOW_UP_READY,
        ConversationStatus.FOLLOW_UP_SENT,
        ConversationStatus.REPLIED,
        ConversationStatus.CLOSED_LOST,
    },
    ConversationStatus.FOLLOW_UP_READY: {
        ConversationStatus.FOLLOW_UP_SENT,
        ConversationStatus.REPLIED,
        ConversationStatus.CLOSED_LOST,
    },
    ConversationStatus.FOLLOW_UP_SENT: {
        ConversationStatus.REPLIED,
        ConversationStatus.INTERESTED,
        ConversationStatus.FOLLOW_UP_PENDING,
        ConversationStatus.CLOSED_LOST,
    },
    ConversationStatus.INTERESTED: {
        ConversationStatus.MEETING_BOOKED,
        ConversationStatus.REPLIED,
        ConversationStatus.SENT,
        ConversationStatus.FOLLOW_UP_PENDING,
        ConversationStatus.CLOSED_WON,
        ConversationStatus.CLOSED_LOST,
    },
    ConversationStatus.MEETING_BOOKED: {
        ConversationStatus.INTERESTED,
        ConversationStatus.CLOSED_WON,
        ConversationStatus.CLOSED_LOST,
        ConversationStatus.FOLLOW_UP_PENDING,
    },
    ConversationStatus.CLOSED_WON: set(),
    ConversationStatus.CLOSED_LOST: set(),
    ConversationStatus.BOUNCED: {
        ConversationStatus.CLOSED_LOST,
    },
}


def validate_transition(
    current: ConversationStatus,
    target: ConversationStatus,
) -> bool:
    """Check if a transition from current to target is allowed."""
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    return target in allowed


def transition(
    current: ConversationStatus,
    target: ConversationStatus,
    raise_on_invalid: bool = True,
) -> ConversationStatus:
    """Attempt a state transition. Returns the new status or raises."""
    if current == target:
        return current
    if validate_transition(current, target):
        return target
    if raise_on_invalid:
        raise ValueError(
            f"Invalid conversation state transition: {current.value} -> {target.value}. "
            f"Allowed transitions from {current.value}: "
            f"{[s.value for s in ALLOWED_TRANSITIONS.get(current, set())]}"
        )
    return current


def terminal_states() -> set[ConversationStatus]:
    """States that cannot transition to any other state."""
    return {s for s, targets in ALLOWED_TRANSITIONS.items() if not targets}


def active_states() -> set[ConversationStatus]:
    """States that are still in play (not terminal)."""
    terminal = terminal_states()
    return {s for s in ConversationStatus if s not in terminal}
