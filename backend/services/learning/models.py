"""PreferenceModel — typed, structured preferences learned from user behavior.

Every preference has:
  key       — typed enum (not free-form string)
  value     — type-specific structured value
  confidence — 0.0–1.0, calibrated, never reaches 1.0
  source    — which learner produced it
  evidence  — how many actions support it

No free-form text blobs.  No natural language.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PreferenceKey(str, Enum):
    """All known preference keys.  Add new ones here as learning expands."""

    EMAIL_TONE = "preferred_email_tone"
    COMPANY_SIZE = "preferred_company_size"
    LAUNCH_STYLE = "launch_style"
    REVIEW_SPEED = "review_speed"
    RISK_TOLERANCE = "risk_tolerance"
    WORKING_HOURS_START = "working_hours_start"
    WORKING_HOURS_END = "working_hours_end"
    CONFIDENCE_THRESHOLD = "confidence_threshold"


@dataclass
class LearnedPreference:
    """A single learned preference with evidence and confidence."""

    key: str
    value: str
    confidence: float
    source: str
    evidence_count: int
    first_observed: str = ""
    last_observed: str = ""

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "value": self.value,
            "confidence": round(self.confidence, 2),
            "source": self.source,
            "evidence_count": self.evidence_count,
            "first_observed": self.first_observed,
            "last_observed": self.last_observed,
        }


@dataclass
class BehaviorRecord:
    """A single observation of user behavior tied to an event."""

    event_type: str
    session_id: str
    timestamp: str
    data: dict[str, Any] = field(default_factory=dict)


# ── Allowed values for each typed preference ──

EMAIL_TONE_VALUES = {"casual", "professional", "balanced"}
COMPANY_SIZE_VALUES = {"small", "mid", "enterprise", "any"}
LAUNCH_STYLE_VALUES = {"immediate", "cautious", "strategic"}
REVIEW_SPEED_VALUES = {"fast", "moderate", "slow"}
RISK_TOLERANCE_VALUES = {"low", "medium", "high"}


def validate_preference_value(key: str, value: str) -> bool:
    valid_sets = {
        PreferenceKey.EMAIL_TONE: EMAIL_TONE_VALUES,
        PreferenceKey.COMPANY_SIZE: COMPANY_SIZE_VALUES,
        PreferenceKey.LAUNCH_STYLE: LAUNCH_STYLE_VALUES,
        PreferenceKey.REVIEW_SPEED: REVIEW_SPEED_VALUES,
        PreferenceKey.RISK_TOLERANCE: RISK_TOLERANCE_VALUES,
    }
    allowed = valid_sets.get(PreferenceKey(key))
    if allowed is None:
        return True
    return value in allowed
