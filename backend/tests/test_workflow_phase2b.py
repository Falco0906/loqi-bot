"""Tests for Phase 3.4.2B features: persistence, recovery, retry, pause/resume/cancel, locks, scheduler, metrics, history.

All tests are deterministic — no API calls, no mocks.
"""

import os
import json
import time
import tempfile
import shutil

from services.workflow_models import WorkflowPlan, WorkflowStep, ActionType
from services.workflow_runtime import (
    RuntimeStatus, RuntimeEntry,
    create_runtime, get_runtime, update_status, clear as clear_runtime,
    get_active_runtimes, get_all_runtimes, get_history,
    add_log, set_current_step, record_completed_step, record_failed_step,
    increment_retry_count, increment_cancel_count, set_pending_step,
    acquire_lock, release_lock, has_active_lock,
    restore_runtime,
)
from services.workflow_events import (
    emit, get_events, get_all_events, get_latest_sequence, EventType,
    clear as clear_events, restore_events,
)
from services.workflow_executor import execute, pause, resume, cancel
from services.workflow_retry import (
    RetryPolicy, RetryState, classify_error, ErrorClass,
    should_retry, get_retry_delay,
)
from services.workflow_locks import try_lock, unlock, unlock_all, is_locked, get_lock_owner, clear as clear_locks
from services.workflow_persistence import persist, load, remove, list_persisted, load_all, clear_all_persisted
from services.workflow_scheduler import schedule, cancel_scheduled, cancel_all as cancel_all_scheduled
from services.workflow_recovery import recover_all


def _simple_plan():
    return WorkflowPlan(
        id="test-p2b",
        goal="Phase 2B test",
        reasoning="Test",
        steps=[
            WorkflowStep(title="S1", action_type=ActionType.SEARCH_LEADS),
            WorkflowStep(title="S2", action_type=ActionType.CREATE_CAMPAIGN),
            WorkflowStep(title="S3", action_type=ActionType.GENERATE_DRAFTS),
        ],
    )


# ── Retry Tests ──


class TestRetry:
    def test_classify_retryable_timeout(self):
        assert classify_error("Connection timed out") == ErrorClass.RETRYABLE

    def test_classify_retryable_503(self):
        assert classify_error("HTTP 503 Service Unavailable") == ErrorClass.RETRYABLE

    def test_classify_retryable_429(self):
        assert classify_error("429 Too Many Requests") == ErrorClass.RETRYABLE

    def test_classify_fatal_validation(self):
        assert classify_error("Validation error: bad input") == ErrorClass.FATAL

    def test_classify_fatal_not_found(self):
        assert classify_error("404 Not Found") == ErrorClass.FATAL

    def test_classify_fatal_permission(self):
        assert classify_error("Permission denied") == ErrorClass.FATAL

    def test_classify_unknown_is_retryable(self):
        assert classify_error("Something weird happened") == ErrorClass.RETRYABLE

    def test_immediate_delay(self):
        assert get_retry_delay(RetryPolicy.IMMEDIATE, 1) == 0.0
        assert get_retry_delay(RetryPolicy.IMMEDIATE, 5) == 0.0

    def test_fixed_delay(self):
        assert get_retry_delay(RetryPolicy.FIXED_DELAY, 1) == 2.0
        assert get_retry_delay(RetryPolicy.FIXED_DELAY, 5) == 2.0

    def test_exponential_backoff(self):
        assert get_retry_delay(RetryPolicy.EXPONENTIAL_BACKOFF, 1) == 2.0
        assert get_retry_delay(RetryPolicy.EXPONENTIAL_BACKOFF, 2) == 4.0
        assert get_retry_delay(RetryPolicy.EXPONENTIAL_BACKOFF, 3) == 8.0

    def test_retry_state_can_retry(self):
        rs = RetryState(max_retries=3)
        assert rs.can_retry()
        rs.next_delay()
        assert rs.can_retry()
        rs.next_delay()
        assert rs.can_retry()
        rs.next_delay()
        assert not rs.can_retry()

    def test_should_retry(self):
        assert should_retry(0, 3)
        assert should_retry(2, 3)
        assert not should_retry(3, 3)

    def test_retry_state_tracks_attempts(self):
        rs = RetryState(max_retries=3)
        assert rs.next_delay() == 2.0
        assert rs.current_attempt == 1
        assert rs.next_delay() == 4.0
        assert rs.current_attempt == 2


# ── Lock Tests ──


class TestLocks:
    def setup_method(self):
        clear_runtime()
        clear_locks()

    def test_try_lock_succeeds(self):
        plan = _simple_plan()
        runtime = create_runtime(plan, "s1")
        assert try_lock(runtime.workflow_id, "campaign:c1")

    def test_try_lock_prevents_duplicate(self):
        p1 = WorkflowPlan(id="l1", goal="A", reasoning="", steps=[])
        p2 = WorkflowPlan(id="l2", goal="B", reasoning="", steps=[])
        r1 = create_runtime(p1, "s1")
        r2 = create_runtime(p2, "s1")
        update_status(r1.workflow_id, RuntimeStatus.RUNNING)
        assert try_lock(r1.workflow_id, "campaign:c1")
        assert not try_lock(r2.workflow_id, "campaign:c1")

    def test_unlock_releases(self):
        plan = _simple_plan()
        runtime = create_runtime(plan, "s1")
        update_status(runtime.workflow_id, RuntimeStatus.RUNNING)
        try_lock(runtime.workflow_id, "campaign:c1")
        assert is_locked("campaign:c1")
        unlock(runtime.workflow_id, "campaign:c1")
        assert not is_locked("campaign:c1")

    def test_unlock_all(self):
        plan = _simple_plan()
        runtime = create_runtime(plan, "s1")
        update_status(runtime.workflow_id, RuntimeStatus.RUNNING)
        try_lock(runtime.workflow_id, "campaign:c1")
        try_lock(runtime.workflow_id, "campaign:c2")
        unlock_all(runtime.workflow_id)
        assert not is_locked("campaign:c1")
        assert not is_locked("campaign:c2")

    def test_get_lock_owner(self):
        plan = _simple_plan()
        runtime = create_runtime(plan, "s1")
        update_status(runtime.workflow_id, RuntimeStatus.RUNNING)
        try_lock(runtime.workflow_id, "campaign:c1")
        assert get_lock_owner("campaign:c1") == runtime.workflow_id

    def test_lock_on_completed_workflow_releases_implicitly(self):
        """Locks are global — unlock when workflow completes via unlock_all in executor."""
        p1 = WorkflowPlan(id="lc1", goal="A", reasoning="", steps=[])
        p2 = WorkflowPlan(id="lc2", goal="B", reasoning="", steps=[])
        r1 = create_runtime(p1, "s1")
        r2 = create_runtime(p2, "s1")
        update_status(r1.workflow_id, RuntimeStatus.RUNNING)
        update_status(r2.workflow_id, RuntimeStatus.RUNNING)
        assert try_lock(r1.workflow_id, "campaign:c1")
        unlock_all(r1.workflow_id)
        assert try_lock(r2.workflow_id, "campaign:c1")


# ── Persistence Tests ──


class TestPersistence:
    def setup_method(self):
        clear_runtime()
        clear_events()

    def teardown_method(self):
        clear_all_persisted()

    def test_persist_and_load(self):
        plan = _simple_plan()
        runtime = create_runtime(plan, "s1")
        update_status(runtime.workflow_id, RuntimeStatus.RUNNING)
        persist(runtime)

        loaded = load(runtime.workflow_id)
        assert loaded is not None
        assert loaded.workflow_id == runtime.workflow_id
        assert loaded.status == RuntimeStatus.RUNNING

    def test_persist_after_status_change(self):
        plan = _simple_plan()
        runtime = create_runtime(plan, "s1")
        update_status(runtime.workflow_id, RuntimeStatus.RUNNING)
        set_current_step(runtime.workflow_id, 1)
        persist(runtime)

        loaded = load(runtime.workflow_id)
        assert loaded.current_step_index == 1

    def test_load_nonexistent(self):
        assert load("nonexistent") is None

    def test_list_persisted(self):
        plan = _simple_plan()
        runtime = create_runtime(plan, "s1")
        persist(runtime)
        ids = list_persisted()
        assert runtime.workflow_id in ids

    def test_load_all(self):
        p1 = WorkflowPlan(id="pa1", goal="A", reasoning="", steps=[])
        p2 = WorkflowPlan(id="pa2", goal="B", reasoning="", steps=[])
        create_runtime(p1, "s1")
        create_runtime(p2, "s1")
        persist(get_runtime("pa1"))
        persist(get_runtime("pa2"))
        entries = load_all()
        assert len(entries) >= 2

    def test_remove_persisted(self):
        plan = _simple_plan()
        runtime = create_runtime(plan, "s1")
        persist(runtime)
        assert runtime.workflow_id in list_persisted()
        remove(runtime.workflow_id)
        assert runtime.workflow_id not in list_persisted()

    def test_persist_events_and_logs(self):
        plan = _simple_plan()
        runtime = create_runtime(plan, "s1")
        update_status(runtime.workflow_id, RuntimeStatus.RUNNING)
        add_log(runtime.workflow_id, "info", "test log")
        persist(runtime)

        loaded = load(runtime.workflow_id)
        assert len(loaded.logs) == 2  # status transition + test log

    def test_round_trip_preserves_metrics(self):
        plan = _simple_plan()
        runtime = create_runtime(plan, "s1")
        update_status(runtime.workflow_id, RuntimeStatus.RUNNING)
        increment_retry_count(runtime.workflow_id)
        persist(runtime)

        loaded = load(runtime.workflow_id)
        assert loaded.metrics["retry_count"] == 1


# ── Event Sequence Tests ──


class TestEventSequences:
    def setup_method(self):
        clear_events()

    def test_sequence_numbers_increment(self):
        emit("wf-seq", EventType.WORKFLOW_STARTED, "Start")
        emit("wf-seq", EventType.STEP_STARTED, "Step")
        events = get_all_events("wf-seq")
        assert events[0]["sequence_number"] == 1
        assert events[1]["sequence_number"] == 2

    def test_get_events_after_sequence(self):
        for i in range(5):
            emit("wf-seq2", EventType.LOG, f"Event {i + 1}")
        recent = get_events("wf-seq2", after_sequence=3)
        assert all(e["sequence_number"] > 3 for e in recent)
        assert len(recent) == 2  # events 4 and 5

    def test_latest_sequence(self):
        assert get_latest_sequence("wf-seq3") == 0
        emit("wf-seq3", EventType.LOG, "A")
        assert get_latest_sequence("wf-seq3") == 1
        emit("wf-seq3", EventType.LOG, "B")
        assert get_latest_sequence("wf-seq3") == 2

    def test_restore_events(self):
        events = [
            {"sequence_number": 1, "type": "started", "message": "A"},
            {"sequence_number": 2, "type": "step", "message": "B"},
        ]
        restore_events("wf-seq4", events)
        assert get_latest_sequence("wf-seq4") == 2
        assert len(get_all_events("wf-seq4")) == 2


# ── Pause / Resume / Cancel Tests ──


class TestPauseResumeCancel:
    def teardown_method(self):
        clear_runtime()
        clear_events()

    def test_pause_running_workflow(self):
        plan = _simple_plan()
        execed = execute(plan, "s1")
        # execution completes immediately for simple plan, so test directly
        runtime = create_runtime(plan, "s1")
        update_status(runtime.workflow_id, RuntimeStatus.RUNNING)
        result = pause(runtime.workflow_id)
        assert result.status == RuntimeStatus.PAUSED

    def test_pause_fails_on_completed(self):
        plan = _simple_plan()
        runtime = create_runtime(plan, "s1")
        update_status(runtime.workflow_id, RuntimeStatus.COMPLETED)
        try:
            pause(runtime.workflow_id)
            assert False, "Should raise"
        except ValueError:
            pass

    def test_resume_paused(self):
        plan = _simple_plan()
        runtime = create_runtime(plan, "s1")
        update_status(runtime.workflow_id, RuntimeStatus.RUNNING)
        set_current_step(runtime.workflow_id, 1)
        pause(runtime.workflow_id)
        resumed = resume(runtime.workflow_id)
        assert resumed.status in (RuntimeStatus.RUNNING, RuntimeStatus.COMPLETED)

    def test_resume_fails_on_running(self):
        plan = _simple_plan()
        runtime = create_runtime(plan, "s1")
        update_status(runtime.workflow_id, RuntimeStatus.RUNNING)
        try:
            resume(runtime.workflow_id)
            assert False, "Should raise"
        except ValueError:
            pass

    def test_cancel_running(self):
        plan = _simple_plan()
        runtime = create_runtime(plan, "s1")
        update_status(runtime.workflow_id, RuntimeStatus.RUNNING)
        result = cancel(runtime.workflow_id)
        assert result.status == RuntimeStatus.CANCELLED

    def test_cancel_fails_on_completed(self):
        plan = _simple_plan()
        runtime = create_runtime(plan, "s1")
        update_status(runtime.workflow_id, RuntimeStatus.COMPLETED)
        try:
            cancel(runtime.workflow_id)
            assert False, "Should raise"
        except ValueError:
            pass

    def test_cancel_fails_on_cancelled(self):
        plan = _simple_plan()
        runtime = create_runtime(plan, "s1")
        update_status(runtime.workflow_id, RuntimeStatus.CANCELLED)
        try:
            cancel(runtime.workflow_id)
            assert False, "Should raise"
        except ValueError:
            pass

    def test_cancel_fails_on_failed(self):
        plan = _simple_plan()
        runtime = create_runtime(plan, "s1")
        update_status(runtime.workflow_id, RuntimeStatus.FAILED)
        try:
            cancel(runtime.workflow_id)
            assert False, "Should raise"
        except ValueError:
            pass

    def test_cancel_preserves_logs(self):
        plan = _simple_plan()
        runtime = create_runtime(plan, "s1")
        update_status(runtime.workflow_id, RuntimeStatus.RUNNING)
        add_log(runtime.workflow_id, "info", "Before cancel")
        cancel(runtime.workflow_id)
        assert len(runtime.logs) >= 2
        assert runtime.completed_at is not None

    def test_cancel_unlocks_resources(self):
        plan = _simple_plan()
        runtime = create_runtime(plan, "s1")
        update_status(runtime.workflow_id, RuntimeStatus.RUNNING)
        acquire_lock(runtime.workflow_id, "campaign:c1")
        cancel(runtime.workflow_id)
        assert not has_active_lock("campaign:c1")


# ── Metrics Tests ──


class TestMetrics:
    def teardown_method(self):
        clear_runtime()

    def test_retry_count_increments(self):
        plan = _simple_plan()
        runtime = create_runtime(plan, "s1")
        increment_retry_count(runtime.workflow_id)
        increment_retry_count(runtime.workflow_id)
        assert runtime.metrics["retry_count"] == 2

    def test_failure_count_on_record_failed(self):
        plan = _simple_plan()
        runtime = create_runtime(plan, "s1")
        step = plan.steps[0]
        record_failed_step(runtime.workflow_id, step, "error")
        assert runtime.metrics["failure_count"] == 1

    def test_cancel_count(self):
        plan = _simple_plan()
        runtime = create_runtime(plan, "s1")
        increment_cancel_count(runtime.workflow_id)
        assert runtime.metrics["cancel_count"] == 1

    def test_workflow_duration_on_completion(self):
        plan = _simple_plan()
        runtime = create_runtime(plan, "s1")
        update_status(runtime.workflow_id, RuntimeStatus.RUNNING)
        update_status(runtime.workflow_id, RuntimeStatus.COMPLETED)
        assert runtime.metrics["workflow_duration_seconds"] is not None

    def test_approval_wait_time_accumulates(self):
        plan = _simple_plan()
        runtime = create_runtime(plan, "s1")
        update_status(runtime.workflow_id, RuntimeStatus.RUNNING)
        update_status(runtime.workflow_id, RuntimeStatus.WAITING_APPROVAL)
        update_status(runtime.workflow_id, RuntimeStatus.RUNNING)
        assert runtime.metrics["total_approval_wait_seconds"] >= 0


# ── History Tests ──


class TestHistory:
    def teardown_method(self):
        clear_runtime()

    def test_get_history_returns_workflows(self):
        plan = _simple_plan()
        create_runtime(plan, "s1")
        history = get_history("s1")
        assert len(history) >= 1
        assert history[0]["workflow_id"] == "test-p2b"

    def test_get_history_with_status_filter(self):
        p1 = WorkflowPlan(id="h1", goal="A", reasoning="", steps=[])
        p2 = WorkflowPlan(id="h2", goal="B", reasoning="", steps=[])
        create_runtime(p1, "s1")
        r2 = create_runtime(p2, "s1")
        update_status(r2.workflow_id, RuntimeStatus.COMPLETED)
        history = get_history("s1", status_filter="completed")
        assert all(h["status"] == "completed" for h in history)

    def test_get_history_respects_limit(self):
        for i in range(5):
            p = WorkflowPlan(id=f"h{i}", goal=str(i), reasoning="", steps=[])
            create_runtime(p, "s1")
        history = get_history("s1", limit=3)
        assert len(history) <= 3


# ── Recovery Tests ──


class TestRecovery:
    def teardown_method(self):
        clear_runtime()
        clear_events()
        clear_all_persisted()

    def test_recover_restores_runtime(self):
        plan = _simple_plan()
        runtime = create_runtime(plan, "s1")
        update_status(runtime.workflow_id, RuntimeStatus.WAITING_APPROVAL)
        set_pending_step(runtime.workflow_id, plan.steps[1])
        persist(runtime)

        clear_runtime()
        assert get_runtime(runtime.workflow_id) is None

        summary = recover_all()
        assert summary["total_recovered"] >= 1
        restored = get_runtime(runtime.workflow_id)
        assert restored is not None
        assert restored.workflow_id == runtime.workflow_id

    def test_recovery_summary_has_counts(self):
        summary = recover_all()
        assert "total_recovered" in summary
        assert "resumed" in summary
        assert "waiting_approval_restored" in summary

    def test_recover_no_workflows(self):
        summary = recover_all()
        assert summary["total_recovered"] >= 0


# ── Scheduler Tests ──


class TestScheduler:
    def teardown_method(self):
        cancel_all_scheduled()

    def test_schedule_and_cancel(self):
        results = []
        def cb():
            results.append("done")
        wid = "sch-1"
        assert schedule(wid, 10.0, cb)
        assert cancel_scheduled(wid)
        time.sleep(0.05)
        assert len(results) == 0

    def test_cancel_all(self):
        def cb():
            pass
        schedule("s1", 10.0, cb)
        schedule("s2", 10.0, cb)
        count = cancel_all_scheduled()
        assert count == 2

    def test_schedule_nonexistent_returns_false(self):
        assert not cancel_scheduled("nonexistent")


# ── RuntimeEntry from_dict Tests ──


class TestRuntimeFromDict:
    def test_from_dict_round_trip(self):
        plan = _simple_plan()
        original = create_runtime(plan, "s1")
        update_status(original.workflow_id, RuntimeStatus.RUNNING)
        set_current_step(original.workflow_id, 1)
        add_log(original.workflow_id, "info", "test")

        data = original.to_dict()
        restored = RuntimeEntry.from_dict(data)
        assert restored.workflow_id == original.workflow_id
        assert restored.status == original.status
        assert restored.current_step_index == original.current_step_index
        assert len(restored.logs) == len(original.logs)

    def test_from_dict_with_events(self):
        plan = _simple_plan()
        runtime = create_runtime(plan, "s1")
        update_status(runtime.workflow_id, RuntimeStatus.RUNNING)
        runtime.events = [{
            "sequence_number": 1, "type": "step_started",
            "timestamp": "2026-01-01T00:00:00", "message": "test",
        }]

        data = runtime.to_dict()
        restored = RuntimeEntry.from_dict(data)
        assert len(restored.events) == 1


# ── Status Transition Tests (Phase 2B additions) ──


class TestStatusTransitions2B:
    def teardown_method(self):
        clear_runtime()

    def test_planned_to_paused_not_allowed_direct(self):
        plan = _simple_plan()
        runtime = create_runtime(plan, "s1")
        try:
            pause(runtime.workflow_id)
            assert False, "Should raise"
        except ValueError:
            pass

    def test_running_to_paused(self):
        plan = _simple_plan()
        runtime = create_runtime(plan, "s1")
        update_status(runtime.workflow_id, RuntimeStatus.RUNNING)
        result = pause(runtime.workflow_id)
        assert result.status == RuntimeStatus.PAUSED
        assert result.completed_at is None

    def test_paused_to_running_on_resume(self):
        plan = _simple_plan()
        runtime = create_runtime(plan, "s1")
        update_status(runtime.workflow_id, RuntimeStatus.RUNNING)
        set_current_step(runtime.workflow_id, 0)
        pause(runtime.workflow_id)
        resumed = resume(runtime.workflow_id)
        assert resumed.status in (RuntimeStatus.RUNNING, RuntimeStatus.COMPLETED)

    def test_running_to_cancelled_preserves_step(self):
        plan = _simple_plan()
        runtime = create_runtime(plan, "s1")
        update_status(runtime.workflow_id, RuntimeStatus.RUNNING)
        set_current_step(runtime.workflow_id, 1)
        cancel(runtime.workflow_id)
        assert runtime.status == RuntimeStatus.CANCELLED
        assert runtime.current_step_index == 1


# ── Workflow Summary Tests ──


class TestSummary:
    def teardown_method(self):
        clear_runtime()

    def test_summary_includes_metrics(self):
        plan = _simple_plan()
        runtime = create_runtime(plan, "s1")
        update_status(runtime.workflow_id, RuntimeStatus.RUNNING)
        increment_retry_count(runtime.workflow_id)
        summary = runtime.summary()
        assert "metrics" in summary
        assert summary["metrics"]["retry_count"] == 1

    def test_active_workflows_excludes_paused(self):
        p1 = WorkflowPlan(id="as1", goal="A", reasoning="", steps=[])
        p2 = WorkflowPlan(id="as2", goal="B", reasoning="", steps=[])
        update_status(create_runtime(p1, "s1").workflow_id, RuntimeStatus.RUNNING)
        update_status(create_runtime(p2, "s1").workflow_id, RuntimeStatus.PAUSED)
        active = get_active_runtimes("s1")
        ids = [r.workflow_id for r in active]
        assert "as1" in ids
        assert "as2" not in ids
