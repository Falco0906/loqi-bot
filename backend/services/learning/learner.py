"""Learner — orchestrator that runs the full learning pipeline.

Flow:
  1. PreferenceLearner evaluates behavior evidence
  2. PatternDetector finds temporal patterns
  3. For each new/higher-confidence preference:
     a. Read the canonical workspace preference record
     b. Only persist when confidence exceeds the stored value

Usage:
    learner = Learner()
    events = learner.run(session_id)
    # returns durable preference record IDs

Learning is deterministic, conservative, and idempotent.
Running it twice with the same evidence produces the same result.
"""

from __future__ import annotations

from typing import Any

from services.learning.behavior_tracker import get_tracker
from services.learning.feedback_interpreter import FeedbackInterpreter
from services.learning.models import LearnedPreference, PreferenceKey
from services.learning.pattern_detector import PatternDetector
from services.learning.preference_learner import PreferenceLearner
from services.learning.preference_store import PreferenceStore


class Learner:
    """Orchestrates the deterministic learning pipeline.

    Idempotent: running twice with the same tracker state produces
    the same number of durable preference writes.
    """

    def __init__(self) -> None:
        tracker = get_tracker()
        self.interpreter = FeedbackInterpreter(tracker)
        self.preference_learner = PreferenceLearner(tracker)
        self.pattern_detector = PatternDetector(tracker)

    def run(
        self,
        session_id: str,
        *,
        workspace_id: str = "",
        actor_user_id: str = "",
    ) -> list[str]:
        """Run the full learning pipeline for a session.

        Returns durable preference record IDs for newly persisted preferences.

        Learned preferences require canonical workspace scope. Calls without
        it remain analysis-only rather than falling back to session-keyed
        process-local preference state.
        """
        if not workspace_id:
            return []
        emitted: list[str] = []
        store = PreferenceStore(
            session_id,
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
        )

        all_new = self.preference_learner.evaluate(session_id)
        all_new.extend(self.pattern_detector.detect(session_id))

        for pref in all_new:
            existing_value = store.get(PreferenceKey(pref.key))
            existing_conf = self._existing_confidence(store, pref.key)

            if existing_value == pref.value and existing_conf >= pref.confidence:
                continue

            if existing_value and existing_conf >= pref.confidence:
                continue

            eid = store.save(pref)
            emitted.append(eid)

        return emitted

    def _existing_confidence(self, store: PreferenceStore, key: str) -> float:
        all_prefs = store.get_all()
        for p in all_prefs:
            if p["key"] == key:
                return p.get("confidence", 0.0)
        return 0.0
