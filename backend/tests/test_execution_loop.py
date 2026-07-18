"""Unit tests for the Execution Engine Loop (Phase 3.6.4E).

Tests the full execution loop: single tasks, linear DAG, diamond DAG,
mixed success/failure, unsupported tasks, adapter exceptions, session
completion states, and edge cases.
"""

from __future__ import annotations

import asyncio
import pytest
from datetime import datetime, timezone
from typing import Optional

from services.execution.base_adapter import ExecutionAdapter
from services.execution.dispatcher import AdapterResolver, Dispatcher
from services.execution.enums import SessionState, TaskState
from services.execution.exceptions import ExecutionDispatchError
from services.execution.execution_context import ExecutionContext
from services.execution.execution_models import (
    ExecutionSession,
    ExecutionTask,
    TaskResult,
    RetryPolicy,
)
from services.execution.execution_pipeline import ExecutionEngine
from services.execution.state_machine import StateMachine
from services.execution.utils import wrap_task

from services.planner.planning_models import (
    Plan, PlanGoal, Task, PlanStatus, TaskStatus, TaskType,
)
from services.planner.payloads import MessagePayload


# ---------------------------------------------------------------------------
# Mock Adapters
# ---------------------------------------------------------------------------

class MockSuccessAdapter(ExecutionAdapter):
    """Adapter that always succeeds."""

    @property
    def adapter_type(self) -> str:
        return "mock_success"

    @property
    def supported_task_types(self) -> list[TaskType]:
        return [TaskType.SEND_MESSAGE]

    async def execute(
        self,
        task: ExecutionTask,
        context: ExecutionContext,
    ) -> TaskResult:
        return TaskResult(
            task_id=task.id,
            attempt=task.attempts,
            success=True,
            output={"result": "ok"},
        )


class MockFailingAdapter(ExecutionAdapter):
    """Adapter that always fails."""

    @property
    def adapter_type(self) -> str:
        return "mock_fail"

    @property
    def supported_task_types(self) -> list[TaskType]:
        return [TaskType.SEND_EMAIL]

    async def execute(
        self,
        task: ExecutionTask,
        context: ExecutionContext,
    ) -> TaskResult:
        return TaskResult(
            task_id=task.id,
            attempt=task.attempts,
            success=False,
            error="Intentional failure",
            error_type="permanent",
        )


class MockThrowAdapter(ExecutionAdapter):
    """Adapter that throws an unexpected exception."""

    @property
    def adapter_type(self) -> str:
        return "mock_throw"

    @property
    def supported_task_types(self) -> list[TaskType]:
        return [TaskType.ANALYZE_REPLY]

    async def execute(
        self,
        task: ExecutionTask,
        context: ExecutionContext,
    ) -> TaskResult:
        raise RuntimeError("Something went wrong in the adapter")


class MockMultiTypeAdapter(ExecutionAdapter):
    """Adapter that supports multiple types."""

    def __init__(self, succeed: bool = True):
        self._succeed = succeed

    @property
    def adapter_type(self) -> str:
        return "mock_multi"

    @property
    def supported_task_types(self) -> list[TaskType]:
        return [TaskType.UPDATE_CRM, TaskType.WAIT_FOR_REPLY]

    async def execute(
        self,
        task: ExecutionTask,
        context: ExecutionContext,
    ) -> TaskResult:
        if self._succeed:
            return TaskResult(
                task_id=task.id,
                attempt=task.attempts,
                success=True,
                output={"action": "done"},
            )
        return TaskResult(
            task_id=task.id,
            attempt=task.attempts,
            success=False,
            error="Intentional multi failure",
            error_type="permanent",
        )


# ---------------------------------------------------------------------------
# Mock Resolver
# ---------------------------------------------------------------------------

class MockResolver:
    """Resolver that returns pre-configured adapters."""

    def __init__(self, adapter_map: dict[TaskType, ExecutionAdapter]):
        self._adapter_map = adapter_map

    def resolve(self, task_type: TaskType) -> Optional[ExecutionAdapter]:
        return self._adapter_map.get(task_type)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def success_adapter():
    return MockSuccessAdapter()


@pytest.fixture
def fail_adapter():
    return MockFailingAdapter()


@pytest.fixture
def throw_adapter():
    return MockThrowAdapter()


@pytest.fixture
def multi_adapter():
    return MockMultiTypeAdapter(succeed=True)


@pytest.fixture
def engine():
    return ExecutionEngine()


@pytest.fixture
def success_resolver(success_adapter, fail_adapter, throw_adapter, multi_adapter):
    return MockResolver({
        TaskType.SEND_MESSAGE: success_adapter,
        TaskType.SEND_EMAIL: fail_adapter,
        TaskType.ANALYZE_REPLY: throw_adapter,
        TaskType.UPDATE_CRM: multi_adapter,
        TaskType.WAIT_FOR_REPLY: multi_adapter,
    })


@pytest.fixture
def single_plan():
    plan = Plan(
        id="single-plan",
        conversation_id="conv-1",
        status=PlanStatus.VALIDATED,
        goal=PlanGoal(outcome="test"),
    )
    plan.tasks = [
        Task(
            id="task-a", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="telegram", template="hello"),
            label="single",
        ),
    ]
    return plan


@pytest.fixture
def single_fail_plan():
    plan = Plan(
        id="single-fail-plan",
        conversation_id="conv-1",
        status=PlanStatus.VALIDATED,
        goal=PlanGoal(outcome="test"),
    )
    plan.tasks = [
        Task(
            id="task-a", plan_id=plan.id, type=TaskType.SEND_EMAIL,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="gmail", template="fail"),
            label="fail single",
        ),
    ]
    return plan


@pytest.fixture
def single_unsupported_plan():
    plan = Plan(
        id="single-unsupported-plan",
        conversation_id="conv-1",
        status=PlanStatus.VALIDATED,
        goal=PlanGoal(outcome="test"),
    )
    plan.tasks = [
        Task(
            id="task-a", plan_id=plan.id, type=TaskType.BRANCH,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="none", template="none"),
            label="unsupported",
        ),
    ]
    return plan


@pytest.fixture
def single_throw_plan():
    plan = Plan(
        id="single-throw-plan",
        conversation_id="conv-1",
        status=PlanStatus.VALIDATED,
        goal=PlanGoal(outcome="test"),
    )
    plan.tasks = [
        Task(
            id="task-a", plan_id=plan.id, type=TaskType.ANALYZE_REPLY,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="none", template="none"),
            label="throw",
        ),
    ]
    return plan


@pytest.fixture
def linear_all_pass_plan():
    """A → B → C, all succeed."""
    plan = Plan(
        id="linear-all-pass",
        conversation_id="conv-2",
        status=PlanStatus.VALIDATED,
        goal=PlanGoal(outcome="test"),
    )
    plan.tasks = [
        Task(
            id="task-a", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="telegram", template="a"),
            label="a",
        ),
        Task(
            id="task-b", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="telegram", template="b"),
            dependencies=["task-a"], label="b",
        ),
        Task(
            id="task-c", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="telegram", template="c"),
            dependencies=["task-b"], label="c",
        ),
    ]
    return plan


@pytest.fixture
def linear_first_fails_plan():
    """A → B → C, A fails."""
    plan = Plan(
        id="linear-first-fails",
        conversation_id="conv-3",
        status=PlanStatus.VALIDATED,
        goal=PlanGoal(outcome="test"),
    )
    plan.tasks = [
        Task(
            id="task-a", plan_id=plan.id, type=TaskType.SEND_EMAIL,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="gmail", template="fail"),
            label="a fails",
        ),
        Task(
            id="task-b", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="telegram", template="b"),
            dependencies=["task-a"], label="b",
        ),
        Task(
            id="task-c", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="telegram", template="c"),
            dependencies=["task-b"], label="c",
        ),
    ]
    return plan


@pytest.fixture
def diamond_plan():
    """A → B, A → C, B → D, C → D."""
    plan = Plan(
        id="diamond-plan",
        conversation_id="conv-4",
        status=PlanStatus.VALIDATED,
        goal=PlanGoal(outcome="test"),
    )
    plan.tasks = [
        Task(
            id="task-a", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="telegram", template="a"),
            label="a",
        ),
        Task(
            id="task-b", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="telegram", template="b"),
            dependencies=["task-a"], label="b",
        ),
        Task(
            id="task-c", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="telegram", template="c"),
            dependencies=["task-a"], label="c",
        ),
        Task(
            id="task-d", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="telegram", template="d"),
            dependencies=["task-b", "task-c"], label="d",
        ),
    ]
    return plan


@pytest.fixture
def diamond_one_fails_plan():
    """A → B, A → C, B → D, C → D; B fails."""
    plan = Plan(
        id="diamond-one-fails",
        conversation_id="conv-5",
        status=PlanStatus.VALIDATED,
        goal=PlanGoal(outcome="test"),
    )
    plan.tasks = [
        Task(
            id="task-a", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="telegram", template="a"),
            label="a",
        ),
        Task(
            id="task-b", plan_id=plan.id, type=TaskType.SEND_EMAIL,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="gmail", template="b"),
            dependencies=["task-a"], label="b fails",
        ),
        Task(
            id="task-c", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="telegram", template="c"),
            dependencies=["task-a"], label="c",
        ),
        Task(
            id="task-d", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="telegram", template="d"),
            dependencies=["task-b", "task-c"], label="d",
        ),
    ]
    return plan


@pytest.fixture
def independent_plan():
    """3 independent tasks (no dependencies)."""
    plan = Plan(
        id="independent-plan",
        conversation_id="conv-6",
        status=PlanStatus.VALIDATED,
        goal=PlanGoal(outcome="test"),
    )
    plan.tasks = [
        Task(
            id="task-a", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="telegram", template="a"),
            label="a",
        ),
        Task(
            id="task-b", plan_id=plan.id, type=TaskType.UPDATE_CRM,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="none", template="none"),
            label="b",
        ),
        Task(
            id="task-c", plan_id=plan.id, type=TaskType.WAIT_FOR_REPLY,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="none", template="none"),
            label="c",
        ),
    ]
    return plan


@pytest.fixture
def mixed_results_plan():
    """3 independent: 2 succeed, 1 fails."""
    plan = Plan(
        id="mixed-plan",
        conversation_id="conv-7",
        status=PlanStatus.VALIDATED,
        goal=PlanGoal(outcome="test"),
    )
    plan.tasks = [
        Task(
            id="task-a", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="telegram", template="a"),
            label="success",
        ),
        Task(
            id="task-b", plan_id=plan.id, type=TaskType.SEND_EMAIL,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="gmail", template="b"),
            label="fail",
        ),
        Task(
            id="task-c", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="telegram", template="c"),
            label="success",
        ),
    ]
    return plan


@pytest.fixture
def all_fail_plan():
    """3 independent tasks, all fail."""
    plan = Plan(
        id="all-fail-plan",
        conversation_id="conv-8",
        status=PlanStatus.VALIDATED,
        goal=PlanGoal(outcome="test"),
    )
    plan.tasks = [
        Task(
            id="task-a", plan_id=plan.id, type=TaskType.SEND_EMAIL,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="gmail", template="a"),
            label="fail",
        ),
        Task(
            id="task-b", plan_id=plan.id, type=TaskType.SEND_EMAIL,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="gmail", template="b"),
            label="fail",
        ),
        Task(
            id="task-c", plan_id=plan.id, type=TaskType.SEND_EMAIL,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="gmail", template="c"),
            label="fail",
        ),
    ]
    return plan


# ===================================================================
# SINGLE TASK TESTS
# ===================================================================

class TestSingleTaskSuccess:
    """A single task completes successfully."""

    def test_single_task_completes(self, engine, single_plan, success_resolver):
        session = asyncio.run(engine.execute(single_plan, resolver=success_resolver))
        assert session.status == SessionState.COMPLETED
        assert session.tasks["task-a"].status == TaskState.COMPLETED

    def test_single_task_has_result(self, engine, single_plan, success_resolver):
        session = asyncio.run(engine.execute(single_plan, resolver=success_resolver))
        task = session.tasks["task-a"]
        assert task.result is not None
        assert task.result.success is True

    def test_single_task_output_stored(self, engine, single_plan, success_resolver):
        session = asyncio.run(engine.execute(single_plan, resolver=success_resolver))
        task = session.tasks["task-a"]
        assert task.result.output == {"result": "ok"}

    def test_single_task_adapter_name_set(self, engine, single_plan, success_resolver):
        session = asyncio.run(engine.execute(single_plan, resolver=success_resolver))
        assert session.tasks["task-a"].adapter_name == "mock_success"

    def test_single_task_session_has_end_time(self, engine, single_plan, success_resolver):
        session = asyncio.run(engine.execute(single_plan, resolver=success_resolver))
        assert session.end_time is not None
        assert session.end_time >= session.created_at

    def test_single_task_updated_at(self, engine, single_plan, success_resolver):
        session = asyncio.run(engine.execute(single_plan, resolver=success_resolver))
        assert session.updated_at >= session.created_at

    def test_single_task_result_counts(self, engine, single_plan, success_resolver):
        session = asyncio.run(engine.execute(single_plan, resolver=success_resolver))
        task = session.tasks["task-a"]
        assert task.attempts == 0  # not incremented by pipeline
        assert task.result.attempt == task.attempts

    def test_single_task_pipeline_returns_session(self, engine, single_plan, success_resolver):
        session = asyncio.run(engine.execute(single_plan, resolver=success_resolver))
        assert isinstance(session, ExecutionSession)
        assert session.id is not None

    def test_single_task_session_stored(self, engine, single_plan, success_resolver):
        session = asyncio.run(engine.execute(single_plan, resolver=success_resolver))
        assert engine.get_session(session.id) is session

    def test_single_task_plan_preserved(self, engine, single_plan, success_resolver):
        session = asyncio.run(engine.execute(single_plan, resolver=success_resolver))
        assert session.plan is single_plan


class TestSingleTaskFailure:
    """A single task fails."""

    def test_single_task_fails(self, engine, single_fail_plan, success_resolver):
        session = asyncio.run(engine.execute(single_fail_plan, resolver=success_resolver))
        task = session.tasks["task-a"]
        assert task.status == TaskState.FAILED

    def test_single_fail_session_state(self, engine, single_fail_plan, success_resolver):
        session = asyncio.run(engine.execute(single_fail_plan, resolver=success_resolver))
        assert session.status == SessionState.FAILED

    def test_single_fail_result_stored(self, engine, single_fail_plan, success_resolver):
        session = asyncio.run(engine.execute(single_fail_plan, resolver=success_resolver))
        task = session.tasks["task-a"]
        assert task.result is not None
        assert task.result.success is False

    def test_single_fail_error_message(self, engine, single_fail_plan, success_resolver):
        session = asyncio.run(engine.execute(single_fail_plan, resolver=success_resolver))
        task = session.tasks["task-a"]
        assert task.result.error == "Intentional failure"

    def test_single_fail_error_type(self, engine, single_fail_plan, success_resolver):
        session = asyncio.run(engine.execute(single_fail_plan, resolver=success_resolver))
        task = session.tasks["task-a"]
        assert task.result.error_type == "permanent"

    def test_single_fail_end_time_set(self, engine, single_fail_plan, success_resolver):
        session = asyncio.run(engine.execute(single_fail_plan, resolver=success_resolver))
        assert session.end_time is not None

    def test_single_fail_plan_preserved(self, engine, single_fail_plan, success_resolver):
        session = asyncio.run(engine.execute(single_fail_plan, resolver=success_resolver))
        assert session.plan is single_fail_plan


class TestSingleTaskUnsupported:
    """A task with no matching adapter."""

    def test_unsupported_task_fails(self, engine, single_unsupported_plan, success_resolver):
        session = asyncio.run(engine.execute(single_unsupported_plan, resolver=success_resolver))
        task = session.tasks["task-a"]
        assert task.status == TaskState.FAILED

    def test_unsupported_session_fails(self, engine, single_unsupported_plan, success_resolver):
        session = asyncio.run(engine.execute(single_unsupported_plan, resolver=success_resolver))
        assert session.status == SessionState.FAILED

    def test_unsupported_has_result(self, engine, single_unsupported_plan, success_resolver):
        session = asyncio.run(engine.execute(single_unsupported_plan, resolver=success_resolver))
        task = session.tasks["task-a"]
        assert task.result is not None
        assert task.result.success is False

    def test_unsupported_unsupported_flag(self, engine, single_unsupported_plan, success_resolver):
        session = asyncio.run(engine.execute(single_unsupported_plan, resolver=success_resolver))
        task = session.tasks["task-a"]
        assert task.result.metadata.get("unsupported_task") is True

    def test_unsupported_no_adapter_name(self, engine, single_unsupported_plan, success_resolver):
        session = asyncio.run(engine.execute(single_unsupported_plan, resolver=success_resolver))
        assert session.tasks["task-a"].adapter_name is None


class TestSingleTaskAdapterException:
    """Adapter throws an unexpected exception."""

    def test_throw_caught_as_failure(self, engine, single_throw_plan, success_resolver):
        session = asyncio.run(engine.execute(single_throw_plan, resolver=success_resolver))
        task = session.tasks["task-a"]
        assert task.status == TaskState.FAILED

    def test_throw_session_fails(self, engine, single_throw_plan, success_resolver):
        session = asyncio.run(engine.execute(single_throw_plan, resolver=success_resolver))
        assert session.status == SessionState.FAILED

    def test_throw_result_contains_error(self, engine, single_throw_plan, success_resolver):
        session = asyncio.run(engine.execute(single_throw_plan, resolver=success_resolver))
        task = session.tasks["task-a"]
        assert task.result is not None
        assert task.result.success is False
        assert "Adapter execution failed" in task.result.error

    def test_throw_result_has_exception_type(self, engine, single_throw_plan, success_resolver):
        session = asyncio.run(engine.execute(single_throw_plan, resolver=success_resolver))
        task = session.tasks["task-a"]
        assert task.result.metadata.get("adapter_exception") == "RuntimeError"

    def test_throw_has_end_time(self, engine, single_throw_plan, success_resolver):
        session = asyncio.run(engine.execute(single_throw_plan, resolver=success_resolver))
        assert session.end_time is not None


# ===================================================================
# LINEAR DAG TESTS
# ===================================================================

class TestLinearDagAllPass:
    """A → B → C, all succeed."""

    def test_linear_all_complete(self, engine, linear_all_pass_plan, success_resolver):
        session = asyncio.run(engine.execute(linear_all_pass_plan, resolver=success_resolver))
        assert session.status == SessionState.COMPLETED
        for tid in ("task-a", "task-b", "task-c"):
            assert session.tasks[tid].status == TaskState.COMPLETED

    def test_linear_all_have_results(self, engine, linear_all_pass_plan, success_resolver):
        session = asyncio.run(engine.execute(linear_all_pass_plan, resolver=success_resolver))
        for tid in ("task-a", "task-b", "task-c"):
            task = session.tasks[tid]
            assert task.result is not None
            assert task.result.success is True

    def test_linear_order_preserved(self, engine, linear_all_pass_plan, success_resolver):
        session = asyncio.run(engine.execute(linear_all_pass_plan, resolver=success_resolver))
        a = session.tasks["task-a"]
        b = session.tasks["task-b"]
        c = session.tasks["task-c"]
        assert a.result.completed_at <= b.result.completed_at
        assert b.result.completed_at <= c.result.completed_at

    def test_linear_all_have_adapter_names(self, engine, linear_all_pass_plan, success_resolver):
        session = asyncio.run(engine.execute(linear_all_pass_plan, resolver=success_resolver))
        for tid in ("task-a", "task-b", "task-c"):
            assert session.tasks[tid].adapter_name is not None

    def test_linear_session_has_end_time(self, engine, linear_all_pass_plan, success_resolver):
        session = asyncio.run(engine.execute(linear_all_pass_plan, resolver=success_resolver))
        assert session.end_time is not None

    def test_linear_single_iteration(self, engine, linear_all_pass_plan, success_resolver):
        """All tasks complete in one pipeline execute call."""
        session = asyncio.run(engine.execute(linear_all_pass_plan, resolver=success_resolver))
        assert session.status.is_terminal
        assert session.tasks["task-c"].status == TaskState.COMPLETED


class TestLinearDagFirstFails:
    """A → B → C, A fails → B and C are skipped."""

    def test_linear_first_fails(self, engine, linear_first_fails_plan, success_resolver):
        session = asyncio.run(engine.execute(linear_first_fails_plan, resolver=success_resolver))
        assert session.tasks["task-a"].status == TaskState.FAILED

    def test_linear_downstream_skipped(self, engine, linear_first_fails_plan, success_resolver):
        session = asyncio.run(engine.execute(linear_first_fails_plan, resolver=success_resolver))
        for tid in ("task-b", "task-c"):
            assert session.tasks[tid].status == TaskState.SKIPPED

    def test_linear_first_fails_session_state(self, engine, linear_first_fails_plan, success_resolver):
        session = asyncio.run(engine.execute(linear_first_fails_plan, resolver=success_resolver))
        assert session.status == SessionState.FAILED

    def test_linear_first_fails_no_result_on_skipped(self, engine, linear_first_fails_plan, success_resolver):
        session = asyncio.run(engine.execute(linear_first_fails_plan, resolver=success_resolver))
        for tid in ("task-b", "task-c"):
            assert session.tasks[tid].result is None

    def test_linear_fail_has_end_time(self, engine, linear_first_fails_plan, success_resolver):
        session = asyncio.run(engine.execute(linear_first_fails_plan, resolver=success_resolver))
        assert session.end_time is not None

    def test_linear_fail_error_propagated(self, engine, linear_first_fails_plan, success_resolver):
        session = asyncio.run(engine.execute(linear_first_fails_plan, resolver=success_resolver))
        task = session.tasks["task-a"]
        assert task.result is not None
        assert task.result.error == "Intentional failure"

    def test_linear_skipped_have_no_adapter(self, engine, linear_first_fails_plan, success_resolver):
        session = asyncio.run(engine.execute(linear_first_fails_plan, resolver=success_resolver))
        for tid in ("task-b", "task-c"):
            assert session.tasks[tid].adapter_name is None


# ===================================================================
# DIAMOND DAG TESTS
# ===================================================================

class TestDiamondDagAllPass:
    """A → B, A → C, B → D, C → D, all succeed."""

    def test_diamond_all_complete(self, engine, diamond_plan, success_resolver):
        session = asyncio.run(engine.execute(diamond_plan, resolver=success_resolver))
        assert session.status == SessionState.COMPLETED
        for tid in ("task-a", "task-b", "task-c", "task-d"):
            assert session.tasks[tid].status == TaskState.COMPLETED

    def test_diamond_all_have_results(self, engine, diamond_plan, success_resolver):
        session = asyncio.run(engine.execute(diamond_plan, resolver=success_resolver))
        for tid in ("task-a", "task-b", "task-c", "task-d"):
            task = session.tasks[tid]
            assert task.result is not None
            assert task.result.success is True

    def test_diamond_b_and_c_complete_before_d(self, engine, diamond_plan, success_resolver):
        session = asyncio.run(engine.execute(diamond_plan, resolver=success_resolver))
        b = session.tasks["task-b"]
        c = session.tasks["task-c"]
        d = session.tasks["task-d"]
        assert b.result.completed_at <= d.result.completed_at
        assert c.result.completed_at <= d.result.completed_at

    def test_diamond_all_adapter_names(self, engine, diamond_plan, success_resolver):
        session = asyncio.run(engine.execute(diamond_plan, resolver=success_resolver))
        for tid in ("task-a", "task-b", "task-c", "task-d"):
            assert session.tasks[tid].adapter_name == "mock_success"


class TestDiamondDagOneFails:
    """A → B, A → C, B → D, C → D; B fails → D blocked/skipped."""

    def test_diamond_a_succeeds(self, engine, diamond_one_fails_plan, success_resolver):
        session = asyncio.run(engine.execute(diamond_one_fails_plan, resolver=success_resolver))
        assert session.tasks["task-a"].status == TaskState.COMPLETED

    def test_diamond_b_fails(self, engine, diamond_one_fails_plan, success_resolver):
        session = asyncio.run(engine.execute(diamond_one_fails_plan, resolver=success_resolver))
        assert session.tasks["task-b"].status == TaskState.FAILED

    def test_diamond_c_succeeds(self, engine, diamond_one_fails_plan, success_resolver):
        session = asyncio.run(engine.execute(diamond_one_fails_plan, resolver=success_resolver))
        assert session.tasks["task-c"].status == TaskState.COMPLETED

    def test_diamond_d_blocked(self, engine, diamond_one_fails_plan, success_resolver):
        session = asyncio.run(engine.execute(diamond_one_fails_plan, resolver=success_resolver))
        assert session.tasks["task-d"].status == TaskState.BLOCKED

    def test_diamond_session_state(self, engine, diamond_one_fails_plan, success_resolver):
        session = asyncio.run(engine.execute(diamond_one_fails_plan, resolver=success_resolver))
        assert session.status == SessionState.COMPLETED_WITH_ERRORS

    def test_diamond_failed_task_has_result(self, engine, diamond_one_fails_plan, success_resolver):
        session = asyncio.run(engine.execute(diamond_one_fails_plan, resolver=success_resolver))
        assert session.tasks["task-b"].result is not None
        assert session.tasks["task-b"].result.success is False

    def test_diamond_alive_task_has_result(self, engine, diamond_one_fails_plan, success_resolver):
        session = asyncio.run(engine.execute(diamond_one_fails_plan, resolver=success_resolver))
        assert session.tasks["task-c"].result is not None
        assert session.tasks["task-c"].result.success is True


# ===================================================================
# INDEPENDENT TASKS TESTS
# ===================================================================

class TestIndependentTasks:
    """Multiple independent tasks (no dependencies)."""

    def test_independent_all_complete(self, engine, independent_plan, success_resolver):
        session = asyncio.run(engine.execute(independent_plan, resolver=success_resolver))
        assert session.status == SessionState.COMPLETED
        for tid in ("task-a", "task-b", "task-c"):
            assert session.tasks[tid].status == TaskState.COMPLETED

    def test_independent_all_have_results(self, engine, independent_plan, success_resolver):
        session = asyncio.run(engine.execute(independent_plan, resolver=success_resolver))
        for tid in ("task-a", "task-b", "task-c"):
            assert session.tasks[tid].result is not None

    def test_independent_mixed_session_state(self, engine, mixed_results_plan, success_resolver):
        session = asyncio.run(engine.execute(mixed_results_plan, resolver=success_resolver))
        assert session.status == SessionState.COMPLETED_WITH_ERRORS

    def test_independent_mixed_successes(self, engine, mixed_results_plan, success_resolver):
        session = asyncio.run(engine.execute(mixed_results_plan, resolver=success_resolver))
        assert session.tasks["task-a"].status == TaskState.COMPLETED
        assert session.tasks["task-c"].status == TaskState.COMPLETED

    def test_independent_mixed_failure(self, engine, mixed_results_plan, success_resolver):
        session = asyncio.run(engine.execute(mixed_results_plan, resolver=success_resolver))
        assert session.tasks["task-b"].status == TaskState.FAILED

    def test_independent_all_fail(self, engine, all_fail_plan, success_resolver):
        session = asyncio.run(engine.execute(all_fail_plan, resolver=success_resolver))
        assert session.status == SessionState.FAILED
        for tid in ("task-a", "task-b", "task-c"):
            assert session.tasks[tid].status == TaskState.FAILED

    def test_independent_all_fail_no_completed(self, engine, all_fail_plan, success_resolver):
        session = asyncio.run(engine.execute(all_fail_plan, resolver=success_resolver))
        assert session.status == SessionState.FAILED
        counts = {"completed": 0, "failed": 0}
        for task in session.tasks.values():
            if task.status == TaskState.COMPLETED:
                counts["completed"] += 1
            elif task.status == TaskState.FAILED:
                counts["failed"] += 1
        assert counts["completed"] == 0
        assert counts["failed"] == 3


# ===================================================================
# SESSION TIMING TESTS
# ===================================================================

class TestSessionTiming:
    """Session timing fields are populated correctly."""

    def test_session_start_time_set_on_execution(self, engine, single_plan, success_resolver):
        session = asyncio.run(engine.execute(single_plan, resolver=success_resolver))
        assert session.start_time is not None
        assert isinstance(session.start_time, datetime)

    def test_session_end_time_set_for_terminal(self, engine, single_plan, success_resolver):
        session = asyncio.run(engine.execute(single_plan, resolver=success_resolver))
        assert session.end_time is not None
        assert session.end_time >= session.created_at

    def test_session_end_time_for_failure(self, engine, single_fail_plan, success_resolver):
        session = asyncio.run(engine.execute(single_fail_plan, resolver=success_resolver))
        assert session.end_time is not None

    def test_session_updated_after_execution(self, engine, single_plan, success_resolver):
        session = asyncio.run(engine.execute(single_plan, resolver=success_resolver))
        assert session.updated_at >= session.created_at

    def test_session_preserves_plan_id(self, engine, single_plan, success_resolver):
        session = asyncio.run(engine.execute(single_plan, resolver=success_resolver))
        assert session.plan_id == single_plan.id

    def test_session_conversation_preserved(self, engine, single_plan, success_resolver):
        session = asyncio.run(engine.execute(single_plan, resolver=success_resolver))
        assert session.conversation_id == "conv-1"


# ===================================================================
# ENGINE LIFE-CYCLE TESTS
# ===================================================================

class TestEngineLifecycle:
    """Engine manages multiple sessions independently."""

    def test_multiple_sessions_independent(self, engine, single_plan, single_fail_plan, success_resolver):
        s1 = asyncio.run(engine.execute(single_plan, resolver=success_resolver))
        s2 = asyncio.run(engine.execute(single_fail_plan, resolver=success_resolver))
        assert s1.id != s2.id
        assert s1.status == SessionState.COMPLETED
        assert s2.status == SessionState.FAILED

    def test_get_session_after_completion(self, engine, single_plan, success_resolver):
        s1 = asyncio.run(engine.execute(single_plan, resolver=success_resolver))
        retrieved = engine.get_session(s1.id)
        assert retrieved is s1
        assert retrieved.status == SessionState.COMPLETED

    def test_get_session_returns_none_for_missing(self, engine):
        assert engine.get_session("nonexistent") is None

    def test_engine_reuse(self, engine, single_plan, success_resolver):
        plans_count = 3
        sessions = []
        for _ in range(plans_count):
            plan = Plan(
                id=f"plan-{_}",
                conversation_id="conv",
                status=PlanStatus.VALIDATED,
                goal=PlanGoal(outcome="test"),
            )
            plan.tasks = [
                Task(
                    id=f"task-{_}", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
                    status=TaskStatus.PENDING,
                    payload=MessagePayload(channel="telegram", template="hello"),
                    label=str(_),
                ),
            ]
            session = asyncio.run(engine.execute(plan, resolver=success_resolver))
            sessions.append(session)
        assert len(sessions) == 3
        assert len(engine._sessions) == 3
        for s in sessions:
            assert s.status == SessionState.COMPLETED

    def test_engine_deep_copy_plan(self, engine, single_plan, success_resolver):
        original_tasks = len(single_plan.tasks)
        asyncio.run(engine.execute(single_plan, resolver=success_resolver))
        assert len(single_plan.tasks) == original_tasks
        for t in single_plan.tasks:
            assert t.status == TaskStatus.PENDING


# ===================================================================
# LEGACY PATH TESTS
# ===================================================================

class TestLegacyPath:
    """No resolver → NotImplementedError (backward compatible)."""

    def test_legacy_still_works(self, engine, single_plan):
        with pytest.raises(NotImplementedError):
            asyncio.run(engine.execute(single_plan))

    def test_legacy_task_running(self, engine, single_plan):
        with pytest.raises(NotImplementedError):
            asyncio.run(engine.execute(single_plan))
        session = next(iter(engine._sessions.values()))
        assert session.tasks["task-a"].status == TaskState.RUNNING

    def test_legacy_no_result(self, engine, single_plan):
        with pytest.raises(NotImplementedError):
            asyncio.run(engine.execute(single_plan))
        session = next(iter(engine._sessions.values()))
        assert session.tasks["task-a"].result is None

    def test_legacy_no_adapter_name(self, engine, single_plan):
        with pytest.raises(NotImplementedError):
            asyncio.run(engine.execute(single_plan))
        session = next(iter(engine._sessions.values()))
        assert session.tasks["task-a"].adapter_name is None

    def test_legacy_not_implemented_message(self, engine, single_plan):
        with pytest.raises(NotImplementedError) as exc:
            asyncio.run(engine.execute(single_plan))
        msg = str(exc.value)
        assert "Next runnable task" in msg


# ===================================================================
# EDGE CASES
# ===================================================================

class TestEdgeCases:
    """Edge cases and robustness."""

    def test_empty_plan_raises(self, engine, success_resolver):
        plan = Plan(
            id="empty", conversation_id="c",
            status=PlanStatus.VALIDATED,
            goal=PlanGoal(outcome="test"),
        )
        plan.tasks = []
        with pytest.raises(Exception):
            asyncio.run(engine.execute(plan, resolver=success_resolver))

    def test_execution_dispatch_error_not_propagated(self, engine, single_unsupported_plan, success_resolver):
        """ExecutionDispatchError is caught internally, not propagated."""
        session = asyncio.run(engine.execute(single_unsupported_plan, resolver=success_resolver))
        assert session.status.is_terminal

    def test_adapter_exception_not_propagated(self, engine, single_throw_plan, success_resolver):
        """RuntimeError from adapter is caught, not propagated."""
        session = asyncio.run(engine.execute(single_throw_plan, resolver=success_resolver))
        assert session.status.is_terminal

    def test_concurrent_independent_tasks(self, engine, independent_plan, success_resolver):
        """Independent tasks all execute and complete."""
        session = asyncio.run(engine.execute(independent_plan, resolver=success_resolver))
        assert session.status == SessionState.COMPLETED
        assert len(session.tasks) == 3

    def test_large_linear_chain(self, engine, success_resolver):
        """10 tasks in a linear chain all complete."""
        plan = Plan(
            id="large-linear",
            conversation_id="c",
            status=PlanStatus.VALIDATED,
            goal=PlanGoal(outcome="test"),
        )
        tasks = []
        for i in range(10):
            deps = [f"task-{i-1}"] if i > 0 else []
            tasks.append(
                Task(
                    id=f"task-{i}", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
                    status=TaskStatus.PENDING,
                    payload=MessagePayload(channel="telegram", template=str(i)),
                    dependencies=deps, label=str(i),
                )
            )
        plan.tasks = tasks
        session = asyncio.run(engine.execute(plan, resolver=success_resolver))
        assert session.status == SessionState.COMPLETED
        for i in range(10):
            assert session.tasks[f"task-{i}"].status == TaskState.COMPLETED

    def test_diamond_all_fail(self, engine, success_resolver):
        """Diamond where A fails → everything downstream is skipped."""
        plan = Plan(
            id="diamond-fail-root",
            conversation_id="c",
            status=PlanStatus.VALIDATED,
            goal=PlanGoal(outcome="test"),
        )
        plan.tasks = [
            Task(
                id="task-a", plan_id=plan.id, type=TaskType.SEND_EMAIL,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="gmail", template="a"),
                label="a",
            ),
            Task(
                id="task-b", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="telegram", template="b"),
                dependencies=["task-a"], label="b",
            ),
            Task(
                id="task-c", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="telegram", template="c"),
                dependencies=["task-a"], label="c",
            ),
            Task(
                id="task-d", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="telegram", template="d"),
                dependencies=["task-b", "task-c"], label="d",
            ),
        ]
        session = asyncio.run(engine.execute(plan, resolver=success_resolver))
        assert session.tasks["task-a"].status == TaskState.FAILED
        for tid in ("task-b", "task-c", "task-d"):
            assert session.tasks[tid].status == TaskState.SKIPPED
        assert session.status == SessionState.FAILED

    def test_leaf_node_fails_mid_dag(self, engine, success_resolver):
        """Diamond: A→B→D, A→C, C fails → D blocked by C."""
        plan = Plan(
            id="leaf-fail-diamond",
            conversation_id="c",
            status=PlanStatus.VALIDATED,
            goal=PlanGoal(outcome="test"),
        )
        plan.tasks = [
            Task(
                id="task-a", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="telegram", template="a"),
                label="a",
            ),
            Task(
                id="task-b", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="telegram", template="b"),
                dependencies=["task-a"], label="b",
            ),
            Task(
                id="task-c", plan_id=plan.id, type=TaskType.SEND_EMAIL,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="gmail", template="c"),
                dependencies=["task-a"], label="c fails",
            ),
            Task(
                id="task-d", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="telegram", template="d"),
                dependencies=["task-b", "task-c"], label="d",
            ),
        ]
        session = asyncio.run(engine.execute(plan, resolver=success_resolver))
        assert session.tasks["task-a"].status == TaskState.COMPLETED
        assert session.tasks["task-b"].status == TaskState.COMPLETED
        assert session.tasks["task-c"].status == TaskState.FAILED
        assert session.tasks["task-d"].status in (TaskState.SKIPPED, TaskState.BLOCKED)


# ===================================================================
# RESULT CONTENT TESTS
# ===================================================================

class TestResultContent:
    """Task results contain correct content."""

    def test_success_result_content(self, engine, single_plan, success_resolver):
        session = asyncio.run(engine.execute(single_plan, resolver=success_resolver))
        task = session.tasks["task-a"]
        assert task.result.task_id == "task-a"
        assert task.result.output == {"result": "ok"}
        assert task.result.error is None

    def test_fail_result_content(self, engine, single_fail_plan, success_resolver):
        session = asyncio.run(engine.execute(single_fail_plan, resolver=success_resolver))
        task = session.tasks["task-a"]
        assert task.result.task_id == "task-a"
        assert task.result.error == "Intentional failure"
        assert task.result.output is None

    def test_unsupported_result_content(self, engine, single_unsupported_plan, success_resolver):
        session = asyncio.run(engine.execute(single_unsupported_plan, resolver=success_resolver))
        task = session.tasks["task-a"]
        assert task.result.task_id == "task-a"
        assert "No adapter registered" in task.result.error
        assert task.result.metadata.get("unsupported_task") is True

    def test_timing_populated_on_success(self, engine, single_plan, success_resolver):
        session = asyncio.run(engine.execute(single_plan, resolver=success_resolver))
        task = session.tasks["task-a"]
        assert task.result.started_at is not None
        assert task.result.completed_at is not None
        assert task.result.started_at <= task.result.completed_at

    def test_timing_populated_on_failure(self, engine, single_fail_plan, success_resolver):
        session = asyncio.run(engine.execute(single_fail_plan, resolver=success_resolver))
        task = session.tasks["task-a"]
        assert task.result.started_at is not None
        assert task.result.completed_at is not None
