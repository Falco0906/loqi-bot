from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from services.planner.payloads import TaskPayload, get_payload_class


PLANNER_VERSION = "1.0.0"


class PlanStatus(str, Enum):
    DRAFT = "draft"
    VALIDATED = "validated"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(str, Enum):
    PENDING = "pending"
    BLOCKED = "blocked"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class TaskType(str, Enum):
    SEND_MESSAGE = "send_message"
    SEND_EMAIL = "send_email"
    SCHEDULE_MEETING = "schedule_meeting"
    WAIT_FOR_REPLY = "wait_for_reply"
    WAIT_DURATION = "wait_duration"
    REQUEST_APPROVAL = "request_approval"
    UPDATE_CRM = "update_crm"
    ANALYZE_REPLY = "analyze_reply"
    ESCALATE = "escalate"
    BRANCH = "branch"
    JOIN = "join"

    # Calendar operations
    CALENDAR_LIST_EVENTS = "calendar_list_events"
    CALENDAR_GET_EVENT = "calendar_get_event"
    CALENDAR_CREATE_EVENT = "calendar_create_event"
    CALENDAR_UPDATE_EVENT = "calendar_update_event"
    CALENDAR_DELETE_EVENT = "calendar_delete_event"

    # CRM operations
    FIND_CONTACT = "find_contact"
    CREATE_CONTACT = "create_contact"
    UPDATE_CONTACT = "update_contact"
    FIND_COMPANY = "find_company"
    CREATE_COMPANY = "create_company"
    CREATE_OPPORTUNITY = "create_opportunity"
    UPDATE_OPPORTUNITY = "update_opportunity"
    CREATE_ACTIVITY = "create_activity"
    CREATE_NOTE = "create_note"
    ASSIGN_OWNER = "assign_owner"

    # Memory operations
    STORE_MEMORY = "store_memory"
    RETRIEVE_MEMORY = "retrieve_memory"
    SEARCH_MEMORY = "search_memory"
    UPDATE_MEMORY = "update_memory"
    DELETE_MEMORY = "delete_memory"
    SUMMARIZE_MEMORY = "summarize_memory"


class TriggerType(str, Enum):
    IMMEDIATELY = "immediately"
    AFTER_REPLY = "after_reply"
    AFTER_DURATION = "after_duration"
    AFTER_TASK = "after_task"
    BUSINESS_HOURS = "business_hours"
    SPECIFIC_TIME = "specific_time"
    ON_CONDITION = "on_condition"


class BranchCondition(str, Enum):
    REPLY_RECEIVED = "reply_received"
    REPLY_NOT_RECEIVED = "reply_not_received"
    OBJECTION_RAISED = "objection_raised"
    MEETING_BOOKED = "meeting_booked"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_DENIED = "approval_denied"
    CONFIDENCE_THRESHOLD = "confidence_threshold"
    HUMAN_DECISION = "human_decision"


class ApprovalRequirement(str, Enum):
    NONE = "none"
    RECOMMENDED = "recommended"
    REQUIRED = "required"
    POLICY_MANDATED = "policy_mandated"


class DependencyType(str, Enum):
    FINISH_TO_START = "finish_to_start"
    START_TO_START = "start_to_start"


@dataclass
class PlanGoal:
    outcome: str = ""
    target_action: str = ""
    success_criteria: list[str] = field(default_factory=list)
    priority: str = "medium"
    constraints: list[str] = field(default_factory=list)


@dataclass
class Trigger:
    type: TriggerType = TriggerType.IMMEDIATELY
    value: str | int | None = None
    window_start: str | None = None
    window_end: str | None = None
    timezone: str = "UTC"


@dataclass
class Branch:
    condition: BranchCondition = BranchCondition.REPLY_RECEIVED
    true_task_ids: list[str] = field(default_factory=list)
    false_task_ids: list[str] = field(default_factory=list)
    evaluation_task_id: str | None = None


@dataclass
class Task:
    id: str = ""
    plan_id: str = ""
    type: TaskType = TaskType.SEND_MESSAGE
    status: TaskStatus = TaskStatus.PENDING
    label: str = ""
    instructions: str = ""
    payload: TaskPayload | None = None
    params: dict[str, Any] = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)
    trigger: Optional[Trigger] = None
    approval: ApprovalRequirement = ApprovalRequirement.NONE
    branch: Optional[Branch] = None
    reasoning_trace: str = ""
    reasoning_goal: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[dict] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.id:
            self.id = uuid4().hex[:12]
        if not self.trigger:
            self.trigger = Trigger()
        if self.payload is not None:
            self.params = self.payload.to_dict()
            self.params["payload_type"] = self.payload.payload_type

    def get_payload(self) -> TaskPayload | None:
        """Return the typed payload if available, otherwise reconstruct from params."""
        if self.payload is not None:
            return self.payload
        payload_type = self.params.get("payload_type")
        if not payload_type:
            return None
        cls = get_payload_class(payload_type)
        if not cls:
            return None
        data = {k: v for k, v in self.params.items() if k != "payload_type"}
        try:
            return cls(**data)
        except Exception:
            return None


@dataclass
class Dependency:
    source_id: str = ""
    target_id: str = ""
    type: DependencyType = DependencyType.FINISH_TO_START
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Schedule:
    timezone: str = "UTC"
    business_hours_only: bool = True
    min_delay_between_tasks: int = 30
    max_daily_tasks: int = 3
    preferred_days: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])
    blackout_periods: list[tuple[datetime, datetime]] = field(default_factory=list)


@dataclass
class Approval:
    task_id: str = ""
    requirement: ApprovalRequirement = ApprovalRequirement.NONE
    status: str = "pending"
    requested_at: Optional[datetime] = None
    decided_at: Optional[datetime] = None
    decided_by: Optional[str] = None
    reason: Optional[str] = None


@dataclass
class Plan:
    id: str = ""
    conversation_id: str = ""
    reasoning_id: str = ""
    status: PlanStatus = PlanStatus.DRAFT
    tasks: list[Task] = field(default_factory=list)
    goal: Optional[PlanGoal] = None
    strategy: str = ""
    version: str = PLANNER_VERSION
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    validated_at: Optional[datetime] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.id:
            self.id = uuid4().hex[:12]
        if not self.goal:
            self.goal = PlanGoal()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "reasoning_id": self.reasoning_id,
            "status": self.status.value,
            "tasks": [self._task_to_dict(t) for t in self.tasks],
            "goal": {
                "outcome": self.goal.outcome if self.goal else "",
                "target_action": self.goal.target_action if self.goal else "",
                "success_criteria": self.goal.success_criteria if self.goal else [],
                "priority": self.goal.priority if self.goal else "medium",
                "constraints": self.goal.constraints if self.goal else [],
            },
            "strategy": self.strategy,
            "version": self.version,
            "created_at": self.created_at.isoformat(),
            "validated_at": self.validated_at.isoformat() if self.validated_at else None,
            "metadata": self.metadata,
        }

    def _task_to_dict(self, t: Task) -> dict:
        return {
            "id": t.id,
            "plan_id": t.plan_id,
            "type": t.type.value,
            "status": t.status.value,
            "label": t.label,
            "instructions": t.instructions,
            "params": t.params,
            "dependencies": t.dependencies,
            "trigger": {
                "type": t.trigger.type.value if t.trigger else TriggerType.IMMEDIATELY.value,
                "value": t.trigger.value if t.trigger else None,
                "window_start": t.trigger.window_start if t.trigger else None,
                "window_end": t.trigger.window_end if t.trigger else None,
                "timezone": t.trigger.timezone if t.trigger else "UTC",
            } if t.trigger else None,
            "approval": t.approval.value,
            "branch": {
                "condition": t.branch.condition.value if t.branch else None,
                "true_task_ids": t.branch.true_task_ids if t.branch else [],
                "false_task_ids": t.branch.false_task_ids if t.branch else [],
                "evaluation_task_id": t.branch.evaluation_task_id if t.branch else None,
            } if t.branch else None,
            "reasoning_trace": t.reasoning_trace,
            "reasoning_goal": t.reasoning_goal,
            "created_at": t.created_at.isoformat(),
            "started_at": t.started_at.isoformat() if t.started_at else None,
            "completed_at": t.completed_at.isoformat() if t.completed_at else None,
            "result": t.result,
            "metadata": t.metadata,
        }

    def get_dag_edges(self) -> list[tuple[str, str]]:
        edges = []
        for task in self.tasks:
            for dep_id in task.dependencies:
                edges.append((dep_id, task.id))
        return edges

    def get_task_map(self) -> dict[str, Task]:
        return {t.id: t for t in self.tasks}

    def get_root_tasks(self) -> list[Task]:
        task_map = self.get_task_map()
        return [t for t in self.tasks if not t.dependencies]

    def get_terminal_tasks(self) -> list[Task]:
        dependents = set()
        for t in self.tasks:
            for dep_id in t.dependencies:
                dependents.add(dep_id)
        return [t for t in self.tasks if t.id not in dependents]

    def get_downstream_tasks(self, task_id: str) -> list[Task]:
        return [t for t in self.tasks if task_id in t.dependencies]

    def get_all_dependency_pairs(self) -> list[tuple[str, str]]:
        pairs = []
        for t in self.tasks:
            for dep_id in t.dependencies:
                pairs.append((dep_id, t.id))
        return pairs
