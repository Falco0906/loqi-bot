from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4


PROMPT_BUILDER_VERSION = "1.0.0"
TEMPLATE_LIBRARY_VERSION = "1.0.0"
STYLE_ENGINE_VERSION = "1.0.0"
CONTEXT_BUILDER_VERSION = "1.0.0"
PIPELINE_VERSION = "1.0.0"
REASONING_VERSION = "1.0.0"


class GenerationStyle(str, Enum):
    PROFESSIONAL = "professional"
    FRIENDLY = "friendly"
    EXECUTIVE = "executive"
    TECHNICAL = "technical"
    CONSULTATIVE = "consultative"
    SHORT = "short"
    DETAILED = "detailed"
    PERSUASIVE = "persuasive"
    NEUTRAL = "neutral"


class GenerationTemplate(str, Enum):
    PRICING_RESPONSE = "pricing_response"
    DEMO_CONFIRMATION = "demo_confirmation"
    TECHNICAL_QUESTION = "technical_question"
    FOLLOW_UP = "follow_up"
    OBJECTION_HANDLING = "objection_handling"
    MEETING_SCHEDULING = "meeting_scheduling"
    GENERAL_REPLY = "general_reply"
    RE_ENGAGEMENT = "re_engagement"
    THANK_YOU = "thank_you"
    CLARIFICATION = "clarification"


class ValidationSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ValidationIssue:
    severity: ValidationSeverity
    code: str
    message: str
    field: str = ""


@dataclass
class GenerationContext:
    """Normalized context passed to providers. Never contains raw messages."""
    conversation_id: str = ""
    executive_summary: str = ""
    conversation_stage: str = ""
    primary_goal: str = ""
    alternative_goal: str = ""
    decision_type: str = ""
    decision_priority: str = ""
    decision_confidence: float = 0.0
    buying_signals: list[str] = field(default_factory=list)
    objections: list[dict] = field(default_factory=list)
    key_entities: list[str] = field(default_factory=list)
    memory_facts: list[str] = field(default_factory=list)
    latest_messages: list[str] = field(default_factory=list)
    style_name: str = ""
    template_name: str = ""
    policy_results: list[str] = field(default_factory=list)
    risk_level: str = ""
    health_score: int = 0
    target_action: str = ""


@dataclass
class ReplyDraft:
    content: str
    original_content: str = ""
    style: GenerationStyle = GenerationStyle.PROFESSIONAL
    variant_index: int = 0

    def __post_init__(self):
        if not self.original_content:
            self.original_content = self.content


@dataclass
class ReplyVariant:
    drafts: list[ReplyDraft]
    style: GenerationStyle


@dataclass
class GenerationMetadata:
    generation_id: str = field(default_factory=lambda: uuid4().hex[:12])
    provider: str = ""
    model: str = ""
    latency_ms: int = 0
    token_usage: dict = field(default_factory=dict)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    template_used: str = ""
    style_used: str = ""
    prompt_builder_version: str = PROMPT_BUILDER_VERSION
    template_library_version: str = TEMPLATE_LIBRARY_VERSION
    style_engine_version: str = STYLE_ENGINE_VERSION
    context_builder_version: str = CONTEXT_BUILDER_VERSION
    pipeline_version: str = PIPELINE_VERSION
    reasoning_version: str = REASONING_VERSION
    prompt_preview: str = ""


@dataclass
class GenerationResult:
    conversation_id: str = ""
    variants: list[ReplyVariant] = field(default_factory=list)
    metadata: GenerationMetadata = field(default_factory=GenerationMetadata)
    validation_results: list[ValidationIssue] = field(default_factory=list)
    timing: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "conversation_id": self.conversation_id,
            "variants": [
                {
                    "style": v.style.value,
                    "drafts": [
                        {
                            "content": d.content,
                            "original_content": d.original_content,
                            "style": d.style.value,
                            "variant_index": d.variant_index,
                        }
                        for d in v.drafts
                    ],
                }
                for v in self.variants
            ],
            "metadata": {
                "generation_id": self.metadata.generation_id,
                "provider": self.metadata.provider,
                "model": self.metadata.model,
                "latency_ms": self.metadata.latency_ms,
                "token_usage": self.metadata.token_usage,
                "generated_at": self.metadata.generated_at.isoformat(),
                "template_used": self.metadata.template_used,
                "style_used": self.metadata.style_used,
                "prompt_builder_version": self.metadata.prompt_builder_version,
                "template_library_version": self.metadata.template_library_version,
                "style_engine_version": self.metadata.style_engine_version,
                "context_builder_version": self.metadata.context_builder_version,
                "pipeline_version": self.metadata.pipeline_version,
                "reasoning_version": self.metadata.reasoning_version,
            },
            "validation_results": [
                {"severity": v.severity.value, "code": v.code, "message": v.message, "field": v.field}
                for v in self.validation_results
            ],
            "timing": self.timing,
        }
