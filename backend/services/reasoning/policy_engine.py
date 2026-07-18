"""Policy Engine — evaluates configurable reasoning policies.

Policies gate decisions based on confidence, risk, lead attributes, and conversation state.
Data-driven — no hardcoded company-specific behavior.
"""

from __future__ import annotations
from typing import Callable, Optional
from dataclasses import dataclass, field
from services.conversation_intelligence.intelligence_models import ConversationIntelligence
from services.reasoning.reasoning_models import (
    DecisionType, PolicyResult, PolicyEvaluation, RiskLevel, DecisionPriority,
)


@dataclass
class Policy:
    name: str
    evaluate: Callable[[ConversationIntelligence, dict], PolicyEvaluation]
    config: dict = field(default_factory=dict)


_POLICIES: list[Policy] = []


def register_policy(policy: Policy) -> None:
    """Register a new policy at runtime."""
    _POLICIES.append(policy)


def register_default_policies() -> None:
    """Register the default set of reasoning policies."""
    _POLICIES.clear()

    _POLICIES.append(Policy(
        name="require_review_first_reply",
        evaluate=_eval_first_reply_review,
        config={"enabled": True},
    ))

    _POLICIES.append(Policy(
        name="no_auto_close",
        evaluate=_eval_no_auto_close,
        config={"enabled": True},
    ))

    _POLICIES.append(Policy(
        name="confidence_threshold",
        evaluate=_eval_confidence_threshold,
        config={"enabled": True, "min_confidence": 0.75},
    ))

    _POLICIES.append(Policy(
        name="escalate_enterprise_signals",
        evaluate=_eval_enterprise_escalation,
        config={"enabled": True},
    ))

    _POLICIES.append(Policy(
        name="follow_up_health_threshold",
        evaluate=_eval_follow_up_health,
        config={"enabled": True, "min_health_score": 40},
    ))

    _POLICIES.append(Policy(
        name="require_review_high_risk",
        evaluate=_eval_high_risk_review,
        config={"enabled": True, "max_risk_score": 60},
    ))


def evaluate_policies(
    intelligence: ConversationIntelligence,
    decision_type: DecisionType,
    risk_level: RiskLevel,
    priority: DecisionPriority,
    confidence: float,
    context: Optional[dict] = None,
) -> list[PolicyEvaluation]:
    """Evaluate all registered policies against the current state."""
    if not _POLICIES:
        register_default_policies()

    state = {
        "decision_type": decision_type,
        "risk_level": risk_level,
        "priority": priority,
        "confidence": confidence,
        **(context or {}),
    }

    results: list[PolicyEvaluation] = []
    for policy in _POLICIES:
        try:
            result = policy.evaluate(intelligence, state)
            results.append(result)
        except Exception:
            results.append(PolicyEvaluation(
                policy_name=policy.name,
                result=PolicyResult.NOT_APPLICABLE,
                reasoning="Evaluation failed — skipped.",
            ))
    return results


def _eval_first_reply_review(intelligence: ConversationIntelligence, state: dict) -> PolicyEvaluation:
    is_first_reply = len(intelligence.memory) < 3
    if is_first_reply and state.get("decision_type") == DecisionType.REPLY:
        return PolicyEvaluation(
            policy_name="require_review_first_reply",
            result=PolicyResult.REQUIRES_REVIEW,
            reasoning="First reply requires human review.",
        )
    return PolicyEvaluation(
        policy_name="require_review_first_reply",
        result=PolicyResult.PASSED,
        reasoning="Not a first reply or not a reply action.",
    )


def _eval_no_auto_close(intelligence: ConversationIntelligence, state: dict) -> PolicyEvaluation:
    if state.get("decision_type") == DecisionType.CLOSE_CONVERSATION:
        return PolicyEvaluation(
            policy_name="no_auto_close",
            result=PolicyResult.REQUIRES_REVIEW,
            reasoning="Conversation closure requires human confirmation.",
        )
    return PolicyEvaluation(
        policy_name="no_auto_close",
        result=PolicyResult.PASSED,
        reasoning="Not a close action.",
    )


def _eval_confidence_threshold(intelligence: ConversationIntelligence, state: dict) -> PolicyEvaluation:
    min_conf = 0.75
    if state.get("confidence", 1.0) < min_conf:
        return PolicyEvaluation(
            policy_name="confidence_threshold",
            result=PolicyResult.REQUIRES_REVIEW,
            reasoning=f"Confidence {state.get('confidence', 0):.2f} below threshold {min_conf}.",
        )
    return PolicyEvaluation(
        policy_name="confidence_threshold",
        result=PolicyResult.PASSED,
        reasoning=f"Confidence {state.get('confidence', 0):.2f} meets threshold.",
    )


def _eval_enterprise_escalation(intelligence: ConversationIntelligence, state: dict) -> PolicyEvaluation:
    has_procurement = any(
        s.signal_type in ("mentioned_procurement", "mentioned_contract")
        for s in intelligence.buying_signals
    )
    has_enterprise = any(
        e.value.lower() in ("sap", "oracle", "ibm", "salesforce")
        for e in intelligence.entities
        if e.entity_type.value == "technology"
    )
    if has_procurement or has_enterprise:
        return PolicyEvaluation(
            policy_name="escalate_enterprise_signals",
            result=PolicyResult.REQUIRES_REVIEW,
            reasoning="Enterprise signals detected — escalation recommended.",
        )
    return PolicyEvaluation(
        policy_name="escalate_enterprise_signals",
        result=PolicyResult.PASSED,
        reasoning="No enterprise signals detected.",
    )


def _eval_follow_up_health(intelligence: ConversationIntelligence, state: dict) -> PolicyEvaluation:
    if state.get("decision_type") != DecisionType.SCHEDULE_FOLLOW_UP:
        return PolicyEvaluation(
            policy_name="follow_up_health_threshold",
            result=PolicyResult.NOT_APPLICABLE,
            reasoning="Not a follow-up decision.",
        )
    min_health = 40
    health_score = intelligence.health.score if intelligence.health else 0
    if health_score < min_health:
        return PolicyEvaluation(
            policy_name="follow_up_health_threshold",
            result=PolicyResult.FAILED,
            reasoning=f"Health score {health_score} below minimum {min_health}.",
        )
    return PolicyEvaluation(
        policy_name="follow_up_health_threshold",
        result=PolicyResult.PASSED,
        reasoning=f"Health score {health_score} meets threshold.",
    )


def _eval_high_risk_review(intelligence: ConversationIntelligence, state: dict) -> PolicyEvaluation:
    if state.get("risk_level") == RiskLevel.HIGH:
        return PolicyEvaluation(
            policy_name="require_review_high_risk",
            result=PolicyResult.REQUIRES_REVIEW,
            reasoning="High-risk conversation requires human review.",
        )
    return PolicyEvaluation(
        policy_name="require_review_high_risk",
        result=PolicyResult.PASSED,
        reasoning="Risk level acceptable.",
    )
