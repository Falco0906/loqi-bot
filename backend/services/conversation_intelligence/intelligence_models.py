"""Enhanced intelligence models for conversation understanding.

Extends the existing models in conversation_models.py with
entity extraction, objection analysis, health scoring, and multi-summary support.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class IntentLabel(str, Enum):
    INTERESTED = "interested"
    INFORMATION_REQUEST = "information_request"
    PRICING_DISCUSSION = "pricing_discussion"
    DEMO_REQUEST = "demo_request"
    TECHNICAL_QUESTION = "technical_question"
    PROCUREMENT = "procurement"
    REFERRAL = "referral"
    BUDGET_DISCUSSION = "budget_discussion"
    TIMELINE_DISCUSSION = "timeline_discussion"
    OBJECTION = "objection"
    MEETING_REQUEST = "meeting_request"
    NOT_INTERESTED = "not_interested"
    FOLLOW_UP = "follow_up"
    CONFIRMATION = "confirmation"
    UNKNOWN = "unknown"


class ObjectionCategory(str, Enum):
    PRICE = "price"
    TIMING = "timing"
    FEATURE_GAP = "feature_gap"
    COMPETITION = "competition"
    SECURITY = "security"
    COMPLIANCE = "compliance"
    INTERNAL_APPROVAL = "internal_approval"
    BUDGET = "budget"
    EXISTING_VENDOR = "existing_vendor"
    IMPLEMENTATION = "implementation"
    UNKNOWN = "unknown"


class ObjectionSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SignalStrength(str, Enum):
    VERY_STRONG = "very_strong"
    STRONG = "strong"
    MEDIUM = "medium"
    WEAK = "weak"
    VERY_WEAK = "very_weak"


class EntityType(str, Enum):
    PERSON = "person"
    COMPANY = "company"
    COMPETITOR = "competitor"
    BUDGET = "budget"
    TIMELINE = "timeline"
    PRODUCT = "product"
    MEETING_DATE = "meeting_date"
    DECISION_MAKER = "decision_maker"
    DEPARTMENT = "department"
    COUNTRY = "country"
    TECHNOLOGY = "technology"
    ROLE = "role"


class SummaryLevel(str, Enum):
    SHORT = "short"
    MEDIUM = "medium"
    EXECUTIVE = "executive"
    ACTION = "action"


@dataclass
class IntentResult:
    label: IntentLabel
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)
    source: str = "rule"
    raw_text: str = ""


@dataclass
class EntityResult:
    entity_type: EntityType
    value: str
    normalized_value: str = ""
    confidence: float = 0.0
    source_text: str = ""
    position: tuple[int, int] = (0, 0)


@dataclass
class ObjectionResult:
    category: ObjectionCategory
    severity: ObjectionSeverity = ObjectionSeverity.MEDIUM
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)
    source: str = "rule"


@dataclass
class BuyingSignalResult:
    signal_type: str = ""
    strength: SignalStrength = SignalStrength.WEAK
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)
    timestamp: Optional[datetime] = None


@dataclass
class ConversationMemoryEntry:
    entity_type: EntityType
    key: str
    value: str
    confidence: float = 0.0
    updated_at: Optional[datetime] = None
    source_message_id: str = ""


@dataclass
class ConversationSummaryResult:
    level: SummaryLevel
    content: str
    generated_at: Optional[datetime] = None


@dataclass
class HealthScoreResult:
    score: int = 0
    max_score: int = 100
    reasoning: list[str] = field(default_factory=list)
    components: dict[str, float] = field(default_factory=dict)


@dataclass
class ConversationIntelligence:
    """Top-level container for all intelligence extracted from a conversation."""

    conversation_id: str = ""
    intents: list[IntentResult] = field(default_factory=list)
    entities: list[EntityResult] = field(default_factory=list)
    buying_signals: list[BuyingSignalResult] = field(default_factory=list)
    objections: list[ObjectionResult] = field(default_factory=list)
    memory: list[ConversationMemoryEntry] = field(default_factory=list)
    summaries: list[ConversationSummaryResult] = field(default_factory=list)
    health: Optional[HealthScoreResult] = None
    analyzed_at: Optional[datetime] = None
    pipeline_version: str = "1.0"

    def to_dict(self) -> dict:
        return {
            "conversation_id": self.conversation_id,
            "intents": [{"label": i.label.value, "confidence": i.confidence, "evidence": i.evidence, "source": i.source} for i in self.intents],
            "entities": [{"entity_type": e.entity_type.value, "value": e.value, "normalized_value": e.normalized_value, "confidence": e.confidence} for e in self.entities],
            "buying_signals": [{"signal_type": s.signal_type, "strength": s.strength.value, "confidence": s.confidence, "evidence": s.evidence} for s in self.buying_signals],
            "objections": [{"category": o.category.value, "severity": o.severity.value, "confidence": o.confidence, "evidence": o.evidence} for o in self.objections],
            "memory": [{"key": m.key, "value": m.value, "entity_type": m.entity_type.value, "confidence": m.confidence} for m in self.memory],
            "summaries": [{"level": s.level.value, "content": s.content} for s in self.summaries],
            "health": {"score": self.health.score, "max_score": self.health.max_score, "reasoning": self.health.reasoning, "components": self.health.components} if self.health else None,
            "analyzed_at": self.analyzed_at.isoformat() if self.analyzed_at else "",
            "pipeline_version": self.pipeline_version,
        }
