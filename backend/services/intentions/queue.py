from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services.intentions.lifecycle import activate, complete, dismiss, expire, can_transition
from services.intentions.models import Intention, LifecycleStatus, PriorityLevel
from services.intentions.priority import order_intentions, highest_priority


class IntentionQueue:
    """Manages the lifecycle and ordering of intentions.

    Maintains separate buckets for active, completed, dismissed,
    and expired intentions.  Active intentions are priority-ordered.

    Thread-safe for single-process use.  Not distributed — each
    workspace gets its own queue instance in the current design.
    """

    def __init__(self) -> None:
        self._active: dict[str, Intention] = {}
        self._completed: dict[str, Intention] = {}
        self._dismissed: dict[str, Intention] = {}
        self._expired: dict[str, Intention] = {}

    # ── Enqueue ───────────────────────────────────────────────────

    def enqueue(self, intention: Intention) -> Intention:
        """Add a new intention to the active queue.

        If the intention already exists (same id), it is replaced.
        Auto-activates if status is CREATED.
        """
        if intention.status == LifecycleStatus.CREATED:
            activate(intention)
        self._active[intention.id] = intention
        return intention

    def enqueue_all(self, intentions: list[Intention]) -> list[Intention]:
        """Add multiple intentions at once."""
        return [self.enqueue(i) for i in intentions]

    # ── Dequeue ───────────────────────────────────────────────────

    def dequeue(self, intention_id: str) -> Intention | None:
        """Remove and return an active intention by ID.

        This does NOT change lifecycle status — use complete/dismiss/expire
        to transition and then remove from active.
        """
        return self._active.pop(intention_id, None)

    # ── Lifecycle transitions ─────────────────────────────────────

    def complete(self, intention_id: str) -> Intention | None:
        """Mark as completed and move out of active queue."""
        intention = self._active.pop(intention_id, None)
        if intention is None:
            return None
        complete(intention)
        self._completed[intention_id] = intention
        return intention

    def dismiss(self, intention_id: str) -> Intention | None:
        """Dismiss and move out of active queue."""
        intention = self._active.pop(intention_id, None)
        if intention is None:
            return None
        dismiss(intention)
        self._dismissed[intention_id] = intention
        return intention

    def expire(self, intention_id: str) -> Intention | None:
        """Expire and move out of active queue."""
        intention = self._active.pop(intention_id, None)
        if intention is None:
            intention = self._completed.pop(intention_id, None)
        if intention is None:
            intention = self._dismissed.pop(intention_id, None)
        if intention is None:
            return None
        expire(intention)
        self._expired[intention_id] = intention
        return intention

    # ── Queries ───────────────────────────────────────────────────

    def get_active(self) -> list[Intention]:
        """Return all active intentions, priority-ordered (highest first)."""
        return order_intentions(list(self._active.values()))

    def get_by_id(self, intention_id: str) -> Intention | None:
        """Find an intention in any bucket."""
        return (
            self._active.get(intention_id)
            or self._completed.get(intention_id)
            or self._dismissed.get(intention_id)
            or self._expired.get(intention_id)
        )

    def highest_priority_active(self) -> Intention | None:
        """Return the single highest-priority active intention."""
        return highest_priority(list(self._active.values()))

    def count_active(self) -> int:
        return len(self._active)

    def count_by_priority(self) -> dict[str, int]:
        counts: dict[str, int] = {p.value: 0 for p in PriorityLevel}
        for i in self._active.values():
            counts[i.priority.value] = counts.get(i.priority.value, 0) + 1
        return counts

    def count_by_type(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for i in self._active.values():
            counts[i.type.value] = counts.get(i.type.value, 0) + 1
        return counts

    def list_completed(self, limit: int = 50) -> list[Intention]:
        return list(self._completed.values())[-limit:]

    def list_dismissed(self, limit: int = 50) -> list[Intention]:
        return list(self._dismissed.values())[-limit:]

    # ── Maintenance ───────────────────────────────────────────────

    def expire_old(self, max_age_hours: float = 24) -> list[Intention]:
        """Expire intentions that have been active too long."""
        now = datetime.now(timezone.utc)
        expired: list[Intention] = []
        for intention in list(self._active.values()):
            try:
                created = datetime.fromisoformat(intention.created_at)
                if (now - created).total_seconds() > max_age_hours * 3600:
                    self.expire(intention.id)
                    expired.append(intention)
            except Exception:
                continue
        return expired

    def has_active(self, intention_id: str) -> bool:
        return intention_id in self._active

    def clear(self) -> None:
        self._active.clear()
        self._completed.clear()
        self._dismissed.clear()
        self._expired.clear()

    # ── Serialization ─────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": [i.to_dict() for i in self.get_active()],
            "completed": [i.to_dict() for i in self.list_completed()],
            "dismissed": [i.to_dict() for i in self.list_dismissed()],
            "counts": {
                "active": self.count_active(),
                "by_priority": self.count_by_priority(),
                "by_type": self.count_by_type(),
            },
        }
