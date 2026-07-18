"""Conversation health scoring.

Produces a 0-100 health score per conversation.
All weights and scoring thresholds come from KnowledgeRegistry.
No magic numbers — configuration is centralized.
"""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional
from services.conversation_intelligence.intelligence_models import (
    ConversationIntelligence, BuyingSignalResult,
    SignalStrength, ObjectionSeverity, HealthScoreResult,
)
from services.conversation_intelligence.knowledge.registry import get_registry


def score_conversation(
    intelligence: ConversationIntelligence,
    weights: Optional[dict[str, int]] = None,
) -> HealthScoreResult:
    """Score conversation health from 0-100 using weighted signals."""
    registry = get_registry()
    w = {**registry.get_scoring_weights(), **(weights or {})}

    baseline = registry.get_confidence("SCORING_BASELINE")
    score = baseline

    score += _score_buying_signals(intelligence.buying_signals, w["buying_signal"], registry)
    score += _score_objections(intelligence.objections, w["objection"], registry)
    score += _score_engagement(intelligence, w["engagement"], registry)

    max_score = registry.get_confidence("SCORING_MAX")
    min_score = registry.get_confidence("SCORING_MIN")
    score = max(min_score, min(max_score, score))

    reasoning = _generate_reasoning(score, intelligence, registry)

    return HealthScoreResult(
        score=score,
        max_score=int(max_score),
        reasoning=reasoning,
        components={k: v for k, v in w.items()},
    )


def _score_buying_signals(
    signals: list[BuyingSignalResult], weight: int, registry,
) -> int:
    if not signals:
        return 0
    strength_scores = registry.get_strength_scores()
    max_possible = max(len(signals), 1)
    total = sum(strength_scores.get(s.strength.value, 0) for s in signals)
    normalized = total / max_possible
    return int(normalized * weight)


def _score_objections(objections, weight: int, registry) -> int:
    if not objections:
        return 0
    penalties = registry.get_severity_penalties()
    total_penalty = sum(penalties.get(o.severity.value, 0) for o in objections)
    normalized = total_penalty / max(len(objections), 1)
    return int(normalized * abs(weight))


def _score_engagement(intelligence: ConversationIntelligence, weight: int, registry) -> int:
    score = 0
    if intelligence.intents:
        top_labels = [i.label.value for i in intelligence.intents[:3]]
        positive_labels = registry.get_confidence("ENGAGEMENT_POSITIVE_LABELS")
        negative_labels = registry.get_confidence("ENGAGEMENT_NEGATIVE_LABELS")
        if isinstance(positive_labels, set):
            positives = sum(1 for l in top_labels if l in positive_labels)
            negatives = sum(1 for l in top_labels if l in negative_labels)
            net = (positives - negatives) / max(len(top_labels), 1)
            score += int(net * weight)
    return score


def _generate_reasoning(score: int, intelligence: ConversationIntelligence, registry) -> list[str]:
    reasons = []
    strong_threshold = registry.get_confidence("HEALTH_STRONG_THRESHOLD")
    moderate_threshold = registry.get_confidence("HEALTH_MODERATE_THRESHOLD")
    attention_threshold = registry.get_confidence("HEALTH_ATTENTION_THRESHOLD")

    if score >= strong_threshold:
        reasons.append("Strong positive engagement signals.")
    elif score >= moderate_threshold:
        reasons.append("Moderate engagement — opportunity developing.")
    elif score >= attention_threshold:
        reasons.append("Conversation needs attention — potential risks.")
    else:
        reasons.append("Conversation at risk — intervene or re-engage.")

    if intelligence.buying_signals:
        strong = [s for s in intelligence.buying_signals
                  if s.strength in (SignalStrength.VERY_STRONG, SignalStrength.STRONG)]
        if strong:
            reasons.append(f"{len(strong)} strong buying signal(s) detected.")
        weak = [s for s in intelligence.buying_signals
                if s.strength in (SignalStrength.WEAK, SignalStrength.VERY_WEAK)]
        if weak and not strong:
            reasons.append("Weak buying signals — may need further qualification.")

    if intelligence.objections:
        high = [o for o in intelligence.objections if o.severity == ObjectionSeverity.HIGH]
        if high:
            reasons.append(
                f"High-severity objection(s): {', '.join(o.category.value for o in high)}."
            )

    return reasons
