"""Integration tests for the BookingStrategy — Phase 8b.

Tests that the strategy produces a heterogeneous Plan with
CALENDAR_CREATE_EVENT + SEND_EMAIL and that the Plan executes
correctly through the existing ExecutionEngine.

Relies on the existing AdapterRegistry with Gmail and Calendar
BridgeAdapters being registered (as in main.py), or on test-double
equivalents.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from services.adapters.adapter_context import AdapterContext
from services.adapters.models import AdapterMetadata, AdapterResult, UsageInfo
from services.adapters.google.gmail import GmailAdapter
from services.adapters.google.calendar import CalendarAdapter

from services.execution import (
    AdapterRegistry,
    AdapterRegistryResolver,
    BridgeAdapter,
    ExecutionEngine,
)
from services.execution.enums import SessionState, TaskState

from services.planner.planning_models import (
    Plan,
    PlanGoal,
    PlanStatus,
    Task,
    TaskStatus,
    TaskType,
)
from services.planner.payloads import (
    CreateEventPayload,
    MessagePayload,
)
from services.planner.strategies.planning_registry import (
    ensure_default_strategies_registered,
    select_strategy,
    list_strategies,
)
from services.planner.strategies.booking import BookingStrategy


# =========================================================================
# Fake Google API adapter
# =========================================================================


class FakeGoogleApiAdapter:
    def __init__(self) -> None:
        self._responses: dict[str, AdapterResult] = {}
        self.executed_requests: list[AdapterContext] = []

    def add_response(self, resource: str, result: AdapterResult) -> None:
        self._responses[resource] = result

    @property
    def metadata(self) -> AdapterMetadata:
        return AdapterMetadata(name="google_api", display_name="", version="1")

    async def execute(self, context: AdapterContext) -> AdapterResult:
        self.executed_requests.append(context)
        resource = context.params.get("resource", "")
        response = self._responses.get(resource)
        if response is not None:
            return response
        return AdapterResult.failure_result(
            error=f"No canned response for {resource!r}",
            metadata={"error_type": "GoogleApiError"},
        )


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture(autouse=True, scope="module")
def _ensure_strategies():
    """Ensure default strategies (including booking) are registered."""
    ensure_default_strategies_registered()


@pytest.fixture
def booking_goal() -> PlanGoal:
    return PlanGoal(
        outcome="Schedule an event and notify the attendee",
        target_action="schedule_event",
    )


@pytest.fixture
def booking_context() -> dict[str, Any]:
    return {
        "summary": "Product Demo",
        "start_time": "2026-02-01T14:00:00",
        "end_time": "2026-02-01T15:00:00",
        "attendee_email": "john@example.com",
        "description": "Demo of the platform",
        "location": "Virtual",
        "timezone": "America/New_York",
    }


@pytest.fixture
def fake_success() -> FakeGoogleApiAdapter:
    f = FakeGoogleApiAdapter()
    f.add_response(
        "calendars/primary/events",
        AdapterResult(
            success=True,
            data={
                "json": {
                    "id": "evt_demo",
                    "summary": "Product Demo",
                    "htmlLink": "https://calendar.google.com/event?eid=evt_demo",
                    "start": {"dateTime": "2026-02-01T14:00:00", "timeZone": "America/New_York"},
                    "end": {"dateTime": "2026-02-01T15:00:00", "timeZone": "America/New_York"},
                    "status": "confirmed",
                },
                "status_code": 200,
                "body": json.dumps({"id": "evt_demo"}),
            },
            metadata={},
            usage=UsageInfo(api_calls=1, latency_ms=60.0),
        ),
    )
    f.add_response(
        "users/me/messages/send",
        AdapterResult(
            success=True,
            data={
                "json": {"id": "msg_notify", "threadId": "th_notify"},
                "status_code": 200,
                "body": json.dumps({"id": "msg_notify", "threadId": "th_notify"}),
            },
            metadata={},
            usage=UsageInfo(api_calls=1, latency_ms=45.0),
        ),
    )
    return f


@pytest.fixture
def fake_calendar_fails() -> FakeGoogleApiAdapter:
    f = FakeGoogleApiAdapter()
    f.add_response(
        "calendars/primary/events",
        AdapterResult(
            success=False,
            data={"status_code": 400, "body": '{"error":{"message":"Invalid event data"}}'},
            metadata={"error_type": "HttpStatusError"},
            error="HTTP 400",
        ),
    )
    f.add_response(
        "users/me/messages/send",
        AdapterResult(
            success=True,
            data={
                "json": {"id": "msg_orphan", "threadId": "th_orphan"},
                "status_code": 200,
                "body": json.dumps({"id": "msg_orphan", "threadId": "th_orphan"}),
            },
            metadata={},
            usage=UsageInfo(api_calls=1, latency_ms=45.0),
        ),
    )
    return f


@pytest.fixture
def engine() -> ExecutionEngine:
    from services.execution.logging_subscriber import LoggingSubscriber
    eng = ExecutionEngine()
    eng.event_bus.subscribe(LoggingSubscriber())
    return eng


@pytest.fixture
def registry_with_bridges(
    fake_success: FakeGoogleApiAdapter,
) -> AdapterRegistry:
    registry = AdapterRegistry()

    calendar = CalendarAdapter(google_adapter=fake_success)  # type: ignore[arg-type]
    registry.register(
        BridgeAdapter(
            sdk_adapter=calendar,
            action_mapping={TaskType.CALENDAR_CREATE_EVENT: "calendar_create_event"},
            credentials={"access_token": "cal_tok", "token_type": "Bearer"},
        ),
        priority=100,
        version="1.0.0",
    )

    gmail = GmailAdapter(google_adapter=fake_success)  # type: ignore[arg-type]
    registry.register(
        BridgeAdapter(
            sdk_adapter=gmail,
            action_mapping={TaskType.SEND_EMAIL: "gmail_send_email"},
            credentials={"access_token": "gmail_tok", "token_type": "Bearer"},
        ),
        priority=100,
        version="1.0.0",
    )

    return registry


# =========================================================================
# Strategy selection tests
# =========================================================================


class TestBookingStrategySelection:
    def test_strategy_registered(self) -> None:
        strategies = list_strategies()
        assert "booking" in strategies

    def test_selected_for_schedule_event(self) -> None:
        goal = PlanGoal(target_action="schedule_event")
        strategy = select_strategy(goal)
        assert strategy is not None
        assert strategy.name == "booking"

    def test_selected_for_create_calendar_event(self) -> None:
        goal = PlanGoal(target_action="create_calendar_event")
        strategy = select_strategy(goal)
        assert strategy is not None
        assert strategy.name == "booking"

    def test_not_selected_for_unrelated(self) -> None:
        goal = PlanGoal(target_action="cold_outreach")
        strategy = select_strategy(goal)
        assert strategy is not None
        assert strategy.name != "booking"


# =========================================================================
# Task generation tests
# =========================================================================


class TestBookingStrategyTaskGeneration:
    def test_generates_two_tasks(
        self,
        booking_goal: PlanGoal,
        booking_context: dict[str, Any],
    ) -> None:
        strategy = BookingStrategy()
        tasks = strategy.generate_tasks(booking_goal, booking_context)
        assert len(tasks) == 2

    def test_first_task_is_calendar_create(
        self,
        booking_goal: PlanGoal,
        booking_context: dict[str, Any],
    ) -> None:
        strategy = BookingStrategy()
        tasks = strategy.generate_tasks(booking_goal, booking_context)
        assert tasks[0].type == TaskType.CALENDAR_CREATE_EVENT

    def test_second_task_is_send_email(
        self,
        booking_goal: PlanGoal,
        booking_context: dict[str, Any],
    ) -> None:
        strategy = BookingStrategy()
        tasks = strategy.generate_tasks(booking_goal, booking_context)
        assert tasks[1].type == TaskType.SEND_EMAIL

    def test_calendar_payload_has_summary(
        self,
        booking_goal: PlanGoal,
        booking_context: dict[str, Any],
    ) -> None:
        strategy = BookingStrategy()
        tasks = strategy.generate_tasks(booking_goal, booking_context)
        payload = tasks[0].get_payload()
        assert isinstance(payload, CreateEventPayload)
        assert payload.summary == "Product Demo"

    def test_email_payload_is_message(
        self,
        booking_goal: PlanGoal,
        booking_context: dict[str, Any],
    ) -> None:
        strategy = BookingStrategy()
        tasks = strategy.generate_tasks(booking_goal, booking_context)
        payload = tasks[1].get_payload()
        assert isinstance(payload, MessagePayload)
        assert payload.channel == "email"

    def test_email_params_have_to_subject_body(
        self,
        booking_goal: PlanGoal,
        booking_context: dict[str, Any],
    ) -> None:
        strategy = BookingStrategy()
        tasks = strategy.generate_tasks(booking_goal, booking_context)
        params = tasks[1].params
        assert params.get("to") == ["john@example.com"]
        assert "Meeting Confirmed" in params.get("subject", "")
        assert "scheduled" in params.get("body_plain", "")

    def test_tasks_have_reasoning_trace(
        self,
        booking_goal: PlanGoal,
        booking_context: dict[str, Any],
    ) -> None:
        strategy = BookingStrategy()
        tasks = strategy.generate_tasks(booking_goal, booking_context)
        for t in tasks:
            assert t.reasoning_trace, f"Task '{t.label}' missing reasoning_trace"

    def test_tasks_have_reasoning_goal(
        self,
        booking_goal: PlanGoal,
        booking_context: dict[str, Any],
    ) -> None:
        strategy = BookingStrategy()
        tasks = strategy.generate_tasks(booking_goal, booking_context)
        for t in tasks:
            assert t.reasoning_goal == "schedule_event"


# =========================================================================
# Dependency tests
# =========================================================================


class TestBookingStrategyDependencies:
    def test_email_depends_on_calendar(
        self,
        booking_goal: PlanGoal,
        booking_context: dict[str, Any],
    ) -> None:
        strategy = BookingStrategy()
        tasks = strategy.generate_tasks(booking_goal, booking_context)
        deps = strategy.dependencies(tasks)
        assert len(deps) == 1
        src, tgt = deps[0]
        assert src == "booking_create_event"
        assert tgt == "booking_send_notification"

    def test_email_task_has_dependency(
        self,
        booking_goal: PlanGoal,
        booking_context: dict[str, Any],
    ) -> None:
        strategy = BookingStrategy()
        tasks = strategy.generate_tasks(booking_goal, booking_context)
        deps = strategy.dependencies(tasks)
        assert len(deps) == 1
        src, tgt = deps[0]
        assert src == "booking_create_event"
        assert tgt == "booking_send_notification"

    def test_calendar_task_has_no_deps(
        self,
        booking_goal: PlanGoal,
        booking_context: dict[str, Any],
    ) -> None:
        strategy = BookingStrategy()
        tasks = strategy.generate_tasks(booking_goal, booking_context)
        cal_task = tasks[0]
        assert cal_task.dependencies == []


# =========================================================================
# Execution tests (via PlanningPipeline → ExecutionEngine)
# =========================================================================


class TestBookingStrategyExecution:
    def test_both_tasks_execute_successfully(
        self,
        booking_goal: PlanGoal,
        booking_context: dict[str, Any],
        registry_with_bridges: AdapterRegistry,
        engine: ExecutionEngine,
    ) -> None:
        strategy = BookingStrategy()
        tasks = strategy.generate_tasks(booking_goal, booking_context)
        deps = strategy.dependencies(tasks)
        for src, tgt in deps:
            tgt_task = next(t for t in tasks if t.id == tgt)
            tgt_task.dependencies.append(src)

        plan = Plan(
            id="booking-plan-exec",
            conversation_id="conv-booking",
            status=PlanStatus.VALIDATED,
            goal=booking_goal,
            strategy="booking",
            tasks=tasks,
        )

        resolver = AdapterRegistryResolver(registry_with_bridges)
        session = asyncio.run(engine.execute(plan, resolver=resolver))

        assert session.status == SessionState.COMPLETED
        assert session.tasks["booking_create_event"].status == TaskState.COMPLETED
        assert session.tasks["booking_send_notification"].status == TaskState.COMPLETED

    def test_calendar_executes_first(
        self,
        booking_goal: PlanGoal,
        booking_context: dict[str, Any],
        registry_with_bridges: AdapterRegistry,
        engine: ExecutionEngine,
        fake_success: FakeGoogleApiAdapter,
    ) -> None:
        strategy = BookingStrategy()
        tasks = strategy.generate_tasks(booking_goal, booking_context)
        deps = strategy.dependencies(tasks)
        for src, tgt in deps:
            tgt_task = next(t for t in tasks if t.id == tgt)
            tgt_task.dependencies.append(src)

        plan = Plan(
            id="booking-plan-order",
            conversation_id="conv-booking",
            status=PlanStatus.VALIDATED,
            goal=booking_goal,
            strategy="booking",
            tasks=tasks,
        )

        resolver = AdapterRegistryResolver(registry_with_bridges)
        session = asyncio.run(engine.execute(plan, resolver=resolver))

        cal_idx = next(
            i for i, r in enumerate(fake_success.executed_requests)
            if "calendars/" in r.params.get("resource", "")
        )
        mail_idx = next(
            i for i, r in enumerate(fake_success.executed_requests)
            if "users/" in r.params.get("resource", "")
        )
        assert cal_idx < mail_idx, "Calendar must execute before email"

    def test_calendar_result_has_event_id(
        self,
        booking_goal: PlanGoal,
        booking_context: dict[str, Any],
        registry_with_bridges: AdapterRegistry,
        engine: ExecutionEngine,
    ) -> None:
        strategy = BookingStrategy()
        tasks = strategy.generate_tasks(booking_goal, booking_context)
        deps = strategy.dependencies(tasks)
        for src, tgt in deps:
            tgt_task = next(t for t in tasks if t.id == tgt)
            tgt_task.dependencies.append(src)

        plan = Plan(
            id="booking-plan-result",
            conversation_id="conv-booking",
            status=PlanStatus.VALIDATED,
            goal=booking_goal,
            strategy="booking",
            tasks=tasks,
        )

        resolver = AdapterRegistryResolver(registry_with_bridges)
        session = asyncio.run(engine.execute(plan, resolver=resolver))

        cal_task = session.tasks["booking_create_event"]
        assert cal_task.result is not None
        assert cal_task.result.success is True
        assert cal_task.result.output.get("id") == "evt_demo"

    def test_email_result_has_message_id(
        self,
        booking_goal: PlanGoal,
        booking_context: dict[str, Any],
        registry_with_bridges: AdapterRegistry,
        engine: ExecutionEngine,
    ) -> None:
        strategy = BookingStrategy()
        tasks = strategy.generate_tasks(booking_goal, booking_context)
        deps = strategy.dependencies(tasks)
        for src, tgt in deps:
            tgt_task = next(t for t in tasks if t.id == tgt)
            tgt_task.dependencies.append(src)

        plan = Plan(
            id="booking-plan-msg",
            conversation_id="conv-booking",
            status=PlanStatus.VALIDATED,
            goal=booking_goal,
            strategy="booking",
            tasks=tasks,
        )

        resolver = AdapterRegistryResolver(registry_with_bridges)
        session = asyncio.run(engine.execute(plan, resolver=resolver))

        email_task = session.tasks["booking_send_notification"]
        assert email_task.result is not None
        assert email_task.result.success is True
        assert email_task.result.output.get("id") == "msg_notify"

    def test_calendar_failure_skips_email(
        self,
        booking_goal: PlanGoal,
        booking_context: dict[str, Any],
        engine: ExecutionEngine,
    ) -> None:
        fake = FakeGoogleApiAdapter()
        fake.add_response(
            "calendars/primary/events",
            AdapterResult(
                success=False,
                data={"status_code": 400, "body": '{"error":{"message":"Bad request"}}'},
                metadata={"error_type": "HttpStatusError"},
                error="HTTP 400",
            ),
        )
        fake.add_response(
            "users/me/messages/send",
            AdapterResult(
                success=True,
                data={
                    "json": {"id": "msg_orphan", "threadId": "th_orphan"},
                    "status_code": 200,
                },
                metadata={},
                usage=UsageInfo(api_calls=1, latency_ms=45.0),
            ),
        )

        registry = AdapterRegistry()

        calendar = CalendarAdapter(google_adapter=fake)  # type: ignore[arg-type]
        registry.register(
            BridgeAdapter(
                sdk_adapter=calendar,
                action_mapping={TaskType.CALENDAR_CREATE_EVENT: "calendar_create_event"},
                credentials={"access_token": "tok", "token_type": "Bearer"},
            ),
            priority=100,
        )

        gmail = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        registry.register(
            BridgeAdapter(
                sdk_adapter=gmail,
                action_mapping={TaskType.SEND_EMAIL: "gmail_send_email"},
                credentials={"access_token": "tok", "token_type": "Bearer"},
            ),
            priority=100,
        )

        strategy = BookingStrategy()
        tasks = strategy.generate_tasks(booking_goal, booking_context)
        deps = strategy.dependencies(tasks)
        for src, tgt in deps:
            tgt_task = next(t for t in tasks if t.id == tgt)
            tgt_task.dependencies.append(src)

        plan = Plan(
            id="booking-plan-fail",
            conversation_id="conv-booking",
            status=PlanStatus.VALIDATED,
            goal=booking_goal,
            strategy="booking",
            tasks=tasks,
        )

        resolver = AdapterRegistryResolver(registry)
        session = asyncio.run(engine.execute(plan, resolver=resolver))

        assert session.tasks["booking_create_event"].status == TaskState.FAILED
        assert session.tasks["booking_send_notification"].status in (
            TaskState.SKIPPED, TaskState.BLOCKED,
        )

    def test_timing_populated(
        self,
        booking_goal: PlanGoal,
        booking_context: dict[str, Any],
        registry_with_bridges: AdapterRegistry,
        engine: ExecutionEngine,
    ) -> None:
        strategy = BookingStrategy()
        tasks = strategy.generate_tasks(booking_goal, booking_context)
        deps = strategy.dependencies(tasks)
        for src, tgt in deps:
            tgt_task = next(t for t in tasks if t.id == tgt)
            tgt_task.dependencies.append(src)

        plan = Plan(
            id="booking-plan-timing",
            conversation_id="conv-booking",
            status=PlanStatus.VALIDATED,
            goal=booking_goal,
            strategy="booking",
            tasks=tasks,
        )

        resolver = AdapterRegistryResolver(registry_with_bridges)
        session = asyncio.run(engine.execute(plan, resolver=resolver))

        assert session.end_time is not None
        for task in session.tasks.values():
            assert task.result is not None
            assert task.result.started_at is not None
            assert task.result.completed_at is not None
            assert task.result.duration_ms is not None


class TestBookingStrategyScheduling:
    def test_scheduling_hints_returned(
        self,
    ) -> None:
        strategy = BookingStrategy()
        hints = strategy.scheduling(PlanGoal(target_action="schedule_event"))
        assert hints.business_hours_only is True
        assert hints.min_delay_between_tasks == 0

    def test_approval_rules_returned(
        self,
    ) -> None:
        strategy = BookingStrategy()
        rules = strategy.approval_rules([])
        assert len(rules) == 1
        assert rules[0].task_type == TaskType.SEND_EMAIL
