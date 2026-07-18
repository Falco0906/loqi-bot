"""Execution Engine exception hierarchy.

All exceptions inherit from ExecutionError and carry structured context
for debugging, logging, and API consumption.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExecutionError(Exception):
    """Base exception for all Execution Engine errors."""

    message: str
    context: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        super().__init__(self.message)

    def to_dict(self) -> dict:
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "context": self.context,
        }


class ExecutionValidationError(ExecutionError):
    """Raised when a plan fails execution-level validation.

    This includes duplicate task IDs, missing payloads, unresolved
    dependency references, and cycle detection failures.
    """

    def __init__(self, message: str, context: dict[str, Any] | None = None):
        super().__init__(message, context or {})


class ExecutionSchedulingError(ExecutionError):
    """Raised when the scheduler encounters an unrecoverable error.

    Examples: dangling dependencies after initialization, terminal
    detection failure, invalid priority queue state.
    """


class ExecutionDispatchError(ExecutionError):
    """Raised when no adapter is registered for a task type.

    This is a permanent failure — the task cannot be dispatched.
    """


class ExecutionAdapterError(ExecutionError):
    """Raised when an adapter execution fails unexpectedly.

    Wraps adapter-level errors that are not simple transient/permanent
    failures (e.g., adapter not found, adapter configuration error).
    """


class ExecutionRetryError(ExecutionError):
    """Raised when the retry engine encounters an invalid state.

    Examples: retry policy with zero max_attempts, negative backoff,
    retry scheduled for a non-retryable task.
    """


class ExecutionSessionError(ExecutionError):
    """Raised when a session operation is invalid.

    Examples: trying to resume a completed session, approving a
    task that is not in WAITING_APPROVAL, cancelling an already
    terminal session.
    """


class ExecutionStateError(ExecutionError):
    """Raised when an invalid state transition is attempted.

    Examples: transitioning COMPLETED → RUNNING, FAILED → READY,
    SKIPPED → COMPLETED.
    """