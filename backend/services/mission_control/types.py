from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class IntentionCard(BaseModel):
    id: str
    title: str
    summary: str
    priority: str
    confidence: float
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    recommended_action: str = ""
    related_campaign: str | None = None
    related_lead: str | None = None
    reason_code: str = ""


class BriefingSection(BaseModel):
    greeting: str = ""
    lines: list[str] = Field(default_factory=list)
    suggestion: str = ""
    overall_summary: str = ""
    primary_focus: str = ""
    top_recommendation: str = ""


class HealthSummary(BaseModel):
    overall_health: str = "unknown"
    pipeline_velocity: str = "unknown"
    bottlenecks: list[str] = Field(default_factory=list)
    provider_health: list[dict[str, Any]] = Field(default_factory=list)
    confidence_score: float = 0.0
    campaigns_ready: int = 0
    campaigns_waiting: int = 0
    draft_backlog: int = 0
    details: dict[str, Any] = Field(default_factory=dict)


class TimelineEvent(BaseModel):
    id: str = ""
    timestamp: str = ""
    type: str = ""
    description: str = ""
    category: str = ""
    actor: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class BriefingResponse(BaseModel):
    ok: bool = True
    briefing: BriefingSection = Field(default_factory=BriefingSection)
    top_priorities: list[IntentionCard] = Field(default_factory=list)
    waiting_on_you: list[IntentionCard] = Field(default_factory=list)
    loqi_handled: list[IntentionCard] = Field(default_factory=list)
    upcoming: list[IntentionCard] = Field(default_factory=list)
    workspace_health: HealthSummary = Field(default_factory=HealthSummary)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    all_intentions: list[IntentionCard] = Field(default_factory=list)
