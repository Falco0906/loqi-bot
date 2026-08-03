"""PatternDetector — detects recurring temporal and behavioral patterns.

Patterns include:
  - Preferred working hours (when the user is most active)
  - Days of week with highest activity
  - Campaign completion velocity

Deterministic.  No LLM.  Conservative — requires repeated evidence.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from services.learning.models import LearnedPreference, PreferenceKey
from services.learning.behavior_tracker import BehaviorTracker, get_tracker


MIN_ACTIONS_FOR_HOURS = 10
"""Minimum actions before inferring working hours."""


class PatternDetector:
    """Analyzes behavior history for recurring patterns.

    Unlike PreferenceLearner which looks at *what* the user did,
    PatternDetector looks at *when* and *how consistently* they did it.
    """

    def __init__(self, tracker: BehaviorTracker) -> None:
        self._tracker = tracker

    def detect(self, session_id: str) -> list[LearnedPreference]:
        patterns: list[LearnedPreference] = []

        pref = self._detect_working_hours(session_id)
        if pref:
            patterns.append(pref)

        return patterns

    def _detect_working_hours(self, session_id: str) -> LearnedPreference | None:
        """Find the hours when the user is most active."""
        hour_counts: dict[int, int] = defaultdict(int)
        total = 0

        for r in self._tracker._actions.get(session_id, []):
            try:
                ts = datetime.fromisoformat(r.timestamp)
                hour_counts[ts.hour] += 1
                total += 1
            except (ValueError, TypeError):
                continue

        if total < MIN_ACTIONS_FOR_HOURS:
            return None

        active = [(h, c) for h, c in hour_counts.items() if c >= 2]
        if not active:
            return None

        active.sort(key=lambda x: x[0])
        start_hour = active[0][0]
        end_hour = active[-1][0]

        if end_hour < start_hour:
            end_hour += 24

        return LearnedPreference(
            key=PreferenceKey.WORKING_HOURS_START.value,
            value=f"{start_hour:02d}:00",
            confidence=min(0.5 + total * 0.02, 0.85),
            source="pattern_detector",
            evidence_count=total,
        )
