"""Risk Assessor — evaluates conversation risk from intelligence signals.

Factors: objections, health, buying signals, decision-maker involvement, sentiment.
Returns a RiskAssessment with level, numeric score, factors, and supporting evidence.
"""

from __future__ import annotations
from services.conversation_intelligence.intelligence_models import (
    ConversationIntelligence, ObjectionSeverity, EntityType,
)
from services.reasoning.reasoning_models import RiskLevel, RiskAssessment


def assess_risk(intelligence: ConversationIntelligence) -> RiskAssessment:
    """Assess conversation risk level from intelligence."""
    factors: list[str] = []
    evidence: list[str] = []
    score = 0

    objection_risk = _evaluate_objections(intelligence)
    score += objection_risk.score
    if objection_risk.factors:
        factors.extend(objection_risk.factors)
    if objection_risk.evidence:
        evidence.extend(objection_risk.evidence)

    health_risk = _evaluate_health(intelligence)
    score += health_risk.score
    if health_risk.factors:
        factors.extend(health_risk.factors)

    signal_risk = _evaluate_signals(intelligence)
    score += signal_risk.score
    if signal_risk.evidence:
        evidence.extend(signal_risk.evidence)

    dm_risk = _evaluate_decision_makers(intelligence)
    score += dm_risk.score
    if dm_risk.factors:
        factors.extend(dm_risk.factors)

    score = max(0, min(100, score))
    level = _map_level(score)
    reasoning = _build_reasoning(level, score, factors, evidence)

    reasoning = _build_reasoning(level, score, factors, evidence)

    return RiskAssessment(
        level=level,
        score=score,
        max_score=100,
        factors=factors,
        evidence=evidence,
        reasoning=reasoning,
    )


def _evaluate_objections(intelligence: ConversationIntelligence) -> RiskAssessment:
    factors = []
    evidence = []
    score = 0
    for o in intelligence.objections:
        if o.severity == ObjectionSeverity.HIGH:
            score += 20
            factors.append(f"High-severity objection: {o.category.value}")
            evidence.extend(o.evidence[:2])
        elif o.severity == ObjectionSeverity.MEDIUM:
            score += 10
            factors.append(f"Medium-severity objection: {o.category.value}")
    if len(intelligence.objections) >= 3:
        score += 10
        factors.append("Multiple unresolved objections")
    return RiskAssessment(level=RiskLevel.LOW, score=score, factors=factors, evidence=evidence)


def _evaluate_health(intelligence: ConversationIntelligence) -> RiskAssessment:
    factors = []
    score = 0
    if intelligence.health:
        if intelligence.health.score < 30:
            score += 25
            factors.append("Critically low conversation health")
        elif intelligence.health.score < 50:
            score += 15
            factors.append("Below-average conversation health")
        if intelligence.health.reasoning:
            for r in intelligence.health.reasoning:
                if "risk" in r.lower() or "intervene" in r.lower():
                    score += 10
                    factors.append(r)
    return RiskAssessment(level=RiskLevel.LOW, score=score, factors=factors)


def _evaluate_signals(intelligence: ConversationIntelligence) -> RiskAssessment:
    evidence = []
    score = 0
    for s in intelligence.buying_signals:
        if s.signal_type in ("mentioned_contract", "mentioned_procurement", "mentioned_rollout"):
            score -= 10
        if s.signal_type == "mentioned_current_vendor":
            score += 5
            evidence.append("Current vendor relationship — potential switching cost")
    return RiskAssessment(level=RiskLevel.LOW, score=score, evidence=evidence)


def _evaluate_decision_makers(intelligence: ConversationIntelligence) -> RiskAssessment:
    factors = []
    score = 0
    has_dm = any(e.entity_type == EntityType.DECISION_MAKER for e in intelligence.entities)
    has_role = any(e.entity_type == EntityType.ROLE for e in intelligence.entities)
    if not has_dm and not has_role:
        score += 10
        factors.append("No decision-maker identified")
    else:
        score -= 5
    return RiskAssessment(level=RiskLevel.LOW, score=score, factors=factors)


def _map_level(score: int) -> RiskLevel:
    if score >= 50:
        return RiskLevel.HIGH
    if score >= 25:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _build_reasoning(
    level: RiskLevel, score: int,
    factors: list[str], evidence: list[str],
) -> list[str]:
    reasons = [f"Risk level: {level.value} (score: {score}/100)."]
    if factors:
        reasons.append(f"Risk factors: {'; '.join(factors[:3])}.")
    if evidence:
        reasons.append(f"Supporting evidence: {'; '.join(evidence[:3])}.")
    return reasons
