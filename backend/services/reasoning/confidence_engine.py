"""Confidence Engine — calculates reasoning confidence from intelligence signals.

Produces an overall 0-1 confidence score with per-component breakdown.
Every component explains why confidence is high or low.
"""

from __future__ import annotations
from services.conversation_intelligence.intelligence_models import ConversationIntelligence
from services.reasoning.reasoning_models import ConfidenceAssessment


def assess_confidence(intelligence: ConversationIntelligence) -> ConfidenceAssessment:
    """Calculate reasoning confidence from all available intelligence signals."""
    intent_conf = _intent_confidence(intelligence)
    signal_conf = _signal_confidence(intelligence)
    objection_conf = _objection_confidence(intelligence)
    entity_conf = _entity_confidence(intelligence)
    completeness = _completeness_score(intelligence)

    weights = {"intent": 0.30, "signal": 0.25, "objection": 0.15, "entity": 0.10, "completeness": 0.20}
    overall = (
        intent_conf * weights["intent"]
        + signal_conf * weights["signal"]
        + objection_conf * weights["objection"]
        + entity_conf * weights["entity"]
        + completeness * weights["completeness"]
    )

    breakdown = _build_breakdown(intent_conf, signal_conf, objection_conf, entity_conf, completeness)

    return ConfidenceAssessment(
        overall=round(overall, 2),
        intent_confidence=round(intent_conf, 2),
        signal_confidence=round(signal_conf, 2),
        objection_confidence=round(objection_conf, 2),
        entity_confidence=round(entity_conf, 2),
        completeness=round(completeness, 2),
        breakdown=breakdown,
    )


def _intent_confidence(intelligence: ConversationIntelligence) -> float:
    if not intelligence.intents:
        return 0.0
    confidences = [i.confidence for i in intelligence.intents[:3]]
    avg = sum(confidences) / len(confidences)
    return min(avg, 1.0)


def _signal_confidence(intelligence: ConversationIntelligence) -> float:
    if not intelligence.buying_signals:
        return 0.0
    confidences = [s.confidence for s in intelligence.buying_signals[:3]]
    avg = sum(confidences) / len(confidences)
    return min(avg, 1.0)


def _objection_confidence(intelligence: ConversationIntelligence) -> float:
    if not intelligence.objections:
        return 0.8
    confidences = [o.confidence for o in intelligence.objections[:3]]
    avg = sum(confidences) / len(confidences)
    return 1.0 - min(avg, 0.8)


def _entity_confidence(intelligence: ConversationIntelligence) -> float:
    if not intelligence.entities:
        return 0.0
    confidences = [e.confidence for e in intelligence.entities[:5]]
    avg = sum(confidences) / len(confidences)
    return min(avg, 1.0)


def _completeness_score(intelligence: ConversationIntelligence) -> float:
    score = 0.0
    total_checks = 6

    if intelligence.intents:
        score += 1.0
    if intelligence.buying_signals:
        score += 1.0
    if intelligence.entities:
        score += 1.0
    if intelligence.objections is not None:
        score += 1.0
    if intelligence.health:
        score += 1.0
    if intelligence.summaries:
        score += 1.0

    return score / total_checks


def _build_breakdown(
    intent_conf: float, signal_conf: float,
    objection_conf: float, entity_conf: float,
    completeness: float,
) -> list[str]:
    reasons = []
    if intent_conf >= 0.7:
        reasons.append(f"Intent confidence high ({intent_conf:.2f}) — clear prospect intent detected.")
    elif intent_conf >= 0.4:
        reasons.append(f"Intent confidence moderate ({intent_conf:.2f}) — some ambiguity.")
    else:
        reasons.append(f"Intent confidence low ({intent_conf:.2f}) — insufficient signal.")

    if signal_conf >= 0.7:
        reasons.append(f"Buying signal confidence high ({signal_conf:.2f}).")
    elif signal_conf > 0:
        reasons.append(f"Buying signal confidence moderate ({signal_conf:.2f}).")
    else:
        reasons.append("No buying signals detected — confidence reduced.")

    if entity_conf >= 0.5:
        reasons.append(f"Entity extraction confidence acceptable ({entity_conf:.2f}).")
    else:
        reasons.append(f"Limited entity extraction ({entity_conf:.2f}) — context may be incomplete.")

    if completeness >= 0.8:
        reasons.append("All intelligence dimensions populated.")
    elif completeness >= 0.5:
        reasons.append("Partial intelligence — some dimensions missing.")
    else:
        reasons.append("Limited intelligence data — reasoning confidence reduced.")

    return reasons
