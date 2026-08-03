"""BehaviorTracker — records user actions and provides evidence counts.

Maintains an in-memory log of user actions per session.
Evidence is used by PreferenceLearner to decide when to learn.

In a production deployment this would be persisted; for the initial
implementation an in-memory store is sufficient since events already
persist in the World Model event log.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from services.learning.models import BehaviorRecord


class BehaviorTracker:
    """Tracks user actions over time, bucketed by action type.

    Thread-safe for single-process use.  Each session has its own
    action log.  Actions are timestamped and can be queried by type.
    """

    def __init__(self) -> None:
        self._actions: dict[str, list[BehaviorRecord]] = defaultdict(list)

    def record(
        self,
        session_id: str,
        event_type: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        record = BehaviorRecord(
            event_type=event_type,
            session_id=session_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            data=data or {},
        )
        self._actions[session_id].append(record)

    def count(
        self,
        session_id: str,
        event_type: str,
    ) -> int:
        return sum(
            1 for r in self._actions.get(session_id, [])
            if r.event_type == event_type
        )

    def count_matching(
        self,
        session_id: str,
        event_type: str,
        data_predicate: dict[str, Any],
    ) -> int:
        count = 0
        for r in self._actions.get(session_id, []):
            if r.event_type != event_type:
                continue
            if all(r.data.get(k) == v for k, v in data_predicate.items()):
                count += 1
        return count

    def recent(
        self,
        session_id: str,
        event_type: str,
        limit: int = 10,
    ) -> list[BehaviorRecord]:
        matching = [
            r for r in self._actions.get(session_id, [])
            if r.event_type == event_type
        ]
        return matching[-limit:]

    def clear_session(self, session_id: str) -> None:
        self._actions.pop(session_id, None)

    def clear_all(self) -> None:
        self._actions.clear()


_global_tracker: BehaviorTracker | None = None


def get_tracker() -> BehaviorTracker:
    global _global_tracker
    if _global_tracker is None:
        _global_tracker = BehaviorTracker()
    return _global_tracker
