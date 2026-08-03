from __future__ import annotations

from datetime import datetime, timezone

from services.intentions.models import Intention, LifecycleStatus


_TRANSITIONS: dict[LifecycleStatus, set[LifecycleStatus]] = {
    LifecycleStatus.CREATED: {LifecycleStatus.ACTIVE, LifecycleStatus.EXPIRED},
    LifecycleStatus.ACTIVE: {LifecycleStatus.COMPLETED, LifecycleStatus.DISMISSED, LifecycleStatus.EXPIRED},
    LifecycleStatus.COMPLETED: set(),
    LifecycleStatus.DISMISSED: set(),
    LifecycleStatus.EXPIRED: set(),
}


class LifecycleError(Exception):
    """Raised when an invalid lifecycle transition is attempted."""
    pass


def transition(intention: Intention, to: LifecycleStatus) -> Intention:
    """Transition an intention to a new lifecycle status.

    Raises LifecycleError if the transition is not allowed.
    Returns the updated intention (mutates and returns same object).
    """
    allowed = _TRANSITIONS.get(intention.status, set())
    if to not in allowed:
        raise LifecycleError(
            f"Cannot transition from {intention.status.value} to {to.value}. "
            f"Allowed: {[s.value for s in allowed]}"
        )
    intention.status = to
    intention.updated_at = datetime.now(timezone.utc).isoformat()
    return intention


def can_transition(intention: Intention, to: LifecycleStatus) -> bool:
    """Check if a transition is allowed without raising."""
    return to in _TRANSITIONS.get(intention.status, set())


def activate(intention: Intention) -> Intention:
    """Move from CREATED to ACTIVE."""
    return transition(intention, LifecycleStatus.ACTIVE)


def complete(intention: Intention) -> Intention:
    """Mark as completed."""
    return transition(intention, LifecycleStatus.COMPLETED)


def dismiss(intention: Intention) -> Intention:
    """Dismiss — user explicitly rejected or acknowledged."""
    return transition(intention, LifecycleStatus.DISMISSED)


def expire(intention: Intention) -> Intention:
    """Expire — deadline passed or superseded."""
    return transition(intention, LifecycleStatus.EXPIRED)
