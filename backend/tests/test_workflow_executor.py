"""Unit tests for Workflow Runtime, Progress, Events, Registry, and Executor.

All tests are deterministic — no API calls, no mocks.
"""

from datetime import datetime, timezone

from services.workflow_models import (
    WorkflowPlan, WorkflowStep, WorkflowStep, ActionType,
    RiskLevel, StepStatus,
)
from services.workflow_runtime import (
    RuntimeStatus, RuntimeEntry,
    create_runtime, get_runtime, update_status,
    add_log, set_current_step, record_completed_step,
    record_failed_step, set_pending_step, clear as clear_runtime,
    get_active_runtimes, get_all_runtimes,
)
from services.workflow_progress import calculate_progress
from services.workflow_events import (
    EventType, emit, get_events, get_all_events,
    emit_workflow_started, emit_step_started, emit_step_finished,
    emit_approval_required, emit_approval_granted,
    clear as clear_events,
)
from services.workflow_registry import dispatch, EXECUTOR_REGISTRY
from services.workflow_executor import execute, approve


def _make_plan(steps: list[WorkflowStep] | None = None) -> WorkflowPlan:
    if not steps:
        steps = [
            WorkflowStep(title="Search leads", action_type=ActionType.SEARCH_LEADS),
            WorkflowStep(title="Create campaign", action_type=ActionType.CREATE_CAMPAIGN, approval_required=True),
            WorkflowStep(title="Generate drafts", action_type=ActionType.GENERATE_DRAFTS),
            WorkflowStep(title="Launch", action_type=ActionType.LAUNCH_CAMPAIGN),
        ]
    return WorkflowPlan(
        id="test-plan-1",
        goal="Test campaign",
        reasoning="Integration test",
        steps=steps,
    )


def _make_simple_plan() -> WorkflowPlan:
    return WorkflowPlan(
        id="simple-plan",
        goal="Simple workflow",
        reasoning="Testing basic execution",
        steps=[
            WorkflowStep(title="Step 1", action_type=ActionType.SEARCH_LEADS),
            WorkflowStep(title="Step 2", action_type=ActionType.CREATE_CAMPAIGN),
            WorkflowStep(title="Step 3", action_type=ActionType.GENERATE_DRAFTS),
        ],
    )


# ── Runtime Tests ──


class TestRuntime:
    def teardown_method(self):
        clear_runtime()
        clear_events()

    def test_create_runtime(self):
        plan = _make_simple_plan()
        runtime = create_runtime(plan, "session-1")
        assert runtime.workflow_id == plan.id
        assert runtime.session_token == "session-1"
        assert runtime.status == RuntimeStatus.PLANNED
        assert runtime.current_step_index == -1

    def test_get_runtime_returns_none_for_invalid(self):
        assert get_runtime("nonexistent") is None

    def test_status_transitions(self):
        plan = _make_simple_plan()
        runtime = create_runtime(plan, "s1")
        assert runtime.status == RuntimeStatus.PLANNED
        update_status(runtime.workflow_id, RuntimeStatus.RUNNING)
        assert runtime.status == RuntimeStatus.RUNNING
        assert runtime.started_at is not None
        update_status(runtime.workflow_id, RuntimeStatus.COMPLETED)
        assert runtime.status == RuntimeStatus.COMPLETED
        assert runtime.completed_at is not None

    def test_status_failed_sets_completed_at(self):
        plan = _make_simple_plan()
        runtime = create_runtime(plan, "s1")
        update_status(runtime.workflow_id, RuntimeStatus.RUNNING)
        update_status(runtime.workflow_id, RuntimeStatus.FAILED)
        assert runtime.status == RuntimeStatus.FAILED
        assert runtime.completed_at is not None

    def test_add_log(self):
        plan = _make_simple_plan()
        runtime = create_runtime(plan, "s1")
        add_log(runtime.workflow_id, "info", "Test log")
        assert len(runtime.logs) == 1
        assert runtime.logs[0]["message"] == "Test log"
        assert runtime.logs[0]["level"] == "info"

    def test_set_current_step(self):
        plan = _make_simple_plan()
        runtime = create_runtime(plan, "s1")
        set_current_step(runtime.workflow_id, 0)
        assert runtime.current_step_index == 0

    def test_record_completed_step(self):
        plan = _make_simple_plan()
        runtime = create_runtime(plan, "s1")
        step = plan.steps[0]
        record_completed_step(runtime.workflow_id, step, {"ok": True})
        assert len(runtime.completed_steps) == 1
        assert runtime.completed_steps[0]["step_id"] == step.id

    def test_record_failed_step(self):
        plan = _make_simple_plan()
        runtime = create_runtime(plan, "s1")
        step = plan.steps[0]
        record_failed_step(runtime.workflow_id, step, "Something broke")
        assert len(runtime.failed_steps) == 1
        assert runtime.failed_steps[0]["error"] == "Something broke"

    def test_set_pending_step(self):
        plan = _make_simple_plan()
        runtime = create_runtime(plan, "s1")
        step = plan.steps[0]
        set_pending_step(runtime.workflow_id, step)
        assert runtime.pending_step is not None
        assert runtime.pending_step["id"] == step.id
        set_pending_step(runtime.workflow_id, None)
        assert runtime.pending_step is None

    def test_get_active_runtimes(self):
        p1 = WorkflowPlan(id="a1", goal="A", reasoning="", steps=[])
        p2 = WorkflowPlan(id="a2", goal="B", reasoning="", steps=[])
        r1 = create_runtime(p1, "s1")
        r2 = create_runtime(p2, "s1")
        update_status(r1.workflow_id, RuntimeStatus.RUNNING)
        update_status(r2.workflow_id, RuntimeStatus.COMPLETED)
        active = get_active_runtimes("s1")
        assert len(active) == 1
        assert active[0].workflow_id == r1.workflow_id

    def test_get_all_runtimes(self):
        p1 = WorkflowPlan(id="b1", goal="X", reasoning="", steps=[])
        p2 = WorkflowPlan(id="b2", goal="Y", reasoning="", steps=[])
        create_runtime(p1, "s1")
        create_runtime(p2, "s1")
        all_wf = get_all_runtimes("s1")
        assert len(all_wf) == 2

    def test_runtime_summary(self):
        plan = _make_simple_plan()
        runtime = create_runtime(plan, "s1")
        update_status(runtime.workflow_id, RuntimeStatus.RUNNING)
        summary = runtime.summary()
        assert summary["workflow_id"] == runtime.workflow_id
        assert summary["status"] == "running"
        assert summary["total_steps"] == 3


# ── Progress Tests ──


class TestProgress:
    def teardown_method(self):
        clear_runtime()

    def test_empty_plan_progress(self):
        plan = WorkflowPlan(id="empty", goal="Empty", reasoning="", steps=[])
        runtime = create_runtime(plan, "s1")
        prog = calculate_progress(runtime)
        assert prog["total_steps"] == 0
        assert prog["percentage"] == 0

    def test_no_steps_started(self):
        plan = _make_simple_plan()
        runtime = create_runtime(plan, "s1")
        update_status(runtime.workflow_id, RuntimeStatus.RUNNING)
        prog = calculate_progress(runtime)
        assert prog["total_steps"] == 3
        assert prog["completed_steps"] == 0
        assert prog["percentage"] == 0

    def test_partial_progress(self):
        plan = _make_simple_plan()
        runtime = create_runtime(plan, "s1")
        update_status(runtime.workflow_id, RuntimeStatus.RUNNING)
        set_current_step(runtime.workflow_id, 1)
        record_completed_step(runtime.workflow_id, plan.steps[0], {"ok": True})
        prog = calculate_progress(runtime)
        assert prog["completed_steps"] == 1
        assert prog["percentage"] == 33
        assert prog["current_step"] == 1

    def test_full_progress(self):
        plan = _make_simple_plan()
        runtime = create_runtime(plan, "s1")
        update_status(runtime.workflow_id, RuntimeStatus.COMPLETED)
        for i, step in enumerate(plan.steps):
            record_completed_step(runtime.workflow_id, step, {"ok": True})
        prog = calculate_progress(runtime)
        assert prog["completed_steps"] == 3
        assert prog["percentage"] == 100
        assert prog["estimated_remaining"] == "done"

    def test_waiting_approval_estimated_remaining(self):
        plan = _make_plan()
        runtime = create_runtime(plan, "s1")
        update_status(runtime.workflow_id, RuntimeStatus.WAITING_APPROVAL)
        prog = calculate_progress(runtime)
        assert prog["estimated_remaining"] == "waiting for approval"

    def test_current_step_title_and_type(self):
        plan = _make_simple_plan()
        runtime = create_runtime(plan, "s1")
        update_status(runtime.workflow_id, RuntimeStatus.RUNNING)
        set_current_step(runtime.workflow_id, 1)
        record_completed_step(runtime.workflow_id, plan.steps[0], {"ok": True})
        prog = calculate_progress(runtime)
        assert prog["current_step_title"] == "Step 2"
        assert prog["current_action_type"] == "create_campaign"


# ── Events Tests ──


class TestEvents:
    def teardown_method(self):
        clear_events()

    def test_emit_event(self):
        evt = emit("wf-1", EventType.WORKFLOW_STARTED, "Started")
        assert evt["type"] == "workflow_started"
        assert evt["message"] == "Started"

    def test_get_events_reversed_order(self):
        emit("wf-1", EventType.WORKFLOW_STARTED, "First")
        emit("wf-1", EventType.STEP_STARTED, "Second")
        events = get_events("wf-1")
        assert len(events) == 2
        assert events[0]["message"] == "Second"

    def test_get_all_events(self):
        emit("wf-1", EventType.WORKFLOW_STARTED, "A")
        emit("wf-1", EventType.STEP_STARTED, "B")
        all_evt = get_all_events("wf-1")
        assert len(all_evt) == 2

    def test_events_for_nonexistent_workflow(self):
        events = get_events("nonexistent")
        assert events == []

    def test_emit_workflow_started(self):
        evt = emit_workflow_started("wf-1", "Test goal")
        assert evt["type"] == "workflow_started"
        assert "Test goal" in evt["message"]

    def test_emit_step_started(self):
        evt = emit_step_started("wf-1", "Searching", 0)
        assert evt["type"] == "step_started"
        assert evt["metadata"]["step_index"] == 0

    def test_emit_step_finished(self):
        evt = emit_step_finished("wf-1", "Searching", 0, {"ok": True})
        assert evt["type"] == "step_finished"

    def test_emit_approval_required(self):
        evt = emit_approval_required("wf-1", "Launch", 3)
        assert evt["type"] == "approval_required"

    def test_emit_approval_granted(self):
        evt = emit_approval_granted("wf-1", "Launch", 3)
        assert evt["type"] == "approval_granted"

    def test_clear_events(self):
        emit("wf-1", EventType.WORKFLOW_STARTED, "X")
        clear_events("wf-1")
        assert get_events("wf-1") == []


# ── Registry Tests ──


class TestRegistry:
    def test_all_action_types_have_executors(self):
        from services.workflow_models import ActionType
        for action in ActionType:
            assert action in EXECUTOR_REGISTRY, f"Missing executor for {action}"

    def test_dispatch_search_leads(self):
        step = WorkflowStep(title="Search", action_type=ActionType.SEARCH_LEADS)
        result = dispatch(ActionType.SEARCH_LEADS, step, "s1")
        assert result["ok"] is True

    def test_dispatch_launch_campaign(self):
        step = WorkflowStep(title="Launch", action_type=ActionType.LAUNCH_CAMPAIGN)
        result = dispatch(ActionType.LAUNCH_CAMPAIGN, step, "s1")
        assert result["ok"] is True

    def test_dispatch_wait_for_user(self):
        step = WorkflowStep(title="Wait", action_type=ActionType.WAIT_FOR_USER)
        result = dispatch(ActionType.WAIT_FOR_USER, step, "s1")
        assert result["ok"] is True
        assert result.get("requires_approval") is True

    def test_dispatch_invalid_action_returns_error(self):
        from services.workflow_models import ActionType
        result = dispatch("nonexistent", WorkflowStep(title="X", action_type=ActionType.WAIT_FOR_USER), "s1")
        assert result["ok"] is False

    def test_dispatch_all_action_types_succeed(self):
        from services.workflow_models import ActionType
        for action in ActionType:
            step = WorkflowStep(title=action.value, action_type=action)
            result = dispatch(action, step, "s1")
            assert result["ok"] is True, f"Dispatch failed for {action}: {result}"

    def test_dispatch_with_context(self):
        step = WorkflowStep(title="Test", action_type=ActionType.SEARCH_LEADS)
        result = dispatch(ActionType.SEARCH_LEADS, step, "s1", {"extra": "data"})
        assert result["ok"] is True


# ── Executor Tests ──


class TestExecutor:
    def teardown_method(self):
        clear_runtime()
        clear_events()

    def test_execute_completes_all_steps(self):
        plan = _make_simple_plan()
        runtime = execute(plan, "session-1")
        assert runtime.status == RuntimeStatus.COMPLETED
        assert len(runtime.completed_steps) == 3

    def test_execute_sets_started_at(self):
        plan = _make_simple_plan()
        runtime = execute(plan, "s1")
        assert runtime.started_at is not None

    def test_execute_emits_events(self):
        plan = _make_simple_plan()
        runtime = execute(plan, "s1")
        events = get_all_events(runtime.workflow_id)
        assert len(events) >= 7  # started + 3 step_started + 3 step_finished + completed

    def test_execute_first_event_is_workflow_started(self):
        plan = _make_simple_plan()
        runtime = execute(plan, "s1")
        events = get_all_events(runtime.workflow_id)
        assert events[0]["type"] == "workflow_started"

    def test_execute_last_event_is_workflow_completed(self):
        plan = _make_simple_plan()
        runtime = execute(plan, "s1")
        events = get_all_events(runtime.workflow_id)
        assert events[-1]["type"] == "workflow_completed"

    def test_execute_adds_logs(self):
        plan = _make_simple_plan()
        runtime = execute(plan, "s1")
        assert len(runtime.logs) > 0

    def test_execute_updates_progress(self):
        plan = _make_simple_plan()
        runtime = execute(plan, "s1")
        prog = calculate_progress(runtime)
        assert prog["percentage"] == 100

    def test_execute_approval_gate_stops_execution(self):
        plan = _make_plan()
        runtime = execute(plan, "s1")
        assert runtime.status == RuntimeStatus.WAITING_APPROVAL
        assert len(runtime.completed_steps) == 1  # only step 0 completed

    def test_approval_continues_from_correct_step(self):
        plan = _make_plan()
        runtime = execute(plan, "s1")
        assert runtime.status == RuntimeStatus.WAITING_APPROVAL
        assert runtime.current_step_index == 1
        assert len(runtime.completed_steps) == 1  # only step 0 done

        runtime = approve(runtime.workflow_id)
        assert runtime.status == RuntimeStatus.COMPLETED
        assert len(runtime.completed_steps) == 4  # all 4 steps done

    def test_approval_on_completed_workflow_raises_error(self):
        plan = _make_simple_plan()
        runtime = execute(plan, "s1")
        assert runtime.status == RuntimeStatus.COMPLETED
        try:
            approve(runtime.workflow_id)
            assert False, "Should have raised ValueError"
        except ValueError:
            pass

    def test_approval_on_nonexistent_raises_error(self):
        try:
            approve("nonexistent")
            assert False, "Should have raised ValueError"
        except ValueError:
            pass

    def test_multiple_approval_gates(self):
        steps = [
            WorkflowStep(title="S1", action_type=ActionType.SEARCH_LEADS),
            WorkflowStep(title="S2", action_type=ActionType.CREATE_CAMPAIGN, approval_required=True),
            WorkflowStep(title="S3", action_type=ActionType.GENERATE_DRAFTS),
            WorkflowStep(title="S4", action_type=ActionType.REVIEW_DRAFTS, approval_required=True),
            WorkflowStep(title="S5", action_type=ActionType.LAUNCH_CAMPAIGN, approval_required=True),
        ]
        plan = WorkflowPlan(id="multi-approve", goal="Multi", reasoning="Test", steps=steps)

        runtime = execute(plan, "s1")
        assert runtime.status == RuntimeStatus.WAITING_APPROVAL
        assert runtime.current_step_index == 1

        runtime = approve(runtime.workflow_id)
        assert runtime.status == RuntimeStatus.WAITING_APPROVAL
        assert runtime.current_step_index == 3

        runtime = approve(runtime.workflow_id)
        assert runtime.status == RuntimeStatus.WAITING_APPROVAL
        assert runtime.current_step_index == 4

        runtime = approve(runtime.workflow_id)
        assert runtime.status == RuntimeStatus.COMPLETED
        assert len(runtime.completed_steps) == 5

    def test_progress_after_approval_gate(self):
        plan = _make_plan()
        runtime = execute(plan, "s1")
        prog = calculate_progress(runtime)
        assert prog["percentage"] == 25  # 1 of 4 steps done

        runtime = approve(runtime.workflow_id)
        prog = calculate_progress(runtime)
        assert prog["percentage"] == 100

    def test_execute_emits_approval_required_event(self):
        plan = _make_plan()
        runtime = execute(plan, "s1")
        events = get_all_events(runtime.workflow_id)
        types = [e["type"] for e in events]
        assert "approval_required" in types

    def test_approval_emits_approval_granted_event(self):
        plan = _make_plan()
        runtime = execute(plan, "s1")
        runtime = approve(runtime.workflow_id)
        events = get_all_events(runtime.workflow_id)
        types = [e["type"] for e in events]
        assert "approval_granted" in types

    def test_execute_uses_plan_id_as_workflow_id(self):
        plan = _make_simple_plan()
        runtime = execute(plan, "s1")
        assert runtime.workflow_id == plan.id

    def test_invalid_workflow_id_returns_none(self):
        assert get_runtime("invalid-id") is None


# ── Status Transition Tests ──


class TestStatusTransitions:
    def teardown_method(self):
        clear_runtime()

    def test_planned_to_running(self):
        plan = _make_simple_plan()
        runtime = create_runtime(plan, "s1")
        assert runtime.status == RuntimeStatus.PLANNED
        update_status(runtime.workflow_id, RuntimeStatus.RUNNING)
        assert runtime.status == RuntimeStatus.RUNNING

    def test_running_to_waiting_approval(self):
        plan = _make_plan()
        runtime = create_runtime(plan, "s1")
        update_status(runtime.workflow_id, RuntimeStatus.RUNNING)
        update_status(runtime.workflow_id, RuntimeStatus.WAITING_APPROVAL)
        assert runtime.status == RuntimeStatus.WAITING_APPROVAL

    def test_waiting_approval_to_running(self):
        plan = _make_plan()
        runtime = create_runtime(plan, "s1")
        update_status(runtime.workflow_id, RuntimeStatus.RUNNING)
        update_status(runtime.workflow_id, RuntimeStatus.WAITING_APPROVAL)
        update_status(runtime.workflow_id, RuntimeStatus.RUNNING)
        assert runtime.status == RuntimeStatus.RUNNING

    def test_running_to_completed(self):
        plan = _make_simple_plan()
        runtime = create_runtime(plan, "s1")
        update_status(runtime.workflow_id, RuntimeStatus.RUNNING)
        update_status(runtime.workflow_id, RuntimeStatus.COMPLETED)
        assert runtime.status == RuntimeStatus.COMPLETED

    def test_running_to_failed(self):
        plan = _make_simple_plan()
        runtime = create_runtime(plan, "s1")
        update_status(runtime.workflow_id, RuntimeStatus.RUNNING)
        update_status(runtime.workflow_id, RuntimeStatus.FAILED)
        assert runtime.status == RuntimeStatus.FAILED

    def test_running_to_cancelled(self):
        plan = _make_simple_plan()
        runtime = create_runtime(plan, "s1")
        update_status(runtime.workflow_id, RuntimeStatus.RUNNING)
        update_status(runtime.workflow_id, RuntimeStatus.CANCELLED)
        assert runtime.status == RuntimeStatus.CANCELLED

    def test_event_ordering(self):
        plan = _make_simple_plan()
        runtime = execute(plan, "s1")
        events = get_all_events(runtime.workflow_id)
        for i in range(len(events) - 1):
            assert events[i]["timestamp"] <= events[i + 1]["timestamp"], \
                f"Events out of order at index {i}"
