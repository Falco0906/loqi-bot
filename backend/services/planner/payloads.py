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
}


def get_payload_class(name: str) -> type[TaskPayload] | None:
    return PAYLOAD_REGISTRY.get(name)


def register_payload_class(name: str, cls: type[TaskPayload]) -> None:
    PAYLOAD_REGISTRY[name] = cls
