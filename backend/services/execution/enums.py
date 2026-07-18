"""Execution Engine enums.

All enum values are strings for serialization compatibility.
"""

from __future__ import annotations

from enum import Enum


class TaskState(str, Enum):
    """Execution state of a single task within a session."""

    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    WAITING = "waiting"
    WAITING_APPROVAL = "waiting_approval"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {
            TaskState.COMPLETED,
            TaskState.FAILED,
            TaskState.SKIPPED,
            TaskState.CANCELLED,
        }

    @property
    def is_active(self) -> bool:
        return self in {
            TaskState.RUNNING,
            TaskState.RETRYING,
            TaskState.WAITING,
            TaskState.WAITING_APPROVAL,
        }


class SessionState(str, Enum):
    """Execution state of an entire session."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {
            SessionState.COMPLETED,
            SessionState.COMPLETED_WITH_ERRORS,
            SessionState.FAILED,
            SessionState.CANCELLED,
        }


class ExecutionEventType(str, Enum):
    """Types of events emitted during execution."""

    SESSION_CREATED = "session.created"
    SESSION_STARTED = "session.started"
    SESSION_PAUSED = "session.paused"
    SESSION_RESUMED = "session.resumed"
    SESSION_COMPLETED = "session.completed"
    SESSION_FAILED = "session.failed"
    SESSION_CANCELLED = "session.cancelled"

    TASK_READY = "task.ready"
    TASK_STARTED = "task.started"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_RETRYING = "task.retrying"
    TASK_CANCELLED = "task.cancelled"
    TASK_SKIPPED = "task.skipped"

    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_GRANTED = "approval.granted"
    APPROVAL_REJECTED = "approval.rejected"

    WAITING_STARTED = "waiting.started"
    WAITING_COMPLETED = "waiting.completed"