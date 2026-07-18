"""Unit tests for the Metrics Collector (Phase 3.6.4H).

Tests that MetricsCollector correctly derives session, task, retry, timing,
and adapter metrics exclusively from EventBus events. The pipeline,
scheduler, dispatcher, registry, retry engine, and event bus are unchanged.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone, timedelta

import pytest

from services.execution.enums import ExecutionEventType, SessionState, TaskState
from services.execution.event_bus import EventBus
from services.execution.execution_models import ExecutionEvent
from services.execution.metrics_collector import (
    AdapterMetricsSnapshot,
    MetricsCollector,
    MetricsSnapshot,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def collector():
    return MetricsCollector()


@pytest.fixture
def subscribed_collector(bus, collector):
    collector.subscribe(bus)
    return collector


def make_event(
    event_type: ExecutionEventType,
    session_id: str = "s1",
    task_id: str | None = None,
    data: dict | None = None,
    timestamp: datetime | None = None,
) -> ExecutionEvent:
    return ExecutionEvent(
        session_id=session_id,
        task_id=task_id,
        event_type=event_type,
        data=data or {},
        timestamp=timestamp or datetime.now(timezone.utc),
    )


# ===================================================================
# SESSION METRICS
# ===================================================================

class TestSessionMetrics:
    def test_session_started(self, bus, subscribed_collector):
        bus.publish(make_event(ExecutionEventType.SESSION_STARTED))
        snap = subscribed_collector.snapshot()
        assert snap.sessions_started == 1

    def test_session_completed(self, bus, subscribed_collector):
        bus.publish(make_event(ExecutionEventType.SESSION_STARTED))
        bus.publish(make_event(ExecutionEventType.SESSION_COMPLETED))
        snap = subscribed_collector.snapshot()
        assert snap.sessions_started == 1
        assert snap.sessions_completed == 1

    def test_session_failed(self, bus, subscribed_collector):
        bus.publish(make_event(ExecutionEventType.SESSION_STARTED))
        bus.publish(make_event(ExecutionEventType.SESSION_FAILED))
        snap = subscribed_collector.snapshot()
        assert snap.sessions_started == 1
        assert snap.sessions_failed == 1

    def test_session_cancelled(self, bus, subscribed_collector):
        bus.publish(make_event(ExecutionEventType.SESSION_STARTED))
        bus.publish(make_event(ExecutionEventType.SESSION_CANCELLED))
        snap = subscribed_collector.snapshot()
        assert snap.sessions_started == 1
        assert snap.sessions_cancelled == 1

    def test_multiple_sessions(self, bus, subscribed_collector):
        for i in range(5):
            bus.publish(make_event(ExecutionEventType.SESSION_STARTED, session_id=f"s{i}"))
            bus.publish(make_event(ExecutionEventType.SESSION_COMPLETED, session_id=f"s{i}"))
        snap = subscribed_collector.snapshot()
        assert snap.sessions_started == 5
        assert snap.sessions_completed == 5

    def test_session_started_only(self, bus, subscribed_collector):
        bus.publish(make_event(ExecutionEventType.SESSION_STARTED))
        snap = subscribed_collector.snapshot()
        assert snap.sessions_started == 1
        assert snap.sessions_completed == 0
        assert snap.sessions_failed == 0
        assert snap.sessions_cancelled == 0

    def test_no_sessions(self, subscribed_collector):
        snap = subscribed_collector.snapshot()
        assert snap.sessions_started == 0

    def test_session_completed_without_start(self, bus, subscribed_collector):
        bus.publish(make_event(ExecutionEventType.SESSION_COMPLETED))
        snap = subscribed_collector.snapshot()
        assert snap.sessions_completed == 1

    def test_session_failed_without_start(self, bus, subscribed_collector):
        bus.publish(make_event(ExecutionEventType.SESSION_FAILED))
        snap = subscribed_collector.snapshot()
        assert snap.sessions_failed == 1

    def test_session_cancelled_without_start(self, bus, subscribed_collector):
        bus.publish(make_event(ExecutionEventType.SESSION_CANCELLED))
        snap = subscribed_collector.snapshot()
        assert snap.sessions_cancelled == 1

    def test_all_session_types(self, bus, subscribed_collector):
        bus.publish(make_event(ExecutionEventType.SESSION_STARTED, session_id="s1"))
        bus.publish(make_event(ExecutionEventType.SESSION_STARTED, session_id="s2"))
        bus.publish(make_event(ExecutionEventType.SESSION_COMPLETED, session_id="s1"))
        bus.publish(make_event(ExecutionEventType.SESSION_FAILED, session_id="s2"))
        bus.publish(make_event(ExecutionEventType.SESSION_STARTED, session_id="s3"))
        bus.publish(make_event(ExecutionEventType.SESSION_CANCELLED, session_id="s3"))
        snap = subscribed_collector.snapshot()
        assert snap.sessions_started == 3
        assert snap.sessions_completed == 1
        assert snap.sessions_failed == 1
        assert snap.sessions_cancelled == 1


# ===================================================================
# TASK METRICS
# ===================================================================

class TestTaskMetrics:
    def test_task_started(self, bus, subscribed_collector):
        bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id="t1"))
        snap = subscribed_collector.snapshot()
        assert snap.tasks_started == 1

    def test_task_completed(self, bus, subscribed_collector):
        now = datetime.now(timezone.utc)
        bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id="t1", timestamp=now - timedelta(seconds=1)))
        bus.publish(make_event(ExecutionEventType.TASK_COMPLETED, task_id="t1", timestamp=now, data={"task_type": "mock"}))
        snap = subscribed_collector.snapshot()
        assert snap.tasks_started == 1
        assert snap.tasks_completed == 1

    def test_task_failed(self, bus, subscribed_collector):
        now = datetime.now(timezone.utc)
        bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id="t1", timestamp=now - timedelta(seconds=1)))
        bus.publish(make_event(ExecutionEventType.TASK_FAILED, task_id="t1", timestamp=now, data={"task_type": "mock"}))
        snap = subscribed_collector.snapshot()
        assert snap.tasks_started == 1
        assert snap.tasks_failed == 1

    def test_task_skipped(self, bus, subscribed_collector):
        bus.publish(make_event(ExecutionEventType.TASK_SKIPPED, task_id="t1"))
        snap = subscribed_collector.snapshot()
        assert snap.tasks_skipped == 1

    def test_multiple_tasks(self, bus, subscribed_collector):
        now = datetime.now(timezone.utc)
        for i in range(5):
            bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id=f"t{i}", timestamp=now - timedelta(seconds=1)))
            bus.publish(make_event(ExecutionEventType.TASK_COMPLETED, task_id=f"t{i}", timestamp=now, data={"task_type": "mock"}))
        snap = subscribed_collector.snapshot()
        assert snap.tasks_started == 5
        assert snap.tasks_completed == 5

    def test_mixed_task_results(self, bus, subscribed_collector):
        now = datetime.now(timezone.utc)
        bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id="t1", timestamp=now - timedelta(seconds=1)))
        bus.publish(make_event(ExecutionEventType.TASK_COMPLETED, task_id="t1", timestamp=now, data={"task_type": "mock"}))
        bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id="t2", timestamp=now - timedelta(seconds=2)))
        bus.publish(make_event(ExecutionEventType.TASK_FAILED, task_id="t2", timestamp=now, data={"task_type": "mock"}))
        bus.publish(make_event(ExecutionEventType.TASK_SKIPPED, task_id="t3"))
        snap = subscribed_collector.snapshot()
        assert snap.tasks_started == 2
        assert snap.tasks_completed == 1
        assert snap.tasks_failed == 1
        assert snap.tasks_skipped == 1

    def test_task_cancelled_separate_counter(self, bus, subscribed_collector):
        bus.publish(make_event(ExecutionEventType.TASK_CANCELLED, task_id="t1"))
        snap = subscribed_collector.snapshot()
        assert snap.tasks_cancelled == 1
        assert snap.tasks_failed == 0  # cancellation is not failure

    def test_no_tasks(self, subscribed_collector):
        snap = subscribed_collector.snapshot()
        assert snap.tasks_started == 0
        assert snap.tasks_completed == 0

    def test_task_completed_without_start(self, bus, subscribed_collector):
        bus.publish(make_event(ExecutionEventType.TASK_COMPLETED, task_id="t1", data={"task_type": "mock"}))
        snap = subscribed_collector.snapshot()
        assert snap.tasks_completed == 1
        # no start time, duration is 0
        assert snap.average_task_duration_ms == 0.0


# ===================================================================
# RETRY METRICS
# ===================================================================

class TestRetryMetrics:
    def test_retry_scheduled(self, bus, subscribed_collector):
        bus.publish(make_event(ExecutionEventType.TASK_RETRY_SCHEDULED, task_id="t1"))
        snap = subscribed_collector.snapshot()
        assert snap.retries_scheduled == 1

    def test_retry_started(self, bus, subscribed_collector):
        bus.publish(make_event(ExecutionEventType.TASK_RETRY_STARTED, task_id="t1"))
        snap = subscribed_collector.snapshot()
        assert snap.retries_started == 1

    def test_retry_exhausted(self, bus, subscribed_collector):
        bus.publish(make_event(ExecutionEventType.TASK_RETRY_EXHAUSTED, task_id="t1"))
        snap = subscribed_collector.snapshot()
        assert snap.retries_exhausted == 1

    def test_retry_started_also_counts_tasks_started(self, bus, subscribed_collector):
        bus.publish(make_event(ExecutionEventType.TASK_RETRY_STARTED, task_id="t1"))
        snap = subscribed_collector.snapshot()
        assert snap.tasks_started == 1
        assert snap.retries_started == 1

    def test_multiple_retries(self, bus, subscribed_collector):
        for i in range(3):
            bus.publish(make_event(ExecutionEventType.TASK_RETRY_SCHEDULED, task_id=f"t{i}"))
            bus.publish(make_event(ExecutionEventType.TASK_RETRY_STARTED, task_id=f"t{i}"))
            bus.publish(make_event(ExecutionEventType.TASK_RETRY_EXHAUSTED, task_id=f"t{i}"))
        snap = subscribed_collector.snapshot()
        assert snap.retries_scheduled == 3
        assert snap.retries_started == 3
        assert snap.retries_exhausted == 3

    def test_no_retries(self, subscribed_collector):
        snap = subscribed_collector.snapshot()
        assert snap.retries_scheduled == 0

    def test_full_retry_flow(self, bus, subscribed_collector):
        now = datetime.now(timezone.utc)
        # First attempt
        bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id="t1", timestamp=now - timedelta(seconds=3)))
        bus.publish(make_event(ExecutionEventType.TASK_RETRY_SCHEDULED, task_id="t1", timestamp=now - timedelta(seconds=2)))
        bus.publish(make_event(ExecutionEventType.TASK_RETRY_STARTED, task_id="t1", timestamp=now - timedelta(seconds=2)))
        bus.publish(make_event(ExecutionEventType.TASK_COMPLETED, task_id="t1", timestamp=now, data={"task_type": "mock"}))
        snap = subscribed_collector.snapshot()
        assert snap.retries_scheduled == 1
        assert snap.retries_started == 1
        assert snap.tasks_started == 2  # initial + retry
        assert snap.tasks_completed == 1

    def test_retry_exhaustion_flow(self, bus, subscribed_collector):
        now = datetime.now(timezone.utc)
        bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id="t1", timestamp=now - timedelta(seconds=3)))
        bus.publish(make_event(ExecutionEventType.TASK_RETRY_SCHEDULED, task_id="t1", timestamp=now - timedelta(seconds=2)))
        bus.publish(make_event(ExecutionEventType.TASK_RETRY_STARTED, task_id="t1", timestamp=now - timedelta(seconds=2)))
        bus.publish(make_event(ExecutionEventType.TASK_RETRY_EXHAUSTED, task_id="t1", timestamp=now))
        bus.publish(make_event(ExecutionEventType.TASK_FAILED, task_id="t1", timestamp=now, data={"task_type": "mock"}))
        snap = subscribed_collector.snapshot()
        assert snap.retries_scheduled == 1
        assert snap.retries_started == 1
        assert snap.retries_exhausted == 1
        assert snap.tasks_failed == 1


# ===================================================================
# TIMING METRICS
# ===================================================================

class TestTimingMetrics:
    def test_duration_calculation(self, bus, subscribed_collector):
        now = datetime.now(timezone.utc)
        bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id="t1", timestamp=now - timedelta(seconds=2)))
        bus.publish(make_event(ExecutionEventType.TASK_COMPLETED, task_id="t1", timestamp=now, data={"task_type": "mock"}))
        snap = subscribed_collector.snapshot()
        assert abs(snap.average_task_duration_ms - 2000.0) < 50  # 2s = 2000ms, allow small delta

    def test_zero_duration_task(self, bus, subscribed_collector):
        now = datetime.now(timezone.utc)
        bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id="t1", timestamp=now))
        bus.publish(make_event(ExecutionEventType.TASK_COMPLETED, task_id="t1", timestamp=now, data={"task_type": "mock"}))
        snap = subscribed_collector.snapshot()
        assert snap.average_task_duration_ms == 0.0

    def test_average_duration(self, bus, subscribed_collector):
        now = datetime.now(timezone.utc)
        bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id="t1", timestamp=now - timedelta(seconds=1)))
        bus.publish(make_event(ExecutionEventType.TASK_COMPLETED, task_id="t1", timestamp=now, data={"task_type": "mock"}))
        bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id="t2", timestamp=now - timedelta(seconds=3)))
        bus.publish(make_event(ExecutionEventType.TASK_COMPLETED, task_id="t2", timestamp=now, data={"task_type": "mock"}))
        snap = subscribed_collector.snapshot()
        # (1000 + 3000) / 2 = 2000ms
        assert abs(snap.average_task_duration_ms - 2000.0) < 50

    def test_longest_task(self, bus, subscribed_collector):
        now = datetime.now(timezone.utc)
        bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id="t1", timestamp=now - timedelta(seconds=1)))
        bus.publish(make_event(ExecutionEventType.TASK_COMPLETED, task_id="t1", timestamp=now, data={"task_type": "mock"}))
        bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id="t2", timestamp=now - timedelta(seconds=5)))
        bus.publish(make_event(ExecutionEventType.TASK_COMPLETED, task_id="t2", timestamp=now, data={"task_type": "mock"}))
        snap = subscribed_collector.snapshot()
        assert snap.longest_task_id == "t2"
        assert abs(snap.longest_task_duration_ms - 5000.0) < 50

    def test_shortest_task(self, bus, subscribed_collector):
        now = datetime.now(timezone.utc)
        bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id="t1", timestamp=now - timedelta(seconds=5)))
        bus.publish(make_event(ExecutionEventType.TASK_COMPLETED, task_id="t1", timestamp=now, data={"task_type": "mock"}))
        bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id="t2", timestamp=now - timedelta(seconds=1)))
        bus.publish(make_event(ExecutionEventType.TASK_COMPLETED, task_id="t2", timestamp=now, data={"task_type": "mock"}))
        snap = subscribed_collector.snapshot()
        assert snap.shortest_task_id == "t2"
        assert abs(snap.shortest_task_duration_ms - 1000.0) < 50

    def test_multiple_tasks_timing(self, bus, subscribed_collector):
        now = datetime.now(timezone.utc)
        durations = [500, 1000, 1500, 2000, 3000]
        for i, d in enumerate(durations):
            bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id=f"t{i}", timestamp=now - timedelta(milliseconds=d)))
            bus.publish(make_event(ExecutionEventType.TASK_COMPLETED, task_id=f"t{i}", timestamp=now, data={"task_type": "mock"}))
        snap = subscribed_collector.snapshot()
        avg = sum(durations) / len(durations)
        assert abs(snap.average_task_duration_ms - avg) < 50
        assert snap.longest_task_id == "t4"

    def test_duration_for_failed_task(self, bus, subscribed_collector):
        now = datetime.now(timezone.utc)
        bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id="t1", timestamp=now - timedelta(seconds=2)))
        bus.publish(make_event(ExecutionEventType.TASK_FAILED, task_id="t1", timestamp=now, data={"task_type": "mock"}))
        snap = subscribed_collector.snapshot()
        assert abs(snap.average_task_duration_ms - 2000.0) < 50

    def test_no_duration_when_no_tasks(self, subscribed_collector):
        snap = subscribed_collector.snapshot()
        assert snap.average_task_duration_ms == 0.0
        assert snap.longest_task_id is None
        assert snap.shortest_task_id is None


# ===================================================================
# ADAPTER METRICS
# ===================================================================

class TestAdapterMetrics:
    def test_single_adapter_success(self, bus, subscribed_collector):
        now = datetime.now(timezone.utc)
        bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id="t1", timestamp=now - timedelta(seconds=1)))
        bus.publish(make_event(ExecutionEventType.TASK_COMPLETED, task_id="t1", timestamp=now, data={"task_type": "send_message"}))
        snap = subscribed_collector.snapshot()
        assert len(snap.adapter_metrics) == 1
        assert snap.adapter_metrics[0].adapter_name == "send_message"
        assert snap.adapter_metrics[0].tasks_completed == 1
        assert snap.adapter_metrics[0].tasks_failed == 0

    def test_single_adapter_failure(self, bus, subscribed_collector):
        now = datetime.now(timezone.utc)
        bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id="t1", timestamp=now - timedelta(seconds=1)))
        bus.publish(make_event(ExecutionEventType.TASK_FAILED, task_id="t1", timestamp=now, data={"task_type": "send_email"}))
        snap = subscribed_collector.snapshot()
        assert len(snap.adapter_metrics) == 1
        assert snap.adapter_metrics[0].adapter_name == "send_email"
        assert snap.adapter_metrics[0].tasks_completed == 0
        assert snap.adapter_metrics[0].tasks_failed == 1

    def test_multiple_adapters(self, bus, subscribed_collector):
        now = datetime.now(timezone.utc)
        bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id="t1", timestamp=now - timedelta(seconds=1)))
        bus.publish(make_event(ExecutionEventType.TASK_COMPLETED, task_id="t1", timestamp=now, data={"task_type": "send_message"}))
        bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id="t2", timestamp=now - timedelta(seconds=2)))
        bus.publish(make_event(ExecutionEventType.TASK_COMPLETED, task_id="t2", timestamp=now, data={"task_type": "update_crm"}))
        bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id="t3", timestamp=now - timedelta(seconds=3)))
        bus.publish(make_event(ExecutionEventType.TASK_FAILED, task_id="t3", timestamp=now, data={"task_type": "send_message"}))
        snap = subscribed_collector.snapshot()
        assert len(snap.adapter_metrics) == 2
        by_name = {a.adapter_name: a for a in snap.adapter_metrics}
        assert by_name["send_message"].tasks_completed == 1
        assert by_name["send_message"].tasks_failed == 1
        assert by_name["update_crm"].tasks_completed == 1
        assert by_name["update_crm"].tasks_failed == 0

    def test_adapter_average_duration(self, bus, subscribed_collector):
        now = datetime.now(timezone.utc)
        bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id="t1", timestamp=now - timedelta(seconds=1)))
        bus.publish(make_event(ExecutionEventType.TASK_COMPLETED, task_id="t1", timestamp=now, data={"task_type": "mock"}))
        bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id="t2", timestamp=now - timedelta(seconds=3)))
        bus.publish(make_event(ExecutionEventType.TASK_COMPLETED, task_id="t2", timestamp=now, data={"task_type": "mock"}))
        snap = subscribed_collector.snapshot()
        assert len(snap.adapter_metrics) == 1
        assert abs(snap.adapter_metrics[0].average_duration_ms - 2000.0) < 50

    def test_no_adapter_metrics(self, subscribed_collector):
        snap = subscribed_collector.snapshot()
        assert len(snap.adapter_metrics) == 0

    def test_unknown_adapter_name_default(self, bus, subscribed_collector):
        now = datetime.now(timezone.utc)
        bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id="t1", timestamp=now - timedelta(seconds=1)))
        bus.publish(make_event(ExecutionEventType.TASK_COMPLETED, task_id="t1", timestamp=now, data={}))
        snap = subscribed_collector.snapshot()
        assert len(snap.adapter_metrics) == 1
        assert snap.adapter_metrics[0].adapter_name == "unknown"

    def test_adapter_task_count(self, bus, subscribed_collector):
        now = datetime.now(timezone.utc)
        for i in range(10):
            bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id=f"t{i}", timestamp=now - timedelta(seconds=1)))
            bus.publish(make_event(ExecutionEventType.TASK_COMPLETED, task_id=f"t{i}", timestamp=now, data={"task_type": "mock"}))
        snap = subscribed_collector.snapshot()
        assert snap.adapter_metrics[0].task_count == 10
        assert snap.adapter_metrics[0].tasks_completed == 10


# ===================================================================
# SNAPSHOT TESTS
# ===================================================================

class TestSnapshot:
    def test_snapshot_is_dataclass(self, bus, subscribed_collector):
        snap = subscribed_collector.snapshot()
        assert isinstance(snap, MetricsSnapshot)

    def test_snapshot_values(self, bus, subscribed_collector):
        bus.publish(make_event(ExecutionEventType.SESSION_STARTED))
        bus.publish(make_event(ExecutionEventType.SESSION_COMPLETED))
        snap = subscribed_collector.snapshot()
        assert snap.sessions_started == 1
        assert snap.sessions_completed == 1

    def test_snapshot_immutable(self, bus, subscribed_collector):
        snap = subscribed_collector.snapshot()
        with pytest.raises(AttributeError):
            snap.sessions_started = 99  # frozen=True

    def test_snapshot_does_not_expose_internal_state(self, subscribed_collector):
        snap = subscribed_collector.snapshot()
        # Should not have _task_start_times or similar internal state
        assert not hasattr(snap, "_task_start_times")
        assert not hasattr(snap, "_lock")

    def test_snapshot_adapter_metrics_immutable(self, bus, subscribed_collector):
        now = datetime.now(timezone.utc)
        bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id="t1", timestamp=now))
        bus.publish(make_event(ExecutionEventType.TASK_COMPLETED, task_id="t1", timestamp=now, data={"task_type": "mock"}))
        snap = subscribed_collector.snapshot()
        assert len(snap.adapter_metrics) == 1
        with pytest.raises(AttributeError):
            snap.adapter_metrics[0].tasks_completed = 99

    def test_multiple_snapshots_consistent(self, bus, subscribed_collector):
        snap1 = subscribed_collector.snapshot()
        assert snap1.sessions_started == 0
        bus.publish(make_event(ExecutionEventType.SESSION_STARTED))
        snap2 = subscribed_collector.snapshot()
        assert snap2.sessions_started == 1
        snap3 = subscribed_collector.snapshot()
        assert snap3.sessions_started == 1  # stable after no new events

    def test_snapshot_with_retries(self, bus, subscribed_collector):
        bus.publish(make_event(ExecutionEventType.TASK_RETRY_SCHEDULED, task_id="t1"))
        bus.publish(make_event(ExecutionEventType.TASK_RETRY_STARTED, task_id="t1"))
        bus.publish(make_event(ExecutionEventType.TASK_RETRY_EXHAUSTED, task_id="t1"))
        snap = subscribed_collector.snapshot()
        assert snap.retries_scheduled == 1
        assert snap.retries_started == 1
        assert snap.retries_exhausted == 1

    def test_snapshot_after_reset(self, bus, subscribed_collector):
        bus.publish(make_event(ExecutionEventType.SESSION_STARTED))
        subscribed_collector.reset()
        snap = subscribed_collector.snapshot()
        assert snap.sessions_started == 0


# ===================================================================
# RESET TESTS
# ===================================================================

class TestReset:
    def test_reset_clears_counters(self, bus, subscribed_collector):
        bus.publish(make_event(ExecutionEventType.SESSION_STARTED))
        bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id="t1"))
        subscribed_collector.reset()
        snap = subscribed_collector.snapshot()
        assert snap.sessions_started == 0
        assert snap.tasks_started == 0

    def test_reset_then_continue(self, bus, subscribed_collector):
        bus.publish(make_event(ExecutionEventType.SESSION_STARTED))
        subscribed_collector.reset()
        bus.publish(make_event(ExecutionEventType.SESSION_STARTED))
        snap = subscribed_collector.snapshot()
        assert snap.sessions_started == 1

    def test_reset_clears_timing(self, bus, subscribed_collector):
        now = datetime.now(timezone.utc)
        bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id="t1", timestamp=now - timedelta(seconds=1)))
        bus.publish(make_event(ExecutionEventType.TASK_COMPLETED, task_id="t1", timestamp=now, data={"task_type": "mock"}))
        subscribed_collector.reset()
        snap = subscribed_collector.snapshot()
        assert snap.average_task_duration_ms == 0.0

    def test_reset_clears_adapter_metrics(self, bus, subscribed_collector):
        now = datetime.now(timezone.utc)
        bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id="t1", timestamp=now))
        bus.publish(make_event(ExecutionEventType.TASK_COMPLETED, task_id="t1", timestamp=now, data={"task_type": "mock"}))
        subscribed_collector.reset()
        snap = subscribed_collector.snapshot()
        assert len(snap.adapter_metrics) == 0

    def test_reset_does_not_affect_subscription(self, bus, collector):
        collector.subscribe(bus)
        collector.reset()
        bus.publish(make_event(ExecutionEventType.SESSION_STARTED))
        snap = collector.snapshot()
        assert snap.sessions_started == 1


# ===================================================================
# SUBSCRIPTION TESTS
# ===================================================================

class TestSubscription:
    def test_subscribe(self, bus, collector):
        collector.subscribe(bus)
        bus.publish(make_event(ExecutionEventType.SESSION_STARTED))
        assert collector.snapshot().sessions_started == 1

    def test_unsubscribe(self, bus, collector):
        collector.subscribe(bus)
        collector.unsubscribe(bus)
        bus.publish(make_event(ExecutionEventType.SESSION_STARTED))
        assert collector.snapshot().sessions_started == 0

    def test_subscribe_twice(self, bus, collector):
        collector.subscribe(bus)
        collector.subscribe(bus)
        bus.publish(make_event(ExecutionEventType.SESSION_STARTED))
        assert collector.snapshot().sessions_started == 1

    def test_unsubscribe_not_subscribed(self, bus, collector):
        collector.unsubscribe(bus)  # should not raise

    def test_subscribe_then_resubscribe(self, bus, collector):
        collector.subscribe(bus)
        collector.unsubscribe(bus)
        collector.subscribe(bus)
        bus.publish(make_event(ExecutionEventType.SESSION_STARTED))
        assert collector.snapshot().sessions_started == 1


# ===================================================================
# LIFECYCLE TESTS
# ===================================================================

class TestLifecycle:
    def test_start_does_not_raise(self, collector):
        collector.start()

    def test_stop_does_not_raise(self, collector):
        collector.stop()

    def test_start_and_stop_no_side_effects(self, bus, collector):
        collector.start()
        collector.subscribe(bus)
        bus.publish(make_event(ExecutionEventType.SESSION_STARTED))
        collector.stop()
        snap = collector.snapshot()
        assert snap.sessions_started == 1


# ===================================================================
# EDGE CASE TESTS
# ===================================================================

class TestEdgeCases:
    def test_no_events(self, subscribed_collector):
        snap = subscribed_collector.snapshot()
        assert snap.sessions_started == 0
        assert snap.tasks_started == 0
        assert snap.retries_scheduled == 0
        assert snap.average_task_duration_ms == 0.0

    def test_unrelated_events_ignored(self, bus, subscribed_collector):
        bus.publish(make_event(ExecutionEventType.APPROVAL_REQUESTED))
        bus.publish(make_event(ExecutionEventType.WAITING_STARTED))
        snap = subscribed_collector.snapshot()
        assert snap.sessions_started == 0
        assert snap.tasks_started == 0

    def test_task_skipped_no_task_started(self, bus, subscribed_collector):
        bus.publish(make_event(ExecutionEventType.TASK_SKIPPED, task_id="t1"))
        snap = subscribed_collector.snapshot()
        assert snap.tasks_skipped == 1
        assert snap.tasks_started == 0

    def test_session_events_without_tasks(self, bus, subscribed_collector):
        bus.publish(make_event(ExecutionEventType.SESSION_STARTED))
        bus.publish(make_event(ExecutionEventType.SESSION_COMPLETED))
        snap = subscribed_collector.snapshot()
        assert snap.sessions_started == 1
        assert snap.sessions_completed == 1
        assert snap.tasks_started == 0

    def test_concurrent_events_same_task(self, bus, subscribed_collector):
        now = datetime.now(timezone.utc)
        bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id="t1", timestamp=now - timedelta(seconds=1)))
        bus.publish(make_event(ExecutionEventType.TASK_COMPLETED, task_id="t1", timestamp=now, data={"task_type": "mock"}))
        bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id="t1", timestamp=now - timedelta(seconds=1)))
        bus.publish(make_event(ExecutionEventType.TASK_COMPLETED, task_id="t1", timestamp=now, data={"task_type": "mock"}))
        snap = subscribed_collector.snapshot()
        assert snap.tasks_started == 2
        assert snap.tasks_completed == 2

    def test_task_duration_same_adapter(self, bus, subscribed_collector):
        now = datetime.now(timezone.utc)
        bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id="t1", timestamp=now - timedelta(seconds=2)))
        bus.publish(make_event(ExecutionEventType.TASK_COMPLETED, task_id="t1", timestamp=now, data={"task_type": "mock"}))
        bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id="t2", timestamp=now - timedelta(seconds=4)))
        bus.publish(make_event(ExecutionEventType.TASK_COMPLETED, task_id="t2", timestamp=now, data={"task_type": "mock"}))
        snap = subscribed_collector.snapshot()
        assert snap.adapter_metrics[0].total_duration_ms > 0
        assert abs(snap.adapter_metrics[0].average_duration_ms - 3000.0) < 50

    def test_handler_not_found_does_nothing(self, collector):
        event = make_event(ExecutionEventType.WAITING_STARTED)
        collector.handle(event)  # should not raise

    def test_task_completed_without_data(self, bus, subscribed_collector):
        now = datetime.now(timezone.utc)
        bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id="t1", timestamp=now))
        bus.publish(make_event(ExecutionEventType.TASK_COMPLETED, task_id="t1", timestamp=now))
        snap = subscribed_collector.snapshot()
        # No "task_type" in data — adapter name defaults to "unknown"
        assert snap.tasks_completed == 1
        assert len(snap.adapter_metrics) == 1
        assert snap.adapter_metrics[0].adapter_name == "unknown"


# ===================================================================
# THREAD SAFETY TESTS
# ===================================================================

class TestThreadSafety:
    def test_concurrent_publish(self, bus, subscribed_collector):
        def publish_events(count: int):
            for i in range(count):
                bus.publish(make_event(ExecutionEventType.SESSION_STARTED, session_id=f"s{i}"))

        threads = [threading.Thread(target=publish_events, args=(50,)) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        snap = subscribed_collector.snapshot()
        assert snap.sessions_started == 200

    def test_concurrent_task_events(self, bus, subscribed_collector):
        now = datetime.now(timezone.utc)

        def publish_tasks(start: int, count: int):
            for i in range(start, start + count):
                bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id=f"t{i}", timestamp=now - timedelta(seconds=1)))
                bus.publish(make_event(ExecutionEventType.TASK_COMPLETED, task_id=f"t{i}", timestamp=now, data={"task_type": "mock"}))

        threads = [threading.Thread(target=publish_tasks, args=(i * 25, 25)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        snap = subscribed_collector.snapshot()
        assert snap.tasks_started == 100
        assert snap.tasks_completed == 100

    def test_concurrent_snapshot(self, bus, subscribed_collector):
        def publish_events():
            for i in range(100):
                bus.publish(make_event(ExecutionEventType.SESSION_STARTED, session_id=f"s{i}"))

        def read_snapshot():
            for _ in range(50):
                subscribed_collector.snapshot()

        threads = [threading.Thread(target=publish_events)]
        threads += [threading.Thread(target=read_snapshot) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        snap = subscribed_collector.snapshot()
        assert snap.sessions_started == 100

    def test_concurrent_reset_and_publish(self, bus, subscribed_collector):
        def publisher():
            for i in range(100):
                bus.publish(make_event(ExecutionEventType.SESSION_STARTED, session_id=f"s{i}"))

        def resetter():
            for _ in range(10):
                subscribed_collector.reset()

        threads = [threading.Thread(target=publisher), threading.Thread(target=resetter)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # Should not deadlock or raise

    def test_concurrent_mixed_events(self, bus, subscribed_collector):
        now = datetime.now(timezone.utc)

        def mixed_publisher():
            for i in range(50):
                bus.publish(make_event(ExecutionEventType.SESSION_STARTED, session_id=f"s{i}"))
                bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id=f"t{i}", timestamp=now - timedelta(seconds=1)))
                bus.publish(make_event(ExecutionEventType.TASK_COMPLETED, task_id=f"t{i}", timestamp=now, data={"task_type": "mock"}))
                bus.publish(make_event(ExecutionEventType.SESSION_COMPLETED, session_id=f"s{i}"))

        threads = [threading.Thread(target=mixed_publisher) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        snap = subscribed_collector.snapshot()
        assert snap.sessions_started == 200
        assert snap.sessions_completed == 200


# ===================================================================
# ADAPTER METRICS SNAPSHOT DATACLASS TESTS
# ===================================================================

class TestAdapterMetricsSnapshot:
    def test_dataclass_attributes(self):
        snap = AdapterMetricsSnapshot(
            adapter_name="mock",
            tasks_completed=5,
            tasks_failed=2,
            total_duration_ms=7000.0,
            task_count=7,
            average_duration_ms=1000.0,
        )
        assert snap.adapter_name == "mock"
        assert snap.tasks_completed == 5
        assert snap.tasks_failed == 2
        assert snap.total_duration_ms == 7000.0
        assert snap.task_count == 7
        assert snap.average_duration_ms == 1000.0

    def test_frozen(self):
        snap = AdapterMetricsSnapshot(adapter_name="m", tasks_completed=0, tasks_failed=0, total_duration_ms=0.0, task_count=0, average_duration_ms=0.0)
        with pytest.raises(AttributeError):
            snap.tasks_completed = 99

    def test_default_values(self):
        snap = AdapterMetricsSnapshot(adapter_name="m", tasks_completed=0, tasks_failed=0, total_duration_ms=0.0, task_count=0, average_duration_ms=0.0)
        assert snap.tasks_completed == 0

    def test_average_calculation_integrity(self):
        snap = AdapterMetricsSnapshot(adapter_name="m", tasks_completed=3, tasks_failed=1, total_duration_ms=4000.0, task_count=4, average_duration_ms=1000.0)
        assert snap.tasks_completed + snap.tasks_failed == snap.task_count
        assert snap.total_duration_ms / snap.task_count == snap.average_duration_ms


# ===================================================================
# METRICS SNAPSHOT DATACLASS TESTS
# ===================================================================

class TestMetricsSnapshotDataclass:
    def test_defaults(self):
        snap = MetricsSnapshot()
        assert snap.sessions_started == 0
        assert snap.tasks_started == 0
        assert snap.retries_scheduled == 0
        assert snap.average_task_duration_ms == 0.0
        assert snap.longest_task_id is None
        assert snap.adapter_metrics == ()

    def test_frozen(self):
        snap = MetricsSnapshot()
        with pytest.raises(AttributeError):
            snap.sessions_started = 99

    def test_adapter_metrics_tuple(self):
        a1 = AdapterMetricsSnapshot(adapter_name="a", tasks_completed=1, tasks_failed=0, total_duration_ms=100.0, task_count=1, average_duration_ms=100.0)
        snap = MetricsSnapshot(adapter_metrics=(a1,))
        assert len(snap.adapter_metrics) == 1
        assert snap.adapter_metrics[0].adapter_name == "a"

    def test_multiple_adapter_metrics_in_snapshot(self):
        adapters = [
            AdapterMetricsSnapshot(adapter_name="a1", tasks_completed=2, tasks_failed=0, total_duration_ms=200.0, task_count=2, average_duration_ms=100.0),
            AdapterMetricsSnapshot(adapter_name="a2", tasks_completed=1, tasks_failed=1, total_duration_ms=300.0, task_count=2, average_duration_ms=150.0),
        ]
        snap = MetricsSnapshot(adapter_metrics=tuple(adapters))
        assert len(snap.adapter_metrics) == 2

    def test_snapshot_sorted_adapters(self, bus, subscribed_collector):
        now = datetime.now(timezone.utc)
        bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id="t1", timestamp=now))
        bus.publish(make_event(ExecutionEventType.TASK_COMPLETED, task_id="t1", timestamp=now, data={"task_type": "z_adapter"}))
        bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id="t2", timestamp=now))
        bus.publish(make_event(ExecutionEventType.TASK_COMPLETED, task_id="t2", timestamp=now, data={"task_type": "a_adapter"}))
        snap = subscribed_collector.snapshot()
        names = [a.adapter_name for a in snap.adapter_metrics]
        assert names == ["a_adapter", "z_adapter"]

    def test_adapter_only_failures(self, bus, subscribed_collector):
        now = datetime.now(timezone.utc)
        for i in range(3):
            bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id=f"t{i}", timestamp=now - timedelta(seconds=1)))
            bus.publish(make_event(ExecutionEventType.TASK_FAILED, task_id=f"t{i}", timestamp=now, data={"task_type": "brittle"}))
        snap = subscribed_collector.snapshot()
        assert snap.adapter_metrics[0].tasks_failed == 3
        assert snap.adapter_metrics[0].tasks_completed == 0

    def test_adapter_only_successes(self, bus, subscribed_collector):
        now = datetime.now(timezone.utc)
        for i in range(5):
            bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id=f"t{i}", timestamp=now - timedelta(seconds=1)))
            bus.publish(make_event(ExecutionEventType.TASK_COMPLETED, task_id=f"t{i}", timestamp=now, data={"task_type": "reliable"}))
        snap = subscribed_collector.snapshot()
        assert snap.adapter_metrics[0].tasks_completed == 5
        assert snap.adapter_metrics[0].tasks_failed == 0

    def test_duplicate_session_completed(self, bus, subscribed_collector):
        bus.publish(make_event(ExecutionEventType.SESSION_COMPLETED))
        bus.publish(make_event(ExecutionEventType.SESSION_COMPLETED))
        snap = subscribed_collector.snapshot()
        assert snap.sessions_completed == 2

    def test_mixed_session_and_task_events(self, bus, subscribed_collector):
        now = datetime.now(timezone.utc)
        for i in range(3):
            bus.publish(make_event(ExecutionEventType.SESSION_STARTED, session_id=f"s{i}"))
            bus.publish(make_event(ExecutionEventType.TASK_STARTED, task_id=f"t{i}", timestamp=now - timedelta(seconds=1)))
            bus.publish(make_event(ExecutionEventType.TASK_COMPLETED, task_id=f"t{i}", timestamp=now, data={"task_type": "mock"}))
            bus.publish(make_event(ExecutionEventType.SESSION_COMPLETED, session_id=f"s{i}"))
        snap = subscribed_collector.snapshot()
        assert snap.sessions_started == 3
        assert snap.sessions_completed == 3
        assert snap.tasks_started == 3
        assert snap.tasks_completed == 3

    def test_retries_without_corresponding_tasks(self, bus, subscribed_collector):
        bus.publish(make_event(ExecutionEventType.TASK_RETRY_SCHEDULED, task_id="t1"))
        bus.publish(make_event(ExecutionEventType.TASK_RETRY_STARTED, task_id="t1"))
        bus.publish(make_event(ExecutionEventType.TASK_RETRY_EXHAUSTED, task_id="t1"))
        snap = subscribed_collector.snapshot()
        assert snap.retries_scheduled == 1
        assert snap.retries_started == 1
        assert snap.retries_exhausted == 1
        assert snap.tasks_started == 1  # retry_started counts as tasks_started
        assert snap.tasks_failed == 0  # no TASK_FAILED event
