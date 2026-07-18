"""Execution Engine core data models.

All models are dataclasses with strong typing and descriptive docstrings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from services.execution.enums import ExecutionEventType, SessionState, TaskState


@dataclass
class RetryPolicy:
    """Controls retry behavior for a single task.

    Attributes:
        max_attempts: Maximum number of execution attempts (including the first).
        backoff_base_seconds: Initial backoff duration.
        backoff_multiplier: Exponential factor applied per retry.
        max_backoff_seconds: Ceiling for backoff duration.
        jitter: If True, adds random ±50% jitter to each backoff.
        retryable_error_types: Set of error type strings that qualify for retry.
    """

    max_attempts: int = 3
    backoff_base_seconds: float = 1.0
    backoff_multiplier: float = 2.0
    max_backoff_seconds: float = 300.0
    jitter: bool = True
    retryable_error_types: set[str] = field(default_factory=lambda: {"transient"})

    def to_dict(self) -> dict:
        return {
            "max_attempts": self.max_attempts,
            "backoff_base_seconds": self.backoff_base_seconds,
            "backoff_multiplier": self.backoff_multiplier,
            "max_backoff_seconds": self.max_backoff_seconds,
            "jitter": self.jitter,
            "retryable_error_types": list(self.retryable_error_types),
        }

    @classmethod
    def default(cls) -> RetryPolicy:
        return cls()


@dataclass
class TaskResult:
    """Result produced by executing a single task attempt.

    Attributes:
        task_id: References the ExecutionTask.id.
        attempt: Which attempt produced this result.
        success: True if execution completed normally.
        output: Adapter-specific output data on success.
        error: Error message on failure.
        error_type: "transient" or "permanent" classification.
        metadata: Adapter-specific metadata.
        started_at: When execution began.
        completed_at: When execution finished.
        duration_ms: Wall-clock execution time in milliseconds.
    """

    task_id: str
    attempt: int
    success: bool
    output: Optional[dict] = None
    error: Optional[str] = None
    error_type: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    duration_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "attempt": self.attempt,
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "error_type": self.error_type,
            "metadata": self.metadata,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "duration_ms": self.duration_ms,
        }


@dataclass
class ExecutionEvent:
    """A structured event emitted during execution.

    Attributes:
        id: Unique event identifier.
        session_id: References ExecutionSession.id.
        task_id: References ExecutionTask.id (None for session-level events).
        event_type: Structured event type.
        data: Event-specific payload.
        timestamp: When the event occurred.
        sequence: Monotonic sequence number within the session.
    """

    id: str = ""
    session_id: str = ""
    task_id: Optional[str] = None
    event_type: ExecutionEventType = ExecutionEventType.SESSION_CREATED
    data: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    sequence: int = 0

    def __post_init__(self):
        if not self.id:
            self.id = uuid4().hex[:12]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "event_type": self.event_type.value,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
            "sequence": self.sequence,
        }


@dataclass
class ExecutionTask:
    """Runtime wrapper around a Plan task within an execution session.

    Attributes:
        id: Matches the Plan Task.id.
        plan_task: Reference to the immutable Plan Task.
        status: Current execution state.
        attempts: Execution attempt count.
        max_attempts: Maximum attempts from retry policy.
        last_error: Error message from the last failed attempt.
        last_error_type: "transient" or "permanent" from the last failure.
        result: Result of successful execution.
        started_at: When execution first began.
        completed_at: When execution finished.
        retry_policy: The retry policy for this task.
        adapter_name: Resolved adapter name (set during dispatch).
    """

    id: str
    plan_task: Any  # services.planner.planning_models.Task (avoid circular import)
    status: TaskState = TaskState.PENDING
    attempts: int = 0
    max_attempts: int = 3
    last_error: Optional[str] = None
    last_error_type: Optional[str] = None
    result: Optional[TaskResult] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy.default)
    adapter_name: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "plan_task_id": self.plan_task.id,
            "plan_task_type": self.plan_task.type.value,
            "status": self.status.value,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "last_error": self.last_error,
            "last_error_type": self.last_error_type,
            "result": self.result.to_dict() if self.result else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "retry_policy": self.retry_policy.to_dict(),
            "adapter_name": self.adapter_name,
        }


@dataclass
class ExecutionMetrics:
    """Aggregated metrics collected during session execution.

    Attributes:
        session_id: References ExecutionSession.id.
        total_tasks: Total tasks in the plan.
        completed_tasks: Tasks completed successfully.
        failed_tasks: Tasks permanently failed.
        skipped_tasks: Tasks skipped due to upstream failure.
        cancelled_tasks: Tasks externally cancelled.
        total_attempts: Total execution attempts across all tasks.
        total_retries: Total retry attempts across all tasks.
        approval_count: Total approval requests made.
        start_time: When the session started.
        end_time: When the session ended.
        duration_seconds: Wall-clock session duration.
        adapter_stats: Per-adapter execution statistics.
    """

    session_id: str
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    skipped_tasks: int = 0
    cancelled_tasks: int = 0
    total_attempts: int = 0
    total_retries: int = 0
    approval_count: int = 0
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    adapter_stats: dict[str, dict] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "total_tasks": self.total_tasks,
            "completed_tasks": self.completed_tasks,
            "failed_tasks": self.failed_tasks,
            "skipped_tasks": self.skipped_tasks,
            "cancelled_tasks": self.cancelled_tasks,
            "total_attempts": self.total_attempts,
            "total_retries": self.total_retries,
            "approval_count": self.approval_count,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": self.duration_seconds,
            "adapter_stats": self.adapter_stats,
        }


@dataclass
class ExecutionSession:
    """Runtime context for a single plan execution.

    An ExecutionSession wraps an immutable Plan and tracks the execution
    state of every task, plus session-level metadata.

    Attributes:
        id: Unique session identifier.
        plan_id: References the Plan.id.
        plan: The original Plan (immutable during execution).
        conversation_id: References the Conversation.id.
        status: Current session state.
        tasks: Map of task_id to ExecutionTask.
        root_tasks: Task IDs with in-degree 0 at initialization.
        start_time: When the session began execution.
        end_time: When the session reached a terminal state.
        metadata: Workspace snapshot and execution policies.
        created_at: When the session was created.
        updated_at: When the session was last modified.
    """

    id: str = ""
    plan_id: str = ""
    plan: Any = None  # services.planner.planning_models.Plan
    conversation_id: str = ""
    status: SessionState = SessionState.PENDING
    tasks: dict[str, ExecutionTask] = field(default_factory=dict)
    root_tasks: list[str] = field(default_factory=list)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self):
        if not self.id:
            self.id = uuid4().hex[:12]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "plan_id": self.plan_id,
            "conversation_id": self.conversation_id,
            "status": self.status.value,
            "tasks": {tid: t.to_dict() for tid, t in self.tasks.items()},
            "root_tasks": self.root_tasks,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class ExecutionResult:
    """Overall result of executing a plan.

    Attributes:
        session: The completed execution session.
        metrics: Aggregated execution metrics.
        events: All events emitted during execution.
    """

    session: ExecutionSession
    metrics: ExecutionMetrics
    events: list[ExecutionEvent]

    def to_dict(self) -> dict:
        return {
            "session": self.session.to_dict(),
            "metrics": self.metrics.to_dict(),
            "events": [e.to_dict() for e in self.events],
        }


@dataclass
class ValidationResult:
    """Result of plan validation before execution.

    Attributes:
        valid: True if the plan passes all execution-level checks.
        errors: Human-readable error messages.
        warnings: Non-blocking warnings.
    """

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
        }


@dataclass
class InDegreeEntry:
    """Tracks dependency satisfaction for a single task during scheduling.

    Attributes:
        task_id: References the ExecutionTask.id.
        remaining: Number of unsatisfied dependencies.
        total: Total number of dependencies.
    """

    task_id: str
    remaining: int = 0
    total: int = 0