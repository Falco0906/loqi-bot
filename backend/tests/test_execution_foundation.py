"""Unit tests for the Execution Engine Foundation (Phase 3.6.4A).

Tests enums, models, exceptions, validation, session initialization,
and the pipeline skeleton.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

from services.execution.enums import (
    ExecutionEventType,
    SessionState,
    TaskState,
)
from services.execution.exceptions import (
    ExecutionAdapterError,
    ExecutionDispatchError,
    ExecutionError,
    ExecutionRetryError,
    ExecutionSchedulingError,
    ExecutionSessionError,
    ExecutionValidationError,
)
from services.execution.execution_models import (
    ExecutionEvent,
    ExecutionMetrics,
    ExecutionResult,
    ExecutionSession,
    ExecutionTask,
    InDegreeEntry,
    RetryPolicy,
    TaskResult,
    ValidationResult,
)
from services.execution.execution_context import ExecutionContext
from services.execution.execution_pipeline import ExecutionEngine, get_pipeline
from services.execution.validation import (
    validate_plan_for_execution,
    validate_session_initialization,
)
from services.execution.utils import (
    build_in_degree_map,
    generate_session_id,
    identify_root_tasks,
    init_metrics,
    wrap_task,
)

from services.planner.planning_models import (
    Plan, PlanGoal, Task, PlanStatus, TaskStatus, TaskType,
)
from services.planner.payloads import MessagePayload


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def valid_plan():
    """A simple but valid plan with two tasks and a dependency."""
    plan = Plan(
        id="test-plan-001",
        conversation_id="conv-1",
        status=PlanStatus.VALIDATED,
        strategy="test_strategy",
        goal=PlanGoal(outcome="test"),
    )
    task_a = Task(
        id="task-a",
        plan_id=plan.id,
        type=TaskType.SEND_MESSAGE,
        status=TaskStatus.PENDING,
        payload=MessagePayload(channel="telegram", template="greeting"),
        label="first message",
    )
    task_b = Task(
        id="task-b",
        plan_id=plan.id,
        type=TaskType.SEND_MESSAGE,
        status=TaskStatus.PENDING,
        payload=MessagePayload(channel="telegram", template="follow_up"),
        dependencies=["task-a"],
        label="follow-up",
    )
    plan.tasks = [task_a, task_b]
    return plan


@pytest.fixture
def valid_session(valid_plan):
    """A properly initialized ExecutionSession."""
    engine = ExecutionEngine()
    session = ExecutionSession(
        id="session-001",
        plan_id=valid_plan.id,
        plan=valid_plan,
        conversation_id=valid_plan.conversation_id,
        status=SessionState.PENDING,
    )
    for plan_task in valid_plan.tasks:
        etask = wrap_task(plan_task)
        session.tasks[plan_task.id] = etask
    session.root_tasks = identify_root_tasks(session.tasks)
    return session


@pytest.fixture
def engine():
    return ExecutionEngine()


# ---------------------------------------------------------------------------
# Enum Tests
# ---------------------------------------------------------------------------

class TestTaskState:
    def test_members(self):
        assert TaskState.PENDING.value == "pending"
        assert TaskState.READY.value == "ready"
        assert TaskState.RUNNING.value == "running"
        assert TaskState.WAITING.value == "waiting"
        assert TaskState.WAITING_APPROVAL.value == "waiting_approval"
        assert TaskState.RETRYING.value == "retrying"
        assert TaskState.COMPLETED.value == "completed"
        assert TaskState.FAILED.value == "failed"
        assert TaskState.BLOCKED.value == "blocked"
        assert TaskState.SKIPPED.value == "skipped"
        assert TaskState.CANCELLED.value == "cancelled"

    def test_is_terminal(self):
        assert TaskState.COMPLETED.is_terminal is True
        assert TaskState.FAILED.is_terminal is True
        assert TaskState.SKIPPED.is_terminal is True
        assert TaskState.CANCELLED.is_terminal is True
        assert TaskState.PENDING.is_terminal is False
        assert TaskState.RUNNING.is_terminal is False
        assert TaskState.READY.is_terminal is False

    def test_is_active(self):
        assert TaskState.RUNNING.is_active is True
        assert TaskState.RETRYING.is_active is True
        assert TaskState.WAITING.is_active is True
        assert TaskState.WAITING_APPROVAL.is_active is True
        assert TaskState.PENDING.is_active is False
        assert TaskState.COMPLETED.is_active is False
        assert TaskState.CANCELLED.is_active is False

    def test_count(self):
        assert len(TaskState) == 11


class TestSessionState:
    def test_members(self):
        assert SessionState.PENDING.value == "pending"
        assert SessionState.RUNNING.value == "running"
        assert SessionState.PAUSED.value == "paused"
        assert SessionState.WAITING_APPROVAL.value == "waiting_approval"
        assert SessionState.COMPLETED.value == "completed"
        assert SessionState.COMPLETED_WITH_ERRORS.value == "completed_with_errors"
        assert SessionState.FAILED.value == "failed"
        assert SessionState.CANCELLED.value == "cancelled"

    def test_is_terminal(self):
        assert SessionState.COMPLETED.is_terminal is True
        assert SessionState.COMPLETED_WITH_ERRORS.is_terminal is True
        assert SessionState.FAILED.is_terminal is True
        assert SessionState.CANCELLED.is_terminal is True
        assert SessionState.PENDING.is_terminal is False
        assert SessionState.RUNNING.is_terminal is False
        assert SessionState.PAUSED.is_terminal is False

    def test_count(self):
        assert len(SessionState) == 8


class TestExecutionEventType:
    def test_session_events(self):
        assert ExecutionEventType.SESSION_CREATED.value == "session.created"
        assert ExecutionEventType.SESSION_STARTED.value == "session.started"
        assert ExecutionEventType.SESSION_PAUSED.value == "session.paused"
        assert ExecutionEventType.SESSION_RESUMED.value == "session.resumed"
        assert ExecutionEventType.SESSION_COMPLETED.value == "session.completed"
        assert ExecutionEventType.SESSION_FAILED.value == "session.failed"
        assert ExecutionEventType.SESSION_CANCELLED.value == "session.cancelled"

    def test_task_events(self):
        assert ExecutionEventType.TASK_READY.value == "task.ready"
        assert ExecutionEventType.TASK_STARTED.value == "task.started"
        assert ExecutionEventType.TASK_COMPLETED.value == "task.completed"
        assert ExecutionEventType.TASK_FAILED.value == "task.failed"
        assert ExecutionEventType.TASK_RETRYING.value == "task.retrying"
        assert ExecutionEventType.TASK_CANCELLED.value == "task.cancelled"
        assert ExecutionEventType.TASK_SKIPPED.value == "task.skipped"

    def test_approval_events(self):
        assert ExecutionEventType.APPROVAL_REQUESTED.value == "approval.requested"
        assert ExecutionEventType.APPROVAL_GRANTED.value == "approval.granted"
        assert ExecutionEventType.APPROVAL_REJECTED.value == "approval.rejected"

    def test_wait_events(self):
        assert ExecutionEventType.WAITING_STARTED.value == "waiting.started"
        assert ExecutionEventType.WAITING_COMPLETED.value == "waiting.completed"

    def test_count(self):
        assert len(ExecutionEventType) == 19


# ---------------------------------------------------------------------------
# Model Tests
# ---------------------------------------------------------------------------

class TestRetryPolicy:
    def test_defaults(self):
        p = RetryPolicy()
        assert p.max_attempts == 3
        assert p.backoff_base_seconds == 1.0
        assert p.backoff_multiplier == 2.0
        assert p.max_backoff_seconds == 300.0
        assert p.jitter is True
        assert "transient" in p.retryable_error_types

    def test_to_dict(self):
        p = RetryPolicy(max_attempts=5)
        d = p.to_dict()
        assert d["max_attempts"] == 5
        assert "retryable_error_types" in d

    def test_default_constructor(self):
        p = RetryPolicy.default()
        assert isinstance(p, RetryPolicy)
        assert p.max_attempts == 3


class TestTaskResult:
    def test_create(self):
        now = datetime.now(timezone.utc)
        r = TaskResult(
            task_id="task-a",
            attempt=1,
            success=True,
            output={"message_id": "msg-123"},
            duration_ms=150,
            started_at=now,
            completed_at=now,
        )
        assert r.task_id == "task-a"
        assert r.success is True
        assert r.output["message_id"] == "msg-123"
        assert r.error is None

    def test_to_dict(self):
        r = TaskResult(task_id="t1", attempt=1, success=True)
        d = r.to_dict()
        assert d["task_id"] == "t1"
        assert d["success"] is True

    def test_failure_result(self):
        r = TaskResult(
            task_id="t1", attempt=1, success=False,
            error="Connection timeout", error_type="transient",
        )
        assert r.success is False
        assert r.error == "Connection timeout"
        assert r.error_type == "transient"


class TestExecutionEvent:
    def test_auto_id(self):
        e = ExecutionEvent(session_id="s1", event_type=ExecutionEventType.SESSION_CREATED)
        assert e.id
        assert len(e.id) == 12

    def test_to_dict(self):
        e = ExecutionEvent(
            id="evt-1", session_id="s1", task_id="t1",
            event_type=ExecutionEventType.TASK_STARTED,
            data={"attempt": 1},
            sequence=3,
        )
        d = e.to_dict()
        assert d["id"] == "evt-1"
        assert d["session_id"] == "s1"
        assert d["task_id"] == "t1"
        assert d["event_type"] == "task.started"
        assert d["sequence"] == 3

    def test_session_level_event(self):
        e = ExecutionEvent(session_id="s1", event_type=ExecutionEventType.SESSION_CREATED)
        assert e.task_id is None


class TestExecutionTask:
    def test_create(self, valid_plan):
        plan_task = valid_plan.tasks[0]
        etask = wrap_task(plan_task)
        assert etask.id == plan_task.id
        assert etask.status == TaskState.PENDING
        assert etask.attempts == 0
        assert etask.max_attempts == 3
        assert etask.adapter_name is None

    def test_to_dict(self, valid_plan):
        plan_task = valid_plan.tasks[0]
        etask = wrap_task(plan_task)
        d = etask.to_dict()
        assert d["id"] == plan_task.id
        assert d["status"] == "pending"
        assert d["attempts"] == 0
        assert d["plan_task_type"] == "send_message"

    def test_custom_retry_policy(self, valid_plan):
        plan_task = valid_plan.tasks[0]
        policy = RetryPolicy(max_attempts=5, backoff_base_seconds=2.0)
        etask = wrap_task(plan_task, policy)
        assert etask.max_attempts == 5
        assert etask.retry_policy.backoff_base_seconds == 2.0


class TestExecutionSession:
    def test_auto_id(self, valid_plan):
        s = ExecutionSession(plan=valid_plan, plan_id=valid_plan.id)
        assert s.id
        assert len(s.id) == 12

    def test_to_dict(self, valid_session):
        d = valid_session.to_dict()
        assert d["id"] == "session-001"
        assert d["plan_id"] == "test-plan-001"
        assert d["status"] == "pending"
        assert "tasks" in d
        assert "root_tasks" in d
        assert "created_at" in d

    def test_status_defaults(self, valid_plan):
        s = ExecutionSession(plan=valid_plan, plan_id=valid_plan.id)
        assert s.status == SessionState.PENDING

    def test_tasks_wrapped(self, valid_session):
        assert len(valid_session.tasks) == 2
        assert "task-a" in valid_session.tasks
        assert "task-b" in valid_session.tasks
        assert valid_session.tasks["task-a"].status == TaskState.PENDING


class TestExecutionMetrics:
    def test_create(self):
        m = ExecutionMetrics(session_id="s1", total_tasks=5)
        assert m.session_id == "s1"
        assert m.total_tasks == 5
        assert m.completed_tasks == 0
        assert m.failed_tasks == 0

    def test_to_dict(self):
        m = ExecutionMetrics(session_id="s1", total_tasks=3, completed_tasks=2)
        d = m.to_dict()
        assert d["session_id"] == "s1"
        assert d["total_tasks"] == 3
        assert d["completed_tasks"] == 2


class TestInDegreeEntry:
    def test_create(self):
        e = InDegreeEntry(task_id="t1", remaining=2, total=2)
        assert e.task_id == "t1"
        assert e.remaining == 2
        assert e.total == 2


class TestExecutionContext:
    def test_create(self):
        ctx = ExecutionContext(
            session_id="s1",
            channel="telegram",
            workspace_snapshot={"org_id": "org-1"},
        )
        assert ctx.session_id == "s1"
        assert ctx.channel == "telegram"
        assert ctx.workspace_snapshot["org_id"] == "org-1"

    def test_to_dict(self):
        ctx = ExecutionContext(session_id="s1", channel="web")
        d = ctx.to_dict()
        assert d["session_id"] == "s1"
        assert d["channel"] == "web"


class TestExecutionResult:
    def test_create(self, valid_session):
        metrics = ExecutionMetrics(session_id=valid_session.id, total_tasks=2)
        result = ExecutionResult(
            session=valid_session,
            metrics=metrics,
            events=[],
        )
        assert result.session.id == "session-001"
        assert result.metrics.total_tasks == 2
        assert result.events == []

    def test_to_dict(self, valid_session):
        metrics = ExecutionMetrics(session_id=valid_session.id, total_tasks=2)
        result = ExecutionResult(session=valid_session, metrics=metrics, events=[])
        d = result.to_dict()
        assert d["session"]["id"] == "session-001"
        assert d["metrics"]["total_tasks"] == 2
        assert d["events"] == []


class TestValidationResult:
    def test_valid(self):
        vr = ValidationResult(valid=True)
        assert vr.valid is True
        assert vr.errors == []
        assert vr.warnings == []

    def test_invalid(self):
        vr = ValidationResult(
            valid=False,
            errors=["Duplicate task IDs: ['a', 'a']"],
        )
        assert vr.valid is False
        assert len(vr.errors) == 1

    def test_to_dict(self):
        vr = ValidationResult(valid=True, warnings=["No root tasks"])
        d = vr.to_dict()
        assert d["valid"] is True
        assert d["warnings"] == ["No root tasks"]


# ---------------------------------------------------------------------------
# Exception Tests
# ---------------------------------------------------------------------------

class TestExceptionHierarchy:
    def test_base_error(self):
        e = ExecutionError("something went wrong", {"task_id": "t1"})
        assert e.message == "something went wrong"
        assert e.context["task_id"] == "t1"

    def test_base_error_to_dict(self):
        e = ExecutionError("fail", {"code": 1})
        d = e.to_dict()
        assert d["error_type"] == "ExecutionError"
        assert d["message"] == "fail"
        assert d["context"]["code"] == 1

    def test_validation_error(self):
        e = ExecutionValidationError("plan invalid", {"errors": ["dup IDs"]})
        assert isinstance(e, ExecutionError)
        assert e.message == "plan invalid"
        assert "dup IDs" in e.context["errors"]

    def test_scheduling_error(self):
        e = ExecutionSchedulingError("dangling dependency")
        assert isinstance(e, ExecutionError)

    def test_dispatch_error(self):
        e = ExecutionDispatchError("no adapter for SEND_MESSAGE")
        assert isinstance(e, ExecutionError)

    def test_adapter_error(self):
        e = ExecutionAdapterError("adapter config missing")
        assert isinstance(e, ExecutionError)

    def test_retry_error(self):
        e = ExecutionRetryError("negative backoff")
        assert isinstance(e, ExecutionError)

    def test_session_error(self):
        e = ExecutionSessionError("session not found")
        assert isinstance(e, ExecutionError)

    def test_all_exceptions_carry_to_dict(self):
        for exc in [
            ExecutionValidationError("x"),
            ExecutionSchedulingError("x"),
            ExecutionDispatchError("x"),
            ExecutionAdapterError("x"),
            ExecutionRetryError("x"),
            ExecutionSessionError("x"),
        ]:
            d = exc.to_dict()
            assert "error_type" in d
            assert "message" in d
            assert "context" in d


# ---------------------------------------------------------------------------
# Validation Tests
# ---------------------------------------------------------------------------

class TestPlanValidation:
    def test_valid_plan_passes(self, valid_plan):
        result = validate_plan_for_execution(valid_plan)
        assert result.valid is True

    def test_none_plan_raises(self):
        with pytest.raises(ExecutionValidationError) as exc:
            validate_plan_for_execution(None)
        assert "None" in exc.value.message

    def test_wrong_status_raises(self, valid_plan):
        valid_plan.status = PlanStatus.DRAFT
        with pytest.raises(ExecutionValidationError) as exc:
            validate_plan_for_execution(valid_plan)
        assert any("draft" in e.lower() for e in exc.value.context["errors"])

    def test_duplicate_task_ids_raises(self, valid_plan):
        task = valid_plan.tasks[0]
        valid_plan.tasks.append(task)
        with pytest.raises(ExecutionValidationError) as exc:
            validate_plan_for_execution(valid_plan)
        assert "Duplicate" in str(exc.value.context["errors"])

    def test_missing_payload_raises(self, valid_plan):
        valid_plan.tasks[0].payload = None
        valid_plan.tasks[0].params.pop("payload_type", None)
        with pytest.raises(ExecutionValidationError) as exc:
            validate_plan_for_execution(valid_plan)
        assert "no payload" in str(exc.value.context["errors"]).lower()

    def test_branch_join_skips_payload_check(self, valid_plan):
        from services.planner.planning_models import TaskType
        task = Task(
            id="branch-task",
            plan_id=valid_plan.id,
            type=TaskType.BRANCH,
            status=TaskStatus.PENDING,
            payload=None,
            params={},
        )
        valid_plan.tasks.append(task)
        result = validate_plan_for_execution(valid_plan)
        assert result.valid is True

    def test_bad_dependency_raises(self, valid_plan):
        valid_plan.tasks[1].dependencies.append("nonexistent-task")
        with pytest.raises(ExecutionValidationError) as exc:
            validate_plan_for_execution(valid_plan)
        assert "nonexistent-task" in exc.value.message or any(
            "nonexistent-task" in e for e in exc.value.context.get("errors", [])
        )

    def test_cycle_detected_raises(self, valid_plan):
        task_a = valid_plan.tasks[0]
        task_b = valid_plan.tasks[1]
        task_a.dependencies = [task_b.id]
        task_b.dependencies = [task_a.id]
        with pytest.raises(ExecutionValidationError) as exc:
            validate_plan_for_execution(valid_plan)
        assert "cycle" in str(exc.value.context["errors"]).lower()

    def test_wrong_initial_status_raises(self, valid_plan):
        valid_plan.tasks[0].status = TaskStatus.COMPLETED
        with pytest.raises(ExecutionValidationError) as exc:
            validate_plan_for_execution(valid_plan)
        assert any("completed" in e.lower() for e in exc.value.context["errors"])

    def test_validation_error_context_has_errors(self, valid_plan):
        valid_plan.status = PlanStatus.DRAFT
        with pytest.raises(ExecutionValidationError) as exc:
            validate_plan_for_execution(valid_plan)
        assert "errors" in exc.value.context
        assert len(exc.value.context["errors"]) > 0


class TestSessionValidation:
    def test_valid_session_passes(self, valid_session):
        result = validate_session_initialization(valid_session)
        assert result.valid is True

    def test_no_id_raises(self, valid_session):
        valid_session.id = ""
        with pytest.raises(ExecutionValidationError) as exc:
            validate_session_initialization(valid_session)
        assert any("no id" in e.lower() for e in exc.value.context["errors"])

    def test_no_plan_raises(self, valid_session):
        valid_session.plan = None
        with pytest.raises(ExecutionValidationError) as exc:
            validate_session_initialization(valid_session)
        assert "no plan" in str(exc.value.context["errors"]).lower()

    def test_no_tasks_raises(self, valid_session):
        valid_session.tasks = {}
        with pytest.raises(ExecutionValidationError) as exc:
            validate_session_initialization(valid_session)
        assert "no tasks" in str(exc.value.context["errors"]).lower()

    def test_task_not_pending_raises(self, valid_session):
        valid_session.tasks["task-a"].status = TaskState.READY
        with pytest.raises(ExecutionValidationError):
            validate_session_initialization(valid_session)

    def test_no_root_tasks_warns(self, valid_session):
        valid_session.root_tasks = []
        result = validate_session_initialization(valid_session)
        assert result.valid is True
        assert len(result.warnings) > 0


# ---------------------------------------------------------------------------
# Utility Tests
# ---------------------------------------------------------------------------

class TestUtils:
    def test_generate_session_id(self):
        sid = generate_session_id()
        assert sid
        assert len(sid) == 12

    def test_identify_root_tasks(self, valid_session):
        roots = identify_root_tasks(valid_session.tasks)
        assert "task-a" in roots
        assert "task-b" not in roots

    def test_identify_root_tasks_empty(self):
        roots = identify_root_tasks({})
        assert roots == []

    def test_build_in_degree_map(self, valid_session):
        degree = build_in_degree_map(valid_session.tasks)
        assert "task-a" in degree
        assert "task-b" in degree
        assert degree["task-a"].remaining == 0
        assert degree["task-b"].remaining == 1
        assert degree["task-b"].total == 1

    def test_wrap_task(self, valid_plan):
        plan_task = valid_plan.tasks[0]
        etask = wrap_task(plan_task)
        assert etask.id == plan_task.id
        assert etask.plan_task is plan_task
        assert etask.status == TaskState.PENDING
        assert etask.attempts == 0

    def test_wrap_task_custom_policy(self, valid_plan):
        plan_task = valid_plan.tasks[0]
        policy = RetryPolicy(max_attempts=7)
        etask = wrap_task(plan_task, policy)
        assert etask.max_attempts == 7

    def test_init_metrics(self, valid_session):
        metrics = init_metrics(valid_session)
        assert metrics.session_id == "session-001"
        assert metrics.total_tasks == 2
        assert metrics.completed_tasks == 0


# ---------------------------------------------------------------------------
# Pipeline Tests
# ---------------------------------------------------------------------------

class TestExecutionEngine:
    def test_create(self, engine):
        assert isinstance(engine, ExecutionEngine)

    def test_execute_raises_not_implemented(self, engine, valid_plan):
        with pytest.raises(NotImplementedError) as exc:
            import asyncio
            asyncio.run(engine.execute(valid_plan))
        assert "4C" in str(exc.value) or "Next runnable task" in str(exc.value)

    def test_get_session_unknown(self, engine):
        assert engine.get_session("nonexistent") is None

    def test_get_session_found(self, engine, valid_plan, valid_session):
        engine._sessions[valid_session.id] = valid_session
        found = engine.get_session(valid_session.id)
        assert found is not None
        assert found.id == valid_session.id

    def test_cancel_session(self, engine, valid_session):
        valid_session.status = SessionState.RUNNING
        engine._sessions[valid_session.id] = valid_session
        result = engine.cancel(valid_session.id)
        assert result.status == SessionState.CANCELLED
        for etask in result.tasks.values():
            assert etask.status == TaskState.CANCELLED

    def test_cancel_terminal_raises(self, engine, valid_session):
        valid_session.status = SessionState.COMPLETED
        engine._sessions[valid_session.id] = valid_session
        with pytest.raises(ExecutionSessionError):
            engine.cancel(valid_session.id)

    def test_cancel_unknown_raises(self, engine):
        with pytest.raises(ExecutionSessionError):
            engine.cancel("ghost")

    def test_pause_session(self, engine, valid_session):
        valid_session.status = SessionState.RUNNING
        engine._sessions[valid_session.id] = valid_session
        result = engine.pause(valid_session.id)
        assert result.status == SessionState.PAUSED

    def test_pause_not_running_raises(self, engine, valid_session):
        valid_session.status = SessionState.PENDING
        engine._sessions[valid_session.id] = valid_session
        with pytest.raises(ExecutionSessionError):
            engine.pause(valid_session.id)

    def test_resume_session(self, engine, valid_session):
        valid_session.status = SessionState.PAUSED
        engine._sessions[valid_session.id] = valid_session
        result = engine.resume(valid_session.id)
        assert result.status == SessionState.RUNNING

    def test_resume_not_paused_raises(self, engine, valid_session):
        valid_session.status = SessionState.RUNNING
        engine._sessions[valid_session.id] = valid_session
        with pytest.raises(ExecutionSessionError):
            engine.resume(valid_session.id)

    def test_approve_task(self, engine, valid_session):
        valid_session.status = SessionState.RUNNING
        etask = valid_session.tasks["task-a"]
        etask.status = TaskState.WAITING_APPROVAL
        engine._sessions[valid_session.id] = valid_session
        result = engine.approve(valid_session.id, "task-a")
        assert result.tasks["task-a"].status == TaskState.READY

    def test_approve_wrong_state_raises(self, engine, valid_session):
        valid_session.status = SessionState.RUNNING
        engine._sessions[valid_session.id] = valid_session
        with pytest.raises(ExecutionSessionError):
            engine.approve(valid_session.id, "task-a")

    def test_approve_unknown_task_raises(self, engine, valid_session):
        valid_session.status = SessionState.RUNNING
        engine._sessions[valid_session.id] = valid_session
        with pytest.raises(ExecutionSessionError):
            engine.approve(valid_session.id, "ghost-task")

    def test_reject_task(self, engine, valid_session):
        valid_session.status = SessionState.RUNNING
        etask = valid_session.tasks["task-a"]
        etask.status = TaskState.WAITING_APPROVAL
        engine._sessions[valid_session.id] = valid_session
        result = engine.reject(valid_session.id, "task-a")
        assert result.tasks["task-a"].status == TaskState.SKIPPED

    def test_reject_wrong_state_raises(self, engine, valid_session):
        valid_session.status = SessionState.RUNNING
        engine._sessions[valid_session.id] = valid_session
        with pytest.raises(ExecutionSessionError):
            engine.reject(valid_session.id, "task-a")

    def test_get_pipeline_singleton(self):
        p1 = get_pipeline()
        p2 = get_pipeline()
        assert p1 is p2
        assert isinstance(p1, ExecutionEngine)


# ---------------------------------------------------------------------------
# Planner Tests Still Pass (verification marker)
# ---------------------------------------------------------------------------

class TestPlannerIntegration:
    """Lightweight check that planner models still work with execution."""

    def test_plan_model_works(self, valid_plan):
        assert valid_plan.status == PlanStatus.VALIDATED
        assert len(valid_plan.tasks) == 2
        assert valid_plan.get_root_tasks()[0].id == "task-a"
        assert valid_plan.get_downstream_tasks("task-a")[0].id == "task-b"

    def test_payload_roundtrip(self):
        payload = MessagePayload(channel="telegram", template="hello")
        assert payload.to_dict()["channel"] == "telegram"
        assert payload.payload_type == "MessagePayload"