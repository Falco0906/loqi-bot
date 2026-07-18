"""Unit tests for the Execution Engine Dispatcher & Base Adapter (Phase 3.6.4C).

Tests base adapter interface, dispatcher routing, adapter resolution,
result handling, unsupported tasks, and pipeline integration.
"""

from __future__ import annotations

import asyncio
import pytest
from datetime import datetime, timezone
from typing import Optional

from services.execution.base_adapter import ExecutionAdapter
from services.execution.dispatcher import AdapterResolver, Dispatcher
from services.execution.enums import TaskState, SessionState
from services.execution.exceptions import (
    ExecutionDispatchError,
    ExecutionAdapterError,
)
from services.execution.execution_context import ExecutionContext
from services.execution.execution_models import (
    ExecutionSession,
    ExecutionTask,
    TaskResult,
    RetryPolicy,
)
from services.execution.execution_pipeline import ExecutionEngine, get_pipeline
from services.execution.state_machine import StateMachine
from services.execution.utils import wrap_task

from services.planner.planning_models import (
    Plan, PlanGoal, Task, PlanStatus, TaskStatus, TaskType,
)
from services.planner.payloads import MessagePayload


# ---------------------------------------------------------------------------
# Mock Adapters
# ---------------------------------------------------------------------------

class MockMessageAdapter(ExecutionAdapter):
    """A mock adapter that simulates sending a message."""

    @property
    def adapter_type(self) -> str:
        return "mock_telegram"

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
            output={"message_id": "msg_123", "channel": "telegram"},
            metadata={"adapter": self.adapter_type},
        )


class MockFailingAdapter(ExecutionAdapter):
    """A mock adapter that always fails."""

    @property
    def adapter_type(self) -> str:
        return "mock_failing"

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
            error="Connection refused",
            error_type="transient",
        )


class MockPermanentFailureAdapter(ExecutionAdapter):
    """A mock adapter that returns permanent failures."""

    @property
    def adapter_type(self) -> str:
        return "mock_permanent"

    @property
    def supported_task_types(self) -> list[TaskType]:
        return [TaskType.SCHEDULE_MEETING]

    async def execute(
        self,
        task: ExecutionTask,
        context: ExecutionContext,
    ) -> TaskResult:
        return TaskResult(
            task_id=task.id,
            attempt=task.attempts,
            success=False,
            error="Calendar API not configured",
            error_type="permanent",
        )


class MockMultiTypeAdapter(ExecutionAdapter):
    """An adapter that supports multiple task types."""

    @property
    def adapter_type(self) -> str:
        return "mock_multi"

    @property
    def supported_task_types(self) -> list[TaskType]:
        return [TaskType.WAIT_FOR_REPLY, TaskType.WAIT_DURATION]

    async def execute(
        self,
        task: ExecutionTask,
        context: ExecutionContext,
    ) -> TaskResult:
        return TaskResult(
            task_id=task.id,
            attempt=task.attempts,
            success=True,
            output={"waited": True},
        )


class MockValidateAdapter(ExecutionAdapter):
    """An adapter with custom validation."""

    def __init__(self, valid: bool = True):
        self._valid = valid

    @property
    def adapter_type(self) -> str:
        return "mock_validate"

    @property
    def supported_task_types(self) -> list[TaskType]:
        return [TaskType.UPDATE_CRM]

    def validate(self) -> Optional[list[str]]:
        if not self._valid:
            return ["API key not configured", "Endpoint unreachable"]
        return None

    async def execute(
        self,
        task: ExecutionTask,
        context: ExecutionContext,
    ) -> TaskResult:
        return TaskResult(
            task_id=task.id,
            attempt=task.attempts,
            success=True,
        )


class MockCompensateAdapter(ExecutionAdapter):
    """An adapter with compensation support."""

    def __init__(self):
        self.compensated = False

    @property
    def adapter_type(self) -> str:
        return "mock_compensate"

    @property
    def supported_task_types(self) -> list[TaskType]:
        return [TaskType.ESCALATE]

    async def execute(
        self,
        task: ExecutionTask,
        context: ExecutionContext,
    ) -> TaskResult:
        return TaskResult(
            task_id=task.id,
            attempt=task.attempts,
            success=True,
            output={"escalated": True},
        )

    async def compensate(
        self,
        task: ExecutionTask,
        context: ExecutionContext,
    ) -> Optional[TaskResult]:
        self.compensated = True
        return TaskResult(
            task_id=task.id,
            attempt=task.attempts,
            success=True,
            output={"compensated": True},
        )


class MockShutdownAdapter(ExecutionAdapter):
    """An adapter with shutdown tracking."""

    def __init__(self):
        self.shutdown_called = False

    @property
    def adapter_type(self) -> str:
        return "mock_shutdown"

    @property
    def supported_task_types(self) -> list[TaskType]:
        return [TaskType.ANALYZE_REPLY]

    def shutdown(self) -> None:
        self.shutdown_called = True

    async def execute(
        self,
        task: ExecutionTask,
        context: ExecutionContext,
    ) -> TaskResult:
        return TaskResult(
            task_id=task.id,
            attempt=task.attempts,
            success=True,
        )


# ---------------------------------------------------------------------------
# Mock Resolvers
# ---------------------------------------------------------------------------

class MockResolver:
    """A resolver that returns pre-configured adapters."""

    def __init__(self, adapter_map: dict[TaskType, ExecutionAdapter]):
        self._adapter_map = adapter_map

    def resolve(self, task_type: TaskType) -> Optional[ExecutionAdapter]:
        return self._adapter_map.get(task_type)


class TrackingResolver:
    """A resolver that tracks which task types were queried."""

    def __init__(self, adapter_map: dict[TaskType, ExecutionAdapter]):
        self._adapter_map = adapter_map
        self.resolved_types: list[TaskType] = []

    def resolve(self, task_type: TaskType) -> Optional[ExecutionAdapter]:
        self.resolved_types.append(task_type)
        return self._adapter_map.get(task_type)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def context():
    return ExecutionContext(session_id="test-session-123")


@pytest.fixture
def message_task():
    plan_task = Task(
        id="task-send",
        plan_id="plan-1",
        type=TaskType.SEND_MESSAGE,
        status=TaskStatus.PENDING,
        payload=MessagePayload(channel="telegram", template="hello"),
        label="send hello",
    )
    etask = wrap_task(plan_task)
    return etask


@pytest.fixture
def email_task():
    plan_task = Task(
        id="task-email",
        plan_id="plan-1",
        type=TaskType.SEND_EMAIL,
        status=TaskStatus.PENDING,
        payload=MessagePayload(channel="gmail", template="followup"),
        label="send email",
    )
    etask = wrap_task(plan_task)
    return etask


@pytest.fixture
def meeting_task():
    plan_task = Task(
        id="task-meeting",
        plan_id="plan-1",
        type=TaskType.SCHEDULE_MEETING,
        status=TaskStatus.PENDING,
        payload=MessagePayload(channel="calendar", template="demo"),
        label="schedule demo",
    )
    etask = wrap_task(plan_task)
    return etask


@pytest.fixture
def unsupported_task():
    """A task type with no adapter registered."""
    plan_task = Task(
        id="task-unknown",
        plan_id="plan-1",
        type=TaskType.BRANCH,
        status=TaskStatus.PENDING,
        payload=MessagePayload(channel="none", template="none"),
        label="unsupported",
    )
    etask = wrap_task(plan_task)
    return etask


@pytest.fixture
def mock_adapter():
    return MockMessageAdapter()


@pytest.fixture
def failing_adapter():
    return MockFailingAdapter()


@pytest.fixture
def permanent_adapter():
    return MockPermanentFailureAdapter()


@pytest.fixture
def multi_adapter():
    return MockMultiTypeAdapter()


@pytest.fixture
def resolver(mock_adapter, failing_adapter, permanent_adapter, multi_adapter):
    return MockResolver({
        TaskType.SEND_MESSAGE: mock_adapter,
        TaskType.SEND_EMAIL: failing_adapter,
        TaskType.SCHEDULE_MEETING: permanent_adapter,
        TaskType.WAIT_FOR_REPLY: multi_adapter,
        TaskType.WAIT_DURATION: multi_adapter,
    })


@pytest.fixture
def tracking_resolver(mock_adapter):
    return TrackingResolver({
        TaskType.SEND_MESSAGE: mock_adapter,
    })


# ---------------------------------------------------------------------------
# Pipeline fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def engine():
    return ExecutionEngine()


@pytest.fixture
def linear_plan():
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
    ]
    plan.tasks = tasks
    return plan


@pytest.fixture
def empty_plan():
    plan = Plan(
        id="empty-plan",
        conversation_id="conv-1",
        status=PlanStatus.VALIDATED,
        goal=PlanGoal(outcome="test"),
    )
    plan.tasks = []
    return plan


# ===================================================================
# BASE ADAPTER TESTS
# ===================================================================

class TestBaseAdapterAbstract:
    """The base adapter must be abstract — cannot instantiate directly."""

    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            ExecutionAdapter()  # type: ignore[abstract]

    def test_abstract_methods_defined(self):
        methods = ["execute"]
        props = ["adapter_type", "supported_task_types"]
        for m in methods:
            assert hasattr(ExecutionAdapter, m)
        for p in props:
            assert hasattr(ExecutionAdapter, p)


class TestBaseAdapterConcrete:
    """Concrete adapters must implement all abstract members."""

    def test_concrete_adapter_is_instance(self, mock_adapter):
        assert isinstance(mock_adapter, ExecutionAdapter)

    def test_adapter_type_property(self, mock_adapter):
        assert mock_adapter.adapter_type == "mock_telegram"

    def test_supported_task_types(self, mock_adapter):
        assert TaskType.SEND_MESSAGE in mock_adapter.supported_task_types
        assert TaskType.SEND_EMAIL not in mock_adapter.supported_task_types

    def test_supports_returns_true(self, mock_adapter):
        assert mock_adapter.supports(TaskType.SEND_MESSAGE) is True

    def test_supports_returns_false(self, mock_adapter):
        assert mock_adapter.supports(TaskType.SEND_EMAIL) is False

    def test_execute_returns_task_result(self, message_task, context, mock_adapter):
        result = asyncio.run(mock_adapter.execute(message_task, context))
        assert isinstance(result, TaskResult)

    def test_execute_success(self, message_task, context, mock_adapter):
        result = asyncio.run(mock_adapter.execute(message_task, context))
        assert result.success is True
        assert result.task_id == "task-send"

    def test_execute_transient_failure(self, email_task, context, failing_adapter):
        result = asyncio.run(failing_adapter.execute(email_task, context))
        assert result.success is False
        assert result.error_type == "transient"

    def test_execute_permanent_failure(self, meeting_task, context, permanent_adapter):
        result = asyncio.run(permanent_adapter.execute(meeting_task, context))
        assert result.success is False
        assert result.error_type == "permanent"

    def test_execute_output_preserved(self, message_task, context, mock_adapter):
        result = asyncio.run(mock_adapter.execute(message_task, context))
        assert result.output is not None
        assert result.output["message_id"] == "msg_123"

    def test_execute_metadata_preserved(self, message_task, context, mock_adapter):
        result = asyncio.run(mock_adapter.execute(message_task, context))
        assert result.metadata["adapter"] == "mock_telegram"


class TestBaseAdapterOptional:
    """Optional adapter methods have sensible defaults."""

    def test_validate_default_returns_none(self, mock_adapter):
        assert mock_adapter.validate() is None

    def test_validate_custom(self):
        adapter = MockValidateAdapter(valid=False)
        issues = adapter.validate()
        assert issues is not None
        assert len(issues) == 2

    def test_validate_valid(self):
        adapter = MockValidateAdapter(valid=True)
        assert adapter.validate() is None

    def test_shutdown_default_noop(self, mock_adapter):
        mock_adapter.shutdown()  # should not raise

    def test_shutdown_custom(self):
        adapter = MockShutdownAdapter()
        assert adapter.shutdown_called is False
        adapter.shutdown()
        assert adapter.shutdown_called is True

    def test_compensate_default_returns_none(self, mock_adapter):
        result = asyncio.run(mock_adapter.compensate(
            ExecutionTask(id="t", plan_task=None),
            ExecutionContext(session_id="s"),
        ))
        assert result is None

    def test_compensate_custom(self, context, meeting_task):
        adapter = MockCompensateAdapter()
        result = asyncio.run(adapter.compensate(meeting_task, context))
        assert result is not None
        assert result.success is True
        assert adapter.compensated is True


class TestBaseAdapterMultiType:
    """Adapters can support multiple task types."""

    def test_multi_type_supports(self, multi_adapter):
        assert multi_adapter.supports(TaskType.WAIT_FOR_REPLY) is True
        assert multi_adapter.supports(TaskType.WAIT_DURATION) is True
        assert multi_adapter.supports(TaskType.SEND_MESSAGE) is False

    def test_multi_type_execute(self, context, multi_adapter):
        wait_task = ExecutionTask(
            id="wait-1",
            plan_task=Task(
                id="wait-1", plan_id="p", type=TaskType.WAIT_FOR_REPLY,
                status=TaskStatus.PENDING,
            ),
        )
        result = asyncio.run(multi_adapter.execute(wait_task, context))
        assert result.success is True


# ===================================================================
# DISPATCHER TESTS
# ===================================================================

class TestDispatcherDispatch:
    """Core dispatch functionality."""

    def test_dispatch_success(self, message_task, context, resolver):
        result = asyncio.run(Dispatcher.dispatch(message_task, context, resolver))
        assert result is not None
        assert isinstance(result, TaskResult)

    def test_dispatch_returns_task_result(self, message_task, context, resolver):
        result = asyncio.run(Dispatcher.dispatch(message_task, context, resolver))
        assert isinstance(result, TaskResult)

    def test_dispatch_task_id_correct(self, message_task, context, resolver):
        result = asyncio.run(Dispatcher.dispatch(message_task, context, resolver))
        assert result.task_id == "task-send"

    def test_dispatch_attempt_preserved(self, message_task, context, resolver):
        message_task.attempts = 2
        result = asyncio.run(Dispatcher.dispatch(message_task, context, resolver))
        assert result.attempt == 2

    def test_dispatch_success_result(self, message_task, context, resolver):
        result = asyncio.run(Dispatcher.dispatch(message_task, context, resolver))
        assert result.success is True

    def test_dispatch_output_preserved(self, message_task, context, resolver):
        result = asyncio.run(Dispatcher.dispatch(message_task, context, resolver))
        assert result.output is not None
        assert result.output["message_id"] == "msg_123"

    def test_dispatch_metadata_preserved(self, message_task, context, resolver):
        result = asyncio.run(Dispatcher.dispatch(message_task, context, resolver))
        assert result.metadata["adapter"] == "mock_telegram"


class TestDispatcherUnsupported:
    """Unsupported tasks raise ExecutionDispatchError."""

    def test_unsupported_task_raises(self, unsupported_task, context, resolver):
        with pytest.raises(ExecutionDispatchError) as exc:
            asyncio.run(Dispatcher.dispatch(unsupported_task, context, resolver))
        assert exc.value is not None

    def test_unsupported_error_has_task_id(self, unsupported_task, context, resolver):
        with pytest.raises(ExecutionDispatchError) as exc:
            asyncio.run(Dispatcher.dispatch(unsupported_task, context, resolver))
        assert "task_id" in exc.value.context
        assert exc.value.context["task_id"] == "task-unknown"

    def test_unsupported_error_has_task_type(self, unsupported_task, context, resolver):
        with pytest.raises(ExecutionDispatchError) as exc:
            asyncio.run(Dispatcher.dispatch(unsupported_task, context, resolver))
        assert "task_type" in exc.value.context
        assert exc.value.context["task_type"] == "branch"

    def test_unsupported_error_has_explanation(self, unsupported_task, context, resolver):
        with pytest.raises(ExecutionDispatchError) as exc:
            asyncio.run(Dispatcher.dispatch(unsupported_task, context, resolver))
        assert "No adapter registered" in str(exc.value)
        assert "branch" in str(exc.value)

    def test_unsupported_error_is_dispatch_error(self, unsupported_task, context, resolver):
        with pytest.raises(ExecutionDispatchError):
            asyncio.run(Dispatcher.dispatch(unsupported_task, context, resolver))


class TestDispatcherFailureModes:
    """Dispatcher correctly propagates adapter failures."""

    def test_transient_failure(self, email_task, context, resolver):
        result = asyncio.run(Dispatcher.dispatch(email_task, context, resolver))
        assert result.success is False
        assert result.error_type == "transient"
        assert result.error == "Connection refused"

    def test_permanent_failure(self, meeting_task, context, resolver):
        result = asyncio.run(Dispatcher.dispatch(meeting_task, context, resolver))
        assert result.success is False
        assert result.error_type == "permanent"
        assert result.error == "Calendar API not configured"

    def test_error_message_preserved(self, email_task, context, resolver):
        result = asyncio.run(Dispatcher.dispatch(email_task, context, resolver))
        assert result.error is not None

    def test_error_type_preserved(self, meeting_task, context, resolver):
        result = asyncio.run(Dispatcher.dispatch(meeting_task, context, resolver))
        assert result.error_type == "permanent"

    def test_success_error_none(self, message_task, context, resolver):
        result = asyncio.run(Dispatcher.dispatch(message_task, context, resolver))
        assert result.error is None

    def test_success_error_type_none(self, message_task, context, resolver):
        result = asyncio.run(Dispatcher.dispatch(message_task, context, resolver))
        assert result.error_type is None


class TestDispatcherStateless:
    """Dispatcher is stateless — multiple calls produce independent results."""

    def test_dispatch_stateless(self, message_task, email_task, context, resolver):
        result1 = asyncio.run(Dispatcher.dispatch(message_task, context, resolver))
        result2 = asyncio.run(Dispatcher.dispatch(email_task, context, resolver))
        assert result1.success is True
        assert result2.success is False
        assert result1.task_id == "task-send"
        assert result2.task_id == "task-email"

    def test_dispatch_independent_calls(self, message_task, context, resolver):
        result1 = asyncio.run(Dispatcher.dispatch(message_task, context, resolver))
        result2 = asyncio.run(Dispatcher.dispatch(message_task, context, resolver))
        assert result1.success == result2.success
        assert result1.task_id == result2.task_id

    def test_dispatch_no_side_effects_on_context(self, message_task, context, resolver):
        original = context.to_dict()
        asyncio.run(Dispatcher.dispatch(message_task, context, resolver))
        assert context.to_dict() == original


class TestDispatcherResolverInteraction:
    """Dispatcher correctly interacts with the resolver."""

    def test_resolver_called_with_correct_type(self, message_task, context, tracking_resolver):
        asyncio.run(Dispatcher.dispatch(message_task, context, tracking_resolver))
        assert TaskType.SEND_MESSAGE in tracking_resolver.resolved_types

    def test_resolver_called_exactly_once(self, message_task, context, tracking_resolver):
        asyncio.run(Dispatcher.dispatch(message_task, context, tracking_resolver))
        assert len(tracking_resolver.resolved_types) == 1

    def test_adapter_name_set_on_task(self, message_task, context, resolver):
        assert message_task.adapter_name is None
        asyncio.run(Dispatcher.dispatch(message_task, context, resolver))
        assert message_task.adapter_name == "mock_telegram"

    def test_adapter_name_matches_adapter(self, message_task, context, resolver):
        asyncio.run(Dispatcher.dispatch(message_task, context, resolver))
        adapter = resolver.resolve(TaskType.SEND_MESSAGE)
        assert message_task.adapter_name == adapter.adapter_type


class TestDispatcherContextPassthrough:
    """Dispatcher passes context to adapter correctly."""

    def test_context_passed_to_adapter(self):
        received_contexts = []

        class CaptureContextAdapter(ExecutionAdapter):
            @property
            def adapter_type(self) -> str:
                return "capture"

            @property
            def supported_task_types(self) -> list[TaskType]:
                return [TaskType.ANALYZE_REPLY]

            async def execute(
                self,
                task: ExecutionTask,
                context: ExecutionContext,
            ) -> TaskResult:
                received_contexts.append(context)
                return TaskResult(task_id=task.id, attempt=1, success=True)

        adapter = CaptureContextAdapter()
        resolver = MockResolver({TaskType.ANALYZE_REPLY: adapter})
        task = ExecutionTask(
            id="t1",
            plan_task=Task(
                id="t1", plan_id="p", type=TaskType.ANALYZE_REPLY,
                status=TaskStatus.PENDING,
            ),
        )
        ctx = ExecutionContext(session_id="session-456", channel="web")
        asyncio.run(Dispatcher.dispatch(task, ctx, resolver))
        assert len(received_contexts) == 1
        assert received_contexts[0].session_id == "session-456"


class TestDispatcherMultipleTaskTypes:
    """Dispatcher handles multiple task types correctly."""

    def test_dispatch_multiple_types(self, resolver, context):
        task_types = [TaskType.SEND_MESSAGE, TaskType.SEND_EMAIL, TaskType.SCHEDULE_MEETING]
        results = []
        for tt in task_types:
            plan_task = Task(
                id=f"task-{tt.value}", plan_id="p", type=tt,
                status=TaskStatus.PENDING,
            )
            etask = wrap_task(plan_task)
            result = asyncio.run(Dispatcher.dispatch(etask, context, resolver))
            results.append(result)
        assert len(results) == 3
        assert results[0].success is True
        assert results[1].success is False
        assert results[2].success is False

    def test_dispatch_with_empty_context(self, resolver):
        plan_task = Task(
            id="t1", plan_id="p", type=TaskType.SEND_MESSAGE,
            status=TaskStatus.PENDING,
        )
        etask = wrap_task(plan_task)
        ctx = ExecutionContext(session_id="empty-session")
        result = asyncio.run(Dispatcher.dispatch(etask, ctx, resolver))
        assert result.success is True


class TestDispatcherTiming:
    """Dispatcher populates timing fields."""

    def test_timing_fields_populated(self, message_task, context, resolver):
        result = asyncio.run(Dispatcher.dispatch(message_task, context, resolver))
        assert result.started_at is not None
        assert result.completed_at is not None

    def test_started_before_completed(self, message_task, context, resolver):
        result = asyncio.run(Dispatcher.dispatch(message_task, context, resolver))
        assert result.started_at <= result.completed_at

    def test_duration_non_negative(self, message_task, context, resolver):
        result = asyncio.run(Dispatcher.dispatch(message_task, context, resolver))
        assert result.duration_ms >= 0


# ===================================================================
# PIPELINE INTEGRATION TESTS
# ===================================================================

class TestPipelineDispatcherIntegration:
    """Pipeline → scheduler → dispatcher integration.

    With a resolver, the execution loop runs all tasks to completion.
    Without a resolver, the legacy single-step behavior is preserved.
    """

    # -----------------------------------------------------------------------
    # Full execution loop (resolver provided)
    # -----------------------------------------------------------------------

    def test_execute_with_resolver_dispatches(self, engine, linear_plan, resolver):
        session = asyncio.run(engine.execute(linear_plan, resolver=resolver))
        assert session.status == SessionState.COMPLETED
        assert session.tasks["task-a"].status == TaskState.COMPLETED

    def test_dispatch_result_stored_on_task(self, engine, linear_plan, resolver):
        session = asyncio.run(engine.execute(linear_plan, resolver=resolver))
        task = session.tasks["task-a"]
        assert task.result is not None
        assert isinstance(task.result, TaskResult)
        assert task.result.success is True

    def test_task_transitioned_to_completed(self, engine, linear_plan, resolver):
        session = asyncio.run(engine.execute(linear_plan, resolver=resolver))
        assert session.tasks["task-a"].status == TaskState.COMPLETED

    def test_adapter_called_during_execute(self, engine, linear_plan, resolver):
        session = asyncio.run(engine.execute(linear_plan, resolver=resolver))
        assert session.tasks["task-a"].adapter_name == "mock_telegram"

    def test_execute_creates_session(self, engine, linear_plan, resolver):
        session = asyncio.run(engine.execute(linear_plan, resolver=resolver))
        assert session.id is not None
        assert session.id in engine._sessions

    def test_execute_session_tasks_wrapped(self, engine, linear_plan, resolver):
        session = asyncio.run(engine.execute(linear_plan, resolver=resolver))
        assert len(session.tasks) == 1
        assert "task-a" in session.tasks

    def test_execute_with_resolver_context_has_session_id(self, engine, linear_plan, resolver):
        session = asyncio.run(engine.execute(linear_plan, resolver=resolver))
        assert session.id is not None

    def test_execute_with_resolver_no_side_effects_on_plan(self, engine, linear_plan, resolver):
        original_status = linear_plan.status
        asyncio.run(engine.execute(linear_plan, resolver=resolver))
        assert linear_plan.status == original_status

    def test_dispatcher_pipeline_integration_full(self, engine, linear_plan, resolver):
        session = asyncio.run(engine.execute(linear_plan, resolver=resolver))
        assert session.status == SessionState.COMPLETED
        task = session.tasks["task-a"]
        assert task.status == TaskState.COMPLETED
        assert task.result is not None
        assert task.result.success is True
        assert task.adapter_name == "mock_telegram"

    # -----------------------------------------------------------------------
    # Unsupported task handling (resolver provided)
    # -----------------------------------------------------------------------

    def test_execute_with_resolver_unsupported_task(self, engine, resolver):
        plan = Plan(
            id="unsupported-plan",
            conversation_id="conv-1",
            status=PlanStatus.VALIDATED,
            goal=PlanGoal(outcome="test"),
        )
        plan.tasks = [
            Task(
                id="task-unknown", plan_id=plan.id, type=TaskType.BRANCH,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="none", template="none"),
                label="unsupported",
            ),
        ]
        session = asyncio.run(engine.execute(plan, resolver=resolver))
        task = session.tasks["task-unknown"]
        assert task.status == TaskState.FAILED
        assert task.result is not None
        assert task.result.success is False
        assert task.result.metadata.get("unsupported_task") is True

    # -----------------------------------------------------------------------
    # Failure handling (resolver provided)
    # -----------------------------------------------------------------------

    def test_execute_transient_failure_flow(self, engine, resolver):
        plan = Plan(
            id="fail-plan",
            conversation_id="conv",
            status=PlanStatus.VALIDATED,
            goal=PlanGoal(outcome="test"),
        )
        plan.tasks = [
            Task(
                id="task-email", plan_id=plan.id, type=TaskType.SEND_EMAIL,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="gmail", template="test"),
                label="fail",
            ),
        ]
        session = asyncio.run(engine.execute(plan, resolver=resolver))
        task = session.tasks["task-email"]
        assert task.status == TaskState.FAILED
        assert task.result is not None
        assert task.result.success is False
        assert task.result.error == "Connection refused"
        assert task.result.error_type == "transient"

    def test_execute_permanent_failure_flow(self, engine, resolver):
        plan = Plan(
            id="perm-plan",
            conversation_id="conv",
            status=PlanStatus.VALIDATED,
            goal=PlanGoal(outcome="test"),
        )
        plan.tasks = [
            Task(
                id="task-meeting", plan_id=plan.id, type=TaskType.SCHEDULE_MEETING,
                status=TaskStatus.PENDING,
                payload=MessagePayload(channel="calendar", template="demo"),
                label="perm fail",
            ),
        ]
        session = asyncio.run(engine.execute(plan, resolver=resolver))
        task = session.tasks["task-meeting"]
        assert task.status == TaskState.FAILED
        assert task.result is not None
        assert task.result.success is False
        assert task.result.error == "Calendar API not configured"
        assert task.result.error_type == "permanent"

    # -----------------------------------------------------------------------
    # Approval-handled task (resolver provided)
    # -----------------------------------------------------------------------

    def test_execute_with_resolver_and_approval(self, engine, resolver):
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
        # Approval metadata on a Plan task does not affect scheduling;
        # the task runs through the execution loop normally.
        session = asyncio.run(engine.execute(plan, resolver=resolver))
        assert session.tasks["task-a"].status == TaskState.COMPLETED
        assert session.status == SessionState.COMPLETED

    # -----------------------------------------------------------------------
    # Empty plan (validation error)
    # -----------------------------------------------------------------------

    def test_terminal_plan_no_dispatch(self, engine, empty_plan, resolver):
        with pytest.raises(Exception):
            asyncio.run(engine.execute(empty_plan, resolver=resolver))
        assert len(engine._sessions) <= 1

    # -----------------------------------------------------------------------
    # Legacy single-step behavior (no resolver)
    # -----------------------------------------------------------------------

    def test_execute_without_resolver_old_behavior(self, engine, linear_plan):
        with pytest.raises(NotImplementedError) as exc:
            asyncio.run(engine.execute(linear_plan))
        assert "3.6.4C" in str(exc.value) or "Next runnable task" in str(exc.value)

    def test_execute_without_resolver_task_running(self, engine, linear_plan):
        with pytest.raises(NotImplementedError):
            asyncio.run(engine.execute(linear_plan))
        session = next(iter(engine._sessions.values()))
        assert session.tasks["task-a"].status == TaskState.RUNNING

    def test_execute_without_resolver_adapter_name_not_set(self, engine, linear_plan):
        with pytest.raises(NotImplementedError):
            asyncio.run(engine.execute(linear_plan))
        session = next(iter(engine._sessions.values()))
        assert session.tasks["task-a"].adapter_name is None

    def test_execute_without_resolver_no_result(self, engine, linear_plan):
        with pytest.raises(NotImplementedError):
            asyncio.run(engine.execute(linear_plan))
        session = next(iter(engine._sessions.values()))
        assert session.tasks["task-a"].result is None

    # -----------------------------------------------------------------------
    # Singleton
    # -----------------------------------------------------------------------

    def test_get_pipeline_singleton(self):
        p1 = get_pipeline()
        p2 = get_pipeline()
        assert p1 is p2
