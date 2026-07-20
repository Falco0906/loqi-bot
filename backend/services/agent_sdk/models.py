from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class AgentType(str, Enum):
    RESEARCH = "research"
    OUTREACH = "outreach"
    CRM = "crm"
    SCHEDULING = "scheduling"
    MEMORY = "memory"


@dataclass
class AgentResult:
    success: bool = True
    agent_type: AgentType = AgentType.RESEARCH
    data: dict[str, Any] = field(default_factory=dict)
    memory_ids: list[str] = field(default_factory=list)
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentContext:
    goal: str = ""
    entity_id: str = ""
    user_id: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# --- Shared structured context types ---

@dataclass
class ResearchReport:
    company_name: str = ""
    company_domain: str = ""
    industry: str = ""
    company_size: str = ""
    account_tier: str = ""
    buying_intent: str = ""
    icp_match_score: float = 0.0
    competitors: list[str] = field(default_factory=list)
    recent_news: list[str] = field(default_factory=list)
    buying_signals: list[str] = field(default_factory=list)
    key_contacts: list[dict] = field(default_factory=list)
    summary: str = ""


@dataclass
class CRMState:
    has_company: bool = False
    company_id: str = ""
    has_contact: bool = False
    contact_id: str = ""
    contact_name: str = ""
    contact_email: str = ""
    contact_title: str = ""
    has_opportunity: bool = False
    opportunity_id: str = ""
    opportunity_stage: str = ""
    opportunity_amount: float = 0.0
    pipeline: str = ""
    recent_activities: list[dict] = field(default_factory=list)


@dataclass
class MemoryContext:
    relevant_memories: list[dict] = field(default_factory=list)
    previous_objections: list[str] = field(default_factory=list)
    previous_outcomes: list[str] = field(default_factory=list)
    preferences: dict[str, str] = field(default_factory=dict)
    meeting_history: list[dict] = field(default_factory=list)
    decision_history: list[dict] = field(default_factory=list)
    memory_citation: str = ""


@dataclass
class CommunicationContext:
    suggested_channel: str = "email"
    message_template: str = ""
    personalization_hints: dict[str, str] = field(default_factory=dict)
    follow_up_suggestions: list[str] = field(default_factory=list)
    objection_strategy: str = ""
    requires_approval: bool = False
    priority: str = "medium"


@dataclass
class AccountContext:
    company_name: str = ""
    company_domain: str = ""
    industry: str = ""
    company_size: str = ""
    account_tier: str = ""
    buying_intent: str = ""
    icp_match: float = 0.0
    existing_contacts: list[ContactContext] = field(default_factory=list)
    open_opportunities: list[OpportunityContext] = field(default_factory=list)


@dataclass
class ContactContext:
    name: str = ""
    email: str = ""
    title: str = ""
    decision_authority: str = ""
    relevance_score: str = ""
    phone: str = ""


@dataclass
class OpportunityContext:
    id: str = ""
    name: str = ""
    stage: str = ""
    amount: float = 0.0
    pipeline: str = ""
    probability: int = 0


@dataclass
class SchedulingContext:
    suggested_date: str = ""
    suggested_time: str = ""
    duration_minutes: int = 30
    timezone: str = "UTC"
    attendees: list[str] = field(default_factory=list)
    requires_coordination: bool = False
