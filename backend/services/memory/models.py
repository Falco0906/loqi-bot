from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class MemoryType(str, Enum):
    ACCOUNT = "account"
    CONTACT = "contact"
    CONVERSATION = "conversation"
    MEETING = "meeting"
    OPPORTUNITY = "opportunity"
    DECISION = "decision"
    PREFERENCE = "preference"
    OUTCOME = "outcome"


@dataclass
class MemoryRelationship:
    target_id: str = ""
    relationship_type: str = ""


@dataclass
class Memory:
    id: str = ""
    memory_type: MemoryType = MemoryType.CONTACT
    source: str = ""
    confidence: float = 0.5
    tags: list[str] = field(default_factory=list)
    embedding_ref: str = ""
    relationships: list[MemoryRelationship] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AccountMemory(Memory):
    company_id: str = ""
    company_name: str = ""
    industry: str = ""
    account_tier: str = ""
    buying_intent: str = ""
    key_contacts: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.memory_type = MemoryType.ACCOUNT


@dataclass
class ContactMemory(Memory):
    contact_id: str = ""
    email: str = ""
    name: str = ""
    title: str = ""
    decision_authority: str = ""
    relevance_score: str = ""
    communication_history: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.memory_type = MemoryType.CONTACT


@dataclass
class ConversationMemory(Memory):
    conversation_id: str = ""
    summary: str = ""
    intents: list[str] = field(default_factory=list)
    objections: list[str] = field(default_factory=list)
    outcome: str = ""

    def __post_init__(self):
        self.memory_type = MemoryType.CONVERSATION


@dataclass
class MeetingMemory(Memory):
    event_id: str = ""
    summary: str = ""
    attendees: list[str] = field(default_factory=list)
    notes: str = ""
    outcome: str = ""

    def __post_init__(self):
        self.memory_type = MemoryType.MEETING


@dataclass
class OpportunityMemory(Memory):
    opportunity_id: str = ""
    company_id: str = ""
    stage: str = ""
    amount: float = 0.0
    close_reason: str = ""

    def __post_init__(self):
        self.memory_type = MemoryType.OPPORTUNITY


@dataclass
class DecisionMemory(Memory):
    context: str = ""
    options: list[str] = field(default_factory=list)
    choice: str = ""
    rationale: str = ""

    def __post_init__(self):
        self.memory_type = MemoryType.DECISION


@dataclass
class PreferenceMemory(Memory):
    entity_type: str = ""
    entity_id: str = ""
    preference_key: str = ""
    preference_value: str = ""

    def __post_init__(self):
        self.memory_type = MemoryType.PREFERENCE


@dataclass
class OutcomeMemory(Memory):
    action_type: str = ""
    result: str = ""
    details: str = ""

    def __post_init__(self):
        self.memory_type = MemoryType.OUTCOME


@dataclass
class MemorySearch:
    query: str = ""
    memory_type: MemoryType | None = None
    tags: list[str] = field(default_factory=list)
    entity_id: str = ""
    source: str = ""
    from_timestamp: datetime | None = None
    to_timestamp: datetime | None = None
    limit: int = 10
    offset: int = 0


@dataclass
class MemorySearchResult:
    memories: list[Memory] = field(default_factory=list)
    total: int = 0
    search: MemorySearch = field(default_factory=MemorySearch)


@dataclass
class MemoryEvidence:
    memory_id: str = ""
    memory_type: MemoryType = MemoryType.CONTACT
    summary: str = ""
    relevance_score: float = 0.0
    excerpt: str = ""


@dataclass
class MemoryCitation:
    memory_ids: list[str] = field(default_factory=list)
    evidence: list[MemoryEvidence] = field(default_factory=list)
    explanation: str = ""
