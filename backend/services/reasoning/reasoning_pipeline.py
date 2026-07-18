"""Reasoning Pipeline — orchestrates all reasoning stages.

Pipeline:
  Conversation Intelligence
  → Goal Selection
  → Priority Assessment
  → Risk Assessment
  → Confidence Assessment
  → Policy Evaluation
  → Decision Synthesis
  → Reasoning Result

Each stage is independently testable.
Failures in one stage do not block others.
"""

from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Optional

from services.conversation_intelligence.intelligence_models import ConversationIntelligence
from services.reasoning.reasoning_models import (
    DecisionType, DecisionPriority, RiskLevel,
    GoalSelection, PriorityAssessment, RiskAssessment,
    ConfidenceAssessment, PolicyEvaluation, PolicyResult,
    ReasoningDecision, ReasoningResult,
)
from services.reasoning.goal_selector import select_goals
from services.reasoning.priority_engine import assess_priority
from services.reasoning.risk_assessor import assess_risk
from services.reasoning.confidence_engine import assess_confidence
from services.reasoning.policy_engine import evaluate_policies, register_default_policies


logger = logging.getLogger(__name__)


class ReasoningPipeline:
    """Full-stack reasoning pipeline.

    Usage:
        pipeline = ReasoningPipeline()
        result = pipeline.reason(intelligence)
        print(result.decision.type.value)
        print(result.decision.reasoning)
    """

    def __init__(self):
        register_default_policies()

    def reason(
        self,
        intelligence: ConversationIntelligence,
        context: Optional[dict] = None,
    ) -> ReasoningResult:
        """Run full reasoning pipeline on conversation intelligence."""
        conversation_id = intelligence.conversation_id

        # Phase 1: Goal Selection
        goal = GoalSelection(primary=DecisionType.REPLY)
        try:
            goal = select_goals(intelligence)
        except Exception as e:
            logger.error("Goal selection failed: %s", e)

        # Phase 2: Priority Assessment
        priority = PriorityAssessment(level=DecisionPriority.MEDIUM)
        try:
            priority = assess_priority(intelligence)
        except Exception as e:
            logger.error("Priority assessment failed: %s", e)

        # Phase 3: Risk Assessment
        risk = RiskAssessment(level=RiskLevel.LOW)
        try:
            risk = assess_risk(intelligence)
        except Exception as e:
            logger.error("Risk assessment failed: %s", e)

        # Phase 4: Confidence Assessment
        confidence = ConfidenceAssessment()
        try:
            confidence = assess_confidence(intelligence)
        except Exception as e:
            logger.error("Confidence assessment failed: %s", e)

        # Phase 5: Decision Synthesis
        decision = self._synthesize_decision(
            intelligence, goal, priority, risk, confidence,
        )

        # Phase 6: Policy Evaluation
        policy_results: list[PolicyEvaluation] = []
        try:
            policy_results = evaluate_policies(
                intelligence=intelligence,
                decision_type=decision.type,
                risk_level=risk.level,
                priority=priority.level,
                confidence=confidence.overall,
                context=context,
            )
            decision.policy_results = policy_results
        except Exception as e:
            logger.error("Policy evaluation failed: %s", e)

        # Apply policy results to decision
        decision = self._apply_policies(decision, policy_results)

        return ReasoningResult(
            conversation_id=conversation_id,
            decision=decision,
            goal=goal,
            priority=priority,
            risk=risk,
            confidence=confidence,
            created_at=datetime.now(timezone.utc),
            pipeline_version="1.0.0",
        )

    def _synthesize_decision(
        self,
        intelligence: ConversationIntelligence,
        goal: GoalSelection,
        priority: PriorityAssessment,
        risk: RiskAssessment,
        confidence: ConfidenceAssessment,
    ) -> ReasoningDecision:
        """Synthesize a decision from all reasoning stages."""
        decision_type = self._choose_decision_type(intelligence, goal, priority, risk)
        evidence = self._collect_evidence(intelligence, goal, risk)
        reasoning = self._build_reasoning(decision_type, goal, priority, risk, confidence, intelligence)

        return ReasoningDecision(
            type=decision_type,
            priority=priority.level,
            risk=risk.level,
            confidence=confidence.overall,
            primary_goal=goal.primary,
            alternative_goal=goal.alternative,
            evidence=evidence,
            reasoning=reasoning,
        )

    def _choose_decision_type(
        self,
        intelligence: ConversationIntelligence,
        goal: GoalSelection,
        priority: PriorityAssessment,
        risk: RiskAssessment,
    ) -> DecisionType:
        """Choose the best decision type based on all signals."""
        goal_str = goal.primary.value

        if goal_str == "book_demo":
            return DecisionType.BOOK_MEETING
        if goal_str == "schedule_meeting":
            return DecisionType.BOOK_MEETING
        if goal_str == "provide_pricing":
            return DecisionType.REPLY
        if goal_str == "overcome_objection":
            return DecisionType.REPLY
        if goal_str == "confirm_interest":
            return DecisionType.REPLY
        if goal_str == "gather_information":
            return DecisionType.REQUEST_MORE_INFO
        if goal_str == "re_engage":
            return DecisionType.SCHEDULE_FOLLOW_UP
        if goal_str == "keep_alive":
            return DecisionType.WAIT

        if priority.level in (DecisionPriority.CRITICAL, DecisionPriority.HIGH):
            return DecisionType.REPLY
        if risk.level == RiskLevel.HIGH:
            return DecisionType.REQUEST_HUMAN_REVIEW

        return DecisionType.WAIT

    def _collect_evidence(
        self,
        intelligence: ConversationIntelligence,
        goal: GoalSelection,
        risk: RiskAssessment,
    ) -> list[str]:
        evidence = []
        if intelligence.intents:
            top_intent = intelligence.intents[0]
            evidence.append(f"Intent: {top_intent.label.value} ({top_intent.confidence:.2f})")
        if intelligence.buying_signals:
            top_signal = intelligence.buying_signals[0]
            evidence.append(f"Buying signal: {top_signal.signal_type} ({top_signal.strength.value})")
        if intelligence.objections:
            top_obj = intelligence.objections[0]
            evidence.append(f"Objection: {top_obj.category.value} ({top_obj.severity.value})")
        if intelligence.health:
            evidence.append(f"Health: {intelligence.health.score}/{intelligence.health.max_score}")
        evidence.append(f"Goal: {goal.primary.value}")
        if risk.evidence:
            evidence.extend(risk.evidence[:2])
        return evidence

    def _build_reasoning(
        self,
        decision_type: DecisionType,
        goal: GoalSelection,
        priority: PriorityAssessment,
        risk: RiskAssessment,
        confidence: ConfidenceAssessment,
        intelligence: ConversationIntelligence,
    ) -> list[str]:
        reasons = [f"Decision: {decision_type.value}."]
        if goal.reasoning:
            reasons.extend(goal.reasoning[:2])
        if priority.reasoning:
            reasons.extend(priority.reasoning[:2])
        if risk.reasoning:
            reasons.extend(risk.reasoning[:2])
        if confidence.breakdown:
            reasons.extend(confidence.breakdown[:2])
        return reasons

    def _apply_policies(
        self,
        decision: ReasoningDecision,
        policy_results: list[PolicyEvaluation],
    ) -> ReasoningDecision:
        """Apply policy results to the decision — override if policies require human review."""
        requires_review = any(
            p.result == PolicyResult.REQUIRES_REVIEW for p in policy_results
        )
        failed = any(p.result == PolicyResult.FAILED for p in policy_results)

        if requires_review or failed:
            decision.type = DecisionType.REQUEST_HUMAN_REVIEW
            decision.reasoning.append(
                "Policy override: human review required before proceeding."
            )
        return decision


# Module-level convenience
_default_pipeline: Optional[ReasoningPipeline] = None


def get_pipeline() -> ReasoningPipeline:
    """Get the shared ReasoningPipeline instance."""
    global _default_pipeline
    if _default_pipeline is None:
        _default_pipeline = ReasoningPipeline()
    return _default_pipeline
