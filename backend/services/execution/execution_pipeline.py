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

import asyncio
import random
from datetime import datetime, timezone
from typing import Any, Optional

from services.execution.dispatcher import AdapterResolver, Dispatcher
from services.execution.enums import ExecutionEventType, SessionState, TaskState
from services.execution.event_bus import EventBus
from services.execution.exceptions import (
    ExecutionDispatchError,
    ExecutionSessionError,
)
from services.execution.recovery_manager import RecoveryError, RecoveryManager
from services.execution.execution_context import ExecutionContext
from services.execution.execution_models import (
    ExecutionEvent,
    ExecutionMetrics,
    ExecutionSession,
    ExecutionTask,
    ExecutionResult,
    RetryDecision,
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


# Default timeout (seconds) for adapter execution.
# When exceeded, the task is failed with a transient error so the
# retry engine can re-attempt.
_ADAPTER_EXECUTION_TIMEOUT = 30.0


class ExecutionEngine:
    """Main orchestrator for plan execution.

    Validates plans, creates sessions, and runs the execution loop
    to execute all tasks until the session reaches a terminal or
    stable state.
    """

    def __init__(self, event_bus: Optional[EventBus] = None):
        self._sessions: dict[str, ExecutionSession] = {}
        self._schedulers: dict[str, Scheduler] = {}
        self.event_bus = event_bus or EventBus()

    async def execute(
        self,
        plan: Any,
        resolver: Optional[AdapterResolver] = None,
        retry_policy: Optional[RetryPolicy] = None,
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

        Args:
            plan: The validated Plan to execute.
            resolver: Optional adapter resolver for dispatching tasks.
            retry_policy: Optional override for the default RetryPolicy.
                          When None, RetryPolicy.default() is used.

        Returns:
            The completed ExecutionSession.

        Raises:
            NotImplementedError: When no resolver is provided (legacy path).
        """
        validate_plan_for_execution(plan)

        session = self._create_session(plan)
        self._initialize(session, retry_policy)
        validate_session_initialization(session)

        scheduler = Scheduler(session)
        scheduler.initialize()

        self._sessions[session.id] = session
        self._schedulers[session.id] = scheduler
        session.start_time = datetime.now(timezone.utc)

        self.event_bus.publish(
            ExecutionEvent(
                session_id=session.id,
                event_type=ExecutionEventType.SESSION_STARTED,
                data={
                    "plan_id": session.plan_id,
                    "task_count": len(session.tasks),
                },
            )
        )

        await self._run_scheduler(session, scheduler, resolver)

        self._schedulers.pop(session.id, None)

        return session

    async def recover(
        self,
        session: ExecutionSession,
        resolver: AdapterResolver,
    ) -> ExecutionSession:
        """Recover and resume execution of a previously interrupted session.

        Stages:
          1. validate  — verify session integrity
          2. fix       — apply recovery state transitions
          3. rebuild   — reconstruct scheduler from session state
          4. run       — invoke the same execution loop as fresh execution

        Args:
            session: The recovered ExecutionSession.
            resolver: Adapter resolver for dispatching tasks.

        Returns:
            The completed ExecutionSession.

        Raises:
            RecoveryError: If session validation fails.
        """
        RecoveryManager.validate(session)
        RecoveryManager.fix_states(session)
        scheduler = RecoveryManager.rebuild_scheduler(session)

        self._sessions[session.id] = session
        self._schedulers[session.id] = scheduler
        session.start_time = datetime.now(timezone.utc)

        self.event_bus.publish(
            ExecutionEvent(
                session_id=session.id,
                event_type=ExecutionEventType.SESSION_STARTED,
                data={
                    "session_id": session.id,
                    "reason": "recovery",
                },
            )
        )

        await self._run_scheduler(session, scheduler, resolver)

        self._schedulers.pop(session.id, None)

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

            event_type = (
                ExecutionEventType.SESSION_COMPLETED
                if session.status == SessionState.COMPLETED
                else ExecutionEventType.SESSION_FAILED
            )
            self.event_bus.publish(
                ExecutionEvent(
                    session_id=session.id,
                    event_type=event_type,
                    data={"status": session.status.value},
                )
            )

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
        self.event_bus.publish(
            ExecutionEvent(
                session_id=session.id,
                task_id=task.id,
                event_type=ExecutionEventType.TASK_READY,
                data={"task_type": task.plan_task.type.value},
            )
        )

        is_retry = task.attempts > 0
        StateMachine.transition_task(task, TaskState.RUNNING)

        self.event_bus.publish(
            ExecutionEvent(
                session_id=session.id,
                task_id=task.id,
                event_type=(
                    ExecutionEventType.TASK_RETRY_STARTED
                    if is_retry
                    else ExecutionEventType.TASK_STARTED
                ),
                data={
                    "attempt": task.attempts,
                    "task_type": task.plan_task.type.value,
                },
            )
        )

        context = ExecutionContext(session_id=session.id)

        started_at = datetime.now(timezone.utc)
        result = await self._dispatch_safe(task, context, resolver)
        completed_at = datetime.now(timezone.utc)

        result.started_at = started_at
        result.completed_at = completed_at
        result.duration_ms = int(
            (completed_at - started_at).total_seconds() * 1000
        )

        await self._handle_result(task, session, scheduler, result)

    @staticmethod
    async def _dispatch_safe(
        task: ExecutionTask,
        context: ExecutionContext,
        resolver: AdapterResolver,
    ) -> TaskResult:
        """Dispatch a task, converting failures to TaskResult.

        Catches ExecutionDispatchError (unsupported task),
        asyncio.TimeoutError (adapter hung), and unexpected adapter
        exceptions, converting all into appropriately classified
        TaskResults.

        Timeout errors are classified as ``transient`` so the retry
        engine can re-attempt.  All other errors are ``permanent``.

        The adapter execution timeout is controlled by the module-level
        ``_ADAPTER_EXECUTION_TIMEOUT`` constant (default 30 seconds).
        """
        timeout = _ADAPTER_EXECUTION_TIMEOUT
        try:
            return await asyncio.wait_for(
                Dispatcher.dispatch(task, context, resolver),
                timeout=timeout,
            )
        except ExecutionDispatchError as e:
            return TaskResult(
                task_id=task.id,
                attempt=task.attempts,
                success=False,
                error=str(e),
                error_type="permanent",
                metadata={"unsupported_task": True},
            )
        except asyncio.TimeoutError:
            return TaskResult(
                task_id=task.id,
                attempt=task.attempts,
                success=False,
                error=(
                    f"Adapter execution timed out after {timeout}s"
                ),
                error_type="transient",
                metadata={"adapter_timeout": True},
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            return TaskResult(
                task_id=task.id,
                attempt=task.attempts,
                success=False,
                error=f"Adapter execution failed: {e}",
                error_type="permanent",
                metadata={"adapter_exception": type(e).__name__},
            )

    async def _handle_result(
        self,
        task: ExecutionTask,
        session: ExecutionSession,
        scheduler: Scheduler,
        result: TaskResult,
    ) -> None:
        """Handle a dispatch result with retry support.

        Success         → COMPLETED, mark_completed.
        Transient fail  → retry if attempts remain, else FAILED.
        Permanent fail  → FAILED, mark_failed.
        """
        task.result = result

        if result.success:
            await self._handle_success(task, session, scheduler)
        else:
            await self._handle_failure(task, session, scheduler, result)

    async def _handle_success(
        self,
        task: ExecutionTask,
        session: ExecutionSession,
        scheduler: Scheduler,
    ) -> None:
        """Handle a successful task result."""
        StateMachine.transition_task(task, TaskState.COMPLETED)
        scheduler.mark_completed(task.id)

        self.event_bus.publish(
            ExecutionEvent(
                session_id=session.id,
                task_id=task.id,
                event_type=ExecutionEventType.TASK_COMPLETED,
                data={
                    "task_type": task.plan_task.type.value,
                    "attempts": task.attempts,
                },
            )
        )

    async def _handle_failure(
        self,
        task: ExecutionTask,
        session: ExecutionSession,
        scheduler: Scheduler,
        result: TaskResult,
    ) -> None:
        """Handle a failed task result — retry transient or fail permanently."""
        decision = self._should_retry(task, result)
        if decision.should_retry:
            self.event_bus.publish(
                ExecutionEvent(
                    session_id=session.id,
                    task_id=task.id,
                    event_type=ExecutionEventType.TASK_RETRY_SCHEDULED,
                    data={
                        "delay_seconds": decision.delay_seconds,
                        "remaining_attempts": decision.remaining_attempts,
                        "task_type": task.plan_task.type.value,
                        "error": result.error,
                    },
                )
            )
            await self._schedule_retry(task, scheduler, decision)
        else:
            if task.attempts > 0:
                self.event_bus.publish(
                    ExecutionEvent(
                        session_id=session.id,
                        task_id=task.id,
                        event_type=ExecutionEventType.TASK_RETRY_EXHAUSTED,
                        data={
                            "task_type": task.plan_task.type.value,
                            "attempts": task.attempts,
                            "error": result.error,
                        },
                    )
                )

            StateMachine.transition_task(task, TaskState.FAILED)

            self.event_bus.publish(
                ExecutionEvent(
                    session_id=session.id,
                    task_id=task.id,
                    event_type=ExecutionEventType.TASK_FAILED,
                    data={
                        "task_type": task.plan_task.type.value,
                        "error": result.error,
                        "error_type": result.error_type,
                        "attempts": task.attempts,
                    },
                )
            )

            skipped = scheduler.mark_failed(task.id)
            for skipped_id in skipped:
                self.event_bus.publish(
                    ExecutionEvent(
                        session_id=session.id,
                        task_id=skipped_id,
                        event_type=ExecutionEventType.TASK_SKIPPED,
                        data={
                            "task_type": session.tasks[skipped_id].plan_task.type.value,
                            "reason": "upstream_failure",
                        },
                    )
                )

    # ------------------------------------------------------------------
    # Retry helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_backoff(task: ExecutionTask) -> float:
        """Compute the retry delay using the task's RetryPolicy.

        Applies exponential backoff, max delay cap, and optional jitter.
        The attempt count used for the backoff exponent is the *next*
        attempt (i.e., the retry being scheduled), which is
        ``task.attempts`` before increment (0-based).
        """
        policy = task.retry_policy
        delay = policy.backoff_base_seconds * (policy.backoff_multiplier ** task.attempts)
        delay = min(delay, policy.max_backoff_seconds)
        if policy.jitter:
            delay *= random.uniform(0.5, 1.5)
        return delay

    @staticmethod
    def _should_retry(task: ExecutionTask, result: TaskResult) -> RetryDecision:
        """Evaluate whether a task should be retried.

        A retry occurs only when:
          - The result is a failure (success=False)
          - The error type is in the task's retryable_error_types set
          - The task has remaining attempts according to its RetryPolicy

        Returns a RetryDecision with the computed delay and remaining count.
        """
        if result.success:
            return RetryDecision(should_retry=False)
        if result.error_type not in task.retry_policy.retryable_error_types:
            return RetryDecision(should_retry=False)

        next_attempt = task.attempts + 1
        remaining = task.max_attempts - next_attempt
        if remaining <= 0:
            return RetryDecision(should_retry=False)

        delay = ExecutionEngine._compute_backoff(task)

        return RetryDecision(
            should_retry=True,
            delay_seconds=delay,
            remaining_attempts=remaining,
        )

    @staticmethod
    async def _schedule_retry(
        task: ExecutionTask,
        scheduler: Scheduler,
        decision: RetryDecision,
    ) -> None:
        """Execute a retry: transition states, increment attempts, wait, requeue.

        Attempts are incremented *after* both state transitions succeed to
        avoid leaving the task with an inconsistent attempt count if a
        transition fails.
        """
        StateMachine.transition_task(task, TaskState.RETRYING)
        StateMachine.transition_task(task, TaskState.WAITING)
        task.attempts += 1
        await asyncio.sleep(decision.delay_seconds)
        scheduler.requeue(task.id)

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

    def _initialize(self, session: ExecutionSession, retry_policy: Optional[RetryPolicy] = None) -> None:
        """Initialize runtime state for a session.

        Wraps each Plan Task into an ExecutionTask, builds the in-degree
        map, identifies root tasks, and initializes metrics.
        """
        default_policy = retry_policy or RetryPolicy.default()

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
                self.event_bus.publish(
                    ExecutionEvent(
                        session_id=session.id,
                        task_id=etask.id,
                        event_type=ExecutionEventType.TASK_CANCELLED,
                        data={"task_type": etask.plan_task.type.value},
                    )
                )

        self.event_bus.publish(
            ExecutionEvent(
                session_id=session.id,
                event_type=ExecutionEventType.SESSION_CANCELLED,
                data={"status": session.status.value},
            )
        )

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
        scheduler = self._schedulers.get(session_id)
        if scheduler:
            scheduler.requeue(task_id)
        else:
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

        scheduler = self._schedulers.get(session_id)
        if scheduler:
            skipped = scheduler.mark_skipped(task_id)
            for skipped_id in skipped:
                skipped_task = session.tasks.get(skipped_id)
                task_type = skipped_task.plan_task.type.value if skipped_task else "unknown"
                self.event_bus.publish(
                    ExecutionEvent(
                        session_id=session.id,
                        task_id=skipped_id,
                        event_type=ExecutionEventType.TASK_SKIPPED,
                        data={
                            "task_type": task_type,
                            "reason": "approval_rejected_cascade",
                        },
                    )
                )

        self.event_bus.publish(
            ExecutionEvent(
                session_id=session.id,
                task_id=etask.id,
                event_type=ExecutionEventType.TASK_SKIPPED,
                data={
                    "task_type": etask.plan_task.type.value,
                    "reason": "approval_rejected",
                },
            )
        )

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