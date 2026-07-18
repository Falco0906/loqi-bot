"""Recovery Manager — orchestrates session recovery and approval integration.

The Recovery Manager is a stateless orchestrator that validates recovered
sessions, fixes task states for crash recovery, reconstructs scheduler
state from session state, and resumes execution via the pipeline.

It does not execute tasks, know about adapters, bypass the StateMachine,
or modify RetryPolicies.
"""

from __future__ import annotations

from services.execution.enums import TaskState
from services.execution.exceptions import ExecutionStateError
from services.execution.execution_models import ExecutionSession
from services.execution.scheduler import Scheduler
from services.execution.state_machine import StateMachine


class RecoveryError(Exception):
    """Raised when session validation or recovery fails."""

    def __init__(self, message: str, *, context: dict | None = None):
        super().__init__(message)
        self.context = context or {}


class RecoveryManager:
    """Stateless orchestrator for session recovery.

    All methods are static. No mutable state is maintained.
    """

    @staticmethod
    def validate(session: ExecutionSession) -> None:
        """Validate a session for recovery.

        Checks:
          - Session has tasks
          - All tasks have valid states (not None)
          - Dependency graph is internally consistent
          - No circular dependencies (enforced by scheduler's in-degree)
          - Retry counters are not negative

        Raises RecoveryError on any validation failure.
        """
        if not session.tasks:
            raise RecoveryError(
                "Session has no tasks",
                context={"session_id": session.id},
            )

        errors: list[str] = []

        for tid, etask in session.tasks.items():
            if etask.status is None:
                errors.append(f"Task {tid} has None status")

            if etask.attempts < 0:
                errors.append(f"Task {tid} has negative attempts: {etask.attempts}")

            if etask.max_attempts < 1:
                errors.append(
                    f"Task {tid} has invalid max_attempts: {etask.max_attempts}"
                )

            if RecoveryManager._has_self_dependency(etask):
                errors.append(f"Task {tid} depends on itself")

            deps = RecoveryManager._get_deps(etask)
            for dep_id in deps:
                if dep_id not in session.tasks:
                    errors.append(
                        f"Task {tid} depends on unknown task {dep_id}"
                    )

        if not errors and RecoveryManager._has_circular_dependency(session):
            errors.append("Circular dependency detected")

        # Check for circular dependencies by verifying in-degree builds
        # (backup check — should be caught above)
        try:
            scheduler = Scheduler(session)
            scheduler.initialize()
        except Exception as e:
            errors.append(f"Scheduler initialization failed: {e}")

        if errors:
            raise RecoveryError(
                "Session validation failed: " + "; ".join(errors),
                context={"errors": errors, "session_id": session.id},
            )

    @staticmethod
    def _has_self_dependency(etask) -> bool:
        deps = RecoveryManager._get_deps(etask)
        return etask.id in deps if hasattr(etask, "id") else False

    @staticmethod
    def _has_circular_dependency(session: ExecutionSession) -> bool:
        """Detect circular dependencies via DFS cycle detection."""
        adj: dict[str, list[str]] = {}
        for tid, etask in session.tasks.items():
            adj[tid] = RecoveryManager._get_deps(etask)
        visited: set[str] = set()
        rec_stack: set[str] = set()

        def dfs(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)
            for neighbor in adj.get(node, []):
                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True
            rec_stack.discard(node)
            return False

        for tid in adj:
            if tid not in visited:
                if dfs(tid):
                    return True
        return False

    @staticmethod
    def fix_states(session: ExecutionSession) -> list[str]:
        """Fix task states for recovery.

        Recovery semantics:
          - RUNNING  → READY    (adapter cannot be assumed safe)
          - RETRYING → WAITING  (interrupted retry countdown)
          - WAITING  → READY    (interrupted retry sleep, re-dispatch)

        Returns a list of task IDs whose states were modified.
        """
        modified: list[str] = []

        for tid, etask in session.tasks.items():
            if etask.status == TaskState.RUNNING:
                try:
                    StateMachine.transition_task(etask, TaskState.READY)
                    modified.append(tid)
                except ExecutionStateError:
                    pass

            elif etask.status == TaskState.RETRYING:
                try:
                    StateMachine.transition_task(etask, TaskState.WAITING)
                    modified.append(tid)
                except ExecutionStateError:
                    pass

            elif etask.status == TaskState.WAITING:
                try:
                    StateMachine.transition_task(etask, TaskState.READY)
                    modified.append(tid)
                except ExecutionStateError:
                    pass

        return modified

    @staticmethod
    def rebuild_scheduler(session: ExecutionSession) -> Scheduler:
        """Reconstruct scheduler state from a recovered session.

        Builds the in-degree map, then processes all terminal tasks
        to correctly set dependency satisfaction state, and enqueues
        any tasks already in READY state.

        The scheduler behaves exactly as if execution had never stopped.
        """
        scheduler = Scheduler(session)
        scheduler.initialize()

        # Process COMPLETED tasks to release downstream dependencies
        for tid, etask in session.tasks.items():
            if etask.status == TaskState.COMPLETED:
                scheduler.mark_completed(tid)

        # Process FAILED tasks to block downstream
        for tid, etask in session.tasks.items():
            if etask.status == TaskState.FAILED:
                scheduler.mark_failed(tid)

        # Process SKIPPED tasks to propagate
        for tid, etask in session.tasks.items():
            if etask.status == TaskState.SKIPPED:
                scheduler.mark_skipped(tid)

        return scheduler

    @staticmethod
    def _get_deps(etask) -> list[str]:
        """Extract dependency list from a task."""
        return list(getattr(etask.plan_task, "dependencies", []))

    @staticmethod
    def _task_count_by_state(session: ExecutionSession) -> dict[str, int]:
        """Count tasks in each state (for validation/diagnostics)."""
        counts: dict[str, int] = {}
        for etask in session.tasks.values():
            state = etask.status.value if etask.status else "unknown"
            counts[state] = counts.get(state, 0) + 1
        return counts

    @staticmethod
    def _verify_dependency_integrity(
        session: ExecutionSession,
        scheduler: Scheduler,
    ) -> list[str]:
        """Verify dependency consistency after scheduler rebuild.

        Checks that:
          - All terminal tasks have been accounted for in the in-degree map
          - No task has an unexpectedly negative remaining count
          - READY tasks have remaining == 0

        Returns a list of integrity warnings (empty = clean).
        """
        warnings: list[str] = []
        for tid, etask in session.tasks.items():
            entry = scheduler.in_degree.get(tid)
            if entry is None:
                warnings.append(f"Task {tid} missing from in-degree map")
                continue
            if entry.remaining < 0:
                warnings.append(
                    f"Task {tid} has negative remaining count: {entry.remaining}"
                )
            if etask.status == TaskState.READY and entry.remaining > 0:
                warnings.append(
                    f"Task {tid} is READY but has {entry.remaining} remaining deps"
                )
        return warnings
