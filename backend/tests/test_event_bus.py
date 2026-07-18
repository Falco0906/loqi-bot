"""Unit tests for the Event Bus (Phase 3.6.4G).

Tests the EventBus standalone and integrated with the execution pipeline.
Covers bus operations, subscriber isolation, thread safety, and end-to-end
event flow through the pipeline.

All existing 552 tests must remain green — event publishing is additive.
"""

from __future__ import annotations

import asyncio
import threading
import pytest
from typing import Optional

from services.execution.base_adapter import ExecutionAdapter
from services.execution.dispatcher import Dispatcher
from services.execution.enums import ExecutionEventType, SessionState, TaskState
from services.execution.event_bus import EventBus, EventSubscriber
from services.execution.execution_context import ExecutionContext
from services.execution.execution_models import (
    ExecutionEvent,
    ExecutionSession,
    ExecutionTask,
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
# Test Subscribers
# ---------------------------------------------------------------------------

class CollectingSubscriber:
    """Records all events it receives for later assertion."""

    def __init__(self):
        self.events: list[ExecutionEvent] = []

    def handle(self, event: ExecutionEvent) -> None:
        self.events.append(event)


class FailingSubscriber:
    """Simulates a subscriber that raises on every event."""

    def handle(self, event: ExecutionEvent) -> None:
        raise RuntimeError("Subscriber failure")


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

    async def execute(self, task: ExecutionTask, context: ExecutionContext) -> TaskResult:
        return TaskResult(
            task_id=task.id, attempt=task.attempts, success=True,
            output={"result": "ok"},
        )


class MockPermanentFailAdapter(ExecutionAdapter):
    @property
    def adapter_type(self) -> str:
        return "mock_perm_fail"

    @property
    def supported_task_types(self) -> list[TaskType]:
        return [TaskType.SEND_EMAIL]

    async def execute(self, task: ExecutionTask, context: ExecutionContext) -> TaskResult:
        return TaskResult(
            task_id=task.id, attempt=task.attempts, success=False,
            error="Permanent error", error_type="permanent",
        )


class MockTransientFailAdapter(ExecutionAdapter):
    def __init__(self):
        self.call_count = 0

    @property
    def adapter_type(self) -> str:
        return "mock_transient"

    @property
    def supported_task_types(self) -> list[TaskType]:
        return [TaskType.UPDATE_CRM]

    async def execute(self, task: ExecutionTask, context: ExecutionContext) -> TaskResult:
        self.call_count += 1
        return TaskResult(
            task_id=task.id, attempt=task.attempts, success=False,
            error="Transient error", error_type="transient",
        )


class MockTransientThenOkAdapter(ExecutionAdapter):
    def __init__(self, fail_count: int = 1):
        self.fail_count = fail_count
        self.call_count = 0

    @property
    def adapter_type(self) -> str:
        return "mock_transient_then_ok"

    @property
    def supported_task_types(self) -> list[TaskType]:
        return [TaskType.ANALYZE_REPLY]

    async def execute(self, task: ExecutionTask, context: ExecutionContext) -> TaskResult:
        self.call_count += 1
        if self.call_count <= self.fail_count:
            return TaskResult(
                task_id=task.id, attempt=task.attempts, success=False,
                error=f"Transient #{self.call_count}", error_type="transient",
                metadata={"call": self.call_count},
            )
        return TaskResult(
            task_id=task.id, attempt=task.attempts, success=True,
            output={"succeeded_on": self.call_count},
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
def event_bus():
    return EventBus()


@pytest.fixture
def subscriber():
    return CollectingSubscriber()


@pytest.fixture
def engine(event_bus):
    eng = ExecutionEngine(event_bus=event_bus)
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
    return MockTransientThenOkAdapter(fail_count=1)


@pytest.fixture
def success_plan():
    plan = Plan(id="p", conversation_id="c", status=PlanStatus.VALIDATED, goal=PlanGoal(outcome="test"))
    plan.tasks = [Task(id="t1", plan_id=plan.id, type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING, payload=MessagePayload(channel="tg", template="ok"), label="success")]
    return plan


@pytest.fixture
def perm_fail_plan():
    plan = Plan(id="p", conversation_id="c", status=PlanStatus.VALIDATED, goal=PlanGoal(outcome="test"))
    plan.tasks = [Task(id="t1", plan_id=plan.id, type=TaskType.SEND_EMAIL, status=TaskStatus.PENDING, payload=MessagePayload(channel="gmail", template="fail"), label="perm")]
    return plan


@pytest.fixture
def transient_fail_plan():
    plan = Plan(id="p", conversation_id="c", status=PlanStatus.VALIDATED, goal=PlanGoal(outcome="test"))
    plan.tasks = [Task(id="t1", plan_id=plan.id, type=TaskType.UPDATE_CRM, status=TaskStatus.PENDING, payload=MessagePayload(channel="none", template="none"), label="transient")]
    return plan


@pytest.fixture
def transient_then_ok_plan():
    plan = Plan(id="p", conversation_id="c", status=PlanStatus.VALIDATED, goal=PlanGoal(outcome="test"))
    plan.tasks = [Task(id="t1", plan_id=plan.id, type=TaskType.ANALYZE_REPLY, status=TaskStatus.PENDING, payload=MessagePayload(channel="none", template="none"), label="retry")]
    return plan


@pytest.fixture
def multi_task_plan():
    plan = Plan(id="p", conversation_id="c", status=PlanStatus.VALIDATED, goal=PlanGoal(outcome="test"))
    plan.tasks = [
        Task(id="t1", plan_id=plan.id, type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING, payload=MessagePayload(channel="tg", template="a"), label="a"),
        Task(id="t2", plan_id=plan.id, type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING, payload=MessagePayload(channel="tg", template="b"), label="b"),
    ]
    return plan


@pytest.fixture
def dag_plan():
    """A → B (B depends on A)."""
    plan = Plan(id="p", conversation_id="c", status=PlanStatus.VALIDATED, goal=PlanGoal(outcome="test"))
    plan.tasks = [
        Task(id="t1", plan_id=plan.id, type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING, payload=MessagePayload(channel="tg", template="a"), label="a"),
        Task(id="t2", plan_id=plan.id, type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING, payload=MessagePayload(channel="tg", template="b"), label="b", dependencies=["t1"]),
    ]
    return plan


@pytest.fixture
def empty_plan():
    plan = Plan(id="p", conversation_id="c", status=PlanStatus.VALIDATED, goal=PlanGoal(outcome="test"))
    plan.tasks = []
    return plan


# ===================================================================
# BUS UNIT TESTS
# ===================================================================

class TestEventBusSubscribe:
    def test_subscribe_adds_subscriber(self, event_bus, subscriber):
        event_bus.subscribe(subscriber)
        assert event_bus.subscriber_count == 1

    def test_subscribe_multiple(self, event_bus):
        s1, s2, s3 = CollectingSubscriber(), CollectingSubscriber(), CollectingSubscriber()
        event_bus.subscribe(s1)
        event_bus.subscribe(s2)
        event_bus.subscribe(s3)
        assert event_bus.subscriber_count == 3

    def test_duplicate_subscribe_ignored(self, event_bus, subscriber):
        event_bus.subscribe(subscriber)
        event_bus.subscribe(subscriber)
        assert event_bus.subscriber_count == 1

    def test_subscribe_same_object_twice(self, event_bus):
        s = CollectingSubscriber()
        event_bus.subscribe(s)
        event_bus.subscribe(s)
        assert event_bus.subscriber_count == 1


class TestEventBusUnsubscribe:
    def test_unsubscribe_removes_subscriber(self, event_bus, subscriber):
        event_bus.subscribe(subscriber)
        event_bus.unsubscribe(subscriber)
        assert event_bus.subscriber_count == 0

    def test_unsubscribe_not_subscribed(self, event_bus):
        s = CollectingSubscriber()
        event_bus.unsubscribe(s)
        assert event_bus.subscriber_count == 0

    def test_unsubscribe_one_of_many(self, event_bus):
        s1, s2 = CollectingSubscriber(), CollectingSubscriber()
        event_bus.subscribe(s1)
        event_bus.subscribe(s2)
        event_bus.unsubscribe(s1)
        assert event_bus.subscriber_count == 1

    def test_unsubscribe_all(self, event_bus):
        subscribers = [CollectingSubscriber() for _ in range(5)]
        for s in subscribers:
            event_bus.subscribe(s)
        for s in subscribers:
            event_bus.unsubscribe(s)
        assert event_bus.subscriber_count == 0


class TestEventBusClear:
    def test_clear_removes_all(self, event_bus):
        for _ in range(10):
            event_bus.subscribe(CollectingSubscriber())
        event_bus.clear()
        assert event_bus.subscriber_count == 0

    def test_clear_empty_bus(self, event_bus):
        event_bus.clear()
        assert event_bus.subscriber_count == 0

    def test_clear_then_add_works(self, event_bus, subscriber):
        event_bus.subscribe(subscriber)
        event_bus.clear()
        event_bus.subscribe(subscriber)
        assert event_bus.subscriber_count == 1


class TestEventBusPublish:
    def test_publish_no_subscribers(self, event_bus):
        event = ExecutionEvent(event_type=ExecutionEventType.SESSION_STARTED, session_id="s1")
        event_bus.publish(event)
        assert event.sequence > 0

    def test_publish_single_subscriber(self, event_bus, subscriber):
        event_bus.subscribe(subscriber)
        event_bus.publish(ExecutionEvent(event_type=ExecutionEventType.SESSION_STARTED, session_id="s1"))
        assert len(subscriber.events) == 1

    def test_publish_multiple_subscribers(self, event_bus):
        s1, s2, s3 = CollectingSubscriber(), CollectingSubscriber(), CollectingSubscriber()
        for s in (s1, s2, s3):
            event_bus.subscribe(s)
        event_bus.publish(ExecutionEvent(event_type=ExecutionEventType.SESSION_STARTED, session_id="s1"))
        assert len(s1.events) == 1
        assert len(s2.events) == 1
        assert len(s3.events) == 1

    def test_publish_multiple_events(self, event_bus, subscriber):
        event_bus.subscribe(subscriber)
        for i in range(5):
            event_bus.publish(ExecutionEvent(event_type=ExecutionEventType.SESSION_STARTED, session_id="s1"))
        assert len(subscriber.events) == 5

    def test_publish_event_data_preserved(self, event_bus, subscriber):
        event_bus.subscribe(subscriber)
        event = ExecutionEvent(event_type=ExecutionEventType.TASK_COMPLETED, session_id="s1", task_id="t1", data={"key": "value"})
        event_bus.publish(event)
        received = subscriber.events[0]
        assert received.event_type == ExecutionEventType.TASK_COMPLETED
        assert received.session_id == "s1"
        assert received.task_id == "t1"
        assert received.data == {"key": "value"}

    def test_publish_sequence_increments(self, event_bus, subscriber):
        event_bus.subscribe(subscriber)
        for _ in range(3):
            event_bus.publish(ExecutionEvent(event_type=ExecutionEventType.SESSION_STARTED, session_id="s1"))
        assert subscriber.events[0].sequence == 1
        assert subscriber.events[1].sequence == 2
        assert subscriber.events[2].sequence == 3

    def test_publish_sets_event_id(self, event_bus, subscriber):
        event_bus.subscribe(subscriber)
        event = ExecutionEvent(event_type=ExecutionEventType.SESSION_STARTED, session_id="s1", id="")
        event_bus.publish(event)
        assert len(event.id) == 12

    def test_publish_after_unsubscribe(self, event_bus, subscriber):
        event_bus.subscribe(subscriber)
        event_bus.unsubscribe(subscriber)
        event_bus.publish(ExecutionEvent(event_type=ExecutionEventType.SESSION_STARTED, session_id="s1"))
        assert len(subscriber.events) == 0


class TestEventBusSubscriberOrder:
    def test_subscribers_called_in_order(self, event_bus):
        order = []
        class OrderedSubscriber:
            def __init__(self, name):
                self.name = name
            def handle(self, event):
                order.append(self.name)

        s1, s2, s3 = OrderedSubscriber("first"), OrderedSubscriber("second"), OrderedSubscriber("third")
        event_bus.subscribe(s1)
        event_bus.subscribe(s2)
        event_bus.subscribe(s3)
        event_bus.publish(ExecutionEvent(event_type=ExecutionEventType.SESSION_STARTED, session_id="s1"))
        assert order == ["first", "second", "third"]


class TestEventBusExceptionIsolation:
    def test_failing_subscriber_does_not_block_others(self, event_bus):
        s_ok1, s_fail, s_ok2 = CollectingSubscriber(), FailingSubscriber(), CollectingSubscriber()
        event_bus.subscribe(s_ok1)
        event_bus.subscribe(s_fail)
        event_bus.subscribe(s_ok2)
        event_bus.publish(ExecutionEvent(event_type=ExecutionEventType.SESSION_STARTED, session_id="s1"))
        assert len(s_ok1.events) == 1
        assert len(s_ok2.events) == 1

    def test_all_failing_subscribers_isolated(self, event_bus, subscriber):
        fail1, fail2, fail3 = FailingSubscriber(), FailingSubscriber(), FailingSubscriber()
        for s in (fail1, fail2, fail3):
            event_bus.subscribe(s)
        event_bus.publish(ExecutionEvent(event_type=ExecutionEventType.SESSION_STARTED, session_id="s1"))

    def test_mixed_fail_and_ok_still_delivers_all_to_ok(self, event_bus):
        ok_subscribers = [CollectingSubscriber() for _ in range(3)]
        fail_subscribers = [FailingSubscriber() for _ in range(3)]
        for s in ok_subscribers + fail_subscribers:
            event_bus.subscribe(s)
        event_bus.publish(ExecutionEvent(event_type=ExecutionEventType.SESSION_STARTED, session_id="s1"))
        for s in ok_subscribers:
            assert len(s.events) == 1


class TestEventBusSubscriberMutation:
    def test_subscribe_during_publish_after(self, event_bus):
        late_subscriber = CollectingSubscriber()
        events_received = []

        class MutatingSubscriber:
            def handle(self, event):
                events_received.append(1)
                event_bus.subscribe(late_subscriber)

        event_bus.subscribe(MutatingSubscriber())
        event_bus.publish(ExecutionEvent(event_type=ExecutionEventType.SESSION_STARTED, session_id="s1"))
        # late subscriber should not have received the first event
        assert len(late_subscriber.events) == 0
        # but should receive subsequent events
        event_bus.publish(ExecutionEvent(event_type=ExecutionEventType.SESSION_STARTED, session_id="s1"))
        assert len(late_subscriber.events) == 1

    def test_unsubscribe_during_publish(self, event_bus):
        unsubscriber = CollectingSubscriber()
        events_received = []

        class UnsubscribingSubscriber:
            def handle(self, event):
                events_received.append(1)
                event_bus.unsubscribe(unsubscriber)

        event_bus.subscribe(unsubscriber)
        event_bus.subscribe(UnsubscribingSubscriber())
        event_bus.publish(ExecutionEvent(event_type=ExecutionEventType.SESSION_STARTED, session_id="s1"))
        # unsubscriber should have received the event (snapshot taken before iteration)
        assert len(unsubscriber.events) == 1

    def test_clear_during_publish(self, event_bus):
        surviving = CollectingSubscriber()
        cleared = CollectingSubscriber()

        class ClearingSubscriber:
            def handle(self, event):
                event_bus.clear()

        event_bus.subscribe(surviving)
        event_bus.subscribe(ClearingSubscriber())
        event_bus.subscribe(cleared)
        event_bus.publish(ExecutionEvent(event_type=ExecutionEventType.SESSION_STARTED, session_id="s1"))
        # All subscribers in the snapshot receive the event
        assert len(surviving.events) == 1
        assert len(cleared.events) == 1
        # After clear, subsequent publishes reach nobody
        event_bus.publish(ExecutionEvent(event_type=ExecutionEventType.SESSION_STARTED, session_id="s1"))
        assert len(surviving.events) == 1
        assert len(cleared.events) == 1


class TestEventBusThreadSafety:
    def test_concurrent_publish(self, event_bus):
        subscriber = CollectingSubscriber()
        event_bus.subscribe(subscriber)

        def publish_many(count: int):
            for i in range(count):
                event_bus.publish(ExecutionEvent(event_type=ExecutionEventType.SESSION_STARTED, session_id="s1"))

        threads = [threading.Thread(target=publish_many, args=(100,)) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(subscriber.events) == 400

    def test_concurrent_subscribe_unsubscribe(self, event_bus):
        subscribers = [CollectingSubscriber() for _ in range(20)]

        def sub_work():
            for s in subscribers:
                event_bus.subscribe(s)
                event_bus.unsubscribe(s)

        threads = [threading.Thread(target=sub_work) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    def test_concurrent_publish_and_subscribe(self, event_bus):
        subscriber = CollectingSubscriber()
        results = []

        def publisher():
            for _ in range(500):
                event_bus.publish(ExecutionEvent(event_type=ExecutionEventType.SESSION_STARTED, session_id="s1"))

        def subscriber_worker():
            event_bus.subscribe(subscriber)
            results.append(len(subscriber.events))

        threads = [threading.Thread(target=publisher) for _ in range(2)]
        threads.append(threading.Thread(target=subscriber_worker))
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert event_bus.subscriber_count >= 0


# ===================================================================
# PIPELINE INTEGRATION TESTS
# ===================================================================

class TestPipelineSessionStarted:
    def test_single_task_session_started(self, event_bus, subscriber, engine, success_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(success_plan, resolver=resolver))
        events = [e for e in subscriber.events if e.event_type == ExecutionEventType.SESSION_STARTED]
        assert len(events) == 1
        assert events[0].session_id
        assert "plan_id" in events[0].data

    def test_session_started_before_any_task_event(self, event_bus, subscriber, engine, success_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(success_plan, resolver=resolver))
        session_started = [e for e in subscriber.events if e.event_type == ExecutionEventType.SESSION_STARTED]
        task_events = [e for e in subscriber.events if e.task_id is not None]
        if session_started and task_events:
            assert session_started[0].sequence < task_events[0].sequence

    def test_session_started_plan_id(self, event_bus, subscriber, engine, success_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(success_plan, resolver=resolver))
        started = [e for e in subscriber.events if e.event_type == ExecutionEventType.SESSION_STARTED][0]
        assert started.data["plan_id"] == "p"


class TestPipelineTaskStarted:
    def test_task_started_event(self, event_bus, subscriber, engine, success_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(success_plan, resolver=resolver))
        started = [e for e in subscriber.events if e.event_type == ExecutionEventType.TASK_STARTED]
        assert len(started) == 1
        assert started[0].task_id == "t1"

    def test_task_started_has_attempt_zero(self, event_bus, subscriber, engine, success_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(success_plan, resolver=resolver))
        started = [e for e in subscriber.events if e.event_type == ExecutionEventType.TASK_STARTED][0]
        assert started.data["attempt"] == 0

    def test_task_started_has_task_type(self, event_bus, subscriber, engine, success_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(success_plan, resolver=resolver))
        started = [e for e in subscriber.events if e.event_type == ExecutionEventType.TASK_STARTED][0]
        assert started.data["task_type"] == TaskType.SEND_MESSAGE.value


class TestPipelineTaskCompleted:
    def test_task_completed_event(self, event_bus, subscriber, engine, success_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(success_plan, resolver=resolver))
        completed = [e for e in subscriber.events if e.event_type == ExecutionEventType.TASK_COMPLETED]
        assert len(completed) == 1
        assert completed[0].task_id == "t1"

    def test_completed_after_started(self, event_bus, subscriber, engine, success_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(success_plan, resolver=resolver))
        started = [e for e in subscriber.events if e.event_type == ExecutionEventType.TASK_STARTED][0]
        completed = [e for e in subscriber.events if e.event_type == ExecutionEventType.TASK_COMPLETED][0]
        assert started.sequence < completed.sequence

    def test_no_task_completed_on_failure(self, event_bus, subscriber, engine, perm_fail_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(perm_fail_plan, resolver=resolver))
        completed = [e for e in subscriber.events if e.event_type == ExecutionEventType.TASK_COMPLETED]
        assert len(completed) == 0


class TestPipelineTaskFailed:
    def test_task_failed_event(self, event_bus, subscriber, engine, perm_fail_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(perm_fail_plan, resolver=resolver))
        failed = [e for e in subscriber.events if e.event_type == ExecutionEventType.TASK_FAILED]
        assert len(failed) == 1
        assert failed[0].task_id == "t1"

    def test_task_failed_has_error(self, event_bus, subscriber, engine, perm_fail_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(perm_fail_plan, resolver=resolver))
        failed = [e for e in subscriber.events if e.event_type == ExecutionEventType.TASK_FAILED][0]
        assert "error" in failed.data
        assert "error_type" in failed.data

    def test_task_failed_error_type_permanent(self, event_bus, subscriber, engine, perm_fail_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(perm_fail_plan, resolver=resolver))
        failed = [e for e in subscriber.events if e.event_type == ExecutionEventType.TASK_FAILED][0]
        assert failed.data["error_type"] == "permanent"

    def test_no_task_failed_on_success(self, event_bus, subscriber, engine, success_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(success_plan, resolver=resolver))
        failed = [e for e in subscriber.events if e.event_type == ExecutionEventType.TASK_FAILED]
        assert len(failed) == 0


class TestPipelineSessionCompleted:
    def test_session_completed_on_success(self, event_bus, subscriber, engine, success_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(success_plan, resolver=resolver))
        completed = [e for e in subscriber.events if e.event_type == ExecutionEventType.SESSION_COMPLETED]
        assert len(completed) == 1

    def test_session_completed_last_event(self, event_bus, subscriber, engine, success_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(success_plan, resolver=resolver))
        completed = [e for e in subscriber.events if e.event_type == ExecutionEventType.SESSION_COMPLETED][0]
        last_event = subscriber.events[-1]
        assert last_event is completed

    def test_session_completed_status(self, event_bus, subscriber, engine, success_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(success_plan, resolver=resolver))
        completed = [e for e in subscriber.events if e.event_type == ExecutionEventType.SESSION_COMPLETED][0]
        assert completed.data["status"] == SessionState.COMPLETED.value

    def test_no_session_completed_on_failure(self, event_bus, subscriber, engine, perm_fail_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(perm_fail_plan, resolver=resolver))
        completed = [e for e in subscriber.events if e.event_type == ExecutionEventType.SESSION_COMPLETED]
        assert len(completed) == 0


class TestPipelineSessionFailed:
    def test_session_failed_on_perm_failure(self, event_bus, subscriber, engine, perm_fail_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(perm_fail_plan, resolver=resolver))
        failed = [e for e in subscriber.events if e.event_type == ExecutionEventType.SESSION_FAILED]
        assert len(failed) == 1

    def test_session_failed_status(self, event_bus, subscriber, engine, perm_fail_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(perm_fail_plan, resolver=resolver))
        failed = [e for e in subscriber.events if e.event_type == ExecutionEventType.SESSION_FAILED][0]
        assert failed.data["status"] != SessionState.COMPLETED.value

    def test_no_session_failed_on_success(self, event_bus, subscriber, engine, success_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(success_plan, resolver=resolver))
        failed = [e for e in subscriber.events if e.event_type == ExecutionEventType.SESSION_FAILED]
        assert len(failed) == 0

    def test_session_failed_is_last_event(self, event_bus, subscriber, engine, perm_fail_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(perm_fail_plan, resolver=resolver))
        failed = [e for e in subscriber.events if e.event_type == ExecutionEventType.SESSION_FAILED][0]
        assert subscriber.events[-1] is failed


class TestPipelineTaskSkipped:
    def test_task_skipped_on_upstream_failure(self, event_bus, subscriber, engine, resolver, perm_fail_adapter, success_adapter):
        plan = Plan(id="p", conversation_id="c", status=PlanStatus.VALIDATED, goal=PlanGoal(outcome="test"))
        plan.tasks = [
            Task(id="t1", plan_id=plan.id, type=TaskType.SEND_EMAIL, status=TaskStatus.PENDING, payload=MessagePayload(channel="g", template="a"), label="a"),
            Task(id="t2", plan_id=plan.id, type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING, payload=MessagePayload(channel="tg", template="b"), label="b", dependencies=["t1"]),
        ]
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(plan, resolver=resolver))
        events = [e for e in subscriber.events if e.event_type == ExecutionEventType.TASK_SKIPPED]
        assert len(events) == 1
        assert events[0].task_id == "t2"

    def test_no_task_skipped_without_dependencies(self, event_bus, subscriber, engine, perm_fail_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(perm_fail_plan, resolver=resolver))
        skipped = [e for e in subscriber.events if e.event_type == ExecutionEventType.TASK_SKIPPED]
        assert len(skipped) == 0


class TestPipelineTaskReady:
    def test_task_ready_before_task_started(self, event_bus, subscriber, engine, success_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(success_plan, resolver=resolver))
        ready = [e for e in subscriber.events if e.event_type == ExecutionEventType.TASK_READY]
        assert len(ready) == 1
        started = [e for e in subscriber.events if e.event_type == ExecutionEventType.TASK_STARTED][0]
        assert ready[0].sequence < started.sequence

    def test_task_ready_task_id(self, event_bus, subscriber, engine, success_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(success_plan, resolver=resolver))
        ready = [e for e in subscriber.events if e.event_type == ExecutionEventType.TASK_READY][0]
        assert ready.task_id == "t1"


class TestPipelineRetryScheduled:
    def test_retry_scheduled_on_transient(self, event_bus, subscriber, engine, resolver, transient_adapter):
        plan = Plan(id="p", conversation_id="c", status=PlanStatus.VALIDATED, goal=PlanGoal(outcome="test"))
        plan.tasks = [Task(id="t1", plan_id=plan.id, type=TaskType.UPDATE_CRM, status=TaskStatus.PENDING, payload=MessagePayload(channel="none", template="none"), label="x")]
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(plan, resolver=resolver))
        scheduled = [e for e in subscriber.events if e.event_type == ExecutionEventType.TASK_RETRY_SCHEDULED]
        assert len(scheduled) == 2  # max_attempts=3, so 2 retry schedules before exhaustion

    def test_retry_scheduled_data(self, event_bus, subscriber, engine, resolver, transient_adapter):
        plan = Plan(id="p", conversation_id="c", status=PlanStatus.VALIDATED, goal=PlanGoal(outcome="test"))
        plan.tasks = [Task(id="t1", plan_id=plan.id, type=TaskType.UPDATE_CRM, status=TaskStatus.PENDING, payload=MessagePayload(channel="none", template="none"), label="x")]
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(plan, resolver=resolver))
        scheduled = [e for e in subscriber.events if e.event_type == ExecutionEventType.TASK_RETRY_SCHEDULED]
        assert scheduled[0].data["remaining_attempts"] > 0
        assert "delay_seconds" in scheduled[0].data
        assert scheduled[0].task_id == "t1"

    def test_no_retry_scheduled_on_success(self, event_bus, subscriber, engine, success_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(success_plan, resolver=resolver))
        scheduled = [e for e in subscriber.events if e.event_type == ExecutionEventType.TASK_RETRY_SCHEDULED]
        assert len(scheduled) == 0

    def test_no_retry_scheduled_on_permanent(self, event_bus, subscriber, engine, perm_fail_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(perm_fail_plan, resolver=resolver))
        scheduled = [e for e in subscriber.events if e.event_type == ExecutionEventType.TASK_RETRY_SCHEDULED]
        assert len(scheduled) == 0


class TestPipelineRetryStarted:
    def test_retry_started_on_retry_execution(self, event_bus, subscriber, engine, resolver, transient_then_ok_adapter, transient_then_ok_plan):
        resolver._adapter_map[TaskType.ANALYZE_REPLY] = transient_then_ok_adapter
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(transient_then_ok_plan, resolver=resolver))
        retry_started = [e for e in subscriber.events if e.event_type == ExecutionEventType.TASK_RETRY_STARTED]
        assert len(retry_started) == 1

    def test_retry_started_has_attempt_gt_zero(self, event_bus, subscriber, engine, resolver, transient_then_ok_adapter, transient_then_ok_plan):
        resolver._adapter_map[TaskType.ANALYZE_REPLY] = transient_then_ok_adapter
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(transient_then_ok_plan, resolver=resolver))
        retry_started = [e for e in subscriber.events if e.event_type == ExecutionEventType.TASK_RETRY_STARTED][0]
        assert retry_started.data["attempt"] > 0

    def test_no_retry_started_on_first_execution(self, event_bus, subscriber, engine, success_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(success_plan, resolver=resolver))
        retry_started = [e for e in subscriber.events if e.event_type == ExecutionEventType.TASK_RETRY_STARTED]
        assert len(retry_started) == 0


class TestPipelineRetryExhausted:
    def test_retry_exhausted_on_exhaustion(self, event_bus, subscriber, engine, resolver, transient_adapter):
        plan = Plan(id="p", conversation_id="c", status=PlanStatus.VALIDATED, goal=PlanGoal(outcome="test"))
        plan.tasks = [Task(id="t1", plan_id=plan.id, type=TaskType.UPDATE_CRM, status=TaskStatus.PENDING, payload=MessagePayload(channel="none", template="none"), label="x")]
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(plan, resolver=resolver))
        exhausted = [e for e in subscriber.events if e.event_type == ExecutionEventType.TASK_RETRY_EXHAUSTED]
        assert len(exhausted) == 1
        assert exhausted[0].task_id == "t1"

    def test_retry_exhausted_only_on_exhaustion(self, event_bus, subscriber, engine, resolver, transient_then_ok_adapter, transient_then_ok_plan):
        resolver._adapter_map[TaskType.ANALYZE_REPLY] = transient_then_ok_adapter
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(transient_then_ok_plan, resolver=resolver))
        exhausted = [e for e in subscriber.events if e.event_type == ExecutionEventType.TASK_RETRY_EXHAUSTED]
        assert len(exhausted) == 0

    def test_retry_exhausted_not_on_perm_failure_first_attempt(self, event_bus, subscriber, engine, perm_fail_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(perm_fail_plan, resolver=resolver))
        exhausted = [e for e in subscriber.events if e.event_type == ExecutionEventType.TASK_RETRY_EXHAUSTED]
        assert len(exhausted) == 0


class TestPipelineEventFlow:
    def test_full_success_event_flow(self, event_bus, subscriber, engine, success_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(success_plan, resolver=resolver))
        types = [e.event_type for e in subscriber.events]
        assert ExecutionEventType.SESSION_STARTED in types
        assert ExecutionEventType.TASK_READY in types
        assert ExecutionEventType.TASK_STARTED in types
        assert ExecutionEventType.TASK_COMPLETED in types
        assert ExecutionEventType.SESSION_COMPLETED in types

    def test_full_failure_event_flow(self, event_bus, subscriber, engine, perm_fail_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(perm_fail_plan, resolver=resolver))
        types = [e.event_type for e in subscriber.events]
        assert ExecutionEventType.SESSION_STARTED in types
        assert ExecutionEventType.TASK_READY in types
        assert ExecutionEventType.TASK_STARTED in types
        assert ExecutionEventType.TASK_FAILED in types
        assert ExecutionEventType.SESSION_FAILED in types

    def test_full_retry_exhaustion_event_flow(self, event_bus, subscriber, engine, resolver, transient_adapter):
        plan = Plan(id="p", conversation_id="c", status=PlanStatus.VALIDATED, goal=PlanGoal(outcome="test"))
        plan.tasks = [Task(id="t1", plan_id=plan.id, type=TaskType.UPDATE_CRM, status=TaskStatus.PENDING, payload=MessagePayload(channel="none", template="none"), label="x")]
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(plan, resolver=resolver))
        types = [e.event_type for e in subscriber.events]
        assert ExecutionEventType.TASK_RETRY_SCHEDULED in types
        assert ExecutionEventType.TASK_RETRY_STARTED in types
        assert ExecutionEventType.TASK_RETRY_EXHAUSTED in types
        assert ExecutionEventType.TASK_FAILED in types
        assert ExecutionEventType.SESSION_FAILED in types

    def test_full_retry_success_event_flow(self, event_bus, subscriber, engine, resolver, transient_then_ok_adapter, transient_then_ok_plan):
        resolver._adapter_map[TaskType.ANALYZE_REPLY] = transient_then_ok_adapter
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(transient_then_ok_plan, resolver=resolver))
        types = [e.event_type for e in subscriber.events]
        assert ExecutionEventType.TASK_RETRY_SCHEDULED in types
        assert ExecutionEventType.TASK_RETRY_STARTED in types
        assert ExecutionEventType.TASK_COMPLETED in types
        assert ExecutionEventType.SESSION_COMPLETED in types

    def test_event_order_success(self, event_bus, subscriber, engine, success_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(success_plan, resolver=resolver))
        ordered = [e.event_type for e in subscriber.events]
        si = ordered.index(ExecutionEventType.SESSION_STARTED)
        ti = ordered.index(ExecutionEventType.TASK_READY)
        si2 = ordered.index(ExecutionEventType.TASK_STARTED)
        ci = ordered.index(ExecutionEventType.TASK_COMPLETED)
        sci = ordered.index(ExecutionEventType.SESSION_COMPLETED)
        assert si < ti < si2 < ci < sci

    def test_event_order_failure(self, event_bus, subscriber, engine, perm_fail_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(perm_fail_plan, resolver=resolver))
        ordered = [e.event_type for e in subscriber.events]
        si = ordered.index(ExecutionEventType.SESSION_STARTED)
        ti = ordered.index(ExecutionEventType.TASK_READY)
        si2 = ordered.index(ExecutionEventType.TASK_STARTED)
        fi = ordered.index(ExecutionEventType.TASK_FAILED)
        sfi = ordered.index(ExecutionEventType.SESSION_FAILED)
        assert si < ti < si2 < fi < sfi


class TestPipelineMultipleTasks:
    def test_two_independent_tasks(self, event_bus, subscriber, engine, multi_task_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(multi_task_plan, resolver=resolver))
        task_started = [e for e in subscriber.events if e.event_type == ExecutionEventType.TASK_STARTED]
        assert len(task_started) == 2
        task_completed = [e for e in subscriber.events if e.event_type == ExecutionEventType.TASK_COMPLETED]
        assert len(task_completed) == 2

    def test_dag_chain_events(self, event_bus, subscriber, engine, dag_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(dag_plan, resolver=resolver))
        task_completed = [e for e in subscriber.events if e.event_type == ExecutionEventType.TASK_COMPLETED]
        assert len(task_completed) == 2
        # t1 completes before t2 starts
        t1_complete = [e for e in subscriber.events if e.event_type == ExecutionEventType.TASK_COMPLETED and e.task_id == "t1"][0]
        t2_started = [e for e in subscriber.events if e.event_type == ExecutionEventType.TASK_STARTED and e.task_id == "t2"][0]
        assert t1_complete.sequence < t2_started.sequence


class TestPipelineSubscriberIsolation:
    def test_failing_subscriber_does_not_break_pipeline(self, event_bus, engine, success_plan, resolver):
        event_bus.subscribe(FailingSubscriber())
        session = asyncio.run(engine.execute(success_plan, resolver=resolver))
        assert session.status == SessionState.COMPLETED

    def test_failing_subscriber_does_not_break_retry(self, event_bus, engine, resolver, transient_then_ok_adapter, transient_then_ok_plan):
        resolver._adapter_map[TaskType.ANALYZE_REPLY] = transient_then_ok_adapter
        event_bus.subscribe(FailingSubscriber())
        session = asyncio.run(engine.execute(transient_then_ok_plan, resolver=resolver))
        assert session.status == SessionState.COMPLETED

    def test_failing_subscriber_does_not_break_exhaustion(self, event_bus, engine, resolver, transient_adapter):
        plan = Plan(id="p", conversation_id="c", status=PlanStatus.VALIDATED, goal=PlanGoal(outcome="test"))
        plan.tasks = [Task(id="t1", plan_id=plan.id, type=TaskType.UPDATE_CRM, status=TaskStatus.PENDING, payload=MessagePayload(channel="none", template="none"), label="x")]
        event_bus.subscribe(FailingSubscriber())
        session = asyncio.run(engine.execute(plan, resolver=resolver))
        assert session.status == SessionState.FAILED

    def test_multiple_subscribers_one_fails_execution_continues(self, event_bus, engine, success_plan, resolver):
        good = CollectingSubscriber()
        event_bus.subscribe(good)
        event_bus.subscribe(FailingSubscriber())
        session = asyncio.run(engine.execute(success_plan, resolver=resolver))
        assert session.status == SessionState.COMPLETED
        assert len(good.events) > 0


class TestPipelineCancelEvents:
    def test_cancel_publishes_task_cancelled(self, event_bus, subscriber, engine):
        # Manually inject a RUNNING session so cancel() succeeds
        session = ExecutionSession(id="s1", plan_id="p1", status=SessionState.RUNNING)
        engine._sessions["s1"] = session
        task = ExecutionTask(id="t1", plan_task=Task(id="t1", plan_id="p1", type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING), status=TaskState.RUNNING)
        session.tasks["t1"] = task
        event_bus.subscribe(subscriber)
        engine.cancel("s1")
        cancelled = [e for e in subscriber.events if e.event_type == ExecutionEventType.TASK_CANCELLED]
        assert len(cancelled) == 1

    def test_cancel_publishes_session_cancelled(self, event_bus, subscriber, engine):
        session = ExecutionSession(id="s1", plan_id="p1", status=SessionState.RUNNING)
        engine._sessions["s1"] = session
        task = ExecutionTask(id="t1", plan_task=Task(id="t1", plan_id="p1", type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING), status=TaskState.RUNNING)
        session.tasks["t1"] = task
        event_bus.subscribe(subscriber)
        engine.cancel("s1")
        cancelled = [e for e in subscriber.events if e.event_type == ExecutionEventType.SESSION_CANCELLED]
        assert len(cancelled) == 1


class TestPipelineRejectEvents:
    def test_reject_publishes_task_skipped(self, event_bus, subscriber, engine):
        session = ExecutionSession(id="s1", plan_id="p1", status=SessionState.RUNNING)
        engine._sessions["s1"] = session
        task = ExecutionTask(id="t1", plan_task=Task(id="t1", plan_id="p1", type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING), status=TaskState.WAITING_APPROVAL)
        session.tasks["t1"] = task
        event_bus.subscribe(subscriber)
        engine.reject("s1", "t1")
        skipped = [e for e in subscriber.events if e.event_type == ExecutionEventType.TASK_SKIPPED]
        assert len(skipped) == 1
        assert skipped[0].task_id == "t1"


# ===================================================================
# EVENT BUS DATACLASS TESTS
# ===================================================================

class TestExecutionEventDefaults:
    def test_event_default_id_generated(self):
        event = ExecutionEvent(event_type=ExecutionEventType.SESSION_STARTED, session_id="s1")
        assert len(event.id) == 12

    def test_event_default_timestamp(self):
        event = ExecutionEvent(event_type=ExecutionEventType.SESSION_STARTED, session_id="s1")
        assert event.timestamp is not None

    def test_event_default_task_id_none(self):
        event = ExecutionEvent(event_type=ExecutionEventType.SESSION_STARTED, session_id="s1")
        assert event.task_id is None

    def test_event_default_data_empty(self):
        event = ExecutionEvent(event_type=ExecutionEventType.SESSION_STARTED, session_id="s1")
        assert event.data == {}

    def test_event_sequence_default_zero(self):
        event = ExecutionEvent(event_type=ExecutionEventType.SESSION_STARTED, session_id="s1")
        assert event.sequence == 0


# ===================================================================
# EXECUTION PIPELINE EVENT TYPE COVERAGE
# ===================================================================

class TestAllEventTypesProduced:
    def test_session_started_produced(self, event_bus, subscriber, engine, success_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(success_plan, resolver=resolver))
        assert any(e.event_type == ExecutionEventType.SESSION_STARTED for e in subscriber.events)

    def test_session_completed_produced(self, event_bus, subscriber, engine, success_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(success_plan, resolver=resolver))
        assert any(e.event_type == ExecutionEventType.SESSION_COMPLETED for e in subscriber.events)

    def test_session_failed_produced(self, event_bus, subscriber, engine, perm_fail_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(perm_fail_plan, resolver=resolver))
        assert any(e.event_type == ExecutionEventType.SESSION_FAILED for e in subscriber.events)

    def test_session_cancelled_produced(self, event_bus, subscriber, engine):
        session = ExecutionSession(id="s1", plan_id="p1", status=SessionState.RUNNING)
        engine._sessions["s1"] = session
        task = ExecutionTask(id="t1", plan_task=Task(id="t1", plan_id="p1", type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING), status=TaskState.RUNNING)
        session.tasks["t1"] = task
        event_bus.subscribe(subscriber)
        engine.cancel("s1")
        assert any(e.event_type == ExecutionEventType.SESSION_CANCELLED for e in subscriber.events)

    def test_task_ready_produced(self, event_bus, subscriber, engine, success_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(success_plan, resolver=resolver))
        assert any(e.event_type == ExecutionEventType.TASK_READY for e in subscriber.events)

    def test_task_started_produced(self, event_bus, subscriber, engine, success_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(success_plan, resolver=resolver))
        assert any(e.event_type == ExecutionEventType.TASK_STARTED for e in subscriber.events)

    def test_task_completed_produced(self, event_bus, subscriber, engine, success_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(success_plan, resolver=resolver))
        assert any(e.event_type == ExecutionEventType.TASK_COMPLETED for e in subscriber.events)

    def test_task_failed_produced(self, event_bus, subscriber, engine, perm_fail_plan, resolver):
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(perm_fail_plan, resolver=resolver))
        assert any(e.event_type == ExecutionEventType.TASK_FAILED for e in subscriber.events)

    def test_task_skipped_produced(self, event_bus, subscriber, engine, resolver):
        plan = Plan(id="p", conversation_id="c", status=PlanStatus.VALIDATED, goal=PlanGoal(outcome="test"))
        plan.tasks = [
            Task(id="t1", plan_id=plan.id, type=TaskType.SEND_EMAIL, status=TaskStatus.PENDING, payload=MessagePayload(channel="g", template="a"), label="a"),
            Task(id="t2", plan_id=plan.id, type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING, payload=MessagePayload(channel="tg", template="b"), label="b", dependencies=["t1"]),
        ]
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(plan, resolver=resolver))
        assert any(e.event_type == ExecutionEventType.TASK_SKIPPED for e in subscriber.events)

    def test_task_retry_scheduled_produced(self, event_bus, subscriber, engine, resolver, transient_adapter):
        plan = Plan(id="p", conversation_id="c", status=PlanStatus.VALIDATED, goal=PlanGoal(outcome="test"))
        plan.tasks = [Task(id="t1", plan_id=plan.id, type=TaskType.UPDATE_CRM, status=TaskStatus.PENDING, payload=MessagePayload(channel="none", template="none"), label="x")]
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(plan, resolver=resolver))
        assert any(e.event_type == ExecutionEventType.TASK_RETRY_SCHEDULED for e in subscriber.events)

    def test_task_retry_started_produced(self, event_bus, subscriber, engine, resolver, transient_adapter):
        plan = Plan(id="p", conversation_id="c", status=PlanStatus.VALIDATED, goal=PlanGoal(outcome="test"))
        plan.tasks = [Task(id="t1", plan_id=plan.id, type=TaskType.UPDATE_CRM, status=TaskStatus.PENDING, payload=MessagePayload(channel="none", template="none"), label="x")]
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(plan, resolver=resolver))
        assert any(e.event_type == ExecutionEventType.TASK_RETRY_STARTED for e in subscriber.events)

    def test_task_retry_exhausted_produced(self, event_bus, subscriber, engine, resolver, transient_adapter):
        plan = Plan(id="p", conversation_id="c", status=PlanStatus.VALIDATED, goal=PlanGoal(outcome="test"))
        plan.tasks = [Task(id="t1", plan_id=plan.id, type=TaskType.UPDATE_CRM, status=TaskStatus.PENDING, payload=MessagePayload(channel="none", template="none"), label="x")]
        event_bus.subscribe(subscriber)
        asyncio.run(engine.execute(plan, resolver=resolver))
        assert any(e.event_type == ExecutionEventType.TASK_RETRY_EXHAUSTED for e in subscriber.events)

    def test_task_skipped_via_reject_produced(self, event_bus, subscriber, engine):
        session = ExecutionSession(id="s1", plan_id="p1", status=SessionState.RUNNING)
        engine._sessions["s1"] = session
        task = ExecutionTask(id="t1", plan_task=Task(id="t1", plan_id="p1", type=TaskType.SEND_MESSAGE, status=TaskStatus.PENDING), status=TaskState.WAITING_APPROVAL)
        session.tasks["t1"] = task
        event_bus.subscribe(subscriber)
        engine.reject("s1", "t1")
        assert any(e.event_type == ExecutionEventType.TASK_SKIPPED for e in subscriber.events)
