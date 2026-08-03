"""PreferenceStore — thin wrapper around World Model preferences.

Provides typed access to learned preferences without exposing
World Model internals to the learning modules.

Reading preferences:
    store = PreferenceStore(session_id)
    tone = store.get(PreferenceKey.EMAIL_TONE)
    if tone:
        print(f"User prefers {tone.value} tone")

Writing preferences (via PREFERENCE_LEARNED events):
    Learner emits events → World Model processes → state updated
"""

from __future__ import annotations

from typing import Any

from services.learning.models import LearnedPreference, PreferenceKey
from services.world_model import get_store as get_wm_store, EventType, publish


class PreferenceStore:
    """Typed access to learned preferences for a given session.

    Wraps the World Model's BusinessContext.preferences list.
    """

    def __init__(self, session_id: str) -> None:
        self._session_id = session_id

    def get_all(self) -> list[dict]:
        store = get_wm_store()
        state = store.get_state(self._session_id)
        if state is None:
            return []
        return [
            {
                "key": p.key,
                "value": p.value,
                "confidence": p.confidence,
                "source": p.source,
            }
            for p in state.business_context.preferences
        ]

    def get(self, key: PreferenceKey, default: str | None = None) -> str | None:
        store = get_wm_store()
        state = store.get_state(self._session_id)
        if state is None:
            return default
        for p in state.business_context.preferences:
            if p.key == key.value:
                return p.value
        return default

    def has(self, key: PreferenceKey) -> bool:
        return self.get(key) is not None

    def save(self, pref: LearnedPreference) -> str:
        return publish(
            session_id=self._session_id,
            event_type=EventType.PREFERENCE_LEARNED,
            data=pref.to_dict(),
            actor="system",
        )
