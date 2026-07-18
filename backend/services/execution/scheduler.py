"""Execution Engine scheduler.

Manages runtime scheduling state: dependency graph, ready queue,
concurrency limits, and terminal detection.

The scheduler does not execute tasks, call adapters, emit events,
or perform retries. It only determines what may run.
"""

from __future__ import annotations

from collections import deque
from typing import Optional

from services.execution.enums import TaskState
from services.execution.exceptions import ExecutionSchedulingError
from services.execution.execution_models import (
    ExecutionSession,
    ExecutionTask,
    InDegreeEntry,
)
from services.execution.state_machine import StateMachine


class Scheduler:
    """Runtime scheduler for DAG-based task execution.

    Maintains the in-degree map, ready queue, and running-task set
    for a single execution session. All methods are deterministic
    and side-effect free (no adapters, events, or execution).

    Attributes:
        session: The execution session being scheduled.
        in_degree: Map of task_id → InDegreeEntry tracking unsatisfied deps.
        _ready_queue: Deque of task IDs ready for execution (FIFO).
        _running: Set of task IDs currently running.
        _max_concurrency: Maximum parallel tasks allowed.
    """

    def __init__(
        self,
        session: ExecutionSession,
        max_concurrency: int = 5,
    ):
        self.session = session
        self.in_degree: dict[str, InDegreeEntry] = {}
        self._ready_queue: deque[str] = deque()
        self._running: set[str] = set()
        self._max_concurrency = max_concurrency
        self._initialized = False

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """Build the in-degree map and enqueue root tasks.

        Must be called once before any scheduling operations.
        Root tasks (in-degree 0) are promoted to READY and enqueued.
        """
        if self._initialized:
            raise ExecutionSchedulingError(
                "Scheduler already initialized",
                context={"session_id": self.session.id},
            )

        self._build_in_degree()
        self._enqueue_root_tasks()
        self._initialized = True

    def _build_in_degree(self) -> None:
        """Build the in-degree map from task dependencies."""
        for tid, etask in self.session.tasks.items():
            deps = self._get_dependencies(etask)
            self.in_degree[tid] = InDegreeEntry(
                task_id=tid,
                remaining=len(deps),
                total=len(deps),
            )

    def _enqueue_root_tasks(self) -> None:
        """Enqueue all tasks with in-degree 0 as READY."""
        for tid, entry in self.in_degree.items():
            if entry.remaining == 0:
                etask = self.session.tasks[tid]
                StateMachine.transition_task(etask, TaskState.READY)
                self._ready_queue.append(tid)

    # ------------------------------------------------------------------
    # Ready Queue
    # ------------------------------------------------------------------

    def get_next_ready(self) -> Optional[str]:
        """Pop the next ready task ID from the queue.

        Returns None if the queue is empty or concurrency limit is reached.
        Does NOT execute the task — only returns the ID.
        """
        if not self._ready_queue:
            return None

        if len(self._running) >= self._max_concurrency:
            return None

        task_id = self._ready_queue.popleft()
        self._running.add(task_id)
        return task_id

    def peek_ready(self) -> Optional[str]:
        """Return the next ready task ID without dequeuing.

        Returns None if the queue is empty.
        """
        if not self._ready_queue:
            return None
        return self._ready_queue[0]

    def ready_count(self) -> int:
        """Return the number of tasks in the ready queue."""
        return len(self._ready_queue)

    def running_count(self) -> int:
        """Return the number of currently running tasks."""
        return len(self._running)

    # ------------------------------------------------------------------
    # Dependency Release
    # ------------------------------------------------------------------

    def mark_completed(self, task_id: str) -> list[str]:
        """Mark a task as completed and release downstream dependencies.

        Returns a list of newly READY task IDs that were enqueued.
        The caller is responsible for transitioning the task to COMPLETED.
        """
        self._running.discard(task_id)
        downstream = self._get_downstream_tasks(task_id)
        newly_ready: list[str] = []

        for downstream_id in downstream:
            etask = self.session.tasks.get(downstream_id)
            if etask is None:
                continue
            if etask.status.is_terminal:
                continue

            entry = self.in_degree.get(downstream_id)
            if entry is None or entry.remaining <= 0:
                continue

            entry.remaining -= 1

            if entry.remaining == 0:
                StateMachine.transition_task(etask, TaskState.READY)
                self._ready_queue.append(downstream_id)
                newly_ready.append(downstream_id)

        return newly_ready

    def mark_failed(self, task_id: str) -> list[str]:
        """Mark a task as failed and block downstream dependencies.

        Downstream tasks that become blocked due to this failure are
        transitioned to BLOCKED. If all their upstreams are terminal,
        they are further transitioned to SKIPPED and the skip is
        cascaded transitively.

        Returns a list of task IDs that were transitioned to SKIPPED.
        """
        self._running.discard(task_id)
        downstream = self._get_downstream_tasks(task_id)
        skipped: list[str] = []

        for downstream_id in downstream:
            etask = self.session.tasks.get(downstream_id)
            if etask is None:
                continue
            if etask.status.is_terminal:
                continue

            StateMachine.transition_task(etask, TaskState.BLOCKED)

            if self._is_permanently_blocked(downstream_id):
                StateMachine.transition_task(etask, TaskState.SKIPPED)
                skipped.append(downstream_id)
                skipped.extend(self.mark_skipped(downstream_id))

        return skipped

    def mark_skipped(self, task_id: str) -> list[str]:
        """Propagate a SKIPPED status to downstream tasks.

        When a task is skipped (e.g., rejected approval), downstream
        tasks that depend on it are blocked and potentially skipped.

        Returns a list of task IDs that were transitioned to SKIPPED.
        """
        self._running.discard(task_id)
        try:
            self._ready_queue.remove(task_id)
        except ValueError:
            pass

        downstream = self._get_downstream_tasks(task_id)
        skipped: list[str] = []

        for downstream_id in downstream:
            etask = self.session.tasks.get(downstream_id)
            if etask is None:
                continue
            if etask.status.is_terminal:
                continue

            entry = self.in_degree.get(downstream_id)
            if entry is not None:
                entry.remaining = max(0, entry.remaining - 1)

            if self._is_permanently_blocked(downstream_id):
                if etask.status == TaskState.PENDING:
                    StateMachine.transition_task(etask, TaskState.SKIPPED)
                    skipped.append(downstream_id)
                    skipped.extend(self.mark_skipped(downstream_id))
                elif etask.status == TaskState.BLOCKED:
                    StateMachine.transition_task(etask, TaskState.SKIPPED)
                    skipped.append(downstream_id)
                    skipped.extend(self.mark_skipped(downstream_id))

        return skipped

    # ------------------------------------------------------------------
    # Terminal Detection
    # ------------------------------------------------------------------

    def is_terminal(self) -> bool:
        """Check if the session has reached a terminal state.

        A session is terminal when:
        - All tasks are in a terminal state (COMPLETED, FAILED, SKIPPED, CANCELLED)
        - No tasks are in an active state (RUNNING, RETRYING, WAITING, WAITING_APPROVAL)
        - The ready queue is empty and no tasks are running
        """
        has_active = False
        has_ready = bool(self._ready_queue)
        all_terminal = True

        for etask in self.session.tasks.values():
            if etask.status.is_active:
                has_active = True
            if not etask.status.is_terminal:
                all_terminal = False

        return (not has_active) and (not has_ready) and all_terminal

    def get_terminal_state(self) -> str:
        """Determine the terminal session state name.

        Must only be called when is_terminal() returns True.
        """
        states = {t.status for t in self.session.tasks.values()}

        if TaskState.CANCELLED in states:
            return "cancelled"
        if TaskState.FAILED in states:
            if TaskState.COMPLETED in states:
                return "completed_with_errors"
            return "failed"
        if TaskState.SKIPPED in states:
            if TaskState.COMPLETED in states:
                return "completed_with_errors"
            return "failed"
        if all(s == TaskState.COMPLETED for s in states):
            return "completed"

        return "completed"

    # ------------------------------------------------------------------
    # Concurrency
    # ------------------------------------------------------------------

    @property
    def can_dispatch(self) -> bool:
        """Check if another task can be dispatched (under concurrency limit)."""
        return len(self._running) < self._max_concurrency and bool(self._ready_queue)

    @property
    def max_concurrency(self) -> int:
        return self._max_concurrency

    @max_concurrency.setter
    def max_concurrency(self, value: int) -> None:
        if value < 1:
            raise ExecutionSchedulingError(
                "max_concurrency must be at least 1",
                context={"value": value},
            )
        self._max_concurrency = value

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_dependencies(etask: ExecutionTask) -> list[str]:
        return list(getattr(etask.plan_task, "dependencies", []))

    def _get_downstream_tasks(self, task_id: str) -> list[str]:
        """Return task IDs that depend on the given task."""
        downstream: list[str] = []
        for tid, etask in self.session.tasks.items():
            deps = self._get_dependencies(etask)
            if task_id in deps:
                downstream.append(tid)
        return downstream

    def _is_permanently_blocked(self, task_id: str) -> bool:
        """Check if a task is permanently blocked (all upstreams terminal)."""
        etask = self.session.tasks.get(task_id)
        if etask is None:
            return True
        deps = self._get_dependencies(etask)
        if not deps:
            return False
        for dep_id in deps:
            dep_task = self.session.tasks.get(dep_id)
            if dep_task is None:
                continue
            if not dep_task.status.is_terminal:
                return False
        return True