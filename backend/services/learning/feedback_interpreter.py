"""FeedbackInterpreter — interprets explicit user feedback signals.

Handles:
  - Recommendation accepted → reinforces the recommendation type
  - Recommendation dismissed → weakens the recommendation type
  - Draft rewritten → signals mismatch with user's preferred style
  - Draft approved as-is → signals alignment with user's preferred style

This is a deterministic signal extractor — it produces evidence counts
that PreferenceLearner consumes.  It does NOT make decisions.
"""

from __future__ import annotations

from typing import Any

from services.learning.behavior_tracker import BehaviorTracker


class FeedbackInterpreter:
    """Reads user feedback events and records behavioral evidence.

    Every feedback event produces a structured evidence record
    that PreferenceLearner can later evaluate.
    """

    def __init__(self, tracker: BehaviorTracker) -> None:
        self._tracker = tracker

    def on_recommendation_actioned(
        self,
        session_id: str,
        rec_type: str,
        confidence: float,
    ) -> None:
        self._tracker.record(
            session_id,
            "recommendation_actioned",
            {"rec_type": rec_type, "confidence": confidence},
        )

    def on_recommendation_dismissed(
        self,
        session_id: str,
        rec_type: str,
    ) -> None:
        self._tracker.record(
            session_id,
            "recommendation_dismissed",
            {"rec_type": rec_type},
        )

    def on_draft_approved(
        self,
        session_id: str,
        draft_id: str,
        tone: str | None = None,
        was_flagged: bool = False,
    ) -> None:
        data: dict[str, Any] = {"draft_id": draft_id, "was_flagged": was_flagged}
        if tone:
            data["tone"] = tone
        self._tracker.record(session_id, "draft_approved", data)

    def on_draft_rejected(
        self,
        session_id: str,
        draft_id: str,
        tone: str | None = None,
        was_flagged: bool = False,
    ) -> None:
        data: dict[str, Any] = {"draft_id": draft_id, "was_flagged": was_flagged}
        if tone:
            data["tone"] = tone
        self._tracker.record(session_id, "draft_rejected", data)

    def on_draft_updated(
        self,
        session_id: str,
        draft_id: str,
        original_tone: str | None = None,
    ) -> None:
        data: dict[str, Any] = {"draft_id": draft_id}
        if original_tone:
            data["original_tone"] = original_tone
        self._tracker.record(session_id, "draft_updated", data)

    def on_campaign_launched(
        self,
        session_id: str,
        campaign_id: str,
        delay_hours: float = 0,
    ) -> None:
        self._tracker.record(
            session_id,
            "campaign_launched",
            {"campaign_id": campaign_id, "delay_hours": delay_hours},
        )

    def on_campaign_created(
        self,
        session_id: str,
        campaign_id: str,
        company_size: str | None = None,
    ) -> None:
        data: dict[str, Any] = {"campaign_id": campaign_id}
        if company_size:
            data["company_size"] = company_size
        self._tracker.record(session_id, "campaign_created", data)

    def on_draft_reviewed(
        self,
        session_id: str,
        draft_id: str,
        hours_to_review: float,
    ) -> None:
        self._tracker.record(
            session_id,
            "draft_reviewed",
            {"draft_id": draft_id, "hours_to_review": hours_to_review},
        )
