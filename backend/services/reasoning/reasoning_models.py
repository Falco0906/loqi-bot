"""Unified reasoning models.

All reasoning components share these models.
Designed to be reusable by future planners, AI generators, and analytics.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class DecisionType(str, Enum):
    REPLY = "reply"
    WAIT = "wait"
    SCHEDULE_FOLLOW_UP = "schedule_follow_up"
    REQUEST_HUMAN_REVIEW = "request_human_review"
    ESCALATE = "escalate"
    BOOK_MEETING = "book_meeting"
    CLOSE_CONVERSATION = "close_conversation"
    STOP_OUTREACH = "stop_outreach"
    CONTINUE_NURTURING = "continue_nurturing"
    REQUEST_MORE_INFO = "request_more_information"


class DecisionPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class GoalType(str, Enum):
    BOOK_DEMO = "book_demo"
    PROVIDE_PRICING = "provide_pricing"
    QUALIFY_NEEDS = "qualify_needs"
    OVERCOME_OBJECTION = "overcome_objection"
    KEEP_ALIVE = "keep_alive"
    GATHER_INFO = "gather_information"
    CONFIRM_INTEREST = "confirm_interest"
    SCHEDULE_MEETING = "schedule_meeting"
    HANDOFF_TO_SALES = "handoff_to_sales"
    RE_ENGAGE = "re_engage"


class PolicyResult(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    REQUIRES_REVIEW = "requires_review"
    NOT_APPLICABLE = "not_applicable"


@dataclass
class GoalSelection:
    primary: GoalType
    alternative: Optional[GoalType] = None
    reasoning: list[str] = field(default_factory=list)


@dataclass
class PriorityAssessment:
    level: DecisionPriority
    score: int = 0
    max_score: int = 100
    factors: dict[str, int] = field(default_factory=dict)
    reasoning: list[str] = field(default_factory=list)


@dataclass
class RiskAssessment:
    level: RiskLevel
    score: int = 0
    max_score: int = 100
    factors: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    reasoning: list[str] = field(default_factory=list)


@dataclass
class ConfidenceAssessment:
    overall: float = 0.0
    intent_confidence: float = 0.0
    signal_confidence: float = 0.0
    objection_confidence: float = 0.0
    entity_confidence: float = 0.0
    completeness: float = 0.0
    breakdown: list[str] = field(default_factory=list)


@dataclass
class PolicyEvaluation:
    policy_name: str
    result: PolicyResult
    reasoning: str = ""


@dataclass
class ReasoningDecision:
    type: DecisionType
    priority: DecisionPriority = DecisionPriority.MEDIUM
    risk: RiskLevel = RiskLevel.LOW
    confidence: float = 0.0
    primary_goal: Optional[GoalType] = None
    alternative_goal: Optional[GoalType] = None
    evidence: list[str] = field(default_factory=list)
    reasoning: list[str] = field(default_factory=list)
    policy_results: list[PolicyEvaluation] = field(default_factory=list)


@dataclass
class ReasoningResult:
    conversation_id: str
    decision: ReasoningDecision
    goal: GoalSelection = field(default_factory=GoalSelection)
    priority: PriorityAssessment = field(default_factory=PriorityAssessment)
    risk: RiskAssessment = field(default_factory=RiskAssessment)
    confidence: ConfidenceAssessment = field(default_factory=ConfidenceAssessment)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    pipeline_version: str = "1.0.0"

    def to_dict(self) -> dict:
        return {
            "conversation_id": self.conversation_id,
            "decision": {
                "type": self.decision.type.value,
                "priority": self.decision.priority.value,
                "risk": self.decision.risk.value,
                "confidence": round(self.decision.confidence, 2),
                "primary_goal": self.decision.primary_goal.value if self.decision.primary_goal else None,
                "alternative_goal": self.decision.alternative_goal.value if self.decision.alternative_goal else None,
                "evidence": self.decision.evidence,
                "reasoning": self.decision.reasoning,
                "policy_results": [
                    {"policy": p.policy_name, "result": p.result.value, "reasoning": p.reasoning}
                    for p in self.decision.policy_results
                ],
            },
            "goal": {
                "primary": self.goal.primary.value,
                "alternative": self.goal.alternative.value if self.goal.alternative else None,
                "reasoning": self.goal.reasoning,
            },
            "priority": {
                "level": self.priority.level.value,
                "score": self.priority.score,
                "max_score": self.priority.max_score,
                "factors": self.priority.factors,
                "reasoning": self.priority.reasoning,
            },
            "risk": {
                "level": self.risk.level.value,
                "score": self.risk.score,
                "max_score": self.risk.max_score,
                "factors": self.risk.factors,
                "evidence": self.risk.evidence,
            },
            "confidence": {
                "overall": round(self.confidence.overall, 2),
                "intent_confidence": round(self.confidence.intent_confidence, 2),
                "signal_confidence": round(self.confidence.signal_confidence, 2),
                "objection_confidence": round(self.confidence.objection_confidence, 2),
                "entity_confidence": round(self.confidence.entity_confidence, 2),
                "completeness": round(self.confidence.completeness, 2),
                "breakdown": self.confidence.breakdown,
            },
            "created_at": self.created_at.isoformat(),
            "pipeline_version": self.pipeline_version,
        }
