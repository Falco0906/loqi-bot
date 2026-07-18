"""Execution Pipeline — main orchestration entry point.

The pipeline stages are:
  1. validate    — plan validation
  2. create      — session creation
  3. initialize  — task wrapping, in-degree map, root task identification
  4. run         — execution loop (Phase 3.6.4E)
  5. finalize    — session completion

The execution loop coordinates the scheduler, dispatcher, and state
machine to execute all tasks in a plan until the session reaches a
terminal or stable state.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from services.execution.dispatcher import AdapterResolver, Dispatcher
from services.execution.enums import SessionState, TaskState
from services.execution.exceptions import (
    ExecutionDispatchError,
    ExecutionSessionError,
)
from services.execution.execution_context import ExecutionContext
from services.execution.execution_models import (
    ExecutionEvent,
    ExecutionMetrics,
    ExecutionSession,
    ExecutionTask,
    ExecutionResult,
    RetryPolicy,
    TaskResult,
)
from services.execution.scheduler import Scheduler
from services.execution.state_machine import StateMachine
from services.execution.utils import (
    build_in_degree_map,
    generate_session_id,
    identify_root_tasks,
    init_metrics,
    wrap_task,
)
from services.execution.validation import (
    validate_plan_for_execution,
    validate_session_initialization,
)


class ExecutionEngine:
    """Main orchestrator for plan execution.

    Validates plans, creates sessions, and runs the execution loop
    to execute all tasks until the session reaches a terminal or
    stable state.
    """

    def __init__(self):
        self._sessions: dict[str, ExecutionSession] = {}

    async def execute(
        self,
        plan: Any,
        resolver: Optional[AdapterResolver] = None,
    ) -> ExecutionSession:
        """Execute a validated plan.

        Stages:
          1. validate   — run execution-level validation
          2. create     — build ExecutionSession
          3. initialize — wrap tasks, build in-degree map
          4. run        — execution loop (until terminal or stuck)
          5. finalize   — derive session state, set end time

        When no resolver is provided, the pipeline raises NotImplementedError
        at the dispatch boundary (backward-compatible with Phase 3.6.4B/C tests).

        When a resolver is provided, the pipeline executes all tasks in a
        continuous loop until the session is terminal or no more tasks can
        be dispatched.

        Returns:
            The completed ExecutionSession.

        Raises:
            NotImplementedError: When no resolver is provided (legacy path).
        """
        validate_plan_for_execution(plan)

        session = self._create_session(plan)
        self._initialize(session)
        validate_session_initialization(session)

        scheduler = Scheduler(session)
        scheduler.initialize()

        self._sessions[session.id] = session

        await self._run_scheduler(session, scheduler, resolver)

        return session

    async def _run_scheduler(
        self,
        session: ExecutionSession,
        scheduler: Scheduler,
        resolver: Optional[AdapterResolver] = None,
    ) -> None:
        """Run the scheduler loop.

        Two modes:
          - No resolver: legacy mode — stops at first runnable task
            and raises NotImplementedError (backward compatible).
          - With resolver: full execution loop — executes tasks until
            the session is terminal or no more tasks can be dispatched.
        """
        if resolver is None:
            await self._legacy_scheduler_step(session, scheduler)
        else:
            await self._execution_loop(session, scheduler, resolver)
            session.status = StateMachine.derive_session_state(session)
            if session.status.is_terminal:
                session.end_time = datetime.now(timezone.utc)
            session.updated_at = datetime.now(timezone.utc)

    async def _legacy_scheduler_step(
        self,
        session: ExecutionSession,
        scheduler: Scheduler,
    ) -> None:
        """Legacy single-step scheduler (backward compatible).

        Stops at the first runnable task and raises NotImplementedError.
        Used when no resolver is provided.
        """
        if scheduler.is_terminal():
            self._finalize(session, scheduler)
            return

        next_task_id = scheduler.get_next_ready()

        if next_task_id is not None:
            task = session.tasks[next_task_id]
            StateMachine.transition_task(task, TaskState.RUNNING)
            raise NotImplementedError(
                f"Execution dispatcher will be implemented in "
                f"Phase 3.6.4C. Next runnable task: {next_task_id}"
            )

        if scheduler.ready_count() == 0 and scheduler.running_count() == 0:
            remaining = [
                tid
                for tid, et in session.tasks.items()
                if not et.status.is_terminal
            ]
            if remaining:
                raise NotImplementedError(
                    f"Execution dispatcher will be implemented in "
                    f"Phase 3.6.4C. "
                    f"Remaining non-terminal tasks (waiting/approval): {remaining}"
                )

        self._finalize(session, scheduler)

    async def _execution_loop(
        self,
        session: ExecutionSession,
        scheduler: Scheduler,
        resolver: AdapterResolver,
    ) -> None:
        """Full execution loop.

        Iterates: while scheduler has work → dispatch → handle result.
        Stops when the scheduler is terminal or no more ready tasks.
        """
        while not scheduler.is_terminal():
            next_task_id = scheduler.get_next_ready()
            if next_task_id is None:
                break

            task = session.tasks[next_task_id]
            await self._execute_task(task, session, scheduler, resolver)

    async def _execute_task(
        self,
        task: ExecutionTask,
        session: ExecutionSession,
        scheduler: Scheduler,
        resolver: AdapterResolver,
    ) -> None:
        """Execute a single task: dispatch and handle the result."""
        StateMachine.transition_task(task, TaskState.RUNNING)

        context = ExecutionContext(session_id=session.id)
        result = await self._dispatch_safe(task, context, resolver)
        await self._handle_result(task, scheduler, result)

    @staticmethod
    async def _dispatch_safe(
        task: ExecutionTask,
        context: ExecutionContext,
        resolver: AdapterResolver,
    ) -> TaskResult:
        """Dispatch a task, converting failures to TaskResult.

        Catches ExecutionDispatchError (unsupported task) and unexpected
        adapter exceptions, converting both into permanent failure
        TaskResults.
        """
        try:
            return await Dispatcher.dispatch(task, context, resolver)
        except ExecutionDispatchError as e:
            return TaskResult(
                task_id=task.id,
                attempt=task.attempts,
                success=False,
                error=str(e),
                error_type="permanent",
                metadata={"unsupported_task": True},
            )
        except Exception as e:
            return TaskResult(
                task_id=task.id,
                attempt=task.attempts,
                success=False,
                error=f"Adapter execution failed: {e}",
                error_type="permanent",
                metadata={"adapter_exception": type(e).__name__},
            )

    @staticmethod
    async def _handle_result(
        task: ExecutionTask,
        scheduler: Scheduler,
        result: TaskResult,
    ) -> None:
        """Handle a dispatch result.

        Success  → transition COMPLETED, mark completed in scheduler.
        Failure  → transition FAILED, mark failed in scheduler.
        """
        task.result = result

        if result.success:
            StateMachine.transition_task(task, TaskState.COMPLETED)
            scheduler.mark_completed(task.id)
        else:
            StateMachine.transition_task(task, TaskState.FAILED)
            scheduler.mark_failed(task.id)

    def _create_session(self, plan: Any) -> ExecutionSession:
        """Create an ExecutionSession from a validated Plan."""
        session_id = generate_session_id()
        now = datetime.now(timezone.utc)
        session = ExecutionSession(
            id=session_id,
            plan_id=plan.id,
            plan=plan,
            conversation_id=getattr(plan, "conversation_id", ""),
            status=SessionState.PENDING,
            created_at=now,
            updated_at=now,
            metadata=getattr(plan, "metadata", {}).copy(),
        )
        return session

    def _initialize(self, session: ExecutionSession) -> None:
        """Initialize runtime state for a session.

        Wraps each Plan Task into an ExecutionTask, builds the in-degree
        map, identifies root tasks, and initializes metrics.
        """
        default_policy = RetryPolicy.default()

        for plan_task in session.plan.tasks:
            etask = wrap_task(plan_task, default_policy)
            session.tasks[plan_task.id] = etask

        session.root_tasks = identify_root_tasks(session.tasks)
        session.status = SessionState.PENDING
        session.updated_at = datetime.now(timezone.utc)

    def _finalize(
        self,
        session: ExecutionSession,
        scheduler: Optional[Scheduler] = None,
    ) -> None:
        """Finalize a session, setting its terminal state."""
        if scheduler is not None:
            terminal = scheduler.get_terminal_state()
        else:
            terminal = self._derive_terminal(session)

        state_map = {
            "completed": SessionState.COMPLETED,
            "completed_with_errors": SessionState.COMPLETED_WITH_ERRORS,
            "failed": SessionState.FAILED,
            "cancelled": SessionState.CANCELLED,
        }
        session.status = state_map.get(terminal, SessionState.COMPLETED)
        session.end_time = datetime.now(timezone.utc)
        session.updated_at = session.end_time

    @staticmethod
    def _derive_terminal(session: ExecutionSession) -> str:
        """Derive terminal state name without a scheduler."""
        states = {t.status for t in session.tasks.values()}
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

    def get_session(self, session_id: str) -> Optional[ExecutionSession]:
        """Retrieve a session by ID."""
        return self._sessions.get(session_id)

    def cancel(self, session_id: str) -> ExecutionSession:
        """Cancel an active session."""
        session = self._get_active_session(session_id)
        if session.status.is_terminal:
            raise ExecutionSessionError(
                f"Cannot cancel session {session_id}: already terminal "
                f"({session.status.value})"
            )
        session.status = SessionState.CANCELLED
        session.end_time = datetime.now(timezone.utc)
        session.updated_at = session.end_time
        for etask in session.tasks.values():
            if not etask.status.is_terminal:
                StateMachine.transition_task(etask, TaskState.CANCELLED)
        return session

    def pause(self, session_id: str) -> ExecutionSession:
        """Pause an active session."""
        session = self._get_active_session(session_id)
        if session.status != SessionState.RUNNING:
            raise ExecutionSessionError(
                f"Cannot pause session {session_id}: "
                f"status is {session.status.value} (expected RUNNING)"
            )
        session.status = SessionState.PAUSED
        session.updated_at = datetime.now(timezone.utc)
        return session

    def resume(self, session_id: str) -> ExecutionSession:
        """Resume a paused session."""
        session = self._get_active_session(session_id)
        if session.status != SessionState.PAUSED:
            raise ExecutionSessionError(
                f"Cannot resume session {session_id}: "
                f"status is {session.status.value} (expected PAUSED)"
            )
        session.status = SessionState.RUNNING
        session.updated_at = datetime.now(timezone.utc)
        return session

    def approve(self, session_id: str, task_id: str) -> ExecutionSession:
        """Approve a task awaiting approval."""
        session = self._get_active_session(session_id)
        etask = session.tasks.get(task_id)
        if etask is None:
            raise ExecutionSessionError(
                f"Task {task_id} not found in session {session_id}"
            )
        if etask.status != TaskState.WAITING_APPROVAL:
            raise ExecutionSessionError(
                f"Cannot approve task {task_id}: "
                f"status is {etask.status.value} (expected WAITING_APPROVAL)"
            )
        StateMachine.transition_task(etask, TaskState.READY)
        session.updated_at = datetime.now(timezone.utc)
        return session

    def reject(self, session_id: str, task_id: str) -> ExecutionSession:
        """Reject a task awaiting approval."""
        session = self._get_active_session(session_id)
        etask = session.tasks.get(task_id)
        if etask is None:
            raise ExecutionSessionError(
                f"Task {task_id} not found in session {session_id}"
            )
        if etask.status != TaskState.WAITING_APPROVAL:
            raise ExecutionSessionError(
                f"Cannot reject task {task_id}: "
                f"status is {etask.status.value} (expected WAITING_APPROVAL)"
            )
        StateMachine.transition_task(etask, TaskState.SKIPPED)
        session.updated_at = datetime.now(timezone.utc)
        return session

    def get_scheduler(self, session_id: str) -> Scheduler:
        """Create a scheduler for an existing session (for testing/replay)."""
        session = self._get_active_session(session_id)
        scheduler = Scheduler(session)
        scheduler.initialize()
        return scheduler

    def _get_active_session(self, session_id: str) -> ExecutionSession:
        """Get a session, raising if not found."""
        session = self._sessions.get(session_id)
        if session is None:
            raise ExecutionSessionError(
                f"Session {session_id} not found"
            )
        return session


# Singleton accessor
_pipeline: ExecutionEngine | None = None


def get_pipeline() -> ExecutionEngine:
    """Get the global ExecutionEngine singleton."""
    global _pipeline
    if _pipeline is None:
        _pipeline = ExecutionEngine()
    return _pipeline