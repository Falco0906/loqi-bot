from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ProviderContactRole(str, Enum):
    DECISION_MAKER = "decision_maker"
    INFLUENCER = "influencer"
    EVALUATOR = "evaluator"
    CHAMPION = "champion"
    UNKNOWN = "unknown"


@dataclass
class ProviderContact:
    first_name: str
    last_name: str
    title: str
    email: str
    linkedin_url: str = ""
    phone: str = ""
    department: str = ""
    role: ProviderContactRole = ProviderContactRole.UNKNOWN
    buying_authority: int = 0
    provider_id: str = ""
    external_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def to_dict(self) -> dict[str, Any]:
        return {
            "first_name": self.first_name,
            "last_name": self.last_name,
            "name": self.name,
            "title": self.title,
            "email": self.email,
            "linkedin_url": self.linkedin_url,
            "phone": self.phone,
            "department": self.department,
            "role": self.role.value,
            "buying_authority": self.buying_authority,
            "provider_id": self.provider_id,
            "external_id": self.external_id,
        }


class CompanySize(str, Enum):
    SMALL = "small"
    MID = "mid"
    ENTERPRISE = "enterprise"


class GrowthStage(str, Enum):
    STARTUP = "startup"
    SERIES_A = "series_a"
    SERIES_B = "series_b"
    SERIES_C = "series_c"
    PUBLIC = "public"
    BOOTSTRAPPED = "bootstrapped"
    UNKNOWN = "unknown"


@dataclass
class ProviderCompany:
    name: str
    industry: str = ""
    sub_industry: str = ""
    description: str = ""
    website: str = ""
    city: str = ""
    country: str = ""
    employees: int = 0
    locations: int = 0
    founded: int = 0
    growth_stage: str = ""
    revenue_band: str = ""
    technologies: list[str] = field(default_factory=list)
    pain_points: list[str] = field(default_factory=list)
    buying_signals: list[str] = field(default_factory=list)
    recent_events: list[str] = field(default_factory=list)
    linkedin_url: str = ""
    provider_id: str = ""
    external_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def company_size(self) -> CompanySize:
        if self.employees <= 50:
            return CompanySize.SMALL
        elif self.employees <= 500:
            return CompanySize.MID
        return CompanySize.ENTERPRISE

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "industry": self.industry,
            "sub_industry": self.sub_industry,
            "description": self.description,
            "website": self.website,
            "city": self.city,
            "country": self.country,
            "employees": self.employees,
            "locations": self.locations,
            "founded": self.founded,
            "growth_stage": self.growth_stage,
            "revenue_band": self.revenue_band,
            "technologies": self.technologies,
            "pain_points": self.pain_points,
            "buying_signals": self.buying_signals,
            "recent_events": self.recent_events,
            "linkedin_url": self.linkedin_url,
            "provider_id": self.provider_id,
            "external_id": self.external_id,
        }


@dataclass
class ProviderLead:
    contact: ProviderContact
    company: ProviderCompany
    score: float = 0.0
    provider_id: str = ""
    external_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = self.contact.to_dict()
        d.update({f"company_{k}": v for k, v in self.company.to_dict().items()})
        d["lead_id"] = self.external_id or self.contact.external_id
        d["provider"] = self.provider_id
        d["score"] = self.score
        return d


class ConversationStage(str, Enum):
    INITIAL = "initial"
    ENGAGED = "engaged"
    NEGOTIATION = "negotiation"
    CLOSED_WON = "closed_won"
    CLOSED_LOST = "closed_lost"
    CHURNED = "churned"
    UNKNOWN = "unknown"


@dataclass
class ProviderMessage:
    message_id: str = ""
    thread_id: str = ""
    from_email: str = ""
    from_name: str = ""
    to_email: str = ""
    to_name: str = ""
    subject: str = ""
    body: str = ""
    snippet: str = ""
    received_at: str = ""
    is_incoming: bool = True
    provider_id: str = ""
    external_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "thread_id": self.thread_id,
            "from_email": self.from_email,
            "from_name": self.from_name,
            "to_email": self.to_email,
            "to_name": self.to_name,
            "subject": self.subject,
            "body": self.body,
            "snippet": self.snippet,
            "received_at": self.received_at,
            "is_incoming": self.is_incoming,
            "provider_id": self.provider_id,
            "external_id": self.external_id,
        }


@dataclass
class ProviderConversation:
    thread_id: str
    subject: str = ""
    messages: list[ProviderMessage] = field(default_factory=list)
    stage: ConversationStage = ConversationStage.UNKNOWN
    provider_id: str = ""
    external_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "subject": self.subject,
            "messages": [m.to_dict() for m in self.messages],
            "stage": self.stage.value,
            "provider_id": self.provider_id,
            "external_id": self.external_id,
        }


class MeetingStatus(str, Enum):
    SCHEDULED = "scheduled"
    CONFIRMED = "confirmed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


@dataclass
class ProviderMeeting:
    title: str
    start_time: str
    end_time: str
    attendees: list[str] = field(default_factory=list)
    status: MeetingStatus = MeetingStatus.UNKNOWN
    description: str = ""
    location: str = ""
    provider_id: str = ""
    external_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "attendees": self.attendees,
            "status": self.status.value,
            "description": self.description,
            "location": self.location,
            "provider_id": self.provider_id,
            "external_id": self.external_id,
        }


@dataclass
class ProviderDocument:
    name: str
    mime_type: str = ""
    size_bytes: int = 0
    url: str = ""
    parent_folder: str = ""
    provider_id: str = ""
    external_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "url": self.url,
            "parent_folder": self.parent_folder,
            "provider_id": self.provider_id,
            "external_id": self.external_id,
        }


class EmailDeliveryStatus(str, Enum):
    QUEUED = "queued"
    DELIVERED = "delivered"
    BOUNCED = "bounced"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass
class ProviderEmail:
    to_email: str
    to_name: str
    subject: str
    body: str
    from_email: str = ""
    from_name: str = ""
    delivery_status: EmailDeliveryStatus = EmailDeliveryStatus.UNKNOWN
    external_message_id: str = ""
    thread_id: str = ""
    provider_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "to_email": self.to_email,
            "to_name": self.to_name,
            "subject": self.subject,
            "body": self.body,
            "from_email": self.from_email,
            "from_name": self.from_name,
            "delivery_status": self.delivery_status.value,
            "external_message_id": self.external_message_id,
            "thread_id": self.thread_id,
            "provider_id": self.provider_id,
        }
