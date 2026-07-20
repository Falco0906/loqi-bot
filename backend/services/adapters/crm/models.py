from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Contact:
    id: str = ""
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    title: str = ""
    company_id: str = ""
    company_name: str = ""
    owner_id: str = ""
    lifecycle_stage: str = "lead"
    custom_fields: dict[str, Any] = field(default_factory=dict)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


@dataclass
class Company:
    id: str = ""
    name: str = ""
    domain: str = ""
    industry: str = ""
    size: str = ""
    website: str = ""
    phone: str = ""
    owner_id: str = ""


@dataclass
class Opportunity:
    id: str = ""
    name: str = ""
    company_id: str = ""
    company_name: str = ""
    contact_id: str = ""
    contact_name: str = ""
    amount: float = 0.0
    stage: str = "discovery"
    pipeline: str = "default"
    probability: int = 10
    close_date: str = ""
    owner_id: str = ""


@dataclass
class Activity:
    id: str = ""
    type: str = "email"
    subject: str = ""
    body: str = ""
    contact_id: str = ""
    company_id: str = ""
    opportunity_id: str = ""
    owner_id: str = ""
    status: str = "completed"
    due_date: str = ""


@dataclass
class Note:
    id: str = ""
    body: str = ""
    contact_id: str = ""
    company_id: str = ""
    opportunity_id: str = ""
    author_id: str = ""


@dataclass
class CrmOwner:
    id: str = ""
    email: str = ""
    name: str = ""


@dataclass
class ContactSearchResult:
    contacts: list[Contact] = field(default_factory=list)
    total: int = 0
    query: str = ""


@dataclass
class CompanySearchResult:
    companies: list[Company] = field(default_factory=list)
    total: int = 0
    query: str = ""
