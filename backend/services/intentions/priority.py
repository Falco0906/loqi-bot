from __future__ import annotations

from typing import Any

from services.intentions.models import Intention, PriorityLevel


_INTENTION_TYPE_WEIGHTS = {
    "ask_user": 100,
    "escalate": 90,
    "follow_up": 70,
    "recommend_action": 60,
    "auto_handle": 50,
    "notify": 40,
    "wait": 20,
    "ignore": 0,
}


def _priority_score(intention: Intention) -> float:
    """Compute a numeric score for ordering.

    Higher score = higher display priority.
    Considers: priority level, confidence, recency, blocking state.
    """
    base = _INTENTION_TYPE_WEIGHTS.get(intention.type.value, 40)

    priority_bonus = {
        PriorityLevel.CRITICAL: 200,
        PriorityLevel.HIGH: 100,
        PriorityLevel.NORMAL: 0,
        PriorityLevel.LOW: -50,
    }.get(intention.priority, 0)

    confidence_bonus = intention.confidence * 50

    blocking_bonus = 80 if intention.blocking else 0

    return base + priority_bonus + confidence_bonus + blocking_bonus


def order_intentions(intentions: list[Intention]) -> list[Intention]:
    """Sort intentions by priority (highest first).

    Deterministic.  Stable sort — intentions with equal scores
    retain their relative order from the input list.
    """
    return sorted(intentions, key=_priority_score, reverse=True)


def highest_priority(intentions: list[Intention]) -> Intention | None:
    """Return the single highest-priority intention, or None."""
    if not intentions:
        return None
    return max(intentions, key=_priority_score)


def priority_level_from_score(score: float) -> PriorityLevel:
    """Map a numeric priority score to a PriorityLevel enum.

    Used when policies provide a raw score rather than a level.
    """
    if score >= 0.9:
        return PriorityLevel.CRITICAL
    if score >= 0.7:
        return PriorityLevel.HIGH
    if score >= 0.4:
        return PriorityLevel.NORMAL
    return PriorityLevel.LOW


def compute_priority(
    signals: dict[str, Any],
    policy_priority: PriorityLevel,
    confidence: float,
    blocking: bool,
) -> PriorityLevel:
    """Combine multiple signals into a final priority level.

    Factors considered:
        - Policy-assigned base priority
        - Confidence (low confidence caps priority)
        - Blocking state (blocking always at least HIGH)
        - Workspace health (failing workspace elevates)
        - Urgent signals override normal priority
    """
    if blocking:
        return PriorityLevel.HIGH

    urgency = signals.get("urgency", 0.0)
    workspace_health = signals.get("workspace_health_score", 1.0)

    raw_level = {
        PriorityLevel.CRITICAL: 4,
        PriorityLevel.HIGH: 3,
        PriorityLevel.NORMAL: 2,
        PriorityLevel.LOW: 1,
    }.get(policy_priority, 2)

    if workspace_health < 0.3:
        raw_level = min(raw_level + 2, 4)
    elif workspace_health < 0.6:
        raw_level = min(raw_level + 1, 4)

    if urgency > 0.8:
        raw_level = min(raw_level + 1, 4)

    if confidence < 0.3:
        raw_level = max(raw_level - 1, 1)
    elif confidence < 0.5:
        raw_level = max(raw_level - 1, 1)

    level_map = {4: PriorityLevel.CRITICAL, 3: PriorityLevel.HIGH,
                 2: PriorityLevel.NORMAL, 1: PriorityLevel.LOW}
    return level_map.get(raw_level, PriorityLevel.NORMAL)
