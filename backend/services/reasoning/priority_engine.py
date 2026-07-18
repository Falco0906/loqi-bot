"""Priority Engine — determines conversation urgency from intelligence.

Factors: buying signal strength, conversation health, recency, objections, engagement.
Returns a PriorityAssessment with level, numeric score, and reasoning.
"""

from __future__ import annotations
from services.conversation_intelligence.intelligence_models import (
    ConversationIntelligence, SignalStrength, ObjectionSeverity,
)
from services.conversation_intelligence.knowledge.registry import get_registry
from services.reasoning.reasoning_models import DecisionPriority, PriorityAssessment


BASE_SCORE = 50


def assess_priority(intelligence: ConversationIntelligence) -> PriorityAssessment:
    """Assess conversation priority from intelligence signals."""
    registry = get_registry()
    factors: dict[str, int] = {}
    score = BASE_SCORE

    signal_score = _score_buying_signals(intelligence)
    score += signal_score
    factors["buying_signals"] = signal_score

    health_score = _score_health(intelligence)
    score += health_score
    factors["conversation_health"] = health_score

    objection_penalty = _score_objections(intelligence)
    score += objection_penalty
    factors["objections"] = objection_penalty

    engagement_score = _score_engagement(intelligence)
    score += engagement_score
    factors["engagement"] = engagement_score

    score = max(0, min(100, score))
    level = _map_level(score)
    reasoning = _build_reasoning(level, score, factors, intelligence)

    return PriorityAssessment(
        level=level,
        score=score,
        max_score=100,
        factors=factors,
        reasoning=reasoning,
    )


def _score_buying_signals(intelligence: ConversationIntelligence) -> int:
    strength_scores = {
        SignalStrength.VERY_STRONG: 15,
        SignalStrength.STRONG: 10,
        SignalStrength.MEDIUM: 5,
        SignalStrength.WEAK: 0,
        SignalStrength.VERY_WEAK: -5,
    }
    return sum(strength_scores.get(s.strength, 0) for s in intelligence.buying_signals[:3])


def _score_health(intelligence: ConversationIntelligence) -> int:
    if not intelligence.health:
        return 0
    h = intelligence.health.score / intelligence.health.max_score
    return int((h - 0.5) * 20)


def _score_objections(intelligence: ConversationIntelligence) -> int:
    penalties = {ObjectionSeverity.HIGH: -10, ObjectionSeverity.MEDIUM: -5, ObjectionSeverity.LOW: -2}
    return sum(penalties.get(o.severity, 0) for o in intelligence.objections[:3])


def _score_engagement(intelligence: ConversationIntelligence) -> int:
    if not intelligence.intents:
        return 0
    positive = {"interested", "meeting_request", "demo_request", "referral", "follow_up"}
    top = [i.label.value for i in intelligence.intents[:3]]
    net = sum(1 for l in top if l in positive) - sum(1 for l in top if l == "not_interested")
    return net * 8


def _map_level(score: int) -> DecisionPriority:
    if score >= 75:
        return DecisionPriority.CRITICAL
    if score >= 55:
        return DecisionPriority.HIGH
    if score >= 35:
        return DecisionPriority.MEDIUM
    return DecisionPriority.LOW


def _build_reasoning(
    level: DecisionPriority, score: int,
    factors: dict[str, int], intelligence: ConversationIntelligence,
) -> list[str]:
    reasons = [f"Priority: {level.value} (score: {score}/100)."]
    if factors.get("buying_signals", 0) > 0:
        reasons.append("Strong buying signals driving priority up.")
    if factors.get("objections", 0) < 0:
        reasons.append("Active objections requiring attention.")
    if intelligence.health and intelligence.health.score < 40:
        reasons.append("Low conversation health — needs intervention.")
    return reasons
