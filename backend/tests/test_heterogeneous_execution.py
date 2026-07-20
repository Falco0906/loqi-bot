"""Heterogeneous multi-task execution test — Phase 8a.

Proves that the execution platform can orchestrate *multiple adapter types*
within a single Plan in a single execution session.

Architecture under test:

    Plan (CALENDAR_CREATE_EVENT + SEND_EMAIL)
    → ExecutionEngine.execute(plan, resolver=AdapterRegistryResolver)
    → Dispatcher → AdapterRegistryResolver → AdapterRegistry
    → BridgeAdapter (Calendar) / BridgeAdapter (Gmail)
    → CalendarAdapter / GmailAdapter
    → FakeGoogleApiAdapter (canned HTTP responses)

No planner, conversation engine, or strategy selection is involved.
All execution reuses shipping infrastructure.
"""

from __future__ import annotations

import asyncio
import json
from typing import Optional

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
    ExecutionSession,
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


# =========================================================================
# Fake Google API adapter — shared between Gmail and Calendar adapters
# =========================================================================


class FakeGoogleApiAdapter:
    """Simulates GoogleApiAdapter with canned responses keyed by resource."""

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


class FakeSuccessApiAdapter(FakeGoogleApiAdapter):
    """Pre-configured with success responses for both Gmail and Calendar."""

    def __init__(self) -> None:
        super().__init__()
        self._setup_defaults()

    def _setup_defaults(self) -> None:
        # Gmail: send
        self.add_response(
            "users/me/messages/send",
            AdapterResult(
                success=True,
                data={
                    "json": {"id": "msg_abc", "threadId": "th_abc"},
                    "status_code": 200,
                    "body": json.dumps({"id": "msg_abc", "threadId": "th_abc"}),
                },
                metadata={},
                usage=UsageInfo(api_calls=1, latency_ms=45.0),
            ),
        )
        # Calendar: create event
        self.add_response(
            "calendars/primary/events",
            AdapterResult(
                success=True,
                data={
                    "json": {
                        "id": "evt_xyz",
                        "summary": "Team Standup",
                        "htmlLink": "https://calendar.google.com/event?eid=evt_xyz",
                        "start": {"dateTime": "2026-01-01T10:00:00", "timeZone": "UTC"},
                        "end": {"dateTime": "2026-01-01T11:00:00", "timeZone": "UTC"},
                        "status": "confirmed",
                    },
                    "status_code": 200,
                    "body": json.dumps({"id": "evt_xyz"}),
                },
                metadata={},
                usage=UsageInfo(api_calls=1, latency_ms=60.0),
            ),
        )


def _make_execution_engine() -> ExecutionEngine:
    """Create a fresh engine with no prior state."""
    from services.execution.logging_subscriber import LoggingSubscriber

    engine = ExecutionEngine()
    engine.event_bus.subscribe(LoggingSubscriber())
    return engine


def _make_calendar_bridge(fake: FakeGoogleApiAdapter) -> BridgeAdapter:
    calendar = CalendarAdapter(google_adapter=fake)  # type: ignore[arg-type]
    return BridgeAdapter(
        sdk_adapter=calendar,
        action_mapping={
            TaskType.CALENDAR_CREATE_EVENT: "calendar_create_event",
        },
        credentials={
            "access_token": "cal_token",
            "token_type": "Bearer",
        },
    )


def _make_gmail_bridge(fake: FakeGoogleApiAdapter) -> BridgeAdapter:
    gmail = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
    return BridgeAdapter(
        sdk_adapter=gmail,
        action_mapping={
            TaskType.SEND_EMAIL: "gmail_send_email",
        },
        credentials={
            "access_token": "gmail_token",
            "token_type": "Bearer",
        },
    )


def _make_registry(
    fake: FakeGoogleApiAdapter,
) -> AdapterRegistry:
    registry = AdapterRegistry()
    registry.register(_make_calendar_bridge(fake), priority=100, version="1.0.0")
    registry.register(_make_gmail_bridge(fake), priority=100, version="1.0.0")
    return registry


def _make_heterogeneous_plan() -> Plan:
    plan = Plan(
        id="het-plan-1",
        conversation_id="conv-het",
        status=PlanStatus.VALIDATED,
        goal=PlanGoal(outcome="schedule-meeting"),
        strategy="test_heterogeneous",
    )
    plan.tasks = [
        Task(
            id="task-cal",
            plan_id=plan.id,
            type=TaskType.CALENDAR_CREATE_EVENT,
            status=TaskStatus.PENDING,
            label="Create calendar event",
            instructions="Create a calendar event for team standup",
            params={
                "payload_type": "CreateEventPayload",
                "summary": "Team Standup",
                "start_time": "2026-01-01T10:00:00",
                "end_time": "2026-01-01T11:00:00",
            },
        ),
        Task(
            id="task-email",
            plan_id=plan.id,
            type=TaskType.SEND_EMAIL,
            status=TaskStatus.PENDING,
            label="Send notification email",
            instructions="Send email notification about the meeting",
            params={
                "payload_type": "MessagePayload",
                "channel": "email",
                "template": "",
                "to": ["john@example.com"],
                "subject": "Meeting Confirmed",
                "body_plain": "Your meeting has been scheduled.",
            },
        ),
    ]
    return plan


# =========================================================================
# Tests
# =========================================================================


class TestHeterogeneousPlanExecution:
    """A Plan with CALENDAR_CREATE_EVENT and SEND_EMAIL executes correctly."""

    @pytest.fixture
    def fake(self) -> FakeSuccessApiAdapter:
        return FakeSuccessApiAdapter()

    @pytest.fixture
    def registry(self, fake: FakeSuccessApiAdapter) -> AdapterRegistry:
        return _make_registry(fake)

    @pytest.fixture
    def resolver(self, registry: AdapterRegistry) -> AdapterRegistryResolver:
        return AdapterRegistryResolver(registry)

    @pytest.fixture
    def plan(self) -> Plan:
        return _make_heterogeneous_plan()

    @pytest.fixture
    def engine(self) -> ExecutionEngine:
        return _make_execution_engine()

    # ── Both adapters execute ──────────────────────────────────────────

    def test_both_adapters_execute(
        self,
        engine: ExecutionEngine,
        plan: Plan,
        resolver: AdapterRegistryResolver,
        fake: FakeSuccessApiAdapter,
    ) -> None:
        session = asyncio.run(engine.execute(plan, resolver=resolver))
        assert session.status == SessionState.COMPLETED
        # Each adapter should have handled exactly one request
        assert len(fake.executed_requests) == 2

    def test_calendar_adapter_executed(
        self,
        engine: ExecutionEngine,
        plan: Plan,
        resolver: AdapterRegistryResolver,
        fake: FakeSuccessApiAdapter,
    ) -> None:
        session = asyncio.run(engine.execute(plan, resolver=resolver))
        cal_task = session.tasks["task-cal"]
        assert cal_task.status == TaskState.COMPLETED
        assert cal_task.adapter_name == "calendar"

    def test_gmail_adapter_executed(
        self,
        engine: ExecutionEngine,
        plan: Plan,
        resolver: AdapterRegistryResolver,
        fake: FakeSuccessApiAdapter,
    ) -> None:
        session = asyncio.run(engine.execute(plan, resolver=resolver))
        email_task = session.tasks["task-email"]
        assert email_task.status == TaskState.COMPLETED
        assert email_task.adapter_name == "gmail"

    # ── TaskResults are correct ────────────────────────────────────────

    def test_calendar_result_has_event_id(
        self,
        engine: ExecutionEngine,
        plan: Plan,
        resolver: AdapterRegistryResolver,
    ) -> None:
        session = asyncio.run(engine.execute(plan, resolver=resolver))
        task = session.tasks["task-cal"]
        assert task.result is not None
        assert task.result.success is True
        assert task.result.output.get("id") == "evt_xyz"

    def test_gmail_result_has_message_id(
        self,
        engine: ExecutionEngine,
        plan: Plan,
        resolver: AdapterRegistryResolver,
    ) -> None:
        session = asyncio.run(engine.execute(plan, resolver=resolver))
        task = session.tasks["task-email"]
        assert task.result is not None
        assert task.result.success is True
        assert task.result.output.get("id") == "msg_abc"

    # ── Execution order (independent tasks) ────────────────────────────

    def test_both_tasks_completed(
        self,
        engine: ExecutionEngine,
        plan: Plan,
        resolver: AdapterRegistryResolver,
    ) -> None:
        session = asyncio.run(engine.execute(plan, resolver=resolver))
        assert session.tasks["task-cal"].status == TaskState.COMPLETED
        assert session.tasks["task-email"].status == TaskState.COMPLETED

    def test_all_results_have_timing(
        self,
        engine: ExecutionEngine,
        plan: Plan,
        resolver: AdapterRegistryResolver,
    ) -> None:
        session = asyncio.run(engine.execute(plan, resolver=resolver))
        for task in session.tasks.values():
            assert task.result is not None
            assert task.result.started_at is not None
            assert task.result.completed_at is not None
            assert task.result.started_at <= task.result.completed_at
            assert task.result.duration_ms is not None

    # ── Session lifecycle ──────────────────────────────────────────────

    def test_session_has_end_time(
        self,
        engine: ExecutionEngine,
        plan: Plan,
        resolver: AdapterRegistryResolver,
    ) -> None:
        session = asyncio.run(engine.execute(plan, resolver=resolver))
        assert session.end_time is not None
        assert session.end_time >= session.created_at

    def test_session_start_time_set(
        self,
        engine: ExecutionEngine,
        plan: Plan,
        resolver: AdapterRegistryResolver,
    ) -> None:
        session = asyncio.run(engine.execute(plan, resolver=resolver))
        assert session.start_time is not None

    def test_session_count(
        self,
        engine: ExecutionEngine,
        plan: Plan,
        resolver: AdapterRegistryResolver,
    ) -> None:
        session = asyncio.run(engine.execute(plan, resolver=resolver))
        assert len(session.tasks) == 2

    # ── Credential resolution ──────────────────────────────────────────

    def test_calendar_credentials_passed(
        self,
        engine: ExecutionEngine,
        plan: Plan,
        resolver: AdapterRegistryResolver,
        fake: FakeSuccessApiAdapter,
    ) -> None:
        asyncio.run(engine.execute(plan, resolver=resolver))
        # Both adapters should receive credentials
        for req in fake.executed_requests:
            assert req.credentials is not None
            assert "access_token" in req.credentials

    # ── AdapterRegistryResolver ────────────────────────────────────────

    def test_resolver_resolves_calendar(
        self,
        registry: AdapterRegistry,
    ) -> None:
        resolver = AdapterRegistryResolver(registry)
        adapter = resolver.resolve(TaskType.CALENDAR_CREATE_EVENT)
        assert adapter is not None
        assert adapter.adapter_type == "calendar"

    def test_resolver_resolves_gmail(
        self,
        registry: AdapterRegistry,
    ) -> None:
        resolver = AdapterRegistryResolver(registry)
        adapter = resolver.resolve(TaskType.SEND_EMAIL)
        assert adapter is not None
        assert adapter.adapter_type == "gmail"

    def test_resolver_returns_none_for_unknown(
        self,
        registry: AdapterRegistry,
    ) -> None:
        resolver = AdapterRegistryResolver(registry)
        adapter = resolver.resolve(TaskType.BRANCH)
        assert adapter is None


class TestHeterogeneousPlanFailure:
    """When one adapter fails, the other should still complete."""

    @pytest.fixture
    def plan(self) -> Plan:
        return _make_heterogeneous_plan()

    @pytest.fixture
    def engine(self) -> ExecutionEngine:
        return _make_execution_engine()

    def test_gmail_fails_calendar_still_succeeds(
        self,
        engine: ExecutionEngine,
        plan: Plan,
    ) -> None:
        fake = FakeGoogleApiAdapter()
        # Calendar succeeds
        fake.add_response(
            "calendars/primary/events",
            AdapterResult(
                success=True,
                data={
                    "json": {
                        "id": "evt_xyz",
                        "summary": "Team Standup",
                        "start": {"dateTime": "2026-01-01T10:00:00", "timeZone": "UTC"},
                        "end": {"dateTime": "2026-01-01T11:00:00", "timeZone": "UTC"},
                    },
                    "status_code": 200,
                },
                metadata={},
                usage=UsageInfo(api_calls=1, latency_ms=50.0),
            ),
        )
        # Gmail fails
        fake.add_response(
            "users/me/messages/send",
            AdapterResult(
                success=False,
                data={"status_code": 403, "body": '{"error":{"message":"Forbidden"}}'},
                metadata={"error_type": "HttpStatusError"},
                error="HTTP 403",
            ),
        )

        registry = _make_registry(fake)
        resolver = AdapterRegistryResolver(registry)
        session = asyncio.run(engine.execute(plan, resolver=resolver))

        assert session.tasks["task-cal"].status == TaskState.COMPLETED
        assert session.tasks["task-email"].status == TaskState.FAILED
        assert session.status == SessionState.COMPLETED_WITH_ERRORS


class TestSequentialHeterogeneousPlan:
    """Tasks with dependencies execute in the correct order."""

    @pytest.fixture
    def engine(self) -> ExecutionEngine:
        return _make_execution_engine()

    def test_calendar_before_email(
        self,
        engine: ExecutionEngine,
    ) -> None:
        fake = FakeSuccessApiAdapter()
        registry = _make_registry(fake)
        resolver = AdapterRegistryResolver(registry)

        plan = Plan(
            id="het-seq",
            conversation_id="conv-seq",
            status=PlanStatus.VALIDATED,
            goal=PlanGoal(outcome="schedule-then-notify"),
        )
        plan.tasks = [
            Task(
                id="task-cal",
                plan_id=plan.id,
                type=TaskType.CALENDAR_CREATE_EVENT,
                status=TaskStatus.PENDING,
                label="Create event",
                instructions="Create calendar event",
                params={
                    "payload_type": "CreateEventPayload",
                    "summary": "Review",
                    "start_time": "2026-01-01T10:00:00",
                    "end_time": "2026-01-01T11:00:00",
                },
            ),
            Task(
                id="task-email",
                plan_id=plan.id,
                type=TaskType.SEND_EMAIL,
                status=TaskStatus.PENDING,
                label="Send notification",
                instructions="Send email after event created",
                dependencies=["task-cal"],
                params={
                    "payload_type": "MessagePayload",
                    "channel": "email",
                    "template": "",
                    "to": ["alice@example.com"],
                    "subject": "Event Created",
                    "body_plain": "The event has been created.",
                },
            ),
        ]

        session = asyncio.run(engine.execute(plan, resolver=resolver))

        assert session.status == SessionState.COMPLETED
        assert session.tasks["task-cal"].status == TaskState.COMPLETED
        assert session.tasks["task-email"].status == TaskState.COMPLETED

        cal_result = session.tasks["task-cal"].result
        email_result = session.tasks["task-email"].result
        assert cal_result is not None
        assert email_result is not None
        assert cal_result.completed_at <= email_result.completed_at

    def test_calendar_failure_blocks_email(
        self,
        engine: ExecutionEngine,
    ) -> None:
        fake = FakeGoogleApiAdapter()
        # Calendar fails
        fake.add_response(
            "calendars/primary/events",
            AdapterResult(
                success=False,
                data={"status_code": 400, "body": '{"error":{"message":"Bad request"}}'},
                metadata={"error_type": "HttpStatusError"},
                error="HTTP 400",
            ),
        )
        # Gmail would succeed if called
        fake.add_response(
            "users/me/messages/send",
            AdapterResult(
                success=True,
                data={
                    "json": {"id": "msg_abc", "threadId": "th_abc"},
                    "status_code": 200,
                },
                metadata={},
                usage=UsageInfo(api_calls=1, latency_ms=45.0),
            ),
        )

        registry = _make_registry(fake)
        resolver = AdapterRegistryResolver(registry)

        plan = Plan(
            id="het-seq-fail",
            conversation_id="conv-seq-fail",
            status=PlanStatus.VALIDATED,
            goal=PlanGoal(outcome="schedule-then-notify"),
        )
        plan.tasks = [
            Task(
                id="task-cal",
                plan_id=plan.id,
                type=TaskType.CALENDAR_CREATE_EVENT,
                status=TaskStatus.PENDING,
                label="Create event",
                instructions="Create calendar event",
                params={
                    "payload_type": "CreateEventPayload",
                    "summary": "Review",
                    "start_time": "2026-01-01T10:00:00",
                    "end_time": "2026-01-01T11:00:00",
                },
            ),
            Task(
                id="task-email",
                plan_id=plan.id,
                type=TaskType.SEND_EMAIL,
                status=TaskStatus.PENDING,
                label="Send notification",
                instructions="Send email after event created",
                dependencies=["task-cal"],
                params={
                    "payload_type": "MessagePayload",
                    "channel": "email",
                    "template": "",
                    "to": ["alice@example.com"],
                    "subject": "Event Created",
                    "body_plain": "The event has been created.",
                },
            ),
        ]

        session = asyncio.run(engine.execute(plan, resolver=resolver))

        assert session.tasks["task-cal"].status == TaskState.FAILED
        assert session.tasks["task-email"].status in (
            TaskState.SKIPPED, TaskState.BLOCKED,
        )
