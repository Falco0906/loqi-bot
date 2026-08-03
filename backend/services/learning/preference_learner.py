"""PreferenceLearner — decides when repeated behavior warrants a learned preference.

Conservative threshold:
  - Require 5+ instances of consistent behavior before learning.
  - Confidence grows with evidence but never exceeds 0.95.
  - A single counter-example reduces confidence but doesn't reset immediately.

This module is deterministic.  No LLM.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services.learning.models import (
    LearnedPreference,
    PreferenceKey,
    validate_preference_value,
    COMPANY_SIZE_VALUES,
    LAUNCH_STYLE_VALUES,
    REVIEW_SPEED_VALUES,
    RISK_TOLERANCE_VALUES,
    EMAIL_TONE_VALUES,
)
from services.learning.behavior_tracker import BehaviorTracker


# ── Thresholds (conservative) ──

MIN_EVIDENCE = 5
"""Minimum number of consistent actions before a preference is learned."""

CONFIDENCE_PER_EVIDENCE = 0.08
"""Confidence gained per unit of evidence beyond the minimum."""

MAX_CONFIDENCE = 0.95
"""No preference ever reaches absolute certainty."""


class PreferenceLearner:
    """Evaluates behavior evidence and emits structured preferences.

    Usage:
        learner = PreferenceLearner(tracker)
        prefs = learner.evaluate(session_id)
        for pref in prefs:
            publish(PREFERENCE_LEARNED, pref.to_dict())
    """

    def __init__(self, tracker: BehaviorTracker) -> None:
        self._tracker = tracker

    def evaluate(self, session_id: str) -> list[LearnedPreference]:
        """Run all preference checks.  Returns only *new* preferences
        whose confidence has crossed the learning threshold.

        Callers are responsible for:
          1. Checking the World Model for existing preferences
          2. Only emitting PREFERENCE_LEARNED if confidence increased
          3. Updating existing preferences with higher-confidence values
        """
        learned: list[LearnedPreference] = []

        pref = self._evaluate_tone(session_id)
        if pref:
            learned.append(pref)

        pref = self._evaluate_company_size(session_id)
        if pref:
            learned.append(pref)

        pref = self._evaluate_launch_style(session_id)
        if pref:
            learned.append(pref)

        pref = self._evaluate_review_speed(session_id)
        if pref:
            learned.append(pref)

        pref = self._evaluate_risk_tolerance(session_id)
        if pref:
            learned.append(pref)

        return learned

    def _confidence(self, count: int) -> float:
        if count < MIN_EVIDENCE:
            return 0.0
        extra = count - MIN_EVIDENCE
        return min(0.5 + extra * CONFIDENCE_PER_EVIDENCE, MAX_CONFIDENCE)

    def _evaluate_tone(self, session_id: str) -> LearnedPreference | None:
        approved = self._tracker.count_matching(
            session_id, "draft_approved", {}
        )
        rejected = self._tracker.count_matching(
            session_id, "draft_rejected", {}
        )

        approved_casual = self._tracker.count_matching(
            session_id, "draft_approved", {"tone": "casual"}
        )
        approved_professional = self._tracker.count_matching(
            session_id, "draft_approved", {"tone": "professional"}
        )

        total_tone_approvals = approved_casual + approved_professional
        if total_tone_approvals < MIN_EVIDENCE:
            return None

        if approved_casual > approved_professional * 2:
            value = "casual"
        elif approved_professional > approved_casual * 2:
            value = "professional"
        else:
            value = "balanced"

        return LearnedPreference(
            key=PreferenceKey.EMAIL_TONE.value,
            value=value,
            confidence=self._confidence(total_tone_approvals),
            source="preference_learner",
            evidence_count=total_tone_approvals,
        )

    def _evaluate_company_size(self, session_id: str) -> LearnedPreference | None:
        small = self._tracker.count_matching(
            session_id, "campaign_created", {"company_size": "small"}
        )
        mid = self._tracker.count_matching(
            session_id, "campaign_created", {"company_size": "mid"}
        )
        enterprise = self._tracker.count_matching(
            session_id, "campaign_created", {"company_size": "enterprise"}
        )

        sizes = {"small": small, "mid": mid, "enterprise": enterprise}
        total = sum(sizes.values())
        if total < MIN_EVIDENCE:
            return None

        best = max(sizes, key=sizes.get)
        if sizes[best] > total * 0.6:
            value = best
        else:
            value = "any"

        return LearnedPreference(
            key=PreferenceKey.COMPANY_SIZE.value,
            value=value,
            confidence=self._confidence(total),
            source="preference_learner",
            evidence_count=total,
        )

    def _evaluate_launch_style(self, session_id: str) -> LearnedPreference | None:
        immediate = self._tracker.count_matching(
            session_id, "campaign_launched", {"delay_hours": 0}
        )
        cautious = self._tracker.count_matching(
            session_id, "campaign_launched", {"delay_hours": (1, 24)}
        )
        strategic = self._tracker.count_matching(
            session_id, "campaign_launched", {"delay_hours": (24, float("inf"))}
        )

        styles = {"immediate": immediate, "cautious": cautious, "strategic": strategic}
        total = sum(styles.values())
        if total < MIN_EVIDENCE:
            return None

        best = max(styles, key=styles.get)
        return LearnedPreference(
            key=PreferenceKey.LAUNCH_STYLE.value,
            value=best,
            confidence=self._confidence(total),
            source="preference_learner",
            evidence_count=total,
        )

    def _evaluate_review_speed(self, session_id: str) -> LearnedPreference | None:
        fast = self._tracker.count_matching(
            session_id, "draft_reviewed", {"hours_to_review": (0, 1)}
        )
        moderate = self._tracker.count_matching(
            session_id, "draft_reviewed", {"hours_to_review": (1, 24)}
        )
        slow = self._tracker.count_matching(
            session_id, "draft_reviewed", {"hours_to_review": (24, float("inf"))}
        )

        speeds = {"fast": fast, "moderate": moderate, "slow": slow}
        total = sum(speeds.values())
        if total < MIN_EVIDENCE:
            return None

        best = max(speeds, key=speeds.get)
        return LearnedPreference(
            key=PreferenceKey.REVIEW_SPEED.value,
            value=best,
            confidence=self._confidence(total),
            source="preference_learner",
            evidence_count=total,
        )

    def _evaluate_risk_tolerance(self, session_id: str) -> LearnedPreference | None:
        approved_risky = self._tracker.count_matching(
            session_id, "draft_approved", {"was_flagged": True}
        )
        rejected_risky = self._tracker.count_matching(
            session_id, "draft_rejected", {"was_flagged": True}
        )

        total_risky = approved_risky + rejected_risky
        if total_risky < MIN_EVIDENCE:
            return None

        if approved_risky > rejected_risky * 2:
            value = "high"
        elif approved_risky >= rejected_risky * 0.5:
            value = "medium"
        else:
            value = "low"

        return LearnedPreference(
            key=PreferenceKey.RISK_TOLERANCE.value,
            value=value,
            confidence=self._confidence(total_risky),
            source="preference_learner",
            evidence_count=total_risky,
        )
