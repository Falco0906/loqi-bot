"""Unit tests for the Retry Engine (Phase 3.6.4F).

Tests retry decision logic, transient vs permanent failure handling,
retry state transitions, retry exhaustion, timing, policy enforcement,
mixed DAG with retries, and edge cases.

All existing tests must remain green — retry is additive, not changing
existing permanent-failure behavior.
"""

from __future__ import annotations

import asyncio
import pytest
from datetime import datetime, timezone
from typing import Optional

from services.execution.base_adapter import ExecutionAdapter
from services.execution.dispatcher import Dispatcher
from services.execution.enums import SessionState, TaskState
from services.execution.execution_context import ExecutionContext
from services.execution.execution_models import (
    ExecutionSession,
    ExecutionTask,
    RetryDecision,
    RetryPolicy,
    TaskResult,
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


class MockPermanentFailAdapter(ExecutionAdapter):
    """Adapter that always fails permanently."""

    @property
    def adapter_type(self) -> str:
        return "mock_perm_fail"

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
            error="Permanent configuration error",
            error_type="permanent",
        )


class MockTransientFailAdapter(ExecutionAdapter):
    """Adapter that always returns a transient failure."""

    @property
    def adapter_type(self) -> str:
        return "mock_transient"

    @property
    def supported_task_types(self) -> list[TaskType]:
        return [TaskType.UPDATE_CRM]

    async def execute(
        self,
        task: ExecutionTask,
        context: ExecutionContext,
    ) -> TaskResult:
        return TaskResult(
            task_id=task.id,
            attempt=task.attempts,
            success=False,
            error="Temporary service unavailable",
            error_type="transient",
        )


class MockTransientThenSuccessAdapter(ExecutionAdapter):
    """Adapter that fails transiently N times then succeeds."""

    def __init__(self, fail_count: int = 1):
        self._fail_count = fail_count
        self._call_count = 0

    @property
    def adapter_type(self) -> str:
        return "mock_transient_then_ok"

    @property
    def supported_task_types(self) -> list[TaskType]:
        return [TaskType.ANALYZE_REPLY]

    async def execute(
        self,
        task: ExecutionTask,
        context: ExecutionContext,
    ) -> TaskResult:
        self._call_count += 1
        if self._call_count <= self._fail_count:
            return TaskResult(
                task_id=task.id,
                attempt=task.attempts,
                success=False,
                error=f"Transient failure #{self._call_count}",
                error_type="transient",
                metadata={"call": self._call_count},
            )
        return TaskResult(
            task_id=task.id,
            attempt=task.attempts,
            success=True,
            output={"succeeded_on_attempt": self._call_count},
        )


# ---------------------------------------------------------------------------
# Mock Resolver
# ---------------------------------------------------------------------------

class MockResolver:
    def __init__(self, adapter_map: dict[TaskType, ExecutionAdapter]):
        self._adapter_map = adapter_map

    def resolve(self, task_type: TaskType) -> Optional[ExecutionAdapter]:
        return self._adapter_map.get(task_type)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def engine():
    eng = ExecutionEngine()
    original_execute = eng.execute

    async def _fast_execute(plan, resolver=None, **kwargs):
        if "retry_policy" not in kwargs:
            kwargs["retry_policy"] = RetryPolicy(backoff_base_seconds=0)
        return await original_execute(plan, resolver=resolver, **kwargs)

    eng.execute = _fast_execute
    return eng


@pytest.fixture
def success_adapter():
    return MockSuccessAdapter()


@pytest.fixture
def perm_fail_adapter():
    return MockPermanentFailAdapter()


@pytest.fixture
def transient_adapter():
    return MockTransientFailAdapter()


@pytest.fixture
def resolver(success_adapter, perm_fail_adapter, transient_adapter):
    return MockResolver({
        TaskType.SEND_MESSAGE: success_adapter,
        TaskType.SEND_EMAIL: perm_fail_adapter,
        TaskType.UPDATE_CRM: transient_adapter,
    })


@pytest.fixture
def transient_then_ok_adapter():
    return MockTransientThenSuccessAdapter(fail_count=1)


@pytest.fixture
def success_plan():
    plan = Plan(
        id="success-plan",
        conversation_id="c",
        status=PlanStatus.VALIDATED,
        goal=PlanGoal(outcome="test"),
    )
    plan.tasks = [
        Task(
            id="task-a", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="telegram", template="ok"),
            label="success",
        ),
    ]
    return plan


@pytest.fixture
def perm_fail_plan():
    plan = Plan(
        id="perm-fail-plan",
        conversation_id="c",
        status=PlanStatus.VALIDATED,
        goal=PlanGoal(outcome="test"),
    )
    plan.tasks = [
        Task(
            id="task-a", plan_id=plan.id, type=TaskType.SEND_EMAIL,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="gmail", template="fail"),
            label="perm",
        ),
    ]
    return plan


@pytest.fixture
def transient_fail_plan():
    plan = Plan(
        id="transient-plan",
        conversation_id="c",
        status=PlanStatus.VALIDATED,
        goal=PlanGoal(outcome="test"),
    )
    plan.tasks = [
        Task(
            id="task-a", plan_id=plan.id, type=TaskType.UPDATE_CRM,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="none", template="none"),
            label="transient",
        ),
    ]
    return plan


@pytest.fixture
def linear_perm_fail_plan():
    """A → B, A fails permanently."""
    plan = Plan(
        id="linear-perm",
        conversation_id="c",
        status=PlanStatus.VALIDATED,
        goal=PlanGoal(outcome="test"),
    )
    plan.tasks = [
        Task(
            id="task-a", plan_id=plan.id, type=TaskType.SEND_EMAIL,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="gmail", template="a"),
            label="a fails perm",
        ),
        Task(
            id="task-b", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="telegram", template="b"),
            dependencies=["task-a"], label="b",
        ),
    ]
    return plan


@pytest.fixture
def transient_retry_then_ok_plan():
    plan = Plan(
        id="transient-retry-ok-plan",
        conversation_id="c",
        status=PlanStatus.VALIDATED,
        goal=PlanGoal(outcome="test"),
    )
    plan.tasks = [
        Task(
            id="task-a", plan_id=plan.id, type=TaskType.ANALYZE_REPLY,
            status=TaskStatus.PENDING,
            payload=MessagePayload(channel="none", template="none"),
            label="retry then ok",
        ),
    ]
    return plan


# ===================================================================
# RETRY DECISION UNIT TESTS
# ===================================================================

class TestRetryDecision:
    """Unit tests for _should_retry logic."""

    def test_no_retry_on_success(self):
        task = ExecutionTask(
            id="t1",
            plan_task=Task(id="t1", plan_id="p", type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING),
            attempts=1, max_attempts=3,
            retry_policy=RetryPolicy.default(),
        )
        result = TaskResult(task_id="t1", attempt=1, success=True)
        decision = ExecutionEngine._should_retry(task, result)
        assert decision.should_retry is False

    def test_no_retry_on_permanent_failure(self):
        task = ExecutionTask(
            id="t1",
            plan_task=Task(id="t1", plan_id="p", type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING),
            attempts=0, max_attempts=3,
            retry_policy=RetryPolicy.default(),
        )
        result = TaskResult(task_id="t1", attempt=0, success=False, error_type="permanent")
        decision = ExecutionEngine._should_retry(task, result)
        assert decision.should_retry is False

    def test_retry_on_transient_with_remaining_attempts(self):
        task = ExecutionTask(
            id="t1",
            plan_task=Task(id="t1", plan_id="p", type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING),
            attempts=0, max_attempts=3,
            retry_policy=RetryPolicy.default(),
        )
        result = TaskResult(task_id="t1", attempt=0, success=False, error_type="transient")
        decision = ExecutionEngine._should_retry(task, result)
        assert decision.should_retry is True
        assert decision.remaining_attempts == 2
        assert decision.delay_seconds > 0

    def test_no_retry_when_attempts_exhausted(self):
        task = ExecutionTask(
            id="t1",
            plan_task=Task(id="t1", plan_id="p", type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING),
            attempts=3, max_attempts=3,
            retry_policy=RetryPolicy.default(),
        )
        result = TaskResult(task_id="t1", attempt=3, success=False, error_type="transient")
        decision = ExecutionEngine._should_retry(task, result)
        assert decision.should_retry is False

    def test_no_retry_on_last_attempt(self):
        task = ExecutionTask(
            id="t1",
            plan_task=Task(id="t1", plan_id="p", type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING),
            attempts=2, max_attempts=3,
            retry_policy=RetryPolicy.default(),
        )
        result = TaskResult(task_id="t1", attempt=2, success=False, error_type="transient")
        decision = ExecutionEngine._should_retry(task, result)
        assert decision.should_retry is False
        assert decision.remaining_attempts == 0

    def test_retry_on_first_attempt_with_two_remaining(self):
        task = ExecutionTask(
            id="t1",
            plan_task=Task(id="t1", plan_id="p", type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING),
            attempts=1, max_attempts=5,
            retry_policy=RetryPolicy.default(),
        )
        result = TaskResult(task_id="t1", attempt=1, success=False, error_type="transient")
        decision = ExecutionEngine._should_retry(task, result)
        assert decision.should_retry is True
        assert decision.remaining_attempts == 3

    def test_no_retry_on_empty_error_type(self):
        task = ExecutionTask(
            id="t1",
            plan_task=Task(id="t1", plan_id="p", type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING),
            attempts=0, max_attempts=3,
            retry_policy=RetryPolicy.default(),
        )
        result = TaskResult(task_id="t1", attempt=0, success=False, error_type=None)
        decision = ExecutionEngine._should_retry(task, result)
        assert decision.should_retry is False

    def test_delay_from_retry_policy(self):
        task = ExecutionTask(
            id="t1",
            plan_task=Task(id="t1", plan_id="p", type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING),
            attempts=0, max_attempts=3,
            retry_policy=RetryPolicy(backoff_base_seconds=5.0, jitter=False),
        )
        result = TaskResult(task_id="t1", attempt=0, success=False, error_type="transient")
        decision = ExecutionEngine._should_retry(task, result)
        assert decision.should_retry is True
        assert decision.delay_seconds == 5.0

    def test_retry_decision_dataclass_fields(self):
        d = RetryDecision(should_retry=True, delay_seconds=2.5, remaining_attempts=1)
        assert d.should_retry is True
        assert d.delay_seconds == 2.5
        assert d.remaining_attempts == 1

    def test_retry_decision_defaults(self):
        d = RetryDecision()
        assert d.should_retry is False
        assert d.delay_seconds == 0.0
        assert d.remaining_attempts == 0


# ===================================================================
# NO RETRY ON SUCCESS
# ===================================================================

class TestNoRetryOnSuccess:
    """Successful tasks must not trigger retry logic."""

    def test_success_stays_completed(self, engine, success_plan, resolver):
        session = asyncio.run(engine.execute(success_plan, resolver=resolver))
        assert session.tasks["task-a"].status == TaskState.COMPLETED
        assert session.status == SessionState.COMPLETED

    def test_success_no_retry_state(self, engine, success_plan, resolver):
        session = asyncio.run(engine.execute(success_plan, resolver=resolver))
        task = session.tasks["task-a"]
        assert task.status != TaskState.RETRYING
        assert task.status != TaskState.WAITING

    def test_success_result_is_correct(self, engine, success_plan, resolver):
        session = asyncio.run(engine.execute(success_plan, resolver=resolver))
        task = session.tasks["task-a"]
        assert task.result is not None
        assert task.result.success is True
        assert task.result.error is None

    def test_success_attempts_not_incremented(self, engine, success_plan, resolver):
        session = asyncio.run(engine.execute(success_plan, resolver=resolver))
        task = session.tasks["task-a"]
        assert task.attempts == 0


# ===================================================================
# PERMANENT FAILURE (unchanged behavior)
# ===================================================================

class TestPermanentFailure:
    """Permanent failures must behave exactly as before — no retry."""

    def test_permanent_fails_immediately(self, engine, perm_fail_plan, resolver):
        session = asyncio.run(engine.execute(perm_fail_plan, resolver=resolver))
        assert session.tasks["task-a"].status == TaskState.FAILED
        assert session.status == SessionState.FAILED

    def test_permanent_no_retry_transition(self, engine, perm_fail_plan, resolver):
        session = asyncio.run(engine.execute(perm_fail_plan, resolver=resolver))
        task = session.tasks["task-a"]
        assert task.status != TaskState.RETRYING
        assert task.status != TaskState.WAITING

    def test_permanent_result_preserved(self, engine, perm_fail_plan, resolver):
        session = asyncio.run(engine.execute(perm_fail_plan, resolver=resolver))
        task = session.tasks["task-a"]
        assert task.result is not None
        assert task.result.success is False
        assert task.result.error == "Permanent configuration error"
        assert task.result.error_type == "permanent"

    def test_permanent_attempts_not_incremented(self, engine, perm_fail_plan, resolver):
        session = asyncio.run(engine.execute(perm_fail_plan, resolver=resolver))
        task = session.tasks["task-a"]
        assert task.attempts == 0

    def test_permanent_downstream_blocked(self, engine, linear_perm_fail_plan, resolver):
        session = asyncio.run(engine.execute(linear_perm_fail_plan, resolver=resolver))
        assert session.tasks["task-a"].status == TaskState.FAILED
        assert session.tasks["task-b"].status == TaskState.SKIPPED

    def test_permanent_session_state_failed(self, engine, perm_fail_plan, resolver):
        session = asyncio.run(engine.execute(perm_fail_plan, resolver=resolver))
        assert session.status == SessionState.FAILED

    def test_permanent_end_time_set(self, engine, perm_fail_plan, resolver):
        session = asyncio.run(engine.execute(perm_fail_plan, resolver=resolver))
        assert session.end_time is not None


# ===================================================================
# TRANSIENT — SINGLE RETRY SUCCEEDS
# ===================================================================

class TestTransientSingleRetrySucceeds:
    """Transient failure, retry succeeds on first retry attempt."""

    def test_retry_ends_completed(self, engine, transient_retry_then_ok_plan, resolver):
        adapter = MockTransientThenSuccessAdapter(fail_count=1)
        custom_resolver = MockResolver({TaskType.ANALYZE_REPLY: adapter})
        session = asyncio.run(engine.execute(transient_retry_then_ok_plan, resolver=custom_resolver))
        assert session.tasks["task-a"].status == TaskState.COMPLETED
        assert session.status == SessionState.COMPLETED

    def test_retry_goes_through_retrying_state(self, engine, transient_retry_then_ok_plan, resolver):
        adapter = MockTransientThenSuccessAdapter(fail_count=1)
        custom_resolver = MockResolver({TaskType.ANALYZE_REPLY: adapter})
        session = asyncio.run(engine.execute(transient_retry_then_ok_plan, resolver=custom_resolver))
        task = session.tasks["task-a"]
        assert task.status == TaskState.COMPLETED

    def test_retry_increments_attempts(self, engine, transient_retry_then_ok_plan, resolver):
        adapter = MockTransientThenSuccessAdapter(fail_count=1)
        custom_resolver = MockResolver({TaskType.ANALYZE_REPLY: adapter})
        session = asyncio.run(engine.execute(transient_retry_then_ok_plan, resolver=custom_resolver))
        task = session.tasks["task-a"]
        assert task.attempts == 1

    def test_retry_final_result_is_success(self, engine, transient_retry_then_ok_plan, resolver):
        adapter = MockTransientThenSuccessAdapter(fail_count=1)
        custom_resolver = MockResolver({TaskType.ANALYZE_REPLY: adapter})
        session = asyncio.run(engine.execute(transient_retry_then_ok_plan, resolver=custom_resolver))
        task = session.tasks["task-a"]
        assert task.result is not None
        assert task.result.success is True

    def test_retry_has_initial_failure_in_result(self, engine, transient_retry_then_ok_plan, resolver):
        adapter = MockTransientThenSuccessAdapter(fail_count=1)
        custom_resolver = MockResolver({TaskType.ANALYZE_REPLY: adapter})
        session = asyncio.run(engine.execute(transient_retry_then_ok_plan, resolver=custom_resolver))
        task = session.tasks["task-a"]
        assert task.result.success is True
        assert task.result.output["succeeded_on_attempt"] == 2


# ===================================================================
# TRANSIENT — RETRY SUCCEEDS ON SECOND ATTEMPT
# ===================================================================

class TestTransientRetrySucceedsOnSecondAttempt:
    """Transient failure twice, then succeeds on the third try."""

    def test_succeeds_after_two_retries(self, engine, transient_retry_then_ok_plan, resolver):
        adapter = MockTransientThenSuccessAdapter(fail_count=2)
        custom_resolver = MockResolver({TaskType.ANALYZE_REPLY: adapter})
        session = asyncio.run(engine.execute(transient_retry_then_ok_plan, resolver=custom_resolver))
        assert session.tasks["task-a"].status == TaskState.COMPLETED
        assert session.status == SessionState.COMPLETED

    def test_two_retries_attempt_count(self, engine, transient_retry_then_ok_plan, resolver):
        adapter = MockTransientThenSuccessAdapter(fail_count=2)
        custom_resolver = MockResolver({TaskType.ANALYZE_REPLY: adapter})
        session = asyncio.run(engine.execute(transient_retry_then_ok_plan, resolver=custom_resolver))
        task = session.tasks["task-a"]
        assert task.attempts == 2

    def test_two_retries_final_result_success(self, engine, transient_retry_then_ok_plan, resolver):
        adapter = MockTransientThenSuccessAdapter(fail_count=2)
        custom_resolver = MockResolver({TaskType.ANALYZE_REPLY: adapter})
        session = asyncio.run(engine.execute(transient_retry_then_ok_plan, resolver=custom_resolver))
        task = session.tasks["task-a"]
        assert task.result is not None
        assert task.result.success is True
        assert task.result.output["succeeded_on_attempt"] == 3


# ===================================================================
# TRANSIENT — RETRY SUCCEEDS ON FINAL ALLOWED ATTEMPT
# ===================================================================

class TestTransientRetrySucceedsOnFinalAttempt:
    """Retry exhausts all attempts except the last one before succeeding."""

    def test_succeeds_on_last_attempt(self, engine, resolver):
        plan = Plan(
            id="final-attempt",
            conversation_id="c",
            status=PlanStatus.VALIDATED,
            goal=PlanGoal(outcome="test"),
        )
        plan.tasks = [
            Task(
                id="task-a", plan_id=plan.id, type=TaskType.ANALYZE_REPLY,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="none", template="none"),
                label="final attempt",
            ),
        ]
        adapter = MockTransientThenSuccessAdapter(fail_count=2)
        custom_resolver = MockResolver({TaskType.ANALYZE_REPLY: adapter})
        # max_attempts = 3, fail twice then succeed → succeeds on 3rd
        session = asyncio.run(engine.execute(plan, resolver=custom_resolver))
        assert session.tasks["task-a"].status == TaskState.COMPLETED
        task = session.tasks["task-a"]
        assert task.attempts == 2

    def test_final_attempt_result(self, engine, resolver):
        plan = Plan(
            id="final-attempt-2",
            conversation_id="c",
            status=PlanStatus.VALIDATED,
            goal=PlanGoal(outcome="test"),
        )
        plan.tasks = [
            Task(
                id="task-a", plan_id=plan.id, type=TaskType.ANALYZE_REPLY,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="none", template="none"),
                label="final attempt",
            ),
        ]
        adapter = MockTransientThenSuccessAdapter(fail_count=2)
        custom_resolver = MockResolver({TaskType.ANALYZE_REPLY: adapter})
        session = asyncio.run(engine.execute(plan, resolver=custom_resolver))
        task = session.tasks["task-a"]
        assert task.result is not None
        assert task.result.success is True
        assert task.result.output["succeeded_on_attempt"] == 3


# ===================================================================
# RETRY EXHAUSTION
# ===================================================================

class TestRetryExhaustion:
    """Transient failures exhaust all retries → FAILED."""

    def test_exhaustion_ends_failed(self, engine, transient_fail_plan, resolver):
        session = asyncio.run(engine.execute(transient_fail_plan, resolver=resolver))
        task = session.tasks["task-a"]
        assert task.status == TaskState.FAILED
        assert session.status == SessionState.FAILED

    def test_exhaustion_attempts_match_max(self, engine, transient_fail_plan, resolver):
        session = asyncio.run(engine.execute(transient_fail_plan, resolver=resolver))
        task = session.tasks["task-a"]
        assert task.attempts == task.max_attempts - 1
        assert task.attempts == 2

    def test_exhaustion_last_error_is_transient(self, engine, transient_fail_plan, resolver):
        session = asyncio.run(engine.execute(transient_fail_plan, resolver=resolver))
        task = session.tasks["task-a"]
        assert task.result is not None
        assert task.result.success is False
        assert task.result.error == "Temporary service unavailable"
        assert task.result.error_type == "transient"

    def test_exhaustion_downstream_not_blocked_until_exhausted(self, engine, resolver):
        """Downstream should only be blocked after retries are exhausted."""
        plan = Plan(
            id="exhaust-downstream",
            conversation_id="c",
            status=PlanStatus.VALIDATED,
            goal=PlanGoal(outcome="test"),
        )
        plan.tasks = [
            Task(
                id="task-a", plan_id=plan.id, type=TaskType.UPDATE_CRM,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="none", template="none"),
                label="a transient",
            ),
            Task(
                id="task-b", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="telegram", template="b"),
                dependencies=["task-a"], label="b",
            ),
        ]
        session = asyncio.run(engine.execute(plan, resolver=resolver))
        assert session.tasks["task-a"].status == TaskState.FAILED
        assert session.tasks["task-b"].status == TaskState.SKIPPED

    def test_exhaustion_session_failed(self, engine, transient_fail_plan, resolver):
        session = asyncio.run(engine.execute(transient_fail_plan, resolver=resolver))
        assert session.status == SessionState.FAILED

    def test_exhaustion_sets_end_time(self, engine, transient_fail_plan, resolver):
        session = asyncio.run(engine.execute(transient_fail_plan, resolver=resolver))
        assert session.end_time is not None


# ===================================================================
# RETRY TIMING
# ===================================================================

class TestRetryTiming:
    """Retry delay must be honored."""

    @staticmethod
    def _make_plan_and_scheduler(task_id: str = "t1", delay: float = 1.0):
        etask = ExecutionTask(
            id=task_id,
            plan_task=Task(id=task_id, plan_id="p", type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING),
            attempts=0, max_attempts=3,
            status=TaskState.RUNNING,
            retry_policy=RetryPolicy(backoff_base_seconds=delay, jitter=False),
        )
        plan = Plan(
            id="timing-plan",
            conversation_id="c",
            status=PlanStatus.VALIDATED,
            goal=PlanGoal(outcome="test"),
        )
        plan.tasks = [
            Task(
                id=task_id, plan_id=plan.id, type=TaskType.SEND_MESSAGE,
                status=TaskStatus.PENDING,
            ),
        ]
        session = ExecutionSession(
            id="timing-session",
            plan_id=plan.id,
            plan=plan,
            conversation_id="c",
            tasks={task_id: etask},
            status=SessionState.RUNNING,
        )
        scheduler = Scheduler(session)
        scheduler._running.add(task_id)
        return scheduler, etask

    def test_retry_delay_zero(self):
        scheduler, task = self._make_plan_and_scheduler(delay=0)
        result = TaskResult(task_id="t1", attempt=0, success=False, error_type="transient")
        decision = ExecutionEngine._should_retry(task, result)
        assert decision.delay_seconds == 0
        asyncio.run(ExecutionEngine._schedule_retry(task, scheduler, decision))

    def test_retry_delay_honored(self):
        scheduler, task = self._make_plan_and_scheduler(delay=0.05)
        result = TaskResult(task_id="t1", attempt=0, success=False, error_type="transient")
        decision = ExecutionEngine._should_retry(task, result)
        start = datetime.now(timezone.utc)
        asyncio.run(ExecutionEngine._schedule_retry(task, scheduler, decision))
        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        assert elapsed >= 0.04

    def test_retry_delay_different_values(self):
        scheduler, task = self._make_plan_and_scheduler(delay=0.1)
        result = TaskResult(task_id="t1", attempt=0, success=False, error_type="transient")
        decision = ExecutionEngine._should_retry(task, result)
        assert decision.delay_seconds == 0.1
        start = datetime.now(timezone.utc)
        asyncio.run(ExecutionEngine._schedule_retry(task, scheduler, decision))
        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        assert elapsed >= 0.09


# ===================================================================
# RETRY POLICY VARIANTS
# ===================================================================

class TestRetryPolicyVariants:
    """Different RetryPolicy configurations."""

    def test_default_max_attempts_three(self, engine, resolver):
        """Default max_attempts=3: transient adapter exhausts after 2 retries."""
        plan = Plan(
            id="default-max-plan",
            conversation_id="c",
            status=PlanStatus.VALIDATED,
            goal=PlanGoal(outcome="test"),
        )
        plan.tasks = [
            Task(
                id="task-a", plan_id=plan.id, type=TaskType.UPDATE_CRM,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="none", template="none"),
                label="max3",
            ),
        ]
        session = asyncio.run(engine.execute(plan, resolver=resolver))
        task = session.tasks["task-a"]
        assert task.status == TaskState.FAILED
        assert task.attempts == 2  # 0 initial + 2 retries = 3 total = max_attempts

    def test_retry_with_max_attempts_one_via_unit(self):
        """max_attempts=1 means no retry allowed — unit test."""
        task = ExecutionTask(
            id="t1",
            plan_task=Task(id="t1", plan_id="p", type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING),
            attempts=0, max_attempts=1,
            retry_policy=RetryPolicy.default(),
        )
        result = TaskResult(task_id="t1", attempt=0, success=False, error_type="transient")
        decision = ExecutionEngine._should_retry(task, result)
        assert decision.should_retry is False

    def test_zero_delay_retry_executes_quickly(self, engine, resolver):
        """retry_delay=0 should not block — retries still occur."""
        plan = Plan(
            id="zero-delay",
            conversation_id="c",
            status=PlanStatus.VALIDATED,
            goal=PlanGoal(outcome="test"),
        )
        plan.tasks = [
            Task(
                id="task-a", plan_id=plan.id, type=TaskType.UPDATE_CRM,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="none", template="none"),
                label="zero delay",
            ),
        ]
        session = asyncio.run(engine.execute(plan, resolver=resolver))
        task = session.tasks["task-a"]
        assert task.status == TaskState.FAILED
        assert task.attempts == 2  # 0 initial + 2 retries = 3 attempts total

    def test_custom_max_attempts_on_task(self, engine, resolver):
        """Task with custom max_attempts in payload params uses it."""
        plan = Plan(
            id="custom-max",
            conversation_id="c",
            status=PlanStatus.VALIDATED,
            goal=PlanGoal(outcome="test"),
        )
        plan.tasks = [
            Task(
                id="task-a", plan_id=plan.id, type=TaskType.UPDATE_CRM,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="none", template="none"),
                label="custom max",
            ),
        ]
        session = asyncio.run(engine.execute(plan, resolver=resolver))
        task = session.tasks["task-a"]
        assert task.status == TaskState.FAILED

    def test_default_retry_policy_used(self):
        policy = RetryPolicy.default()
        assert policy.max_attempts == 3
        assert policy.backoff_base_seconds == 1.0


# ===================================================================
# MIXED DAG WITH RETRY
# ===================================================================

class TestMixedDagWithRetry:
    """A retries, B executes normally, C depends on A (waits)."""

    def test_retry_and_independent_task(self, engine, resolver):
        """A retries (transient then ok), B runs independently."""
        plan = Plan(
            id="mixed-dag",
            conversation_id="c",
            status=PlanStatus.VALIDATED,
            goal=PlanGoal(outcome="test"),
        )
        plan.tasks = [
            Task(
                id="task-a", plan_id=plan.id, type=TaskType.ANALYZE_REPLY,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="none", template="none"),
                label="a retries",
            ),
            Task(
                id="task-b", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="telegram", template="b"),
                label="b independent",
            ),
        ]
        adapter_a = MockTransientThenSuccessAdapter(fail_count=1)
        custom_resolver = MockResolver({
            TaskType.ANALYZE_REPLY: adapter_a,
            TaskType.SEND_MESSAGE: MockSuccessAdapter(),
        })
        session = asyncio.run(engine.execute(plan, resolver=custom_resolver))
        assert session.tasks["task-a"].status == TaskState.COMPLETED
        assert session.tasks["task-b"].status == TaskState.COMPLETED
        assert session.status == SessionState.COMPLETED

    def test_retry_fails_downstream_waits(self, engine, resolver):
        """A retries and exhausts, B (dependent) is skipped."""
        plan = Plan(
            id="retry-downstream",
            conversation_id="c",
            status=PlanStatus.VALIDATED,
            goal=PlanGoal(outcome="test"),
        )
        plan.tasks = [
            Task(
                id="task-a", plan_id=plan.id, type=TaskType.UPDATE_CRM,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="none", template="none"),
                label="a retries and exhausts",
            ),
            Task(
                id="task-b", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="telegram", template="b"),
                dependencies=["task-a"], label="b depends on a",
            ),
        ]
        session = asyncio.run(engine.execute(plan, resolver=resolver))
        assert session.tasks["task-a"].status == TaskState.FAILED
        assert session.tasks["task-b"].status == TaskState.SKIPPED

    def test_retry_recovers_downstream_executes(self, engine, resolver):
        """A retries and succeeds, B (dependent) executes."""
        plan = Plan(
            id="retry-recover",
            conversation_id="c",
            status=PlanStatus.VALIDATED,
            goal=PlanGoal(outcome="test"),
        )
        plan.tasks = [
            Task(
                id="task-a", plan_id=plan.id, type=TaskType.ANALYZE_REPLY,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="none", template="none"),
                label="a retries then ok",
            ),
            Task(
                id="task-b", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="telegram", template="b"),
                dependencies=["task-a"], label="b depends on a",
            ),
        ]
        adapter_a = MockTransientThenSuccessAdapter(fail_count=1)
        custom_resolver = MockResolver({
            TaskType.ANALYZE_REPLY: adapter_a,
            TaskType.SEND_MESSAGE: MockSuccessAdapter(),
        })
        session = asyncio.run(engine.execute(plan, resolver=custom_resolver))
        assert session.tasks["task-a"].status == TaskState.COMPLETED
        assert session.tasks["task-b"].status == TaskState.COMPLETED

    def test_independent_not_affected_by_retry(self, engine, resolver):
        """Independent task should complete even if another retries."""
        plan = Plan(
            id="independent-not-affected",
            conversation_id="c",
            status=PlanStatus.VALIDATED,
            goal=PlanGoal(outcome="test"),
        )
        plan.tasks = [
            Task(
                id="task-a", plan_id=plan.id, type=TaskType.UPDATE_CRM,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="none", template="none"),
                label="a retries and exhausts",
            ),
            Task(
                id="task-b", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="telegram", template="b"),
                label="b independent",
            ),
        ]
        session = asyncio.run(engine.execute(plan, resolver=resolver))
        assert session.tasks["task-a"].status == TaskState.FAILED
        assert session.tasks["task-b"].status == TaskState.COMPLETED

    def test_chain_retry_middle_recovers(self, engine, resolver):
        """A→B→C, B retries and succeeds, A and C complete."""
        plan = Plan(
            id="chain-retry-middle",
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
                id="task-b", plan_id=plan.id, type=TaskType.ANALYZE_REPLY,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="none", template="none"),
                dependencies=["task-a"], label="b retries",
            ),
            Task(
                id="task-c", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="telegram", template="c"),
                dependencies=["task-b"], label="c",
            ),
        ]
        adapter_b = MockTransientThenSuccessAdapter(fail_count=1)
        custom_resolver = MockResolver({
            TaskType.SEND_MESSAGE: MockSuccessAdapter(),
            TaskType.ANALYZE_REPLY: adapter_b,
        })
        session = asyncio.run(engine.execute(plan, resolver=custom_resolver))
        assert session.tasks["task-a"].status == TaskState.COMPLETED
        assert session.tasks["task-b"].status == TaskState.COMPLETED
        assert session.tasks["task-c"].status == TaskState.COMPLETED

    def test_chain_retry_middle_exhausts(self, engine, resolver):
        """A→B→C, B retries and exhausts, A ok, C skipped."""
        plan = Plan(
            id="chain-retry-exhaust",
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
                id="task-b", plan_id=plan.id, type=TaskType.UPDATE_CRM,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="none", template="none"),
                dependencies=["task-a"], label="b exhausts",
            ),
            Task(
                id="task-c", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="telegram", template="c"),
                dependencies=["task-b"], label="c",
            ),
        ]
        custom_resolver = MockResolver({
            TaskType.SEND_MESSAGE: MockSuccessAdapter(),
            TaskType.UPDATE_CRM: MockTransientFailAdapter(),
        })
        session = asyncio.run(engine.execute(plan, resolver=custom_resolver))
        assert session.tasks["task-a"].status == TaskState.COMPLETED
        assert session.tasks["task-b"].status == TaskState.FAILED
        assert session.tasks["task-c"].status == TaskState.SKIPPED


# ===================================================================
# EDGE CASES
# ===================================================================

class TestEdgeCases:
    """Edge cases and robustness."""

    def test_multiple_retrying_tasks(self, engine, resolver):
        """Two independent tasks both retry and exhaust."""
        plan = Plan(
            id="multi-retry",
            conversation_id="c",
            status=PlanStatus.VALIDATED,
            goal=PlanGoal(outcome="test"),
        )
        plan.tasks = [
            Task(
                id="task-a", plan_id=plan.id, type=TaskType.UPDATE_CRM,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="none", template="none"),
                label="a",
            ),
            Task(
                id="task-b", plan_id=plan.id, type=TaskType.UPDATE_CRM,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="none", template="none"),
                label="b",
            ),
        ]
        session = asyncio.run(engine.execute(plan, resolver=resolver))
        assert session.tasks["task-a"].status == TaskState.FAILED
        assert session.tasks["task-b"].status == TaskState.FAILED
        assert session.status == SessionState.FAILED

    def test_independent_retry_chains(self, engine, resolver):
        """Two independent chains each with a transient-then-ok task."""
        plan = Plan(
            id="independent-chains",
            conversation_id="c",
            status=PlanStatus.VALIDATED,
            goal=PlanGoal(outcome="test"),
        )
        plan.tasks = [
            Task(
                id="task-a", plan_id=plan.id, type=TaskType.ANALYZE_REPLY,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="none", template="none"),
                label="a",
            ),
            Task(
                id="task-b", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="telegram", template="b"),
                dependencies=["task-a"], label="b",
            ),
            Task(
                id="task-c", plan_id=plan.id, type=TaskType.ANALYZE_REPLY,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="none", template="none"),
                label="c",
            ),
            Task(
                id="task-d", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="telegram", template="d"),
                dependencies=["task-c"], label="d",
            ),
        ]
        adapter = MockTransientThenSuccessAdapter(fail_count=1)
        custom_resolver = MockResolver({
            TaskType.ANALYZE_REPLY: adapter,
            TaskType.SEND_MESSAGE: MockSuccessAdapter(),
        })
        session = asyncio.run(engine.execute(plan, resolver=custom_resolver))
        for tid in ("task-a", "task-b", "task-c", "task-d"):
            assert session.tasks[tid].status == TaskState.COMPLETED

    def test_transient_then_permanent(self, engine, resolver):
        """Transient on first attempt, permanent on second."""
        class TransientThenPermAdapter(ExecutionAdapter):
            def __init__(self):
                self.call_count = 0

            @property
            def adapter_type(self): return "transient_then_perm"

            @property
            def supported_task_types(self): return [TaskType.ANALYZE_REPLY]

            async def execute(self, task, ctx):
                self.call_count += 1
                if self.call_count == 1:
                    return TaskResult(task_id=task.id, attempt=0, success=False,
                                      error="transient", error_type="transient")
                return TaskResult(task_id=task.id, attempt=1, success=False,
                                  error="permanent now", error_type="permanent")

        plan = Plan(
            id="trans-then-perm",
            conversation_id="c",
            status=PlanStatus.VALIDATED,
            goal=PlanGoal(outcome="test"),
        )
        plan.tasks = [
            Task(
                id="task-a", plan_id=plan.id, type=TaskType.ANALYZE_REPLY,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="none", template="none"),
                label="a",
            ),
        ]
        custom_resolver = MockResolver({TaskType.ANALYZE_REPLY: TransientThenPermAdapter()})
        session = asyncio.run(engine.execute(plan, resolver=custom_resolver))
        task = session.tasks["task-a"]
        assert task.status == TaskState.FAILED
        assert task.attempts == 1
        assert task.result.error_type == "permanent"

    def test_retry_does_not_affect_other_sessions(self, engine, resolver):
        """Retry in one session should not impact another."""
        plan1 = Plan(
            id="s1", conversation_id="c", status=PlanStatus.VALIDATED,
            goal=PlanGoal(outcome="test"),
        )
        plan1.tasks = [
            Task(
                id="task-a", plan_id="s1", type=TaskType.ANALYZE_REPLY,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="none", template="none"),
                label="a",
            ),
        ]

        plan2 = Plan(
            id="s2", conversation_id="c", status=PlanStatus.VALIDATED,
            goal=PlanGoal(outcome="test"),
        )
        plan2.tasks = [
            Task(
                id="task-b", plan_id="s2", type=TaskType.SEND_MESSAGE,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="telegram", template="b"),
                label="b",
            ),
        ]

        adapter_a = MockTransientThenSuccessAdapter(fail_count=1)
        custom_resolver1 = MockResolver({TaskType.ANALYZE_REPLY: adapter_a})
        s1 = asyncio.run(engine.execute(plan1, resolver=custom_resolver1))

        s2 = asyncio.run(engine.execute(plan2, resolver=resolver))
        assert s1.tasks["task-a"].status == TaskState.COMPLETED
        assert s2.tasks["task-b"].status == TaskState.COMPLETED

    def test_retry_with_zero_delay_still_retries(self, engine, resolver):
        """Zero delay should still execute retry flow."""
        plan = Plan(
            id="zero-delay-retry",
            conversation_id="c",
            status=PlanStatus.VALIDATED,
            goal=PlanGoal(outcome="test"),
        )
        plan.tasks = [
            Task(
                id="task-a", plan_id=plan.id, type=TaskType.ANALYZE_REPLY,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="none", template="none"),
                label="zero delay retry",
            ),
        ]
        adapter = MockTransientThenSuccessAdapter(fail_count=1)
        custom_resolver = MockResolver({TaskType.ANALYZE_REPLY: adapter})
        session = asyncio.run(engine.execute(plan, resolver=custom_resolver))
        assert session.tasks["task-a"].status == TaskState.COMPLETED
        assert session.tasks["task-a"].attempts == 1


# ===================================================================
# SCHEDULER INTERACTION
# ===================================================================

class TestSchedulerInteraction:
    """Retry interactions with the scheduler."""

    @staticmethod
    def _make_session_with_task(task_status=TaskState.WAITING):
        plan = Plan(
            id="req-plan",
            conversation_id="c",
            status=PlanStatus.VALIDATED,
            goal=PlanGoal(outcome="test"),
        )
        plan.tasks = [
            Task(
                id="t1", plan_id="req-plan", type=TaskType.SEND_MESSAGE,
                status=TaskStatus.PENDING,
            ),
        ]
        etask = ExecutionTask(
            id="t1",
            plan_task=plan.tasks[0],
            status=task_status,
        )
        session = ExecutionSession(
            id="sess",
            plan_id="req-plan",
            plan=plan,
            conversation_id="c",
            tasks={"t1": etask},
            status=SessionState.RUNNING,
        )
        scheduler = Scheduler(session)
        scheduler._ready_queue.clear()
        return scheduler, etask

    def test_requeue_releases_running_slot(self):
        scheduler, task = self._make_session_with_task(TaskState.WAITING)
        scheduler._running.add("t1")
        assert "t1" in scheduler._running
        scheduler.requeue("t1")
        assert "t1" not in scheduler._running

    def test_requeue_transitions_to_ready(self):
        scheduler, task = self._make_session_with_task(TaskState.WAITING)
        scheduler._running.add("t1")
        scheduler.requeue("t1")
        assert task.status == TaskState.READY

    def test_requeue_task_available_in_ready_queue(self):
        scheduler, task = self._make_session_with_task(TaskState.WAITING)
        scheduler._running.add("t1")
        original_count = scheduler.ready_count()
        scheduler.requeue("t1")
        assert scheduler.ready_count() == original_count + 1
        next_id = scheduler.get_next_ready()
        assert next_id == "t1"

    def test_concurrency_slot_released_on_retry(self, engine, resolver):
        """Retry should release concurrency slot so other tasks can run."""
        plan = Plan(
            id="concurrency-retry",
            conversation_id="c",
            status=PlanStatus.VALIDATED,
            goal=PlanGoal(outcome="test"),
        )
        plan.tasks = [
            Task(
                id="task-a", plan_id=plan.id, type=TaskType.UPDATE_CRM,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="none", template="none"),
                label="a retries",
            ),
            Task(
                id="task-b", plan_id=plan.id, type=TaskType.SEND_MESSAGE,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="telegram", template="b"),
                label="b independent",
            ),
        ]
        session = asyncio.run(engine.execute(plan, resolver=resolver))
        assert session.tasks["task-a"].status == TaskState.FAILED
        assert session.tasks["task-b"].status == TaskState.COMPLETED


# ===================================================================
# STATE TRANSITION TESTS
# ===================================================================

class TestRetryStateTransitions:
    """Verify retry state transitions through the state machine."""

    def test_running_to_retrying_allowed(self):
        task = ExecutionTask(
            id="t1",
            plan_task=Task(id="t1", plan_id="p", type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING),
            status=TaskState.RUNNING,
        )
        StateMachine.transition_task(task, TaskState.RETRYING)
        assert task.status == TaskState.RETRYING

    def test_retrying_to_waiting_allowed(self):
        task = ExecutionTask(
            id="t1",
            plan_task=Task(id="t1", plan_id="p", type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING),
            status=TaskState.RETRYING,
        )
        StateMachine.transition_task(task, TaskState.WAITING)
        assert task.status == TaskState.WAITING

    def test_waiting_to_ready_allowed(self):
        task = ExecutionTask(
            id="t1",
            plan_task=Task(id="t1", plan_id="p", type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING),
            status=TaskState.WAITING,
        )
        StateMachine.transition_task(task, TaskState.READY)
        assert task.status == TaskState.READY

    def test_ready_to_running_allowed(self):
        task = ExecutionTask(
            id="t1",
            plan_task=Task(id="t1", plan_id="p", type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING),
            status=TaskState.READY,
        )
        StateMachine.transition_task(task, TaskState.RUNNING)
        assert task.status == TaskState.RUNNING

    def test_complete_retry_cycle(self):
        task = ExecutionTask(
            id="t1",
            plan_task=Task(id="t1", plan_id="p", type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING),
            status=TaskState.RUNNING,
        )
        StateMachine.transition_task(task, TaskState.RETRYING)
        StateMachine.transition_task(task, TaskState.WAITING)
        StateMachine.transition_task(task, TaskState.READY)
        StateMachine.transition_task(task, TaskState.RUNNING)
        StateMachine.transition_task(task, TaskState.COMPLETED)
        assert task.status == TaskState.COMPLETED

    def test_retrying_to_failed_allowed(self):
        task = ExecutionTask(
            id="t1",
            plan_task=Task(id="t1", plan_id="p", type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING),
            status=TaskState.RETRYING,
        )
        StateMachine.transition_task(task, TaskState.FAILED)
        assert task.status == TaskState.FAILED

    def test_running_to_retrying_on_transient(self, engine, resolver):
        """Pipeline should transition through RETRYING for transient errors."""
        plan = Plan(
            id="state-transition-test",
            conversation_id="c",
            status=PlanStatus.VALIDATED,
            goal=PlanGoal(outcome="test"),
        )
        plan.tasks = [
            Task(
                id="task-a", plan_id=plan.id, type=TaskType.ANALYZE_REPLY,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="none", template="none"),
                label="a",
            ),
        ]
        adapter = MockTransientThenSuccessAdapter(fail_count=1)
        custom_resolver = MockResolver({TaskType.ANALYZE_REPLY: adapter})
        session = asyncio.run(engine.execute(plan, resolver=custom_resolver))
        task = session.tasks["task-a"]
        assert task.status == TaskState.COMPLETED
        assert task.attempts == 1

    def test_retry_exhaustion_ends_failed(self, engine, resolver):
        """After exhausting retries, task should be FAILED."""
        plan = Plan(
            id="exhaust-state",
            conversation_id="c",
            status=PlanStatus.VALIDATED,
            goal=PlanGoal(outcome="test"),
        )
        plan.tasks = [
            Task(
                id="task-a", plan_id=plan.id, type=TaskType.UPDATE_CRM,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="none", template="none"),
                label="a",
            ),
        ]
        session = asyncio.run(engine.execute(plan, resolver=resolver))
        assert session.tasks["task-a"].status == TaskState.FAILED


# ===================================================================
# RETRYDECISION DATACLASS
# ===================================================================

class TestRetryDecisionDataclass:
    """Verify RetryDecision dataclass works correctly."""

    def test_construction(self):
        d = RetryDecision(should_retry=True, delay_seconds=2.0, remaining_attempts=3)
        assert d.should_retry is True
        assert d.delay_seconds == 2.0
        assert d.remaining_attempts == 3

    def test_default_construction(self):
        d = RetryDecision()
        assert d.should_retry is False
        assert d.delay_seconds == 0.0
        assert d.remaining_attempts == 0

    def test_partial_construction(self):
        d = RetryDecision(should_retry=True)
        assert d.should_retry is True
        assert d.delay_seconds == 0.0
        assert d.remaining_attempts == 0

    def test_mutable(self):
        d = RetryDecision()
        d.should_retry = True
        d.delay_seconds = 5.0
        d.remaining_attempts = 2
        assert d.should_retry is True
        assert d.delay_seconds == 5.0
        assert d.remaining_attempts == 2

    def test_used_by_should_retry(self):
        task = ExecutionTask(
            id="t1",
            plan_task=Task(id="t1", plan_id="p", type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING),
            attempts=0, max_attempts=3,
            retry_policy=RetryPolicy(backoff_base_seconds=1.5, jitter=False),
        )
        result = TaskResult(task_id="t1", attempt=0, success=False, error_type="transient")
        decision = ExecutionEngine._should_retry(task, result)
        assert isinstance(decision, RetryDecision)
        assert decision.should_retry is True
        assert decision.delay_seconds == 1.5
        assert decision.remaining_attempts == 2
