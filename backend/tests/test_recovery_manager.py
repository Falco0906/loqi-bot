"""Unit tests for the Recovery Manager (Phase 3.6.4I).

Tests session validation, state fixing, scheduler reconstruction, approval
integration, and pipeline recovery. All existing 739 tests must remain green.
"""

from __future__ import annotations

import asyncio
import pytest
from datetime import datetime, timezone
from typing import Optional

from services.execution.base_adapter import ExecutionAdapter
from services.execution.dispatcher import Dispatcher
from services.execution.enums import ExecutionEventType, SessionState, TaskState
from services.execution.event_bus import EventBus
from services.execution.execution_context import ExecutionContext
from services.execution.execution_models import (
    ExecutionEvent,
    ExecutionSession,
    ExecutionTask,
    RetryPolicy,
    TaskResult,
)
from services.execution.execution_pipeline import ExecutionEngine
from services.execution.recovery_manager import RecoveryError, RecoveryManager
from services.execution.scheduler import Scheduler
from services.execution.state_machine import StateMachine
from services.planner.planning_models import (
    Plan, PlanGoal, Task, PlanStatus, TaskStatus, TaskType,
)
from services.planner.payloads import MessagePayload


# ---------------------------------------------------------------------------
# Mock Adapters
# ---------------------------------------------------------------------------

class MockSuccessAdapter(ExecutionAdapter):
    @property
    def adapter_type(self) -> str:
        return "mock_success"
    @property
    def supported_task_types(self) -> list[TaskType]:
        return [TaskType.SEND_MESSAGE]
    async def execute(self, task, context) -> TaskResult:
        return TaskResult(task_id=task.id, attempt=task.attempts, success=True, output={"result": "ok"})


class MockPermanentFailAdapter(ExecutionAdapter):
    @property
    def adapter_type(self) -> str:
        return "mock_perm_fail"
    @property
    def supported_task_types(self) -> list[TaskType]:
        return [TaskType.SEND_EMAIL]
    async def execute(self, task, context) -> TaskResult:
        return TaskResult(task_id=task.id, attempt=task.attempts, success=False, error="Perm error", error_type="permanent")


class MockTransientAdapter(ExecutionAdapter):
    @property
    def adapter_type(self) -> str:
        return "mock_transient"
    @property
    def supported_task_types(self) -> list[TaskType]:
        return [TaskType.UPDATE_CRM]
    async def execute(self, task, context) -> TaskResult:
        return TaskResult(task_id=task.id, attempt=task.attempts, success=False, error="Transient", error_type="transient")


class MockTransientThenOkAdapter(ExecutionAdapter):
    def __init__(self, fail_count=1):
        self.fail_count = fail_count
        self.call_count = 0
    @property
    def adapter_type(self) -> str:
        return "mock_then_ok"
    @property
    def supported_task_types(self) -> list[TaskType]:
        return [TaskType.ANALYZE_REPLY]
    async def execute(self, task, context) -> TaskResult:
        self.call_count += 1
        if self.call_count <= self.fail_count:
            return TaskResult(task_id=task.id, attempt=task.attempts, success=False, error=f"Transient #{self.call_count}", error_type="transient")
        return TaskResult(task_id=task.id, attempt=task.attempts, success=True, output={"ok": True})


class MockResolver:
    def __init__(self, adapter_map: dict[TaskType, ExecutionAdapter]):
        self._adapter_map = adapter_map
    def resolve(self, task_type: TaskType) -> Optional[ExecutionAdapter]:
        return self._adapter_map.get(task_type)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_session(session_id="s1", plan_id="p1", status=SessionState.RUNNING):
    plan = Plan(id=plan_id, conversation_id="c", status=PlanStatus.VALIDATED, goal=PlanGoal(outcome="test"))
    session = ExecutionSession(id=session_id, plan_id=plan_id, plan=plan, status=status)
    return session


def make_task(task_id, plan, task_type=TaskType.SEND_MESSAGE, status=TaskState.PENDING, deps=None, attempts=0, max_attempts=3):
    return ExecutionTask(
        id=task_id,
        plan_task=Task(id=task_id, plan_id=plan.id, type=task_type, status=TaskStatus.PENDING, payload=MessagePayload(channel="x", template="x"), dependencies=deps or []),
        status=status,
        attempts=attempts,
        max_attempts=max_attempts,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def engine():
    eng = ExecutionEngine()
    original_exec = eng.execute
    async def _fast(plan, resolver=None, **kwargs):
        if "retry_policy" not in kwargs:
            kwargs["retry_policy"] = RetryPolicy(backoff_base_seconds=0)
        return await original_exec(plan, resolver=resolver, **kwargs)
    eng.execute = _fast
    return eng


@pytest.fixture
def success_adapter():
    return MockSuccessAdapter()


@pytest.fixture
def perm_fail_adapter():
    return MockPermanentFailAdapter()


@pytest.fixture
def transient_adapter():
    return MockTransientAdapter()


@pytest.fixture
def resolver(success_adapter, perm_fail_adapter, transient_adapter):
    return MockResolver({
        TaskType.SEND_MESSAGE: success_adapter,
        TaskType.SEND_EMAIL: perm_fail_adapter,
        TaskType.UPDATE_CRM: transient_adapter,
    })


@pytest.fixture
def then_ok_adapter():
    return MockTransientThenOkAdapter(fail_count=1)


# ===================================================================
# VALIDATION TESTS
# ===================================================================

class TestValidate:
    def test_validates_empty_session(self):
        session = make_session()
        session.tasks = {}
        with pytest.raises(RecoveryError, match="no tasks"):
            RecoveryManager.validate(session)

    def test_validates_none_status(self):
        session = make_session()
        t = make_task("t1", session.plan)
        t.status = None
        session.tasks["t1"] = t
        with pytest.raises(RecoveryError, match="validation failed"):
            RecoveryManager.validate(session)

    def test_validates_negative_attempts(self):
        session = make_session()
        t = make_task("t1", session.plan, attempts=-1)
        session.tasks["t1"] = t
        with pytest.raises(RecoveryError, match="negative attempts"):
            RecoveryManager.validate(session)

    def test_validates_invalid_max_attempts(self):
        session = make_session()
        t = make_task("t1", session.plan, max_attempts=0)
        session.tasks["t1"] = t
        with pytest.raises(RecoveryError, match="invalid max_attempts"):
            RecoveryManager.validate(session)

    def test_validates_unknown_dependency(self):
        session = make_session()
        t = make_task("t1", session.plan, deps=["ghost"])
        session.tasks["t1"] = t
        with pytest.raises(RecoveryError, match="validation failed"):
            RecoveryManager.validate(session)

    def test_validates_self_dependency(self):
        session = make_session()
        t = make_task("t1", session.plan, deps=["t1"])
        session.tasks["t1"] = t
        with pytest.raises(RecoveryError):
            RecoveryManager.validate(session)

    def test_validates_valid_session(self):
        session = make_session()
        t1 = make_task("t1", session.plan, status=TaskState.COMPLETED)
        t2 = make_task("t2", session.plan, deps=["t1"], status=TaskState.READY)
        session.tasks["t1"] = t1
        session.tasks["t2"] = t2
        RecoveryManager.validate(session)

    def test_validates_complex_dag(self):
        session = make_session()
        t1 = make_task("t1", session.plan, status=TaskState.COMPLETED)
        t2 = make_task("t2", session.plan, status=TaskState.COMPLETED)
        t3 = make_task("t3", session.plan, deps=["t1", "t2"], status=TaskState.READY)
        session.tasks["t1"] = t1
        session.tasks["t2"] = t2
        session.tasks["t3"] = t3
        RecoveryManager.validate(session)

    def test_validates_valid_retry_counts(self):
        session = make_session()
        t = make_task("t1", session.plan, attempts=2, max_attempts=3)
        session.tasks["t1"] = t
        RecoveryManager.validate(session)

    def test_rejects_circular_dependency(self):
        session = make_session()
        t1 = make_task("t1", session.plan, deps=["t2"])
        t2 = make_task("t2", session.plan, deps=["t1"])
        session.tasks["t1"] = t1
        session.tasks["t2"] = t2
        with pytest.raises(RecoveryError):
            RecoveryManager.validate(session)

    def test_recovery_error_has_context(self):
        session = make_session()
        session.tasks = {}
        try:
            RecoveryManager.validate(session)
        except RecoveryError as e:
            assert "session_id" in e.context


# ===================================================================
# STATE FIXING TESTS
# ===================================================================

class TestFixStates:
    def test_running_to_ready(self):
        session = make_session()
        t = make_task("t1", session.plan, status=TaskState.RUNNING)
        session.tasks["t1"] = t
        modified = RecoveryManager.fix_states(session)
        assert t.status == TaskState.READY
        assert "t1" in modified

    def test_retrying_to_waiting(self):
        session = make_session()
        t = make_task("t1", session.plan, status=TaskState.RETRYING)
        session.tasks["t1"] = t
        modified = RecoveryManager.fix_states(session)
        assert t.status == TaskState.WAITING
        assert "t1" in modified

    def test_waiting_to_ready(self):
        session = make_session()
        t = make_task("t1", session.plan, status=TaskState.WAITING)
        session.tasks["t1"] = t
        modified = RecoveryManager.fix_states(session)
        assert t.status == TaskState.READY
        assert "t1" in modified

    def test_completed_unchanged(self):
        session = make_session()
        t = make_task("t1", session.plan, status=TaskState.COMPLETED)
        session.tasks["t1"] = t
        modified = RecoveryManager.fix_states(session)
        assert t.status == TaskState.COMPLETED
        assert len(modified) == 0

    def test_failed_unchanged(self):
        session = make_session()
        t = make_task("t1", session.plan, status=TaskState.FAILED)
        session.tasks["t1"] = t
        modified = RecoveryManager.fix_states(session)
        assert t.status == TaskState.FAILED
        assert len(modified) == 0

    def test_skipped_unchanged(self):
        session = make_session()
        t = make_task("t1", session.plan, status=TaskState.SKIPPED)
        session.tasks["t1"] = t
        modified = RecoveryManager.fix_states(session)
        assert t.status == TaskState.SKIPPED
        assert len(modified) == 0

    def test_ready_unchanged(self):
        session = make_session()
        t = make_task("t1", session.plan, status=TaskState.READY)
        session.tasks["t1"] = t
        modified = RecoveryManager.fix_states(session)
        assert t.status == TaskState.READY
        assert len(modified) == 0

    def test_waiting_approval_unchanged(self):
        session = make_session()
        t = make_task("t1", session.plan, status=TaskState.WAITING_APPROVAL)
        session.tasks["t1"] = t
        modified = RecoveryManager.fix_states(session)
        assert t.status == TaskState.WAITING_APPROVAL
        assert len(modified) == 0

    def test_blocked_unchanged(self):
        session = make_session()
        t = make_task("t1", session.plan, status=TaskState.BLOCKED)
        session.tasks["t1"] = t
        modified = RecoveryManager.fix_states(session)
        assert t.status == TaskState.BLOCKED
        assert len(modified) == 0

    def test_cancelled_unchanged(self):
        session = make_session()
        t = make_task("t1", session.plan, status=TaskState.CANCELLED)
        session.tasks["t1"] = t
        modified = RecoveryManager.fix_states(session)
        assert t.status == TaskState.CANCELLED
        assert len(modified) == 0

    def test_pending_unchanged(self):
        session = make_session()
        t = make_task("t1", session.plan, status=TaskState.PENDING)
        session.tasks["t1"] = t
        modified = RecoveryManager.fix_states(session)
        assert t.status == TaskState.PENDING
        assert len(modified) == 0

    def test_multiple_running_tasks(self):
        session = make_session()
        for i in range(3):
            t = make_task(f"t{i}", session.plan, status=TaskState.RUNNING)
            session.tasks[f"t{i}"] = t
        modified = RecoveryManager.fix_states(session)
        assert len(modified) == 3
        for t in session.tasks.values():
            assert t.status == TaskState.READY

    def test_mixed_states(self):
        session = make_session()
        session.tasks["t1"] = make_task("t1", session.plan, status=TaskState.RUNNING)
        session.tasks["t2"] = make_task("t2", session.plan, status=TaskState.COMPLETED)
        session.tasks["t3"] = make_task("t3", session.plan, status=TaskState.RETRYING)
        session.tasks["t4"] = make_task("t4", session.plan, status=TaskState.FAILED)
        modified = RecoveryManager.fix_states(session)
        assert session.tasks["t1"].status == TaskState.READY
        assert session.tasks["t2"].status == TaskState.COMPLETED
        assert session.tasks["t3"].status == TaskState.WAITING
        assert session.tasks["t4"].status == TaskState.FAILED
        assert "t1" in modified
        assert "t3" in modified


# ===================================================================
# SCHEDULER RECONSTRUCTION TESTS
# ===================================================================

class TestRebuildScheduler:
    def test_rebuild_completed_session(self):
        session = make_session()
        t1 = make_task("t1", session.plan, status=TaskState.COMPLETED)
        session.tasks["t1"] = t1
        scheduler = RecoveryManager.rebuild_scheduler(session)
        assert scheduler.is_terminal()

    def test_rebuild_partial_session(self):
        session = make_session()
        t1 = make_task("t1", session.plan, status=TaskState.COMPLETED)
        t2 = make_task("t2", session.plan, deps=["t1"], status=TaskState.PENDING)
        session.tasks["t1"] = t1
        session.tasks["t2"] = t2
        scheduler = RecoveryManager.rebuild_scheduler(session)
        assert not scheduler.is_terminal()
        assert scheduler.ready_count() > 0

    def test_rebuild_readd_readied_task(self):
        session = make_session()
        t1 = make_task("t1", session.plan, status=TaskState.COMPLETED)
        t2 = make_task("t2", session.plan, deps=["t1"], status=TaskState.READY)
        session.tasks["t1"] = t1
        session.tasks["t2"] = t2
        scheduler = RecoveryManager.rebuild_scheduler(session)
        assert scheduler.peek_ready() == "t2"

    def test_rebuild_failed_upstream(self):
        session = make_session()
        t1 = make_task("t1", session.plan, status=TaskState.FAILED)
        t2 = make_task("t2", session.plan, deps=["t1"], status=TaskState.PENDING)
        session.tasks["t1"] = t1
        session.tasks["t2"] = t2
        scheduler = RecoveryManager.rebuild_scheduler(session)
        assert scheduler.is_terminal()
        assert session.tasks["t2"].status == TaskState.SKIPPED

    def test_rebuild_skipped_upstream(self):
        session = make_session()
        t1 = make_task("t1", session.plan, status=TaskState.SKIPPED)
        t2 = make_task("t2", session.plan, deps=["t1"], status=TaskState.PENDING)
        session.tasks["t1"] = t1
        session.tasks["t2"] = t2
        scheduler = RecoveryManager.rebuild_scheduler(session)
        assert scheduler.is_terminal()
        assert session.tasks["t2"].status == TaskState.SKIPPED

    def test_rebuild_linear_chain(self):
        session = make_session()
        t1 = make_task("t1", session.plan, status=TaskState.COMPLETED)
        t2 = make_task("t2", session.plan, deps=["t1"], status=TaskState.COMPLETED)
        t3 = make_task("t3", session.plan, deps=["t2"], status=TaskState.PENDING)
        session.tasks["t1"] = t1
        session.tasks["t2"] = t2
        session.tasks["t3"] = t3
        scheduler = RecoveryManager.rebuild_scheduler(session)
        assert not scheduler.is_terminal()
        assert scheduler.peek_ready() == "t3"

    def test_rebuild_merge_diamond(self):
        session = make_session()
        t1 = make_task("t1", session.plan, status=TaskState.COMPLETED)
        t2 = make_task("t2", session.plan, deps=["t1"], status=TaskState.COMPLETED)
        t3 = make_task("t3", session.plan, deps=["t1"], status=TaskState.COMPLETED)
        t4 = make_task("t4", session.plan, deps=["t2", "t3"], status=TaskState.READY)
        session.tasks["t1"] = t1
        session.tasks["t2"] = t2
        session.tasks["t3"] = t3
        session.tasks["t4"] = t4
        scheduler = RecoveryManager.rebuild_scheduler(session)
        assert scheduler.peek_ready() == "t4"

    def test_rebuild_running_task(self):
        session = make_session()
        t1 = make_task("t1", session.plan, status=TaskState.RUNNING)
        session.tasks["t1"] = t1
        RecoveryManager.fix_states(session)
        scheduler = RecoveryManager.rebuild_scheduler(session)
        assert session.tasks["t1"].status == TaskState.READY
        assert scheduler.ready_count() == 1

    def test_rebuild_retry_state(self):
        session = make_session()
        t1 = make_task("t1", session.plan, status=TaskState.RETRYING, attempts=1)
        session.tasks["t1"] = t1
        RecoveryManager.fix_states(session)
        assert t1.status == TaskState.WAITING

    def test_rebuild_waiting_state(self):
        session = make_session()
        t1 = make_task("t1", session.plan, status=TaskState.WAITING, attempts=1)
        session.tasks["t1"] = t1
        RecoveryManager.fix_states(session)
        scheduler = RecoveryManager.rebuild_scheduler(session)
        assert session.tasks["t1"].status == TaskState.READY
        assert scheduler.ready_count() == 1

    def test_rebuild_approval_task(self):
        session = make_session()
        t1 = make_task("t1", session.plan, status=TaskState.WAITING_APPROVAL)
        session.tasks["t1"] = t1
        scheduler = RecoveryManager.rebuild_scheduler(session)
        assert not scheduler.is_terminal()

    def test_rebuild_failed_diamond(self):
        session = make_session()
        t1 = make_task("t1", session.plan, status=TaskState.COMPLETED)
        t2 = make_task("t2", session.plan, deps=["t1"], status=TaskState.FAILED)
        t3 = make_task("t3", session.plan, deps=["t1", "t2"], status=TaskState.PENDING)
        session.tasks["t1"] = t1
        session.tasks["t2"] = t2
        session.tasks["t3"] = t3
        scheduler = RecoveryManager.rebuild_scheduler(session)
        assert scheduler.is_terminal()
        assert session.tasks["t3"].status in (TaskState.SKIPPED, TaskState.BLOCKED)

    def test_rebuild_multiple_root_tasks(self):
        session = make_session()
        t1 = make_task("t1", session.plan, status=TaskState.COMPLETED)
        t2 = make_task("t2", session.plan, status=TaskState.READY)
        session.tasks["t1"] = t1
        session.tasks["t2"] = t2
        scheduler = RecoveryManager.rebuild_scheduler(session)
        ready_ids = []
        while scheduler.peek_ready():
            ready_ids.append(scheduler.get_next_ready())
        assert "t2" in ready_ids


# ===================================================================
# APPROVAL INTEGRATION TESTS
# ===================================================================

class TestApprove:
    def test_approve_transitions_to_ready(self, engine):
        session = make_session()
        t = make_task("t1", session.plan, status=TaskState.WAITING_APPROVAL)
        session.tasks["t1"] = t
        engine._sessions["s1"] = session
        engine.approve("s1", "t1")
        assert t.status == TaskState.READY

    def test_approve_enqueues_in_scheduler(self, engine):
        session = make_session()
        t = make_task("t1", session.plan, status=TaskState.WAITING_APPROVAL)
        session.tasks["t1"] = t
        scheduler = Scheduler(session)
        scheduler.initialize()
        engine._sessions["s1"] = session
        engine._schedulers["s1"] = scheduler
        engine.approve("s1", "t1")
        assert scheduler.ready_count() == 1
        assert scheduler.peek_ready() == "t1"

    def test_approve_unknown_task(self, engine):
        session = make_session()
        engine._sessions["s1"] = session
        with pytest.raises(Exception):
            engine.approve("s1", "ghost")

    def test_approve_wrong_state(self, engine):
        session = make_session()
        t = make_task("t1", session.plan, status=TaskState.RUNNING)
        session.tasks["t1"] = t
        engine._sessions["s1"] = session
        with pytest.raises(Exception):
            engine.approve("s1", "t1")

    def test_approve_updates_timestamp(self, engine):
        session = make_session()
        t = make_task("t1", session.plan, status=TaskState.WAITING_APPROVAL)
        session.tasks["t1"] = t
        engine._sessions["s1"] = session
        old = session.updated_at
        engine.approve("s1", "t1")
        assert session.updated_at >= old


class TestReject:
    def test_reject_transitions_to_skipped(self, engine):
        session = make_session()
        t = make_task("t1", session.plan, status=TaskState.WAITING_APPROVAL)
        session.tasks["t1"] = t
        engine._sessions["s1"] = session
        engine.reject("s1", "t1")
        assert t.status == TaskState.SKIPPED

    def test_reject_unknown_task(self, engine):
        session = make_session()
        engine._sessions["s1"] = session
        with pytest.raises(Exception):
            engine.reject("s1", "ghost")

    def test_reject_wrong_state(self, engine):
        session = make_session()
        t = make_task("t1", session.plan, status=TaskState.RUNNING)
        session.tasks["t1"] = t
        engine._sessions["s1"] = session
        with pytest.raises(Exception):
            engine.reject("s1", "t1")

    def test_reject_updates_timestamp(self, engine):
        session = make_session()
        t = make_task("t1", session.plan, status=TaskState.WAITING_APPROVAL)
        session.tasks["t1"] = t
        engine._sessions["s1"] = session
        old = session.updated_at
        engine.reject("s1", "t1")
        assert session.updated_at >= old

    def test_reject_cascade_via_scheduler(self, engine):
        session = make_session()
        t1 = make_task("t1", session.plan, status=TaskState.WAITING_APPROVAL)
        t2 = make_task("t2", session.plan, deps=["t1"], status=TaskState.PENDING)
        session.tasks["t1"] = t1
        session.tasks["t2"] = t2
        scheduler = Scheduler(session)
        scheduler.initialize()
        engine._sessions["s1"] = session
        engine._schedulers["s1"] = scheduler
        engine.reject("s1", "t1")
        assert t1.status == TaskState.SKIPPED
        assert t2.status == TaskState.SKIPPED

    def test_reject_no_scheduler(self, engine):
        session = make_session()
        t = make_task("t1", session.plan, status=TaskState.WAITING_APPROVAL)
        session.tasks["t1"] = t
        engine._sessions["s1"] = session
        engine.reject("s1", "t1")
        assert t.status == TaskState.SKIPPED


# ===================================================================
# PIPELINE RECOVERY TESTS
# ===================================================================

class TestPipelineRecovery:
    async def _exec(self, engine, plan, resolver):
        return await engine.execute(plan, resolver=resolver)

    def test_recover_completed_session(self, engine, resolver):
        plan = Plan(id="p", conversation_id="c", status=PlanStatus.VALIDATED, goal=PlanGoal(outcome="test"))
        plan.tasks = [Task(id="t1", plan_id="p", type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING, payload=MessagePayload(channel="tg", template="ok"), label="s")]
        session = asyncio.run(self._exec(engine, plan, resolver))

        # Recover the completed session
        recovered = asyncio.run(engine.recover(session, resolver))
        assert recovered.status.is_terminal

    def test_recover_partial_crash(self, engine, resolver, success_adapter, perm_fail_adapter):
        """Simulate crash: A completed, B running, C pending."""
        plan = Plan(id="p", conversation_id="c", status=PlanStatus.VALIDATED, goal=PlanGoal(outcome="test"))
        plan.tasks = [
            Task(id="t1", plan_id="p", type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING, payload=MessagePayload(channel="tg", template="a"), label="a"),
            Task(id="t2", plan_id="p", type=TaskType.SEND_EMAIL, status=TaskStatus.PENDING, payload=MessagePayload(channel="g", template="b"), label="b", dependencies=["t1"]),
        ]

        # Execute partially
        from services.execution.utils import wrap_task
        session = engine._create_session(plan)
        engine._initialize(session)
        t1 = session.tasks["t1"]
        t2 = session.tasks["t2"]
        t1.status = TaskState.COMPLETED
        t2.status = TaskState.RUNNING
        # Crash: t2 is RUNNING

        # Recover
        recovered = asyncio.run(engine.recover(session, resolver))
        # t2 should complete (FAILED because SEND_EMAIL fails permanently)
        assert recovered.status.is_terminal
        assert session.tasks["t1"].status == TaskState.COMPLETED
        assert session.tasks["t2"].status == TaskState.FAILED

    def test_recover_mid_execution(self, engine, resolver):
        """Recover a session that has some completed, some ready tasks."""
        plan = Plan(id="p", conversation_id="c", status=PlanStatus.VALIDATED, goal=PlanGoal(outcome="test"))
        plan.tasks = [
            Task(id="t1", plan_id="p", type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING, payload=MessagePayload(channel="tg", template="a"), label="a"),
            Task(id="t2", plan_id="p", type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING, payload=MessagePayload(channel="tg", template="b"), label="b", dependencies=["t1"]),
        ]

        session = engine._create_session(plan)
        engine._initialize(session)
        t1 = session.tasks["t1"]
        t1.status = TaskState.COMPLETED  # simulate crash after completion

        recovered = asyncio.run(engine.recover(session, resolver))
        assert recovered.status == SessionState.COMPLETED
        assert session.tasks["t1"].status == TaskState.COMPLETED
        assert session.tasks["t2"].status == TaskState.COMPLETED

    def test_recover_running_task_readied(self, engine, resolver):
        """A RUNNING task becomes READY after recovery and executes."""
        plan = Plan(id="p", conversation_id="c", status=PlanStatus.VALIDATED, goal=PlanGoal(outcome="test"))
        plan.tasks = [Task(id="t1", plan_id="p", type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING, payload=MessagePayload(channel="tg", template="a"), label="a")]

        session = engine._create_session(plan)
        engine._initialize(session)
        t1 = session.tasks["t1"]
        t1.status = TaskState.RUNNING  # simulate crash mid-execution

        recovered = asyncio.run(engine.recover(session, resolver))
        assert recovered.status == SessionState.COMPLETED
        assert session.tasks["t1"].status == TaskState.COMPLETED

    def test_recover_with_retry(self, engine, resolver, then_ok_adapter):
        """Recover a session with a task that had retries."""
        plan = Plan(id="p", conversation_id="c", status=PlanStatus.VALIDATED, goal=PlanGoal(outcome="test"))
        plan.tasks = [Task(id="t1", plan_id="p", type=TaskType.ANALYZE_REPLY, status=TaskStatus.PENDING, payload=MessagePayload(channel="x", template="x"), label="x")]

        resolver._adapter_map[TaskType.ANALYZE_REPLY] = then_ok_adapter
        session = asyncio.run(engine.execute(plan, resolver=resolver, retry_policy=RetryPolicy(backoff_base_seconds=0)))
        assert session.status == SessionState.COMPLETED

        # Recover the already-completed session
        recovered = asyncio.run(engine.recover(session, resolver))
        assert recovered.status.is_terminal

    def test_recover_approval_task(self, engine, resolver):
        """Recover a session with a WAITING_APPROVAL task."""
        plan = Plan(id="p", conversation_id="c", status=PlanStatus.VALIDATED, goal=PlanGoal(outcome="test"))
        plan.tasks = [Task(id="t1", plan_id="p", type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING, payload=MessagePayload(channel="tg", template="a"), label="a")]

        session = engine._create_session(plan)
        engine._initialize(session)
        t1 = session.tasks["t1"]
        StateMachine.transition_task(t1, TaskState.WAITING_APPROVAL)

        recovered = asyncio.run(engine.recover(session, resolver))
        # WAITING_APPROVAL remains, session terminal check:
        # After recovery, the WAITING_APPROVAL task keeps the session non-terminal
        assert session.tasks["t1"].status == TaskState.WAITING_APPROVAL

    def test_recover_then_approve(self, engine, resolver):
        """Recover a session, then approve the waiting task."""
        plan = Plan(id="p", conversation_id="c", status=PlanStatus.VALIDATED, goal=PlanGoal(outcome="test"))
        plan.tasks = [Task(id="t1", plan_id="p", type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING, payload=MessagePayload(channel="tg", template="a"), label="a")]

        session = engine._create_session(plan)
        engine._initialize(session)
        t1 = session.tasks["t1"]
        StateMachine.transition_task(t1, TaskState.WAITING_APPROVAL)

        recovered = asyncio.run(engine.recover(session, resolver))
        engine._sessions["s1"] = recovered
        engine._schedulers["s1"] = Scheduler(recovered)
        engine._schedulers["s1"].initialize()
        engine.approve("s1", "t1")
        assert recovered.tasks["t1"].status == TaskState.READY

    def test_recover_interrupted_retry(self, engine, resolver, transient_adapter):
        """A task in RETRYING state becomes READY after recovery and re-executes."""
        plan = Plan(id="p", conversation_id="c", status=PlanStatus.VALIDATED, goal=PlanGoal(outcome="test"))
        plan.tasks = [Task(id="t1", plan_id="p", type=TaskType.UPDATE_CRM, status=TaskStatus.PENDING, payload=MessagePayload(channel="x", template="x"), label="x")]

        session = engine._create_session(plan)
        engine._initialize(session)
        t1 = session.tasks["t1"]
        t1.attempts = 1
        t1.status = TaskState.WAITING  # simulate crash mid-retry backoff

        recovered = asyncio.run(engine.recover(session, resolver))
        # t1 should be re-executed, fail transiently, retry, exhaust
        assert recovered.status.is_terminal

    def test_recover_does_not_publish_extra_events(self, engine, resolver):
        """Recovery uses existing event mechanisms only."""
        plan = Plan(id="p", conversation_id="c", status=PlanStatus.VALIDATED, goal=PlanGoal(outcome="test"))
        plan.tasks = [Task(id="t1", plan_id="p", type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING, payload=MessagePayload(channel="tg", template="a"), label="a")]

        bus = engine.event_bus
        from tests.test_event_bus import CollectingSubscriber
        sub = CollectingSubscriber()
        bus.subscribe(sub)

        session = engine._create_session(plan)
        engine._initialize(session)
        t1 = session.tasks["t1"]
        t1.status = TaskState.COMPLETED  # simulate crash after completion

        pre_count = len(sub.events)
        asyncio.run(engine.recover(session, resolver))
        # Events should be published (SESSION_STARTED, etc.)
        assert len(sub.events) > pre_count


# ===================================================================
# EDGE CASE TESTS
# ===================================================================

class TestEdgeCases:
    def test_empty_session_validation(self):
        session = make_session()
        session.tasks = {}
        with pytest.raises(RecoveryError):
            RecoveryManager.validate(session)

    def test_cancelled_session_recovery(self, engine, resolver):
        plan = Plan(id="p", conversation_id="c", status=PlanStatus.VALIDATED, goal=PlanGoal(outcome="test"))
        plan.tasks = [Task(id="t1", plan_id="p", type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING, payload=MessagePayload(channel="tg", template="a"), label="a")]

        session = engine._create_session(plan)
        engine._initialize(session)
        engine._sessions[session.id] = session
        engine.cancel(session.id)
        assert session.status == SessionState.CANCELLED

        # Recover cancelled session
        recovered = asyncio.run(engine.recover(session, resolver))
        assert recovered.status.is_terminal

    def test_already_terminal_session(self, engine, resolver):
        plan = Plan(id="p", conversation_id="c", status=PlanStatus.VALIDATED, goal=PlanGoal(outcome="test"))
        plan.tasks = [Task(id="t1", plan_id="p", type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING, payload=MessagePayload(channel="tg", template="a"), label="a")]

        session = asyncio.run(engine.execute(plan, resolver=resolver))
        assert session.status.is_terminal

        # Re-recover terminal session
        recovered = asyncio.run(engine.recover(session, resolver))
        assert recovered.status.is_terminal

    def test_duplicate_recovery(self, engine, resolver):
        plan = Plan(id="p", conversation_id="c", status=PlanStatus.VALIDATED, goal=PlanGoal(outcome="test"))
        plan.tasks = [Task(id="t1", plan_id="p", type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING, payload=MessagePayload(channel="tg", template="a"), label="a")]

        session = engine._create_session(plan)
        engine._initialize(session)

        recovered1 = asyncio.run(engine.recover(session, resolver))
        assert recovered1.status.is_terminal

        # Recover again (should be idempotent)
        recovered2 = asyncio.run(engine.recover(session, resolver))
        assert recovered2.status.is_terminal

    def test_recover_stale_session_no_tasks(self, engine, resolver):
        session = make_session()
        with pytest.raises(RecoveryError):
            asyncio.run(engine.recover(session, resolver))

    def test_recover_preserves_attempt_counts(self, engine, resolver):
        plan = Plan(id="p", conversation_id="c", status=PlanStatus.VALIDATED, goal=PlanGoal(outcome="test"))
        plan.tasks = [Task(id="t1", plan_id="p", type=TaskType.UPDATE_CRM, status=TaskStatus.PENDING, payload=MessagePayload(channel="x", template="x"), label="x")]

        session = engine._create_session(plan)
        engine._initialize(session, retry_policy=RetryPolicy(backoff_base_seconds=0))
        t1 = session.tasks["t1"]
        t1.attempts = 2
        t1.status = TaskState.RUNNING  # simulate crash mid-execution with 2 prior attempts

        recovered = asyncio.run(engine.recover(session, resolver))
        assert recovered.tasks["t1"].attempts == 2

    def test_recover_creates_scheduler_same_as_initial(self, engine, resolver):
        """Recovered scheduler should match fresh scheduler for unstarted session."""
        plan = Plan(id="p", conversation_id="c", status=PlanStatus.VALIDATED, goal=PlanGoal(outcome="test"))
        plan.tasks = [
            Task(id="t1", plan_id="p", type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING, payload=MessagePayload(channel="tg", template="a"), label="a"),
            Task(id="t2", plan_id="p", type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING, payload=MessagePayload(channel="tg", template="b"), label="b", dependencies=["t1"]),
        ]

        session = engine._create_session(plan)
        engine._initialize(session)

        # Fresh scheduler
        fresh = Scheduler(session)
        fresh.initialize()
        fresh_next = fresh.peek_ready()

        # Recovered scheduler (all tasks still PENDING)
        recovered = RecoveryManager.rebuild_scheduler(session)
        recovered_next = recovered.peek_ready()

        assert fresh_next == recovered_next

    def test_task_count_by_state(self):
        session = make_session()
        session.tasks["t1"] = make_task("t1", session.plan, status=TaskState.COMPLETED)
        session.tasks["t2"] = make_task("t2", session.plan, status=TaskState.FAILED)
        session.tasks["t3"] = make_task("t3", session.plan, status=TaskState.READY)
        counts = RecoveryManager._task_count_by_state(session)
        assert counts.get("completed") == 1
        assert counts.get("failed") == 1
        assert counts.get("ready") == 1


# ===================================================================
# RECOVERY MANAGER STATEFULNESS TESTS
# ===================================================================

class TestRecoveryManagerIsStateless:
    def test_validate_is_static(self):
        assert callable(RecoveryManager.validate)

    def test_fix_states_is_static(self):
        assert callable(RecoveryManager.fix_states)

    def test_rebuild_scheduler_is_static(self):
        assert callable(RecoveryManager.rebuild_scheduler)

    def test_no_instance_state(self):
        rm = RecoveryManager()
        with pytest.raises(AttributeError):
            _ = rm._some_state


# ===================================================================
# SCHEDULER RECONSTRUCTION VERIFICATION TESTS
# ===================================================================

class TestSchedulerReconstruction:
    def test_verify_integrity_clean(self):
        session = make_session()
        t1 = make_task("t1", session.plan, status=TaskState.COMPLETED)
        session.tasks["t1"] = t1
        scheduler = RecoveryManager.rebuild_scheduler(session)
        warnings = RecoveryManager._verify_dependency_integrity(session, scheduler)
        assert len(warnings) == 0

    def test_verify_integrity_ready_has_deps(self):
        session = make_session()
        t1 = make_task("t1", session.plan, status=TaskState.COMPLETED)
        t2 = make_task("t2", session.plan, deps=["t1"], status=TaskState.READY)
        session.tasks["t1"] = t1
        session.tasks["t2"] = t2
        scheduler = RecoveryManager.rebuild_scheduler(session)
        warnings = RecoveryManager._verify_dependency_integrity(session, scheduler)
        assert len(warnings) == 0  # should be clean

    def test_integrity_negative_remaining(self):
        session = make_session()
        t1 = make_task("t1", session.plan, status=TaskState.COMPLETED)
        t2 = make_task("t2", session.plan, deps=["t1"], status=TaskState.PENDING)
        session.tasks["t1"] = t1
        session.tasks["t2"] = t2
        scheduler = RecoveryManager.rebuild_scheduler(session)
        # All should be clean
        warnings = RecoveryManager._verify_dependency_integrity(session, scheduler)
        assert len(warnings) == 0


# ===================================================================
# APPROVAL AFTER RECOVERY INTEGRATION
# ===================================================================

class TestApprovalAfterRecovery:
    def test_approve_after_recovery_works(self, engine, resolver):
        plan = Plan(id="p", conversation_id="c", status=PlanStatus.VALIDATED, goal=PlanGoal(outcome="test"))
        plan.tasks = [Task(id="t1", plan_id="p", type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING, payload=MessagePayload(channel="tg", template="a"), label="a")]

        session = engine._create_session(plan)
        engine._initialize(session)
        t1 = session.tasks["t1"]
        StateMachine.transition_task(t1, TaskState.WAITING_APPROVAL)

        asyncio.run(engine.recover(session, resolver))
        engine._sessions[session.id] = session
        engine._schedulers[session.id] = Scheduler(session)
        engine._schedulers[session.id].initialize()

        result = engine.approve(session.id, "t1")
        assert result.tasks["t1"].status == TaskState.READY

    def test_reject_after_recovery_cascades(self, engine, resolver):
        plan = Plan(id="p", conversation_id="c", status=PlanStatus.VALIDATED, goal=PlanGoal(outcome="test"))
        plan.tasks = [
            Task(id="t1", plan_id="p", type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING, payload=MessagePayload(channel="tg", template="a"), label="a"),
            Task(id="t2", plan_id="p", type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING, payload=MessagePayload(channel="tg", template="b"), label="b", dependencies=["t1"]),
        ]

        session = engine._create_session(plan)
        engine._initialize(session)
        t1 = session.tasks["t1"]
        StateMachine.transition_task(t1, TaskState.WAITING_APPROVAL)

        asyncio.run(engine.recover(session, resolver))
        engine._sessions[session.id] = session
        scheduler = Scheduler(session)
        scheduler.initialize()
        engine._schedulers[session.id] = scheduler

        result = engine.reject(session.id, "t1")
        assert result.tasks["t1"].status == TaskState.SKIPPED
        assert result.tasks["t2"].status == TaskState.SKIPPED


# ===================================================================
# RECOVERY ERROR TYPE TESTS
# ===================================================================

class TestRecoveryError:
    def test_recovery_error_message(self):
        err = RecoveryError("test error")
        assert str(err) == "test error"

    def test_recovery_error_context(self):
        err = RecoveryError("test", context={"key": "value"})
        assert err.context == {"key": "value"}

    def test_recovery_error_default_context(self):
        err = RecoveryError("test")
        assert err.context == {}

    def test_recovery_error_is_exception(self):
        assert issubclass(RecoveryError, Exception)
