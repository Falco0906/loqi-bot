"""Unit tests for the Execution Engine Scheduler & State Machine (Phase 3.6.4B).

Tests state machine transitions, scheduler DAG management, ready queue,
terminal detection, and pipeline integration.
"""

from __future__ import annotations

import asyncio
import pytest
from datetime import datetime, timezone

from services.execution.enums import SessionState, TaskState
from services.execution.exceptions import (
    ExecutionSchedulingError,
    ExecutionSessionError,
    ExecutionStateError,
)
from services.execution.execution_models import (
    ExecutionSession,
    ExecutionTask,
    InDegreeEntry,
    RetryPolicy,
)
from services.execution.execution_pipeline import ExecutionEngine
from services.execution.scheduler import Scheduler
from services.execution.state_machine import StateMachine
from services.execution.utils import wrap_task

from services.planner.planning_models import (
    Plan, PlanGoal, Task, PlanStatus, TaskStatus, TaskType,
)
from services.planner.payloads import MessagePayload


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def linear_plan():
    """A linear plan: task-a → task-b → task-c."""
    plan = Plan(
        id="linear-plan",
        conversation_id="conv-1",
        status=PlanStatus.VALIDATED,
        goal=PlanGoal(outcome="test"),
    )
    tasks = [
        Task(
            id="task-a", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="telegram", template="first"),
            label="first",
        ),
        Task(
            id="task-b", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="telegram", template="second"),
            dependencies=["task-a"], label="second",
        ),
        Task(
            id="task-c", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="telegram", template="third"),
            dependencies=["task-b"], label="third",
        ),
    ]
    plan.tasks = tasks
    return plan


@pytest.fixture
def diamond_plan():
    """A diamond plan: a → (b, c) → d."""
    plan = Plan(
        id="diamond-plan",
        conversation_id="conv-2",
        status=PlanStatus.VALIDATED,
        goal=PlanGoal(outcome="test"),
    )
    tasks = [
        Task(
            id="task-a", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="telegram", template="root"),
            label="root",
        ),
        Task(
            id="task-b", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="telegram", template="left"),
            dependencies=["task-a"], label="left",
        ),
        Task(
            id="task-c", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="telegram", template="right"),
            dependencies=["task-a"], label="right",
        ),
        Task(
            id="task-d", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="telegram", template="join"),
            dependencies=["task-b", "task-c"], label="join",
        ),
    ]
    plan.tasks = tasks
    return plan


@pytest.fixture
def independent_plan():
    """Three independent tasks with no dependencies."""
    plan = Plan(
        id="independent-plan",
        conversation_id="conv-3",
        status=PlanStatus.VALIDATED,
        goal=PlanGoal(outcome="test"),
    )
    tasks = [
        Task(
            id="task-1", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="telegram", template="one"),
            label="one",
        ),
        Task(
            id="task-2", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="telegram", template="two"),
            label="two",
        ),
        Task(
            id="task-3", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="telegram", template="three"),
            label="three",
        ),
    ]
    plan.tasks = tasks
    return plan


@pytest.fixture
def session_from_plan(linear_plan):
    """Build an ExecutionSession from a plan with tasks wrapped."""
    session = ExecutionSession(
        id="test-session",
        plan_id=linear_plan.id,
        plan=linear_plan,
        conversation_id=linear_plan.conversation_id,
        status=SessionState.PENDING,
    )
    for pt in linear_plan.tasks:
        etask = wrap_task(pt)
        session.tasks[pt.id] = etask
    session.root_tasks = [t.id for t in linear_plan.get_root_tasks()]
    return session


@pytest.fixture
def engine():
    return ExecutionEngine()


# ===================================================================
# STATE MACHINE TESTS
# ===================================================================

class TestTaskTransitions:
    """Every valid and invalid task transition."""

    def test_pending_to_ready(self, session_from_plan):
        task = session_from_plan.tasks["task-a"]
        StateMachine.transition_task(task, TaskState.READY)
        assert task.status == TaskState.READY

    def test_pending_to_waiting_approval(self, session_from_plan):
        task = session_from_plan.tasks["task-a"]
        StateMachine.transition_task(task, TaskState.WAITING_APPROVAL)
        assert task.status == TaskState.WAITING_APPROVAL

    def test_pending_to_cancelled(self, session_from_plan):
        task = session_from_plan.tasks["task-a"]
        StateMachine.transition_task(task, TaskState.CANCELLED)
        assert task.status == TaskState.CANCELLED

    def test_ready_to_running(self, session_from_plan):
        task = session_from_plan.tasks["task-a"]
        StateMachine.transition_task(task, TaskState.READY)
        StateMachine.transition_task(task, TaskState.RUNNING)
        assert task.status == TaskState.RUNNING

    def test_running_to_completed(self, session_from_plan):
        task = session_from_plan.tasks["task-a"]
        StateMachine.transition_task(task, TaskState.READY)
        StateMachine.transition_task(task, TaskState.RUNNING)
        StateMachine.transition_task(task, TaskState.COMPLETED)
        assert task.status == TaskState.COMPLETED

    def test_running_to_failed(self, session_from_plan):
        task = session_from_plan.tasks["task-a"]
        StateMachine.transition_task(task, TaskState.READY)
        StateMachine.transition_task(task, TaskState.RUNNING)
        StateMachine.transition_task(task, TaskState.FAILED)
        assert task.status == TaskState.FAILED

    def test_running_to_waiting(self, session_from_plan):
        task = session_from_plan.tasks["task-a"]
        StateMachine.transition_task(task, TaskState.READY)
        StateMachine.transition_task(task, TaskState.RUNNING)
        StateMachine.transition_task(task, TaskState.WAITING)
        assert task.status == TaskState.WAITING

    def test_running_to_retrying(self, session_from_plan):
        task = session_from_plan.tasks["task-a"]
        StateMachine.transition_task(task, TaskState.READY)
        StateMachine.transition_task(task, TaskState.RUNNING)
        StateMachine.transition_task(task, TaskState.RETRYING)
        assert task.status == TaskState.RETRYING

    def test_running_to_waiting_approval(self, session_from_plan):
        task = session_from_plan.tasks["task-a"]
        StateMachine.transition_task(task, TaskState.READY)
        StateMachine.transition_task(task, TaskState.RUNNING)
        StateMachine.transition_task(task, TaskState.WAITING_APPROVAL)
        assert task.status == TaskState.WAITING_APPROVAL

    def test_waiting_to_ready(self, session_from_plan):
        task = session_from_plan.tasks["task-a"]
        StateMachine.transition_task(task, TaskState.READY)
        StateMachine.transition_task(task, TaskState.RUNNING)
        StateMachine.transition_task(task, TaskState.WAITING)
        StateMachine.transition_task(task, TaskState.READY)
        assert task.status == TaskState.READY

    def test_waiting_to_failed(self, session_from_plan):
        task = session_from_plan.tasks["task-a"]
        StateMachine.transition_task(task, TaskState.READY)
        StateMachine.transition_task(task, TaskState.RUNNING)
        StateMachine.transition_task(task, TaskState.WAITING)
        StateMachine.transition_task(task, TaskState.FAILED)
        assert task.status == TaskState.FAILED

    def test_waiting_approval_to_ready(self, session_from_plan):
        task = session_from_plan.tasks["task-a"]
        StateMachine.transition_task(task, TaskState.WAITING_APPROVAL)
        StateMachine.transition_task(task, TaskState.READY)
        assert task.status == TaskState.READY

    def test_waiting_approval_to_skipped(self, session_from_plan):
        task = session_from_plan.tasks["task-a"]
        StateMachine.transition_task(task, TaskState.WAITING_APPROVAL)
        StateMachine.transition_task(task, TaskState.SKIPPED)
        assert task.status == TaskState.SKIPPED

    def test_retrying_to_ready(self, session_from_plan):
        task = session_from_plan.tasks["task-a"]
        StateMachine.transition_task(task, TaskState.READY)
        StateMachine.transition_task(task, TaskState.RUNNING)
        StateMachine.transition_task(task, TaskState.RETRYING)
        StateMachine.transition_task(task, TaskState.READY)
        assert task.status == TaskState.READY

    def test_retrying_to_failed(self, session_from_plan):
        task = session_from_plan.tasks["task-a"]
        StateMachine.transition_task(task, TaskState.READY)
        StateMachine.transition_task(task, TaskState.RUNNING)
        StateMachine.transition_task(task, TaskState.RETRYING)
        StateMachine.transition_task(task, TaskState.FAILED)
        assert task.status == TaskState.FAILED

    def test_blocked_to_skipped(self, session_from_plan):
        task = session_from_plan.tasks["task-a"]
        StateMachine.transition_task(task, TaskState.BLOCKED)
        StateMachine.transition_task(task, TaskState.SKIPPED)
        assert task.status == TaskState.SKIPPED

    def test_blocked_to_ready(self, session_from_plan):
        task = session_from_plan.tasks["task-a"]
        StateMachine.transition_task(task, TaskState.BLOCKED)
        StateMachine.transition_task(task, TaskState.READY)
        assert task.status == TaskState.READY

    def test_any_to_cancelled(self, session_from_plan):
        task = session_from_plan.tasks["task-a"]
        StateMachine.transition_task(task, TaskState.READY)
        StateMachine.transition_task(task, TaskState.RUNNING)
        StateMachine.transition_task(task, TaskState.CANCELLED)
        assert task.status == TaskState.CANCELLED

    def test_cancelled_from_pending(self, session_from_plan):
        task = session_from_plan.tasks["task-a"]
        StateMachine.transition_task(task, TaskState.CANCELLED)
        assert task.status == TaskState.CANCELLED

    def test_is_valid_task_transition(self):
        assert StateMachine.is_valid_task_transition(TaskState.PENDING, TaskState.READY) is True
        assert StateMachine.is_valid_task_transition(TaskState.COMPLETED, TaskState.RUNNING) is False
        assert StateMachine.is_valid_task_transition(TaskState.FAILED, TaskState.READY) is False
        assert StateMachine.is_valid_task_transition(TaskState.PENDING, TaskState.COMPLETED) is False

    def test_terminal_states_have_no_valid_transitions(self):
        for terminal in (TaskState.COMPLETED, TaskState.FAILED, TaskState.SKIPPED, TaskState.CANCELLED):
            for target in TaskState:
                assert StateMachine.is_valid_task_transition(terminal, target) is False


class TestInvalidTaskTransitions:
    """Every invalid transition must raise ExecutionStateError."""

    INVALID_PAIRS = [
        (TaskState.PENDING, TaskState.RUNNING),
        (TaskState.PENDING, TaskState.COMPLETED),
        (TaskState.PENDING, TaskState.FAILED),
        (TaskState.PENDING, TaskState.RETRYING),
        (TaskState.PENDING, TaskState.WAITING),
        (TaskState.READY, TaskState.COMPLETED),
        (TaskState.READY, TaskState.FAILED),
        (TaskState.READY, TaskState.BLOCKED),
        (TaskState.READY, TaskState.WAITING),
        (TaskState.READY, TaskState.WAITING_APPROVAL),
        (TaskState.READY, TaskState.RETRYING),
        (TaskState.READY, TaskState.READY),
        (TaskState.RUNNING, TaskState.READY),
        (TaskState.RUNNING, TaskState.BLOCKED),
        (TaskState.RUNNING, TaskState.SKIPPED),
        (TaskState.COMPLETED, TaskState.PENDING),
        (TaskState.COMPLETED, TaskState.READY),
        (TaskState.COMPLETED, TaskState.RUNNING),
        (TaskState.FAILED, TaskState.READY),
        (TaskState.FAILED, TaskState.RUNNING),
        (TaskState.FAILED, TaskState.COMPLETED),
        (TaskState.SKIPPED, TaskState.READY),
        (TaskState.SKIPPED, TaskState.RUNNING),
        (TaskState.SKIPPED, TaskState.COMPLETED),
        (TaskState.CANCELLED, TaskState.READY),
        (TaskState.CANCELLED, TaskState.RUNNING),
        (TaskState.CANCELLED, TaskState.COMPLETED),
        (TaskState.PENDING, TaskState.PENDING),
        (TaskState.RUNNING, TaskState.RUNNING),
    ]

    @pytest.mark.parametrize("from_state,to_state", INVALID_PAIRS)
    def test_invalid_transition_raises(self, from_state, to_state, session_from_plan):
        task = session_from_plan.tasks["task-a"]
        task.status = from_state
        with pytest.raises(ExecutionStateError):
            StateMachine.transition_task(task, to_state)
        assert task.status == from_state


class TestSessionTransitions:
    def test_pending_to_running(self, session_from_plan):
        StateMachine.transition_session(session_from_plan, SessionState.RUNNING)
        assert session_from_plan.status == SessionState.RUNNING

    def test_running_to_paused(self, session_from_plan):
        session_from_plan.status = SessionState.RUNNING
        StateMachine.transition_session(session_from_plan, SessionState.PAUSED)
        assert session_from_plan.status == SessionState.PAUSED

    def test_paused_to_running(self, session_from_plan):
        session_from_plan.status = SessionState.PAUSED
        StateMachine.transition_session(session_from_plan, SessionState.RUNNING)
        assert session_from_plan.status == SessionState.RUNNING

    def test_running_to_completed(self, session_from_plan):
        session_from_plan.status = SessionState.RUNNING
        StateMachine.transition_session(session_from_plan, SessionState.COMPLETED)
        assert session_from_plan.status == SessionState.COMPLETED

    def test_running_to_cancelled(self, session_from_plan):
        session_from_plan.status = SessionState.RUNNING
        StateMachine.transition_session(session_from_plan, SessionState.CANCELLED)
        assert session_from_plan.status == SessionState.CANCELLED

    def test_terminal_states_block(self, session_from_plan):
        session_from_plan.status = SessionState.COMPLETED
        with pytest.raises(ExecutionStateError):
            StateMachine.transition_session(session_from_plan, SessionState.RUNNING)

    def test_is_valid_session_transition(self):
        assert StateMachine.is_valid_session_transition(SessionState.PENDING, SessionState.RUNNING) is True
        assert StateMachine.is_valid_session_transition(SessionState.RUNNING, SessionState.PAUSED) is True
        assert StateMachine.is_valid_session_transition(SessionState.COMPLETED, SessionState.RUNNING) is False


class TestDeriveSessionState:
    def test_all_completed(self, session_from_plan):
        for etask in session_from_plan.tasks.values():
            StateMachine.transition_task(etask, TaskState.READY)
            StateMachine.transition_task(etask, TaskState.RUNNING)
            StateMachine.transition_task(etask, TaskState.COMPLETED)
        assert StateMachine.derive_session_state(session_from_plan) == SessionState.COMPLETED

    def test_some_failed_some_completed(self, session_from_plan):
        tasks = list(session_from_plan.tasks.values())
        StateMachine.transition_task(tasks[0], TaskState.READY)
        StateMachine.transition_task(tasks[0], TaskState.RUNNING)
        StateMachine.transition_task(tasks[0], TaskState.COMPLETED)
        StateMachine.transition_task(tasks[1], TaskState.READY)
        StateMachine.transition_task(tasks[1], TaskState.RUNNING)
        StateMachine.transition_task(tasks[1], TaskState.FAILED)
        # task-c depends on task-b which failed → should be skipped
        StateMachine.transition_task(tasks[2], TaskState.BLOCKED)
        StateMachine.transition_task(tasks[2], TaskState.SKIPPED)
        assert StateMachine.derive_session_state(session_from_plan) == SessionState.COMPLETED_WITH_ERRORS

    def test_all_failed(self, session_from_plan):
        for etask in session_from_plan.tasks.values():
            StateMachine.transition_task(etask, TaskState.READY)
            StateMachine.transition_task(etask, TaskState.RUNNING)
            StateMachine.transition_task(etask, TaskState.FAILED)
        assert StateMachine.derive_session_state(session_from_plan) == SessionState.FAILED

    def test_running_task(self, session_from_plan):
        tasks = list(session_from_plan.tasks.values())
        StateMachine.transition_task(tasks[0], TaskState.READY)
        StateMachine.transition_task(tasks[0], TaskState.RUNNING)
        assert StateMachine.derive_session_state(session_from_plan) == SessionState.RUNNING

    def test_waiting_approval(self, session_from_plan):
        tasks = list(session_from_plan.tasks.values())
        StateMachine.transition_task(tasks[0], TaskState.WAITING_APPROVAL)
        assert StateMachine.derive_session_state(session_from_plan) == SessionState.WAITING_APPROVAL

    def test_cancelled_task(self, session_from_plan):
        tasks = list(session_from_plan.tasks.values())
        StateMachine.transition_task(tasks[0], TaskState.CANCELLED)
        assert StateMachine.derive_session_state(session_from_plan) == SessionState.CANCELLED

    def test_ready_task(self, session_from_plan):
        tasks = list(session_from_plan.tasks.values())
        StateMachine.transition_task(tasks[0], TaskState.READY)
        assert StateMachine.derive_session_state(session_from_plan) == SessionState.RUNNING

    def test_empty_session(self):
        session = ExecutionSession(id="empty", plan=None)
        assert StateMachine.derive_session_state(session) == SessionState.FAILED


# ===================================================================
# SCHEDULER TESTS
# ===================================================================

class TestSchedulerInitialization:
    def test_initialize_linear_plan(self, session_from_plan):
        scheduler = Scheduler(session_from_plan)
        scheduler.initialize()
        assert scheduler._initialized is True
        assert scheduler.in_degree["task-a"].remaining == 0
        assert scheduler.in_degree["task-b"].remaining == 1
        assert scheduler.in_degree["task-c"].remaining == 1
        assert scheduler.ready_count() == 1
        assert scheduler.peek_ready() == "task-a"

    def test_initialize_diamond_plan(self, diamond_plan):
        session = _build_session(diamond_plan)
        scheduler = Scheduler(session)
        scheduler.initialize()
        assert scheduler.ready_count() == 1
        assert scheduler.peek_ready() == "task-a"

    def test_initialize_independent_plan(self, independent_plan):
        session = _build_session(independent_plan)
        scheduler = Scheduler(session)
        scheduler.initialize()
        assert scheduler.ready_count() == 3

    def test_double_initialize_raises(self, session_from_plan):
        scheduler = Scheduler(session_from_plan)
        scheduler.initialize()
        with pytest.raises(ExecutionSchedulingError):
            scheduler.initialize()

    def test_ready_tasks_promoted(self, session_from_plan):
        scheduler = Scheduler(session_from_plan)
        scheduler.initialize()
        assert session_from_plan.tasks["task-a"].status == TaskState.READY
        assert session_from_plan.tasks["task-b"].status == TaskState.PENDING
        assert session_from_plan.tasks["task-c"].status == TaskState.PENDING


class TestSchedulerReadyQueue:
    def test_get_next_ready_linear(self, session_from_plan):
        scheduler = Scheduler(session_from_plan)
        scheduler.initialize()
        task_id = scheduler.get_next_ready()
        assert task_id == "task-a"
        assert scheduler.running_count() == 1
        assert scheduler.ready_count() == 0

    def test_get_next_ready_independent(self, independent_plan):
        session = _build_session(independent_plan)
        scheduler = Scheduler(session)
        scheduler.initialize()
        ready = set()
        for _ in range(3):
            tid = scheduler.get_next_ready()
            assert tid is not None
            ready.add(tid)
        assert ready == {"task-1", "task-2", "task-3"}
        assert scheduler.get_next_ready() is None

    def test_deterministic_ordering(self, session_from_plan):
        scheduler = Scheduler(session_from_plan)
        scheduler.initialize()
        order = []
        for _ in range(3):
            tid = scheduler.get_next_ready()
            if tid:
                order.append(tid)
                scheduler.mark_completed(tid)
        assert order == ["task-a", "task-b", "task-c"]

    def test_peek_ready_does_not_dequeue(self, session_from_plan):
        scheduler = Scheduler(session_from_plan)
        scheduler.initialize()
        assert scheduler.peek_ready() == "task-a"
        assert scheduler.ready_count() == 1

    def test_empty_queue_returns_none(self, session_from_plan):
        scheduler = Scheduler(session_from_plan)
        scheduler.initialize()
        scheduler.get_next_ready()
        scheduler.get_next_ready()
        scheduler.get_next_ready()
        assert scheduler.get_next_ready() is None

    def test_ready_count(self, independent_plan):
        session = _build_session(independent_plan)
        scheduler = Scheduler(session)
        scheduler.initialize()
        assert scheduler.ready_count() == 3
        scheduler.get_next_ready()
        assert scheduler.ready_count() == 2


class TestSchedulerConcurrency:
    def test_concurrency_limit_blocks(self, independent_plan):
        session = _build_session(independent_plan)
        scheduler = Scheduler(session, max_concurrency=2)
        scheduler.initialize()
        tid1 = scheduler.get_next_ready()
        assert tid1 is not None
        tid2 = scheduler.get_next_ready()
        assert tid2 is not None
        assert scheduler.get_next_ready() is None

    def test_concurrency_releases_on_completion(self, independent_plan):
        session = _build_session(independent_plan)
        scheduler = Scheduler(session, max_concurrency=2)
        scheduler.initialize()
        scheduler.get_next_ready()
        scheduler.get_next_ready()
        scheduler.mark_completed("task-1")
        assert scheduler.get_next_ready() == "task-3"

    def test_max_concurrency_setter(self, session_from_plan):
        scheduler = Scheduler(session_from_plan)
        assert scheduler.max_concurrency == 5
        scheduler.max_concurrency = 10
        assert scheduler.max_concurrency == 10

    def test_max_concurrency_minimum(self, session_from_plan):
        scheduler = Scheduler(session_from_plan)
        with pytest.raises(ExecutionSchedulingError):
            scheduler.max_concurrency = 0

    def test_can_dispatch(self, independent_plan):
        session = _build_session(independent_plan)
        scheduler = Scheduler(session, max_concurrency=2)
        scheduler.initialize()
        assert scheduler.can_dispatch is True
        scheduler.get_next_ready()
        scheduler.get_next_ready()
        assert scheduler.can_dispatch is False


class TestSchedulerDependencyRelease:
    def test_completion_releases_downstream(self, session_from_plan):
        scheduler = Scheduler(session_from_plan)
        scheduler.initialize()
        scheduler.get_next_ready()
        newly_ready = scheduler.mark_completed("task-a")
        assert "task-b" in newly_ready
        assert scheduler.ready_count() == 1
        assert session_from_plan.tasks["task-b"].status == TaskState.READY

    def test_diamond_completion(self, diamond_plan):
        session = _build_session(diamond_plan)
        scheduler = Scheduler(session)
        scheduler.initialize()
        scheduler.get_next_ready()
        scheduler.mark_completed("task-a")
        assert scheduler.ready_count() == 2
        scheduler.get_next_ready()
        scheduler.get_next_ready()
        assert scheduler.running_count() == 2

    def test_diamond_join_releases(self, diamond_plan):
        session = _build_session(diamond_plan)
        scheduler = Scheduler(session)
        scheduler.initialize()
        scheduler.get_next_ready()
        scheduler.mark_completed("task-a")
        scheduler.get_next_ready()
        scheduler.get_next_ready()
        # task-d still has 2 upstream deps
        assert scheduler.in_degree["task-d"].remaining == 2
        scheduler.mark_completed("task-b")
        assert scheduler.in_degree["task-d"].remaining == 1
        scheduler.mark_completed("task-c")
        assert scheduler.in_degree["task-d"].remaining == 0
        assert scheduler.ready_count() == 1
        assert scheduler.peek_ready() == "task-d"

    def test_failure_blocks_downstream(self, session_from_plan):
        scheduler = Scheduler(session_from_plan)
        scheduler.initialize()
        scheduler.get_next_ready()
        StateMachine.transition_task(
            session_from_plan.tasks["task-a"], TaskState.RUNNING
        )
        StateMachine.transition_task(
            session_from_plan.tasks["task-a"], TaskState.FAILED
        )
        skipped = scheduler.mark_failed("task-a")
        assert "task-b" in skipped
        assert session_from_plan.tasks["task-b"].status == TaskState.SKIPPED
        assert scheduler.is_terminal() is True

    def test_skipped_propagates(self, session_from_plan):
        scheduler = Scheduler(session_from_plan)
        scheduler.initialize()
        # Transition task-a to SKIPPED first, then propagate
        StateMachine.transition_task(
            session_from_plan.tasks["task-a"], TaskState.SKIPPED
        )
        skipped = scheduler.mark_skipped("task-a")
        assert "task-b" in skipped
        assert session_from_plan.tasks["task-b"].status == TaskState.SKIPPED
        assert session_from_plan.tasks["task-c"].status == TaskState.SKIPPED
        assert scheduler.is_terminal() is True

    def test_completion_does_not_affect_unrelated(self, independent_plan):
        session = _build_session(independent_plan)
        scheduler = Scheduler(session)
        scheduler.initialize()
        scheduler.get_next_ready()
        scheduler.mark_completed("task-1")
        assert scheduler.ready_count() == 2

    def test_double_completion_safe(self, session_from_plan):
        scheduler = Scheduler(session_from_plan)
        scheduler.initialize()
        scheduler.get_next_ready()
        scheduler.mark_completed("task-a")
        # Calling again should be safe (no-op since running was already discarded)
        scheduler.mark_completed("task-a")
        assert scheduler.running_count() == 0


class TestSchedulerTerminalDetection:
    def test_linear_completion_terminal(self, session_from_plan):
        scheduler = Scheduler(session_from_plan)
        scheduler.initialize()
        for _ in range(3):
            tid = scheduler.get_next_ready()
            if tid:
                StateMachine.transition_task(
                    session_from_plan.tasks[tid], TaskState.RUNNING
                )
                StateMachine.transition_task(
                    session_from_plan.tasks[tid], TaskState.COMPLETED
                )
                scheduler.mark_completed(tid)
        assert scheduler.is_terminal() is True

    def test_linear_failure_terminal(self, session_from_plan):
        scheduler = Scheduler(session_from_plan)
        scheduler.initialize()
        scheduler.get_next_ready()
        StateMachine.transition_task(
            session_from_plan.tasks["task-a"], TaskState.RUNNING
        )
        StateMachine.transition_task(
            session_from_plan.tasks["task-a"], TaskState.FAILED
        )
        scheduler.mark_failed("task-a")
        assert scheduler.is_terminal() is True

    def test_ready_tasks_prevents_terminal(self, session_from_plan):
        scheduler = Scheduler(session_from_plan)
        scheduler.initialize()
        assert scheduler.is_terminal() is False

    def test_running_tasks_prevents_terminal(self, independent_plan):
        session = _build_session(independent_plan)
        scheduler = Scheduler(session)
        scheduler.initialize()
        scheduler.get_next_ready()
        assert scheduler.is_terminal() is False

    def test_empty_session_terminal(self):
        session = ExecutionSession(id="empty", plan=None)
        scheduler = Scheduler(session)
        scheduler._build_in_degree()
        # No tasks → terminal
        assert scheduler.is_terminal() is True

    def test_get_terminal_state_completed(self, session_from_plan):
        scheduler = Scheduler(session_from_plan)
        scheduler.initialize()
        for _ in range(3):
            tid = scheduler.get_next_ready()
            if tid:
                StateMachine.transition_task(
                    session_from_plan.tasks[tid], TaskState.RUNNING
                )
                StateMachine.transition_task(
                    session_from_plan.tasks[tid], TaskState.COMPLETED
                )
                scheduler.mark_completed(tid)
        assert scheduler.get_terminal_state() == "completed"

    def test_get_terminal_state_failed(self, session_from_plan):
        scheduler = Scheduler(session_from_plan)
        scheduler.initialize()
        scheduler.get_next_ready()
        StateMachine.transition_task(
            session_from_plan.tasks["task-a"], TaskState.RUNNING
        )
        StateMachine.transition_task(
            session_from_plan.tasks["task-a"], TaskState.FAILED
        )
        scheduler.mark_failed("task-a")
        assert scheduler.get_terminal_state() == "failed"

    def test_get_terminal_state_cancelled(self, session_from_plan):
        from services.execution.enums import TaskState
        scheduler = Scheduler(session_from_plan)
        scheduler.initialize()
        for etask in session_from_plan.tasks.values():
            etask.status = TaskState.CANCELLED
        assert scheduler.get_terminal_state() == "cancelled"

    def test_failure_blocks_and_cascades(self, diamond_plan):
        session = _build_session(diamond_plan)
        scheduler = Scheduler(session)
        scheduler.initialize()
        scheduler.get_next_ready()
        StateMachine.transition_task(
            session.tasks["task-a"], TaskState.RUNNING
        )
        StateMachine.transition_task(
            session.tasks["task-a"], TaskState.FAILED
        )
        scheduler.mark_failed("task-a")
        # task-b and task-c should be skipped
        assert session.tasks["task-b"].status == TaskState.SKIPPED
        assert session.tasks["task-c"].status == TaskState.SKIPPED
        # task-d should be skipped (all upstreams skipped)
        assert session.tasks["task-d"].status == TaskState.SKIPPED
        assert scheduler.is_terminal() is True


# ===================================================================
# PIPELINE INTEGRATION TESTS
# ===================================================================

class TestPipelineSchedulerIntegration:
    def test_execute_raises_with_next_task(self, engine, linear_plan):
        with pytest.raises(NotImplementedError) as exc:
            asyncio.run(engine.execute(linear_plan))
        assert "4C" in str(exc.value) or "Next runnable task" in str(exc.value)

    def test_execute_creates_session(self, engine, linear_plan):
        with pytest.raises(NotImplementedError):
            asyncio.run(engine.execute(linear_plan))
        sessions = engine._sessions
        assert len(sessions) == 1
        sid = list(sessions.keys())[0]
        session = sessions[sid]
        assert session.plan_id == linear_plan.id
        assert len(session.tasks) == 3
        assert session.tasks["task-a"].status == TaskState.RUNNING

    def test_execute_with_terminal_plan(self, engine, linear_plan):
        """A plan that is already terminal should finalize immediately."""
        linear_plan.tasks = []
        with pytest.raises(Exception):
            asyncio.run(engine.execute(linear_plan))

    def test_get_scheduler(self, engine, session_from_plan):
        engine._sessions[session_from_plan.id] = session_from_plan
        scheduler = engine.get_scheduler(session_from_plan.id)
        assert isinstance(scheduler, Scheduler)
        assert scheduler._initialized is True

    def test_execute_root_task_promoted(self, engine, linear_plan):
        with pytest.raises(NotImplementedError):
            asyncio.run(engine.execute(linear_plan))
        session = next(iter(engine._sessions.values()))
        assert session.tasks["task-a"].status == TaskState.RUNNING

    def test_pipeline_then_cancel(self, engine, linear_plan):
        with pytest.raises(NotImplementedError):
            asyncio.run(engine.execute(linear_plan))
        session = next(iter(engine._sessions.values()))
        session.status = SessionState.RUNNING
        result = engine.cancel(session.id)
        assert result.status == SessionState.CANCELLED
        for etask in result.tasks.values():
            assert etask.status == TaskState.CANCELLED

    def test_execute_with_approval_plan(self, engine):
        """A plan where the first task requires approval should not have a
        READY task — it should be WAITING_APPROVAL."""
        from services.planner.planning_models import ApprovalRequirement
        plan = Plan(
            id="approval-plan",
            conversation_id="conv",
            status=PlanStatus.VALIDATED,
            goal=PlanGoal(outcome="test"),
        )
        task = Task(
            id="task-a", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="telegram", template="hello"),
            label="needs approval",
            approval=ApprovalRequirement.REQUIRED,
        )
        plan.tasks = [task]
        with pytest.raises(NotImplementedError) as exc:
            asyncio.run(engine.execute(plan))
        assert "4C" in str(exc.value)


# ===================================================================
# UTILITY HELPERS
# ===================================================================

def _build_session(plan: Plan) -> ExecutionSession:
    """Build an ExecutionSession from a Plan for testing."""
    session = ExecutionSession(
        id=plan.id + "-session",
        plan_id=plan.id,
        plan=plan,
        conversation_id=plan.conversation_id,
        status=SessionState.PENDING,
    )
    for pt in plan.tasks:
        etask = wrap_task(pt)
        session.tasks[pt.id] = etask
    session.root_tasks = [t.id for t in plan.get_root_tasks()]
    return session