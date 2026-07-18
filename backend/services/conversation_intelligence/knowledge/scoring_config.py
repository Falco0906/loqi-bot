"""Scoring configuration — tunable weights for conversation health scoring.

No extraction logic. Data only.
"""

DEFAULT_SCORING_WEIGHTS: dict[str, int] = {
    "buying_signal": 35,
    "objection": -25,
    "engagement": 20,
    "velocity": 15,
    "sentiment": 10,
}

STRENGTH_SCORES: dict[str, float] = {
    "very_strong": 1.0,
    "strong": 0.75,
    "medium": 0.5,
    "weak": 0.25,
    "very_weak": 0.0,
}

SEVERITY_PENALTIES: dict[str, float] = {
    "high": -1.0,
    "medium": -0.6,
    "low": -0.3,
}
