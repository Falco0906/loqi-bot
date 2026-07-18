"""Execution Engine state machine.

Implements all task and session state transitions using explicit
transition tables. Invalid transitions raise typed exceptions.
"""

from __future__ import annotations

from typing import Optional

from services.execution.enums import SessionState, TaskState
from services.execution.exceptions import ExecutionStateError
from services.execution.execution_models import ExecutionSession, ExecutionTask

# ---------------------------------------------------------------------------
# Task state transition table
# ---------------------------------------------------------------------------

_TASK_TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.PENDING: {
        TaskState.READY,
        TaskState.BLOCKED,
        TaskState.WAITING_APPROVAL,
        TaskState.SKIPPED,
        TaskState.CANCELLED,
    },
    TaskState.READY: {
        TaskState.RUNNING,
        TaskState.SKIPPED,
        TaskState.CANCELLED,
    },
    TaskState.RUNNING: {
        TaskState.COMPLETED,
        TaskState.FAILED,
        TaskState.WAITING,
        TaskState.WAITING_APPROVAL,
        TaskState.RETRYING,
        TaskState.CANCELLED,
    },
    TaskState.WAITING: {
        TaskState.READY,
        TaskState.FAILED,
        TaskState.CANCELLED,
    },
    TaskState.WAITING_APPROVAL: {
        TaskState.READY,
        TaskState.SKIPPED,
        TaskState.CANCELLED,
    },
    TaskState.RETRYING: {
        TaskState.READY,
        TaskState.FAILED,
        TaskState.CANCELLED,
    },
    TaskState.BLOCKED: {
        TaskState.SKIPPED,
        TaskState.READY,
        TaskState.CANCELLED,
    },
    TaskState.COMPLETED: set(),
    TaskState.FAILED: set(),
    TaskState.SKIPPED: set(),
    TaskState.CANCELLED: set(),
}

# ---------------------------------------------------------------------------
# Session state transition table
# ---------------------------------------------------------------------------

_SESSION_TRANSITIONS: dict[SessionState, set[SessionState]] = {
    SessionState.PENDING: {
        SessionState.RUNNING,
        SessionState.CANCELLED,
    },
    SessionState.RUNNING: {
        SessionState.PAUSED,
        SessionState.WAITING_APPROVAL,
        SessionState.COMPLETED,
        SessionState.COMPLETED_WITH_ERRORS,
        SessionState.FAILED,
        SessionState.CANCELLED,
    },
    SessionState.PAUSED: {
        SessionState.RUNNING,
        SessionState.CANCELLED,
    },
    SessionState.WAITING_APPROVAL: {
        SessionState.RUNNING,
        SessionState.COMPLETED,
        SessionState.COMPLETED_WITH_ERRORS,
        SessionState.FAILED,
        SessionState.CANCELLED,
    },
    SessionState.COMPLETED: set(),
    SessionState.COMPLETED_WITH_ERRORS: set(),
    SessionState.FAILED: set(),
    SessionState.CANCELLED: set(),
}


class StateMachine:
    """Validates and executes state transitions for tasks and sessions.

    Uses explicit transition tables. Invalid transitions are rejected
    immediately with a typed exception.
    """

    @staticmethod
    def transition_task(task: ExecutionTask, to_state: TaskState) -> None:
        """Transition a task to a new state.

        Validates the transition is allowed by the transition table.
        Raises ExecutionStateError if the transition is invalid.

        Args:
            task: The task to transition.
            to_state: The target state.

        Raises:
            ExecutionStateError: If the transition is not allowed.
        """
        from_state = task.status
        allowed = _TASK_TRANSITIONS.get(from_state, set())

        if to_state not in allowed:
            raise ExecutionStateError(
                f"Invalid task state transition: {from_state.value} → {to_state.value}",
                context={
                    "task_id": task.id,
                    "from_state": from_state.value,
                    "to_state": to_state.value,
                    "allowed_transitions": sorted(s.value for s in allowed),
                },
            )

        task.status = to_state

    @staticmethod
    def transition_session(session: ExecutionSession, to_state: SessionState) -> None:
        """Transition a session to a new state.

        Validates the transition is allowed by the transition table.
        Raises ExecutionStateError if the transition is invalid.

        Args:
            session: The session to transition.
            to_state: The target state.

        Raises:
            ExecutionStateError: If the transition is not allowed.
        """
        from_state = session.status
        allowed = _SESSION_TRANSITIONS.get(from_state, set())

        if to_state not in allowed:
            raise ExecutionStateError(
                f"Invalid session state transition: "
                f"{from_state.value} → {to_state.value}",
                context={
                    "session_id": session.id,
                    "from_state": from_state.value,
                    "to_state": to_state.value,
                    "allowed_transitions": sorted(s.value for s in allowed),
                },
            )

        session.status = to_state

    @staticmethod
    def is_valid_task_transition(from_state: TaskState, to_state: TaskState) -> bool:
        """Check if a task state transition is valid without applying it."""
        allowed = _TASK_TRANSITIONS.get(from_state, set())
        return to_state in allowed

    @staticmethod
    def is_valid_session_transition(
        from_state: SessionState, to_state: SessionState
    ) -> bool:
        """Check if a session state transition is valid without applying it."""
        allowed = _SESSION_TRANSITIONS.get(from_state, set())
        return to_state in allowed

    @staticmethod
    def derive_session_state(session: ExecutionSession) -> SessionState:
        """Derive the session state from the collective task states.

        This is the source of truth for session state. The session
        status is never mutated independently; it is derived from
        task states.

        Priority order:
          1. If any task is CANCELLED → session CANCELLED
          2. If any task is RUNNING, RETRYING, WAITING → session RUNNING
          3. If any task is WAITING_APPROVAL → session WAITING_APPROVAL
          4. If any task is READY → session RUNNING (ready to execute)
          5. If any task is PENDING → session RUNNING (not yet ready)
          6. If all tasks are terminal → derive terminal state
        """
        if not session.tasks:
            return SessionState.FAILED

        states = {t.status for t in session.tasks.values()}

        # Check for cancellation first
        if TaskState.CANCELLED in states:
            return SessionState.CANCELLED

        # Active states mean the session is still running
        if any(
            s in states
            for s in (TaskState.RUNNING, TaskState.RETRYING, TaskState.WAITING)
        ):
            return SessionState.RUNNING

        if TaskState.WAITING_APPROVAL in states:
            return SessionState.WAITING_APPROVAL

        if TaskState.READY in states:
            return SessionState.RUNNING

        if TaskState.PENDING in states:
            return SessionState.RUNNING

        # All tasks are terminal — derive final state
        if TaskState.FAILED in states:
            if TaskState.COMPLETED in states:
                return SessionState.COMPLETED_WITH_ERRORS
            return SessionState.FAILED

        if TaskState.SKIPPED in states:
            if TaskState.COMPLETED in states:
                return SessionState.COMPLETED_WITH_ERRORS
            return SessionState.FAILED

        if all(s == TaskState.COMPLETED for s in states):
            return SessionState.COMPLETED

        if TaskState.BLOCKED in states:
            return SessionState.RUNNING  # Blocked tasks may still be resolvable

        return SessionState.RUNNING