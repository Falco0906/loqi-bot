"""Typed task payload system.

Every task should carry a strongly typed payload describing its parameters.
Payloads are serializable to dictionaries for persistence and API responses.
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any
import re


class TaskPayload:
    """Base class for all task payloads.

    Subclasses are plain dataclasses.  Do not store runtime or execution state here.
    """

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate(self) -> list[str]:
        """Return a list of human-readable validation errors (empty if valid)."""
        return []

    @property
    def payload_type(self) -> str:
        return self.__class__.__name__


# --- Typed payloads ---

@dataclass
class MessagePayload(TaskPayload):
    """Payload for SEND_MESSAGE / SEND_EMAIL tasks."""

    channel: str = ""
    template: str = ""

    def validate(self) -> list[str]:
        errors = []
        if not self.channel or not self.channel.strip():
            errors.append("channel is required")
        if not self.template or not self.template.strip():
            errors.append("template is required")
        return errors


@dataclass
class WaitForReplyPayload(TaskPayload):
    """Payload for WAIT_FOR_REPLY tasks."""

    timeout: str = "3d"
    fallback: str = ""

    def validate(self) -> list[str]:
        errors = []
        if not self.timeout or not re.match(r"^\d+[mhdw]$", self.timeout):
            errors.append("timeout must be a duration like '30m', '2h', '3d', or '1w'")
        return errors


@dataclass
class WaitDurationPayload(TaskPayload):
    """Payload for WAIT_DURATION tasks."""

    duration: str = "1d"

    def validate(self) -> list[str]:
        errors = []
        if not self.duration or not re.match(r"^\d+[mhdw]$", self.duration):
            errors.append("duration must be a duration like '30m', '2h', '3d', or '1w'")
        return errors


@dataclass
class AnalyzeReplyPayload(TaskPayload):
    """Payload for ANALYZE_REPLY tasks."""

    reason: str = ""


@dataclass
class EscalatePayload(TaskPayload):
    """Payload for ESCALATE tasks."""

    channel: str = "internal"
    priority: str = "high"
    reason: str = ""

    def validate(self) -> list[str]:
        errors = []
        if not self.reason:
            errors.append("escalation reason is required")
        if self.priority not in ("low", "medium", "high", "critical"):
            errors.append("priority must be one of low, medium, high, critical")
        return errors


@dataclass
class UpdateCRMPayload(TaskPayload):
    """Payload for UPDATE_CRM tasks."""

    action: str = ""
    status: str = ""

    def validate(self) -> list[str]:
        errors = []
        if not self.action:
            errors.append("action is required")
        if not self.status:
            errors.append("status is required")
        return errors


@dataclass
class RequestApprovalPayload(TaskPayload):
    """Payload for REQUEST_APPROVAL tasks."""

    approver_role: str = ""


@dataclass
class ScheduleMeetingPayload(TaskPayload):
    """Payload for SCHEDULE_MEETING tasks."""

    duration_minutes: int = 30


@dataclass
class BranchPayload(TaskPayload):
    """Payload for BRANCH nodes."""

    condition: str = ""


@dataclass
class JoinPayload(TaskPayload):
    """Payload for JOIN nodes."""

    branch_task_id: str = ""
    condition: str = ""


# --- Calendar payloads ---

@dataclass
class ListEventsPayload(TaskPayload):
    """Payload for CALENDAR_LIST_EVENTS tasks."""

    calendar_id: str = "primary"
    time_min: str = ""
    time_max: str = ""
    max_results: int = 100
    query: str = ""
    show_deleted: bool = False

    def validate(self) -> list[str]:
        errors = []
        if not self.calendar_id:
            errors.append("calendar_id is required")
        if self.max_results < 1 or self.max_results > 2500:
            errors.append("max_results must be between 1 and 2500")
        return errors


@dataclass
class GetEventPayload(TaskPayload):
    """Payload for CALENDAR_GET_EVENT tasks."""

    event_id: str = ""
    calendar_id: str = "primary"

    def validate(self) -> list[str]:
        errors = []
        if not self.event_id:
            errors.append("event_id is required")
        return errors


@dataclass
class CreateEventPayload(TaskPayload):
    """Payload for CALENDAR_CREATE_EVENT tasks."""

    summary: str = ""
    start_time: str = ""
    end_time: str = ""
    calendar_id: str = "primary"
    description: str = ""
    location: str = ""
    timezone: str = "UTC"
    attendees: tuple[str, ...] = ()

    def validate(self) -> list[str]:
        errors = []
        if not self.summary:
            errors.append("summary is required")
        if not self.start_time:
            errors.append("start_time is required")
        if not self.end_time:
            errors.append("end_time is required")
        return errors


@dataclass
class UpdateEventPayload(TaskPayload):
    """Payload for CALENDAR_UPDATE_EVENT tasks."""

    event_id: str = ""
    summary: str = ""
    start_time: str = ""
    end_time: str = ""
    calendar_id: str = "primary"
    description: str = ""
    location: str = ""
    timezone: str = "UTC"
    attendees: tuple[str, ...] = ()

    def validate(self) -> list[str]:
        errors = []
        if not self.event_id:
            errors.append("event_id is required")
        return errors


@dataclass
class DeleteEventPayload(TaskPayload):
    """Payload for CALENDAR_DELETE_EVENT tasks."""

    event_id: str = ""
    calendar_id: str = "primary"

    def validate(self) -> list[str]:
        errors = []
        if not self.event_id:
            errors.append("event_id is required")
        return errors


# --- CRM payloads ---

@dataclass
class FindContactPayload(TaskPayload):
    """Payload for FIND_CONTACT tasks."""

    email: str = ""
    company_domain: str = ""
    name: str = ""

    def validate(self) -> list[str]:
        errors = []
        if not any([self.email, self.company_domain, self.name]):
            errors.append("email, company_domain, or name is required")
        return errors


@dataclass
class CreateContactPayload(TaskPayload):
    """Payload for CREATE_CONTACT tasks."""

    email: str = ""
    first_name: str = ""
    last_name: str = ""
    phone: str = ""
    title: str = ""
    company_id: str = ""
    lifecycle_stage: str = "lead"

    def validate(self) -> list[str]:
        errors = []
        if not self.email:
            errors.append("email is required")
        return errors


@dataclass
class UpdateContactPayload(TaskPayload):
    """Payload for UPDATE_CONTACT tasks."""

    contact_id: str = ""
    fields: dict[str, str] = field(default_factory=dict)

    def validate(self) -> list[str]:
        errors = []
        if not self.contact_id:
            errors.append("contact_id is required")
        return errors


@dataclass
class FindCompanyPayload(TaskPayload):
    """Payload for FIND_COMPANY tasks."""

    domain: str = ""
    name: str = ""

    def validate(self) -> list[str]:
        errors = []
        if not any([self.domain, self.name]):
            errors.append("domain or name is required")
        return errors


@dataclass
class CreateCompanyPayload(TaskPayload):
    """Payload for CREATE_COMPANY tasks."""

    name: str = ""
    domain: str = ""
    industry: str = ""
    size: str = ""
    website: str = ""
    phone: str = ""

    def validate(self) -> list[str]:
        errors = []
        if not self.name:
            errors.append("name is required")
        return errors


@dataclass
class CreateOpportunityPayload(TaskPayload):
    """Payload for CREATE_OPPORTUNITY tasks."""

    name: str = ""
    company_id: str = ""
    contact_id: str = ""
    amount: float = 0.0
    stage: str = "discovery"
    pipeline: str = "default"

    def validate(self) -> list[str]:
        errors = []
        if not self.name:
            errors.append("name is required")
        return errors


@dataclass
class UpdateOpportunityPayload(TaskPayload):
    """Payload for UPDATE_OPPORTUNITY tasks."""

    opportunity_id: str = ""
    stage: str = ""
    amount: float = 0.0
    close_date: str = ""

    def validate(self) -> list[str]:
        errors = []
        if not self.opportunity_id:
            errors.append("opportunity_id is required")
        return errors


@dataclass
class CreateActivityPayload(TaskPayload):
    """Payload for CREATE_ACTIVITY tasks."""

    type: str = "email"
    subject: str = ""
    body: str = ""
    contact_id: str = ""
    company_id: str = ""
    opportunity_id: str = ""
    due_date: str = ""

    def validate(self) -> list[str]:
        errors = []
        if not self.subject:
            errors.append("subject is required")
        return errors


@dataclass
class CreateNotePayload(TaskPayload):
    """Payload for CREATE_NOTE tasks."""

    body: str = ""
    contact_id: str = ""
    company_id: str = ""
    opportunity_id: str = ""

    def validate(self) -> list[str]:
        errors = []
        if not self.body:
            errors.append("body is required")
        if not any([self.contact_id, self.company_id, self.opportunity_id]):
            errors.append("contact_id, company_id, or opportunity_id is required")
        return errors


@dataclass
class AssignOwnerPayload(TaskPayload):
    """Payload for ASSIGN_OWNER tasks."""

    owner_email: str = ""
    contact_id: str = ""
    company_id: str = ""
    opportunity_id: str = ""

    def validate(self) -> list[str]:
        errors = []
        if not self.owner_email:
            errors.append("owner_email is required")
        if not any([self.contact_id, self.company_id, self.opportunity_id]):
            errors.append("contact_id, company_id, or opportunity_id is required")
        return errors


# --- Memory payloads ---

@dataclass
class StoreMemoryPayload(TaskPayload):
    """Payload for STORE_MEMORY tasks."""

    memory_type: str = "contact"
    source: str = ""
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)

    def validate(self) -> list[str]:
        errors = []
        if not self.memory_type:
            errors.append("memory_type is required")
        return errors


@dataclass
class RetrieveMemoryPayload(TaskPayload):
    """Payload for RETRIEVE_MEMORY tasks."""

    memory_id: str = ""

    def validate(self) -> list[str]:
        errors = []
        if not self.memory_id:
            errors.append("memory_id is required")
        return errors


@dataclass
class SearchMemoryPayload(TaskPayload):
    """Payload for SEARCH_MEMORY tasks."""

    query: str = ""
    memory_type: str = ""
    entity_id: str = ""
    tags: list[str] = field(default_factory=list)
    limit: int = 10
    offset: int = 0


@dataclass
class UpdateMemoryPayload(TaskPayload):
    """Payload for UPDATE_MEMORY tasks."""

    memory_id: str = ""
    updates: dict[str, str] = field(default_factory=dict)

    def validate(self) -> list[str]:
        errors = []
        if not self.memory_id:
            errors.append("memory_id is required")
        return errors


@dataclass
class DeleteMemoryPayload(TaskPayload):
    """Payload for DELETE_MEMORY tasks."""

    memory_id: str = ""

    def validate(self) -> list[str]:
        errors = []
        if not self.memory_id:
            errors.append("memory_id is required")
        return errors


@dataclass
class SummarizeMemoryPayload(TaskPayload):
    """Payload for SUMMARIZE_MEMORY tasks."""

    entity_type: str = ""
    entity_id: str = ""

    def validate(self) -> list[str]:
        errors = []
        if not self.entity_type:
            errors.append("entity_type is required")
        if not self.entity_id:
            errors.append("entity_id is required")
        return errors


# Registry used for deserialization if/when execution layer needs it.
PAYLOAD_REGISTRY: dict[str, type[TaskPayload]] = {
    MessagePayload.__name__: MessagePayload,
    WaitForReplyPayload.__name__: WaitForReplyPayload,
    WaitDurationPayload.__name__: WaitDurationPayload,
    AnalyzeReplyPayload.__name__: AnalyzeReplyPayload,
    EscalatePayload.__name__: EscalatePayload,
    UpdateCRMPayload.__name__: UpdateCRMPayload,
    RequestApprovalPayload.__name__: RequestApprovalPayload,
    ScheduleMeetingPayload.__name__: ScheduleMeetingPayload,
    BranchPayload.__name__: BranchPayload,
    JoinPayload.__name__: JoinPayload,
    ListEventsPayload.__name__: ListEventsPayload,
    GetEventPayload.__name__: GetEventPayload,
    CreateEventPayload.__name__: CreateEventPayload,
    UpdateEventPayload.__name__: UpdateEventPayload,
    DeleteEventPayload.__name__: DeleteEventPayload,
    FindContactPayload.__name__: FindContactPayload,
    CreateContactPayload.__name__: CreateContactPayload,
    UpdateContactPayload.__name__: UpdateContactPayload,
    FindCompanyPayload.__name__: FindCompanyPayload,
    CreateCompanyPayload.__name__: CreateCompanyPayload,
    CreateOpportunityPayload.__name__: CreateOpportunityPayload,
    UpdateOpportunityPayload.__name__: UpdateOpportunityPayload,
    CreateActivityPayload.__name__: CreateActivityPayload,
    CreateNotePayload.__name__: CreateNotePayload,
    AssignOwnerPayload.__name__: AssignOwnerPayload,
    StoreMemoryPayload.__name__: StoreMemoryPayload,
    RetrieveMemoryPayload.__name__: RetrieveMemoryPayload,
    SearchMemoryPayload.__name__: SearchMemoryPayload,
    UpdateMemoryPayload.__name__: UpdateMemoryPayload,
    DeleteMemoryPayload.__name__: DeleteMemoryPayload,
    SummarizeMemoryPayload.__name__: SummarizeMemoryPayload,
}


def get_payload_class(name: str) -> type[TaskPayload] | None:
    return PAYLOAD_REGISTRY.get(name)


def register_payload_class(name: str, cls: type[TaskPayload]) -> None:
    PAYLOAD_REGISTRY[name] = cls
