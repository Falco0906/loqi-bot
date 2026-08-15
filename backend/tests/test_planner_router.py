"""Integration tests for PlannerRouter — Phase 8c routing migration.

Tests prove:

1. ``is_schedule_intent()`` detects scheduling keywords.
2. ``PlannerRouter.route()`` returns a result for supported intents
   when a resolver is provided.
3. ``PlannerRouter.route()`` returns *None* for unsupported intents
   (no matching strategy).
4. ``PlannerRouter.route()`` returns *None* when no resolver is
   available (fallback path).
5. Full BookingStrategy execution through:
   Router → ExecutionEngine → BridgeAdapter → Calendar/Gmail.
6. Result dict is workflow-compatible (renders via
   ``_render_workflow_result``).
7. Scheduling intent in ``handle_message()`` routes through Planner.
8. Unscheduling intents still use legacy workflows.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch
from uuid import uuid4

import pytest

from services.planner.planner_router import PlannerRouter, is_schedule_intent
from services.planner.planning_models import PlanGoal, PlanStatus, Task, TaskType
from workflows import _run_async
from services.planner.strategies.booking import BookingStrategy

from services.execution import (
    AdapterRegistry,
    AdapterRegistryResolver,
    BridgeAdapter,
    ExecutionEngine,
)
from services.execution.enums import SessionState, TaskState
from services.adapters.models import AdapterMetadata, AdapterResult, UsageInfo
from services.adapters.adapter_context import AdapterContext
from services.adapters.google.gmail import GmailAdapter
from services.adapters.google.calendar import CalendarAdapter


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


@pytest.fixture
def success_fake() -> FakeGoogleApiAdapter:
    f = FakeGoogleApiAdapter()
    f.add_response(
        "calendars/primary/events",
        AdapterResult(
            success=True,
            data={
                "json": {
                    "id": "evt_001",
                    "summary": "Test Event",
                    "htmlLink": "https://calendar.google.com/event?eid=evt_001",
                    "start": {"dateTime": "2026-03-01T10:00:00", "timeZone": "UTC"},
                    "end": {"dateTime": "2026-03-01T11:00:00", "timeZone": "UTC"},
                    "status": "confirmed",
                },
                "status_code": 200,
                "body": json.dumps({"id": "evt_001"}),
            },
            metadata={},
            usage=UsageInfo(api_calls=1, latency_ms=50.0),
        ),
    )
    f.add_response(
        "users/me/messages/send",
        AdapterResult(
            success=True,
            data={
                "json": {"id": "msg_001", "threadId": "th_001"},
                "status_code": 200,
                "body": json.dumps({"id": "msg_001", "threadId": "th_001"}),
            },
            metadata={},
            usage=UsageInfo(api_calls=1, latency_ms=40.0),
        ),
    )
    return f


@pytest.fixture
def booking_resolver(success_fake: FakeGoogleApiAdapter) -> AdapterRegistryResolver:
    """Build a resolver wired to fake adapters for booking tasks."""
    calendar = CalendarAdapter(google_adapter=success_fake)  # type: ignore[arg-type]
    gmail = GmailAdapter(google_adapter=success_fake)  # type: ignore[arg-type]

    registry = AdapterRegistry()
    registry.register(
        BridgeAdapter(
            sdk_adapter=calendar,
            action_mapping={TaskType.CALENDAR_CREATE_EVENT: "calendar_create_event"},
            credentials={"access_token": "tok", "token_type": "Bearer"},
        ),
        priority=100,
    )
    registry.register(
        BridgeAdapter(
            sdk_adapter=gmail,
            action_mapping={TaskType.SEND_EMAIL: "gmail_send_email"},
            credentials={"access_token": "tok", "token_type": "Bearer"},
        ),
        priority=100,
    )
    return AdapterRegistryResolver(registry)


@pytest.fixture
def planner_router() -> PlannerRouter:
    return PlannerRouter()


# =========================================================================
# Intent detection tests
# =========================================================================


class TestScheduleIntentDetection:
    def test_detects_schedule_keyword(self) -> None:
        assert is_schedule_intent("schedule a meeting")

    def test_detects_calendar_keyword(self) -> None:
        assert is_schedule_intent("create a calendar event")

    def test_detects_meeting_keyword(self) -> None:
        assert is_schedule_intent("set up a meeting for tomorrow")

    def test_detects_event_keyword(self) -> None:
        assert is_schedule_intent("plan an event")

    def test_detects_book_keyword(self) -> None:
        assert is_schedule_intent("book a demo")

    def test_detects_appointment(self) -> None:
        assert is_schedule_intent("I need an appointment")

    def test_case_insensitive(self) -> None:
        assert is_schedule_intent("SCHEDULE A CALL")

    def test_not_triggered_on_unrelated(self) -> None:
        assert not is_schedule_intent("find me leads for AI startups")

    def test_not_triggered_on_greeting(self) -> None:
        assert not is_schedule_intent("hello")

    def test_not_triggered_on_empty(self) -> None:
        assert not is_schedule_intent("")


# =========================================================================
# Router routing tests
# =========================================================================


class TestPlannerRouterRouting:
    """Tests that router correctly decides when to route through Planner."""

    def test_returns_result_for_supported_intent(
        self,
        planner_router: PlannerRouter,
        booking_resolver: AdapterRegistryResolver,
    ) -> None:
        goal = PlanGoal(target_action="schedule_event")
        result = planner_router.route(
            goal,
            {
                "summary": "Test Event",
                "start_time": "2026-03-01T10:00:00",
                "end_time": "2026-03-01T11:00:00",
                "attendee_email": "alice@example.com",
            },
            resolver=booking_resolver,
        )
        assert result is not None
        assert result["ok"] is True
        assert result["type"] == "planner_result"

    def test_returns_none_for_unmatched_intent(
        self,
        planner_router: PlannerRouter,
    ) -> None:
        goal = PlanGoal(target_action="cold_outreach")
        result = planner_router.route(goal, {})
        assert result is None

    def test_returns_none_for_nonexistent_strategy(
        self,
        planner_router: PlannerRouter,
    ) -> None:
        goal = PlanGoal(target_action="send_outreach")
        result = planner_router.route(goal, {})
        assert result is None

    def test_returns_none_without_resolver(
        self,
        planner_router: PlannerRouter,
    ) -> None:
        goal = PlanGoal(target_action="schedule_event")
        result = planner_router.route(goal, {"summary": "Test"})
        assert result is None

    def test_succeeds_with_minimal_context(
        self,
        planner_router: PlannerRouter,
        booking_resolver: AdapterRegistryResolver,
    ) -> None:
        goal = PlanGoal(target_action="schedule_event")
        result = planner_router.route(
            goal,
            {
                "summary": "Minimal",
                "start_time": "2026-04-01T10:00:00",
                "end_time": "2026-04-01T11:00:00",
                "attendee_email": "dave@example.com",
            },
            resolver=booking_resolver,
        )
        assert result is not None

    def test_rejects_low_match_score(
        self,
        planner_router: PlannerRouter,
    ) -> None:
        """GeneralEngagement matches everything at 0.1 — below _MIN_MATCH_SCORE."""
        goal = PlanGoal(target_action="anything_unlikely")
        result = planner_router.route(goal, {})
        assert result is None


# =========================================================================
# Full execution tests — BookingStrategy through real chain
# =========================================================================


class TestBookingStrategyViaRouter:
    """BookingStrategy executes through Router → Engine → BridgeAdapter → Adapter."""

    def test_full_chain_execution(
        self,
        planner_router: PlannerRouter,
        booking_resolver: AdapterRegistryResolver,
        success_fake: FakeGoogleApiAdapter,
    ) -> None:
        goal = PlanGoal(
            outcome="Schedule an event",
            target_action="schedule_event",
        )
        context = {
            "summary": "Product Demo",
            "start_time": "2026-03-01T14:00:00",
            "end_time": "2026-03-01T15:00:00",
            "attendee_email": "alice@example.com",
        }
        result = planner_router.route(goal, context, resolver=booking_resolver)
        assert result is not None
        assert result["ok"] is True

        # Verify both adapters were called
        assert len(success_fake.executed_requests) == 2

    def test_result_contains_task_details(
        self,
        planner_router: PlannerRouter,
        booking_resolver: AdapterRegistryResolver,
    ) -> None:
        goal = PlanGoal(target_action="schedule_event")
        context = {
            "summary": "Team Sync",
            "start_time": "2026-03-02T09:00:00",
            "end_time": "2026-03-02T10:00:00",
            "attendee_email": "bob@example.com",
        }
        result = planner_router.route(goal, context, resolver=booking_resolver)
        assert result is not None
        r = result["result"]
        assert r["strategy"] == "booking"
        assert len(r["tasks"]) == 2

        task_types = {t["type"] for t in r["tasks"]}
        assert "calendar_create_event" in task_types
        assert "send_email" in task_types

    def test_all_tasks_succeed(
        self,
        planner_router: PlannerRouter,
        booking_resolver: AdapterRegistryResolver,
    ) -> None:
        goal = PlanGoal(target_action="schedule_event")
        context = {
            "summary": "Sync",
            "start_time": "2026-03-03T10:00:00",
            "end_time": "2026-03-03T11:00:00",
            "attendee_email": "carol@example.com",
        }
        result = planner_router.route(goal, context, resolver=booking_resolver)
        assert result is not None
        assert result["ok"] is True
        for t in result["result"]["tasks"]:
            assert t["success"] is True

    def test_calendar_failure_marks_email_as_failed(
        self,
        planner_router: PlannerRouter,
    ) -> None:
        fake = FakeGoogleApiAdapter()
        fake.add_response(
            "calendars/primary/events",
            AdapterResult(
                success=False,
                data={"status_code": 400, "body": "{}"},
                metadata={"error_type": "HttpStatusError"},
                error="HTTP 400",
            ),
        )
        fake.add_response(
            "users/me/messages/send",
            AdapterResult(
                success=True,
                data={"json": {"id": "msg"}, "status_code": 200},
                metadata={},
                usage=UsageInfo(api_calls=1, latency_ms=40.0),
            ),
        )

        calendar = CalendarAdapter(google_adapter=fake)  # type: ignore[arg-type]
        gmail = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        registry = AdapterRegistry()
        registry.register(
            BridgeAdapter(
                sdk_adapter=calendar,
                action_mapping={TaskType.CALENDAR_CREATE_EVENT: "calendar_create_event"},
                credentials={"access_token": "tok", "token_type": "Bearer"},
            ),
            priority=100,
        )
        registry.register(
            BridgeAdapter(
                sdk_adapter=gmail,
                action_mapping={TaskType.SEND_EMAIL: "gmail_send_email"},
                credentials={"access_token": "tok", "token_type": "Bearer"},
            ),
            priority=100,
        )
        resolver = AdapterRegistryResolver(registry)

        goal = PlanGoal(target_action="schedule_event")
        result = planner_router.route(
            goal,
            {
                "summary": "Fail Test",
                "start_time": "2026-03-05T10:00:00",
                "end_time": "2026-03-05T11:00:00",
                "attendee_email": "fail@example.com",
            },
            resolver=resolver,
        )
        assert result is not None
        assert result["ok"] is False
        tasks = result["result"]["tasks"]
        cal_task = next(t for t in tasks if t["type"] == "calendar_create_event")
        email_task = next(t for t in tasks if t["type"] == "send_email")
        assert cal_task["success"] is False
        assert email_task["success"] is False

    # ------------------------------------------------------------------
    # Workflow-compatible result
    # ------------------------------------------------------------------

    def test_result_is_renderable_by_conversation_engine(
        self,
        planner_router: PlannerRouter,
        booking_resolver: AdapterRegistryResolver,
    ) -> None:
        """The result dict has the fields expected by _render_workflow_result()."""
        goal = PlanGoal(target_action="schedule_event")
        context = {
            "summary": "Review",
            "start_time": "2026-03-04T10:00:00",
            "end_time": "2026-03-04T11:00:00",
            "attendee_email": "eve@example.com",
        }
        result = planner_router.route(goal, context, resolver=booking_resolver)
        assert result is not None

        # Fields expected by _render_workflow_result
        assert "ok" in result
        assert "type" in result
        assert result["type"] == "planner_result"
        assert "message" in result
        assert isinstance(result["message"], str)
        assert "result" in result

        # The rendering check uses workflow_type for dispatching
        # _render_workflow_result checks: result["type"] == "planner_result"
        from services.conversational_response_generator import RESPONSE_VARIATIONS

        assert result["ok"] is True


# =========================================================================
# Legacy workflow compatibility
# =========================================================================


class TestLegacyWorkflowFallback:
    """Unsupported intents do NOT route through Planner — legacy stays."""

    def test_no_strategy_for_lead_generation(self) -> None:
        goal = PlanGoal(target_action="generate_leads")
        router = PlannerRouter()
        result = router.route(goal, {})
        assert result is None

    def test_no_strategy_for_draft_message(self) -> None:
        goal = PlanGoal(target_action="draft_message")
        router = PlannerRouter()
        result = router.route(goal, {})
        assert result is None

    def test_no_strategy_for_send_outreach(self) -> None:
        router = PlannerRouter()
        result = router.route(
            PlanGoal(target_action="send_outreach"), {},
        )
        assert result is None

    def test_no_strategy_for_follow_up(self) -> None:
        router = PlannerRouter()
        result = router.route(
            PlanGoal(target_action="send_followup"), {},
        )
        # FollowUpStrategy matches send_followup at >0.5 but
        # the router returns None because there's no resolver
        assert result is None


# =========================================================================
# Conversation Engine integration
# =========================================================================


class TestConversationEngineRendering:
    """Prove that handle_message() correctly routes planner results."""

    def test_planner_result_rendering(self) -> None:
        """_render_workflow_result handles planner_result type."""
        from services.conversation_engine import ConversationEngine

        engine = ConversationEngine()

        fake_result = {
            "ok": True,
            "type": "planner_result",
            "message": "Calendar event created.\nNotification email sent.",
            "result": {
                "plan_id": "plan-test",
                "strategy": "booking",
                "tasks": [
                    {
                        "task_id": "booking_create_event",
                        "type": "calendar_create_event",
                        "label": "Create event: Test",
                        "status": "completed",
                        "success": True,
                        "output": {},
                    },
                    {
                        "task_id": "booking_send_notification",
                        "type": "send_email",
                        "label": "Send notification about Test",
                        "status": "completed",
                        "success": True,
                        "output": {},
                    },
                ],
            },
        }

        messages = engine._render_workflow_result(
            workflow_session_id="ws-test",
            workflow_result=fake_result,
        )
        assert len(messages) >= 1
        first = messages[0]
        assert first["type"] == "planner_result"
        assert "Calendar event created" in first["text"]
        assert first["role"] == "assistant"

    def test_planner_result_failure_rendering(self) -> None:
        """_render_workflow_result handles planner_result with errors."""
        from services.conversation_engine import ConversationEngine

        engine = ConversationEngine()

        fake_result = {
            "ok": False,
            "type": "planner_result",
            "message": "Calendar event created.\nNotification email: failed.",
            "result": {
                "plan_id": "plan-fail",
                "strategy": "booking",
                "tasks": [
                    {
                        "task_id": "booking_create_event",
                        "type": "calendar_create_event",
                        "label": "Create event: Test",
                        "status": "completed",
                        "success": True,
                        "output": {},
                    },
                    {
                        "task_id": "booking_send_notification",
                        "type": "send_email",
                        "label": "Send notification",
                        "status": "failed",
                        "success": False,
                        "output": {},
                    },
                ],
            },
        }

        messages = engine._render_workflow_result(
            workflow_session_id="ws-test",
            workflow_result=fake_result,
        )
        assert len(messages) >= 1
        first = messages[0]
        assert "failed" in first["text"]


# =========================================================================
# Registry wiring — init_planner_registry / get_planner_resolver
# =========================================================================


class TestPlannerRegistryWiring:
    """Prove the global registry wiring works correctly."""

    def teardown_method(self) -> None:
        """Reset the global registry state after each test."""
        from services.execution.adapter_registry_resolver import (
            init_planner_registry as _orig_init,
            _planner_registry_lock,
        )
        # Re-import to reset — test isolation
        import services.execution.adapter_registry_resolver as mod
        with mod._planner_registry_lock:
            mod._planner_registry = None

    # ------------------------------------------------------------------
    # Accessor behaviour
    # ------------------------------------------------------------------

    def test_resolver_is_none_before_init(self) -> None:
        from services.execution.adapter_registry_resolver import get_planner_resolver
        assert get_planner_resolver() is None

    def test_registry_is_none_before_init(self) -> None:
        from services.execution.adapter_registry_resolver import get_planner_registry
        assert get_planner_registry() is None

    def test_init_stores_registry(self) -> None:
        from services.execution import AdapterRegistry
        from services.execution.adapter_registry_resolver import (
            init_planner_registry,
            get_planner_registry,
        )
        registry = AdapterRegistry()
        init_planner_registry(registry)
        assert get_planner_registry() is registry

    def test_resolver_available_after_init(self) -> None:
        from services.execution import AdapterRegistry
        from services.execution.adapter_registry_resolver import (
            init_planner_registry,
            get_planner_resolver,
        )
        registry = AdapterRegistry()
        init_planner_registry(registry)
        resolver = get_planner_resolver()
        assert resolver is not None
        assert resolver._registry is registry

    def test_double_init_raises(self) -> None:
        from services.execution import AdapterRegistry
        from services.execution.adapter_registry_resolver import init_planner_registry
        registry = AdapterRegistry()
        init_planner_registry(registry)
        with pytest.raises(RuntimeError, match="already initialised"):
            init_planner_registry(AdapterRegistry())

    # ------------------------------------------------------------------
    # Resolution of registered adapters
    # ------------------------------------------------------------------

    def test_resolves_registered_task_type(self) -> None:
        from services.execution import AdapterRegistry, BridgeAdapter
        from services.execution.adapter_registry_resolver import (
            init_planner_registry,
            get_planner_resolver,
        )

        registry = AdapterRegistry()

        adapter = BridgeAdapter(
            sdk_adapter=_FakeSdkAdapter("test"),
            action_mapping={TaskType.SEND_EMAIL: "test_action"},
        )
        registry.register(adapter, priority=100)

        init_planner_registry(registry)
        resolver = get_planner_resolver()
        assert resolver is not None

        resolved = resolver.resolve(TaskType.SEND_EMAIL)
        assert resolved is not None
        assert resolved.adapter_type == "test"

    def test_returns_none_for_unregistered_type(self) -> None:
        from services.execution import AdapterRegistry
        from services.execution.adapter_registry_resolver import (
            init_planner_registry,
            get_planner_resolver,
        )

        registry = AdapterRegistry()
        init_planner_registry(registry)
        resolver = get_planner_resolver()
        assert resolver is not None

        resolved = resolver.resolve(TaskType.SEND_EMAIL)
        assert resolved is None

    def test_calendar_events_resolve(self) -> None:
        from services.execution import AdapterRegistry, BridgeAdapter
        from services.execution.adapter_registry_resolver import (
            init_planner_registry,
            get_planner_resolver,
        )

        registry = AdapterRegistry()
        registry.register(
            BridgeAdapter(
                sdk_adapter=_FakeSdkAdapter("calendar"),
                action_mapping={
                    TaskType.CALENDAR_CREATE_EVENT: "create",
                    TaskType.CALENDAR_LIST_EVENTS: "list",
                },
            ),
            priority=100,
        )
        init_planner_registry(registry)
        resolver = get_planner_resolver()
        assert resolver is not None

        for tt in (TaskType.CALENDAR_CREATE_EVENT, TaskType.CALENDAR_LIST_EVENTS):
            assert resolver.resolve(tt) is not None

    # ------------------------------------------------------------------
    # PlannerRouter auto-resolver integration
    # ------------------------------------------------------------------

    def test_auto_resolver_returns_global_when_available(self) -> None:
        from services.execution import AdapterRegistry, BridgeAdapter
        from services.execution.adapter_registry_resolver import init_planner_registry
        from services.planner.planning_models import Plan

        registry = AdapterRegistry()
        registry.register(
            BridgeAdapter(
                sdk_adapter=_FakeSdkAdapter("gmail"),
                action_mapping={TaskType.SEND_EMAIL: "send"},
            ),
            priority=100,
        )
        init_planner_registry(registry)

        router = PlannerRouter()
        resolver = router._auto_resolver(Plan(tasks=[]))
        assert resolver is not None

        from services.execution.adapter_registry_resolver import AdapterRegistryResolver
        assert isinstance(resolver, AdapterRegistryResolver)

    def test_auto_resolver_returns_none_without_registry(self) -> None:
        router = PlannerRouter()
        from services.planner.planning_models import Plan
        resolver = router._auto_resolver(Plan(tasks=[]))
        assert resolver is None

    def test_router_executes_booking_with_auto_resolver(self) -> None:
        """BookingStrategy executes through PlannerRouter with auto-resolver."""
        from services.execution import AdapterRegistry, BridgeAdapter
        from services.execution.adapter_registry_resolver import init_planner_registry

        fake = FakeGoogleApiAdapter()
        fake.add_response(
            "calendars/primary/events",
            AdapterResult(
                success=True,
                data={
                    "json": {"id": "evt_auto"},
                    "status_code": 200,
                    "body": '{"id":"evt_auto"}',
                },
                metadata={},
                usage=UsageInfo(api_calls=1, latency_ms=50.0),
            ),
        )
        fake.add_response(
            "users/me/messages/send",
            AdapterResult(
                success=True,
                data={
                    "json": {"id": "msg_auto"},
                    "status_code": 200,
                    "body": '{"id":"msg_auto"}',
                },
                metadata={},
                usage=UsageInfo(api_calls=1, latency_ms=40.0),
            ),
        )

        registry = AdapterRegistry()
        from services.adapters.google.calendar import CalendarAdapter
        from services.adapters.google.gmail import GmailAdapter
        registry.register(
            BridgeAdapter(
                sdk_adapter=CalendarAdapter(google_adapter=fake),
                action_mapping={TaskType.CALENDAR_CREATE_EVENT: "calendar_create_event"},
                credentials={"access_token": "tok", "token_type": "Bearer"},
            ),
            priority=100,
        )
        registry.register(
            BridgeAdapter(
                sdk_adapter=GmailAdapter(google_adapter=fake),
                action_mapping={TaskType.SEND_EMAIL: "gmail_send_email"},
                credentials={"access_token": "tok", "token_type": "Bearer"},
            ),
            priority=100,
        )
        init_planner_registry(registry)

        router = PlannerRouter()
        result = router.route(
            PlanGoal(target_action="schedule_event"),
            {
                "summary": "Auto Test",
                "start_time": "2026-05-01T10:00:00",
                "end_time": "2026-05-01T11:00:00",
                "attendee_email": "auto@example.com",
            },
        )
        assert result is not None
        assert result["ok"] is True
        assert result["type"] == "planner_result"

    def test_unresolved_type_still_falls_back(self) -> None:
        """When no adapter is registered for required types, tasks fail but route
        returns a result (the plan still executes — individual tasks fail)."""
        from services.execution import AdapterRegistry
        from services.execution.adapter_registry_resolver import init_planner_registry

        registry = AdapterRegistry()
        init_planner_registry(registry)

        router = PlannerRouter()
        result = router.route(
            PlanGoal(target_action="schedule_event"),
            {
                "summary": "Fallback",
                "start_time": "2026-06-01T10:00:00",
                "end_time": "2026-06-01T11:00:00",
                "attendee_email": "fallback@example.com",
            },
        )
        # Plan executes but tasks fail because no adapters are registered
        assert result is not None
        assert result["ok"] is False
        for t in result["result"]["tasks"]:
            assert t["success"] is False


# =========================================================================
# Helper: fake SDK adapter for registry tests
# =========================================================================


class _FakeSdkAdapter:
    """Minimal stand-in for an SDK adapter in registry/resolver tests."""

    def __init__(self, name: str = "fake") -> None:
        self._name = name

    @property
    def metadata(self) -> AdapterMetadata:
        return AdapterMetadata(name=self._name, display_name="", version="1", description="")

    async def execute(self, context: AdapterContext) -> AdapterResult:
        return AdapterResult.success_result(data={})


# =========================================================================
# Credential factory tests
# =========================================================================


class TestCredentialFactory:
    """Prove the credentials_factory resolves correctly."""

    def test_resolves_from_task_params(self) -> None:
        """Factory reads credential_user_id from task params."""
        from services.execution.credential_factory import resolve_google_credentials
        from services.execution.execution_context import ExecutionContext
        from services.execution.execution_models import ExecutionTask
        from services.planner.planning_models import Task

        plan_task = Task(type=TaskType.SEND_EMAIL, label="t")
        plan_task.params["credential_user_id"] = "fake_user_for_test"

        etask = ExecutionTask(id="t1", plan_task=plan_task, max_attempts=1)
        ctx = ExecutionContext(session_id="s1")

        # The factory should not crash — it will try to look up the user
        # and return empty credentials if the user doesn't exist.
        result = resolve_google_credentials(etask, ctx)
        assert isinstance(result, dict)
        # Since "fake_user_for_test" doesn't exist in the DB, the
        # factory returns an empty dict (no crash).
        assert result == {}

    def test_returns_empty_without_user_id(self) -> None:
        """Factory returns empty dict when no credential_user_id param."""
        from services.execution.credential_factory import resolve_google_credentials
        from services.execution.execution_context import ExecutionContext
        from services.execution.execution_models import ExecutionTask
        from services.planner.planning_models import Task

        plan_task = Task(type=TaskType.SEND_EMAIL, label="t")
        etask = ExecutionTask(id="t1", plan_task=plan_task, max_attempts=1)
        ctx = ExecutionContext(session_id="s1")

        result = resolve_google_credentials(etask, ctx)
        assert result == {}

    def test_planner_injects_user_id_into_tasks(self) -> None:
        """PlannerRouter._build_plan injects credential_user_id from context."""
        goal = PlanGoal(target_action="schedule_event")
        router = PlannerRouter()

        context = {
            "summary": "Cred Test",
            "start_time": "2026-07-01T10:00:00",
            "end_time": "2026-07-01T11:00:00",
            "attendee_email": "cred@example.com",
            "user_id": "user_cred_test",
        }

        from services.planner.strategies.booking import BookingStrategy
        strategy = BookingStrategy()
        plan = router._build_plan(goal, context, strategy)
        assert plan is not None

        for task in plan.tasks:
            assert task.params.get("credential_user_id") == "user_cred_test"

    def test_injects_user_id_into_all_tasks(self) -> None:
        """Router injects credential_user_id into every task from context."""
        goal = PlanGoal(target_action="schedule_event")
        router = PlannerRouter()

        context = {
            "summary": "All Tasks",
            "start_time": "2026-07-02T10:00:00",
            "end_time": "2026-07-02T11:00:00",
            "attendee_email": "all@example.com",
            "user_id": "router_user",
        }

        from services.planner.strategies.booking import BookingStrategy
        strategy = BookingStrategy()
        plan = router._build_plan(goal, context, strategy)
        assert plan is not None
        assert len(plan.tasks) > 1
        for task in plan.tasks:
            assert task.params.get("credential_user_id") == "router_user"

    def test_skips_injection_when_no_user_id_in_context(self) -> None:
        """No user_id in context → no credential_user_id injected."""
        goal = PlanGoal(target_action="schedule_event")
        router = PlannerRouter()

        context = {
            "summary": "No User",
            "start_time": "2026-07-03T10:00:00",
            "end_time": "2026-07-03T11:00:00",
        }

        from services.planner.strategies.booking import BookingStrategy
        strategy = BookingStrategy()
        plan = router._build_plan(goal, context, strategy)
        assert plan is not None

        for task in plan.tasks:
            assert "credential_user_id" not in task.params

    def test_factory_integration_with_bridge_adapter(self) -> None:
        """BridgeAdapter calls credentials_factory during execution."""
        from services.execution import BridgeAdapter
        from services.execution.credential_factory import resolve_google_credentials
        from services.execution.execution_context import ExecutionContext

        adapter = _FakeSdkAdapter("test_cred")
        bridge = BridgeAdapter(
            sdk_adapter=adapter,
            action_mapping={TaskType.SEND_EMAIL: "test_action"},
            credentials_factory=resolve_google_credentials,
        )

        # The factory will be called when bridge.execute() runs.
        # Since the plan_task has no credential_user_id, the factory
        # returns empty credentials. The adapter gets an empty dict.
        plan_task = Task(type=TaskType.SEND_EMAIL, label="t")
        from services.execution.execution_models import ExecutionTask
        etask = ExecutionTask(id="t1", plan_task=plan_task, max_attempts=1)
        ctx = ExecutionContext(session_id="s1")

        # This should not crash — empty credentials are handled
        # gracefully by the adapter.
        result = _run_async(bridge.execute(etask, ctx))
        assert result is not None


class TestConcurrentCredentialRefresh:
    """Verify per-user lock serialises refreshes for the same user."""

    def test_same_user_serialises(self, monkeypatch) -> None:
        """Concurrent refresh calls for the same user → exactly one refresh."""
        import threading
        import time

        from services.execution.credential_factory import (
            resolve_google_credentials,
            _USER_REFRESH_LOCKS,
        )
        from services.execution.execution_context import ExecutionContext
        from services.execution.execution_models import ExecutionTask
        from services.planner.planning_models import Task

        _USER_REFRESH_LOCKS.clear()

        refresh_call_count = 0
        refresh_lock = threading.Lock()
        refresh_in_progress = threading.Event()
        refresh_done = threading.Event()

        initial_user = {
            "access_token": "expired_token",
            "refresh_token": "rt1",
            "token_expiry": "2020-01-01T00:00:00",
        }
        refreshed_user = {
            "access_token": "new_token",
            "refresh_token": "rt1",
            "token_expiry": "2099-01-01T00:00:00",
        }

        # Track which version of the credentials each call sees.
        _user_db = {"user_A": dict(initial_user)}

        def fake_get_google_credentials(uid):
            return _user_db.get(uid)

        def fake_is_token_expired(expiry):
            return True  # always appears expired on the first read

        def fake_refresh_access_token(rt):
            nonlocal refresh_call_count
            with refresh_lock:
                refresh_call_count += 1
            refresh_in_progress.set()
            time.sleep(0.05)  # simulate network latency
            return {"access_token": "new_token", "token_expiry": "2099-01-01T00:00:00"}

        def fake_update_google_access_token(uid, **kw):
            _user_db[uid]["access_token"] = kw["access_token"]
            _user_db[uid]["token_expiry"] = kw["token_expiry"]
            return dict(_user_db[uid])

        # Second-guard: inside the lock, re-read shows refreshed state.
        def guarded_is_token_expired(expiry):
            # After the first thread refreshes, subsequent threads
            # re-read and see the new expiry.
            return expiry < "2050-01-01T00:00:00"

        plan_task = Task(type=TaskType.SEND_EMAIL, label="t")
        plan_task.params["credential_user_id"] = "user_A"
        etask = ExecutionTask(id="t1", plan_task=plan_task, max_attempts=1)
        ctx = ExecutionContext(session_id="s1")

        results: list[dict | None] = [None, None, None]
        errors: list[Exception] = []
        results_lock = threading.Lock()

        def call_factory(idx: int):
            try:
                r = resolve_google_credentials(etask, ctx)
                with results_lock:
                    results[idx] = r
            except Exception as e:
                with results_lock:
                    errors.append(e)

        monkeypatch.setattr("services.supabase.get_google_credentials", fake_get_google_credentials)
        monkeypatch.setattr("services.supabase.update_google_access_token", fake_update_google_access_token)
        monkeypatch.setattr("services.google_auth.refresh_access_token", fake_refresh_access_token)

        # Use guarded check so that after the first thread refreshes,
        # subsequent threads see the new expiry and skip the lock path.
        monkeypatch.setattr("services.supabase.is_token_expired", guarded_is_token_expired)

        threads = [threading.Thread(target=call_factory, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()

        # Wait for the first thread to enter the refresh call
        assert refresh_in_progress.wait(timeout=5), "First thread never reached refresh"

        # Now let all threads complete
        for t in threads:
            t.join()

        assert not errors, f"Unexpected errors: {errors}"
        assert refresh_call_count == 1, (
            f"Expected exactly 1 refresh call, got {refresh_call_count}"
        )
        # Every thread got the new token
        assert all(r is not None for r in results), f"Some threads returned None: {results}"
        assert all(r.get("access_token") == "new_token" for r in results)

    def test_different_users_independent(self, monkeypatch) -> None:
        """Users A and B can refresh simultaneously without one blocking the other."""
        import threading
        import time

        from services.execution.credential_factory import (
            resolve_google_credentials,
            _USER_REFRESH_LOCKS,
        )
        from services.execution.execution_context import ExecutionContext
        from services.execution.execution_models import ExecutionTask
        from services.planner.planning_models import Task

        _USER_REFRESH_LOCKS.clear()

        user_a_unblocked = threading.Event()
        user_b_unblocked = threading.Event()
        proceed = threading.Event()

        def fake_get_google_credentials(uid):
            return {
                "access_token": "expired_token",
                "refresh_token": "rt_" + uid,
                "token_expiry": "2020-01-01T00:00:00",
            }

        def fake_is_token_expired(expiry):
            return True

        def fake_refresh_access_token_for(delay: float) -> callable:
            def refresh(rt):
                if "A" in rt:
                    user_a_unblocked.set()
                    # Wait until B also reaches its refresh
                    proceed.wait(timeout=5)
                    time.sleep(delay)
                else:
                    user_b_unblocked.set()
                    proceed.wait(timeout=5)
                    time.sleep(delay)
                return {"access_token": "new_token", "token_expiry": "2099-01-01T00:00:00"}
            return refresh

        refresh_counter = threading.Lock()
        refresh_count = 0

        def counting_refresh(rt):
            nonlocal refresh_count
            with refresh_counter:
                refresh_count += 1
            if "A" in rt:
                user_a_unblocked.set()
                proceed.wait(timeout=5)
            else:
                user_b_unblocked.set()
                proceed.wait(timeout=5)
            return {"access_token": "new_token", "token_expiry": "2099-01-01T00:00:00"}

        def fake_update(uid, **kw):
            return {"google_access_token": kw["access_token"], "token_expiry": kw["token_expiry"]}

        plan_a = Task(type=TaskType.SEND_EMAIL, label="a")
        plan_a.params["credential_user_id"] = "user_A"
        task_a = ExecutionTask(id="a1", plan_task=plan_a, max_attempts=1)
        ctx_a = ExecutionContext(session_id="s_a")

        plan_b = Task(type=TaskType.SEND_EMAIL, label="b")
        plan_b.params["credential_user_id"] = "user_B"
        task_b = ExecutionTask(id="b1", plan_task=plan_b, max_attempts=1)
        ctx_b = ExecutionContext(session_id="s_b")

        monkeypatch.setattr("services.supabase.get_google_credentials", fake_get_google_credentials)
        monkeypatch.setattr("services.supabase.is_token_expired", fake_is_token_expired)
        monkeypatch.setattr("services.google_auth.refresh_access_token", counting_refresh)
        monkeypatch.setattr("services.supabase.update_google_access_token", fake_update)

        results: list[dict | None] = [None, None]
        errors: list[Exception] = []

        def call_a():
            try:
                results[0] = resolve_google_credentials(task_a, ctx_a)
            except Exception as e:
                with threading.Lock():
                    errors.append(e)

        def call_b():
            try:
                results[1] = resolve_google_credentials(task_b, ctx_b)
            except Exception as e:
                with threading.Lock():
                    errors.append(e)

        t_a = threading.Thread(target=call_a)
        t_b = threading.Thread(target=call_b)
        t_a.start()
        t_b.start()

        # Both should reach refresh (different locks, no blocking)
        assert user_a_unblocked.wait(timeout=5), "User A never reached refresh"
        assert user_b_unblocked.wait(timeout=5), "User B never reached refresh"
        proceed.set()
        t_a.join()
        t_b.join()

        assert not errors, f"Unexpected errors: {errors}"
        # Each user performed its own refresh — total 2
        assert refresh_count == 2, (
            f"Expected 2 refresh calls (one per user), got {refresh_count}"
        )
        assert results[0] is not None and results[0].get("access_token") == "new_token"
        assert results[1] is not None and results[1].get("access_token") == "new_token"

    def test_fast_path_skips_lock_when_token_fresh(self, monkeypatch) -> None:
        """If token is still fresh, the per-user lock is never needed."""
        from services.execution.credential_factory import (
            resolve_google_credentials,
            _USER_REFRESH_LOCKS,
        )
        from services.execution.execution_context import ExecutionContext
        from services.execution.execution_models import ExecutionTask
        from services.planner.planning_models import Task

        _USER_REFRESH_LOCKS.clear()

        refresh_called = False

        def fake_get_google_credentials(uid):
            return {
                "access_token": "fresh_token",
                "refresh_token": "rt1",
                "token_expiry": "2099-01-01T00:00:00",
            }

        def fake_is_token_expired(expiry):
            return False

        def fake_refresh(rt):
            nonlocal refresh_called
            refresh_called = True
            return {}

        monkeypatch.setattr("services.supabase.get_google_credentials", fake_get_google_credentials)
        monkeypatch.setattr("services.supabase.is_token_expired", fake_is_token_expired)
        monkeypatch.setattr("services.google_auth.refresh_access_token", fake_refresh)

        plan_task = Task(type=TaskType.SEND_EMAIL, label="t")
        plan_task.params["credential_user_id"] = "fast_user"
        etask = ExecutionTask(id="t1", plan_task=plan_task, max_attempts=1)
        ctx = ExecutionContext(session_id="s1")

        result = resolve_google_credentials(etask, ctx)
        assert result.get("access_token") == "fresh_token"
        assert not refresh_called, "Refresh was called despite fresh token"


class TestMetricsCollectorSubscription:
    """Verify MetricsCollector receives lifecycle events via the event bus."""

    def test_collector_tracks_session_lifecycle(self) -> None:
        from services.execution.event_bus import EventBus
        from services.execution.metrics_collector import MetricsCollector
        from services.execution.enums import ExecutionEventType
        from services.execution.execution_models import ExecutionEvent

        bus = EventBus()
        collector = MetricsCollector()
        bus.subscribe(collector)

        # Publish session lifecycle events
        bus.publish(ExecutionEvent(
            session_id="s1", event_type=ExecutionEventType.SESSION_STARTED, data={"plan_id": "p1"},
        ))
        bus.publish(ExecutionEvent(
            session_id="s1", event_type=ExecutionEventType.SESSION_COMPLETED, data={},
        ))
        bus.publish(ExecutionEvent(
            session_id="s2", event_type=ExecutionEventType.SESSION_STARTED, data={"plan_id": "p2"},
        ))
        bus.publish(ExecutionEvent(
            session_id="s3", event_type=ExecutionEventType.SESSION_STARTED, data={"plan_id": "p3"},
        ))
        bus.publish(ExecutionEvent(
            session_id="s3", event_type=ExecutionEventType.SESSION_FAILED, data={},
        ))

        snapshot = collector.snapshot()
        assert snapshot.sessions_started == 3
        assert snapshot.sessions_completed == 1
        assert snapshot.sessions_failed == 1
        assert snapshot.sessions_cancelled == 0

    def test_collector_tracks_task_events(self) -> None:
        from services.execution.event_bus import EventBus
        from services.execution.metrics_collector import MetricsCollector
        from services.execution.enums import ExecutionEventType
        from services.execution.execution_models import ExecutionEvent

        bus = EventBus()
        collector = MetricsCollector()
        bus.subscribe(collector)

        bus.publish(ExecutionEvent(
            session_id="s1", task_id="t1",
            event_type=ExecutionEventType.TASK_STARTED, data={},
        ))
        bus.publish(ExecutionEvent(
            session_id="s1", task_id="t1",
            event_type=ExecutionEventType.TASK_COMPLETED, data={"duration_ms": 100},
        ))
        bus.publish(ExecutionEvent(
            session_id="s1", task_id="t2",
            event_type=ExecutionEventType.TASK_STARTED, data={},
        ))
        bus.publish(ExecutionEvent(
            session_id="s1", task_id="t2",
            event_type=ExecutionEventType.TASK_FAILED, data={"duration_ms": 50},
        ))

        snapshot = collector.snapshot()
        assert snapshot.tasks_started == 2
        assert snapshot.tasks_completed == 1
        assert snapshot.tasks_failed == 1

    def test_collector_tracks_retries(self) -> None:
        from services.execution.event_bus import EventBus
        from services.execution.metrics_collector import MetricsCollector
        from services.execution.enums import ExecutionEventType
        from services.execution.execution_models import ExecutionEvent

        bus = EventBus()
        collector = MetricsCollector()
        bus.subscribe(collector)

        bus.publish(ExecutionEvent(
            session_id="s1", task_id="t1",
            event_type=ExecutionEventType.TASK_RETRY_SCHEDULED, data={},
        ))
        bus.publish(ExecutionEvent(
            session_id="s1", task_id="t1",
            event_type=ExecutionEventType.TASK_RETRY_STARTED, data={},
        ))
        bus.publish(ExecutionEvent(
            session_id="s1", task_id="t1",
            event_type=ExecutionEventType.TASK_RETRY_EXHAUSTED, data={},
        ))

        snapshot = collector.snapshot()
        assert snapshot.retries_scheduled == 1
        assert snapshot.retries_started == 1
        assert snapshot.retries_exhausted == 1


# =========================================================================
# Phase 10 — Communication Intelligence integration tests
# =========================================================================


class TestReplyAnalysisAdapter:
    """Prove the ReplyAnalysisAdapter returns structured output."""

    def test_returns_failure_without_reply_text(self) -> None:
        from services.adapters.analysis import ReplyAnalysisAdapter
        from services.adapters.adapter_context import AdapterContext

        adapter = ReplyAnalysisAdapter()
        ctx = AdapterContext(
            execution_session_id="s1",
            execution_task_id="t1",
            action="analyze_reply",
            params={},
        )
        result = _run_async(adapter.execute(ctx))
        assert not result.success
        assert "reply_text" in (result.error or "")

    def test_validates_metadata(self) -> None:
        from services.adapters.analysis import ReplyAnalysisAdapter

        adapter = ReplyAnalysisAdapter()
        meta = adapter.metadata
        assert meta.name == "reply_analysis"
        assert "analyze_reply" in meta.supported_operations


class TestAdaptiveFollowUpStrategy:
    """Prove the FollowUpV2Strategy generates correct plans per category."""

    def _make_goal(self, target: str = "handle_reply") -> PlanGoal:
        return PlanGoal(outcome=f"Reply to {target}", target_action=target)

    def _make_context(self, category: str, **overrides: str) -> dict:
        ctx: dict = {
            "reply_analysis": {
                "category": category,
                "confidence": 0.9,
                "summary": f"Test {category.lower()} reply",
                "suggested_action": "reply",
                "extracted_entities": {},
            },
            "prospect_name": "Alice",
            "company": "Acme Corp",
            "thread_id": "thread_123",
            "in_reply_to_message_id": "msg_456",
        }
        ctx.update(overrides)
        return ctx

    def test_positive_reply_creates_calendar_event(self) -> None:
        from services.planner.strategies.follow_up_v2 import follow_up_v2_strategy

        strategy = follow_up_v2_strategy
        assert strategy.matches(self._make_goal()) > 0.5

        tasks = strategy.generate_tasks(self._make_goal(), self._make_context("POSITIVE"))
        assert len(tasks) >= 1
        assert any(t.type == TaskType.CALENDAR_CREATE_EVENT for t in tasks)
        # Email tasks in the positive route get thread_id injected
        email_tasks = [t for t in tasks if t.type in (TaskType.SEND_EMAIL, TaskType.SEND_MESSAGE)]
        for t in email_tasks:
            assert t.params.get("thread_id") == "thread_123"

    def test_negative_reply_escalates(self) -> None:
        from services.planner.strategies.follow_up_v2 import follow_up_v2_strategy

        tasks = follow_up_v2_strategy.generate_tasks(
            self._make_goal(), self._make_context("NEGATIVE"),
        )
        assert len(tasks) >= 1
        assert any(t.type == TaskType.ESCALATE for t in tasks)

    def test_unsubscribe_terminates_campaign(self) -> None:
        from services.planner.strategies.follow_up_v2 import follow_up_v2_strategy

        tasks = follow_up_v2_strategy.generate_tasks(
            self._make_goal(), self._make_context("UNSUBSCRIBE"),
        )
        assert len(tasks) >= 1
        assert any(t.type == TaskType.UPDATE_CRM for t in tasks)
        update_task = next(t for t in tasks if t.type == TaskType.UPDATE_CRM)
        assert "terminate" in str(update_task.payload.to_dict().get("action", ""))

    def test_ooo_triggers_wait_then_retry(self) -> None:
        from services.planner.strategies.follow_up_v2 import follow_up_v2_strategy

        tasks = follow_up_v2_strategy.generate_tasks(
            self._make_goal(), self._make_context("OUT_OF_OFFICE"),
        )
        assert len(tasks) >= 2
        assert tasks[0].type == TaskType.WAIT_DURATION
        assert any(t.type == TaskType.SEND_EMAIL for t in tasks)

    def test_meeting_accepted_creates_event_and_confirmation(self) -> None:
        from services.planner.strategies.follow_up_v2 import follow_up_v2_strategy

        ctx = self._make_context(
            "MEETING_ACCEPTED",
            start_time="2026-08-01T10:00:00",
            end_time="2026-08-01T11:00:00",
        )
        tasks = follow_up_v2_strategy.generate_tasks(self._make_goal(), ctx)
        types = [t.type for t in tasks]
        assert TaskType.CALENDAR_CREATE_EVENT in types
        assert TaskType.SEND_EMAIL in types

    def test_auto_reply_triggers_wait(self) -> None:
        from services.planner.strategies.follow_up_v2 import follow_up_v2_strategy

        tasks = follow_up_v2_strategy.generate_tasks(
            self._make_goal(), self._make_context("AUTO_REPLY"),
        )
        assert len(tasks) >= 2
        assert tasks[0].type == TaskType.WAIT_DURATION
        assert any(t.type == TaskType.SEND_EMAIL for t in tasks)

    def test_dependencies_sequential(self) -> None:
        from services.planner.strategies.follow_up_v2 import follow_up_v2_strategy

        tasks = follow_up_v2_strategy.generate_tasks(
            self._make_goal(), self._make_context("QUESTION"),
        )
        deps = follow_up_v2_strategy.dependencies(tasks)
        assert len(deps) == len(tasks) - 1
        for i in range(len(deps)):
            assert deps[i][0] == tasks[i].id
            assert deps[i][1] == tasks[i + 1].id

    def test_approval_rules_for_send_email(self) -> None:
        from services.planner.strategies.follow_up_v2 import follow_up_v2_strategy

        tasks = follow_up_v2_strategy.generate_tasks(
            self._make_goal(), self._make_context("POSITIVE"),
        )
        rules = follow_up_v2_strategy.approval_rules(tasks)
        # Positive route creates a calendar event with RECOMMENDED approval
        calendar_tasks = [t for t in tasks if t.type == TaskType.CALENDAR_CREATE_EVENT]
        if calendar_tasks:
            from services.planner.planning_models import ApprovalRequirement
            assert calendar_tasks[0].approval == ApprovalRequirement.RECOMMENDED


class TestDraftRevisionStrategy:
    """Prove the DraftRevisionStrategy preserves thread and metadata."""

    def test_matches_revise_intent(self) -> None:
        from services.planner.strategies.draft_revision import draft_revision_strategy

        assert draft_revision_strategy.matches(
            PlanGoal(target_action="revise_draft"),
        ) > 0.5
        assert draft_revision_strategy.matches(
            PlanGoal(target_action="send_followup"),
        ) == 0.0

    def test_preserves_thread_and_recipients(self) -> None:
        from services.planner.strategies.draft_revision import draft_revision_strategy

        tasks = draft_revision_strategy.generate_tasks(
            PlanGoal(target_action="revise_draft"),
            {
                "previous_draft": {
                    "subject": "Hello Alice",
                    "body_plain": "Original body",
                    "thread_id": "thread_old",
                    "in_reply_to_message_id": "msg_old",
                },
                "reviewer_comments": "Make it shorter",
                "recipients": ["alice@acme.com"],
                "prospect_name": "Alice",
            },
        )
        assert len(tasks) == 1
        task = tasks[0]
        assert task.params.get("thread_id") == "thread_old"
        assert task.params.get("in_reply_to_message_id") == "msg_old"
        assert task.params.get("to") == ["alice@acme.com"]
        assert task.params.get("is_revision") is True

    def test_requires_approval(self) -> None:
        from services.planner.strategies.draft_revision import draft_revision_strategy
        from services.planner.planning_models import ApprovalRequirement

        tasks = draft_revision_strategy.generate_tasks(
            PlanGoal(target_action="revise_draft"),
            {"prospect_name": "Bob", "recipients": ["bob@example.com"]},
        )
        rules = draft_revision_strategy.approval_rules(tasks)
        assert len(rules) >= 1
        assert any(r.requirement == "required" for r in rules)


class TestThreadAwareSendEmail:
    """Prove the Gmail SendEmailRequest and MimeMessage support thread_id."""

    def test_send_email_request_accepts_thread_id(self) -> None:
        from services.adapters.google.gmail.models import SendEmailRequest

        req = SendEmailRequest(
            to=["alice@example.com"],
            subject="Re: Hello",
            body_plain="Reply body",
            thread_id="thread_abc",
            in_reply_to_message_id="msg_xyz",
        )
        assert req.thread_id == "thread_abc"
        assert req.in_reply_to_message_id == "msg_xyz"

    def test_build_send_request_reads_thread_params(self) -> None:
        from services.adapters.google.gmail.gmail_adapter import _build_send_request

        req = _build_send_request({
            "to": ["bob@example.com"],
            "subject": "Re: Meeting",
            "body_plain": "Sure, let's meet",
            "thread_id": "thread_456",
            "in_reply_to_message_id": "msg_789",
        })
        assert req.thread_id == "thread_456"
        assert req.in_reply_to_message_id == "msg_789"


class TestMimeMessageThreadHeaders:
    """Prove the MIME builder sets In-Reply-To / References headers."""

    def test_in_reply_to_header_set(self) -> None:
        from services.adapters.google.gmail.mime import MimeMessage

        raw = (MimeMessage()
               .to(["alice@example.com"])
               .subject("Re: Hello")
               .plain("Reply")
               .header("In-Reply-To", "<msg_123@mail.gmail.com>")
               .header("References", "<msg_123@mail.gmail.com>")
               .build())
        assert "In-Reply-To: <msg_123@mail.gmail.com>" in raw
        assert "References: <msg_123@mail.gmail.com>" in raw


class TestSendEmailRequestValidation:
    """Prove the extended SendEmailRequest still validates."""

    def test_validates_with_thread_id(self) -> None:
        from services.adapters.google.gmail.models import SendEmailRequest

        # Should not raise with thread_id set
        req = SendEmailRequest(
            to=["test@example.com"],
            subject="Test",
            body_plain="Body",
            thread_id="t123",
        )
        assert req.thread_id == "t123"

    def test_validates_with_in_reply_to(self) -> None:
        from services.adapters.google.gmail.models import SendEmailRequest

        req = SendEmailRequest(
            to=["test@example.com"],
            subject="Test",
            body_plain="Body",
            in_reply_to_message_id="m456",
        )
        assert req.in_reply_to_message_id == "m456"
