"""DeltaReasoner — computes what changed since the user's last visit.

Thin wrapper around WorldModelStore.compute_delta().
Adds no business logic — just translates WM state into delta dicts.

The actual delta computation lives in WorldModelStore (event-sourced).
This reasoner exists so the pipeline has a uniform interface.
"""

from typing import Any

from services.world_model import get_store as get_wm_store


class DeltaReasoner:
    """Computes workspace delta from the World Model event log."""

    def compute(
        self,
        session_token: str,
        after_sequence: int = 0,
    ) -> tuple[dict[str, Any], int]:
        store = get_wm_store()
        last_seq = store.get_last_sequence(session_token)
        wm_delta = store.compute_delta(session_token, after_sequence=after_sequence)

        delta_dict: dict[str, Any] = {
            "first_visit": wm_delta.first_visit,
            "has_delta": not wm_delta.is_empty(),
            "event_count": wm_delta.event_count,
            "event_range": list(wm_delta.event_range),
            "new_campaigns": len(wm_delta.new_campaigns),
            "changed_campaigns": len(wm_delta.changed_campaigns),
            "new_drafts": len(wm_delta.new_drafts),
            "scheduled_drafts": len(wm_delta.scheduled_drafts),
            "sent_outreach": len(wm_delta.sent_outreach),
            "new_leads": len(wm_delta.new_leads),
            "new_providers": len(wm_delta.new_providers),
            "new_conversations": len(wm_delta.new_conversations),
            "escalated_conversations": len(wm_delta.escalated_conversations),
            "completed_jobs": len(wm_delta.completed_jobs),
            "learned_preferences": len(wm_delta.learned_preferences),
            "new_insights": len(wm_delta.new_insights),
        }

        return delta_dict, last_seq
