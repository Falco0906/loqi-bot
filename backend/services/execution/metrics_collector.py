"""Metrics Collector — passive event-driven statistics for the execution engine.

The Metrics Collector derives execution statistics exclusively by subscribing
to EventBus events. It never influences execution, never calls the pipeline,
never modifies tasks, and never publishes events.

Architectural constraints:
  - ExecutionPipeline: unchanged
  - Scheduler: unchanged
  - Dispatcher: unchanged
  - Registry: unchanged
  - Retry Engine: unchanged
  - Event Bus: unchanged
  - MetricsCollector: subscribes to EventBus, never called directly by pipeline
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from services.execution.enums import ExecutionEventType
from services.execution.event_bus import EventBus
from services.execution.execution_models import ExecutionEvent


@dataclass(frozen=True)
class AdapterMetricsSnapshot:
    """Immutable per-adapter metric snapshot."""

    adapter_name: str
    tasks_completed: int
    tasks_failed: int
    total_duration_ms: float
    task_count: int
    average_duration_ms: float


@dataclass(frozen=True)
class MetricsSnapshot:
    """Immutable point-in-time snapshot of all collected metrics.

    All fields are read-only. Dashboards, tests, and log formatters
    consume this object without accessing mutable internal state.
    """

    sessions_started: int = 0
    sessions_completed: int = 0
    sessions_failed: int = 0
    sessions_cancelled: int = 0

    tasks_started: int = 0
    tasks_completed: int = 0
    tasks_failed: int = 0
    tasks_skipped: int = 0
    tasks_cancelled: int = 0

    retries_scheduled: int = 0
    retries_started: int = 0
    retries_exhausted: int = 0

    average_task_duration_ms: float = 0.0
    longest_task_id: Optional[str] = None
    longest_task_duration_ms: float = 0.0
    shortest_task_id: Optional[str] = None
    shortest_task_duration_ms: float = 0.0

    adapter_metrics: tuple[AdapterMetricsSnapshot, ...] = ()


class MetricsCollector:
    """Passive event-driven metrics collector.

    Subscribe to an EventBus and receives all execution lifecycle events.
    Derives session, task, retry, timing, and per-adapter statistics.

    Thread-safe: all mutable state is protected by a single lock.
    """

    def __init__(self):
        self._lock = threading.Lock()

        # Session counters
        self._sessions_started: int = 0
        self._sessions_completed: int = 0
        self._sessions_failed: int = 0
        self._sessions_cancelled: int = 0

        # Task counters
        self._tasks_started: int = 0
        self._tasks_completed: int = 0
        self._tasks_failed: int = 0
        self._tasks_skipped: int = 0
        self._tasks_cancelled: int = 0

        # Retry counters
        self._retries_scheduled: int = 0
        self._retries_started: int = 0
        self._retries_exhausted: int = 0

        # Timing state
        self._task_start_times: dict[str, datetime] = {}
        self._session_start_times: dict[str, datetime] = {}
        self._task_durations: dict[str, float] = {}

        # Adapter metrics: adapter_name -> dict
        self._adapter_metrics: dict[str, dict] = {}

        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Mark the collector as running. No-op; provided for lifecycle symmetry."""
        self._running = True

    def stop(self) -> None:
        """Mark the collector as stopped. No-op; provided for lifecycle symmetry."""
        self._running = False

    def reset(self) -> None:
        """Reset all counters and timing state to zero."""
        with self._lock:
            self._sessions_started = 0
            self._sessions_completed = 0
            self._sessions_failed = 0
            self._sessions_cancelled = 0
            self._tasks_started = 0
            self._tasks_completed = 0
            self._tasks_failed = 0
            self._tasks_skipped = 0
            self._tasks_cancelled = 0
            self._retries_scheduled = 0
            self._retries_started = 0
            self._retries_exhausted = 0
            self._task_start_times.clear()
            self._session_start_times.clear()
            self._task_durations.clear()
            self._adapter_metrics.clear()

    # ------------------------------------------------------------------
    # Event Bus Integration
    # ------------------------------------------------------------------

    def subscribe(self, bus: EventBus) -> None:
        """Subscribe this collector to an EventBus."""
        bus.subscribe(self)

    def unsubscribe(self, bus: EventBus) -> None:
        """Unsubscribe this collector from an EventBus."""
        bus.unsubscribe(self)

    # ------------------------------------------------------------------
    # EventSubscriber Protocol
    # ------------------------------------------------------------------

    def handle(self, event: ExecutionEvent) -> None:
        """Process a single execution event and update metrics.

        This method is called by the EventBus for each published event.
        It must never raise (the EventBus already isolates subscriber
        exceptions, but defensive coding is good practice).
        """
        handler = self._get_handler(event.event_type)
        if handler is not None:
            try:
                handler(event)
            except Exception:
                pass  # EventBus already wraps in try/except

    def _get_handler(self, event_type: ExecutionEventType):
        handlers = {
            ExecutionEventType.SESSION_STARTED: self._on_session_started,
            ExecutionEventType.SESSION_COMPLETED: self._on_session_completed,
            ExecutionEventType.SESSION_FAILED: self._on_session_failed,
            ExecutionEventType.SESSION_CANCELLED: self._on_session_cancelled,
            ExecutionEventType.TASK_STARTED: self._on_task_started,
            ExecutionEventType.TASK_RETRY_STARTED: self._on_task_retry_started,
            ExecutionEventType.TASK_COMPLETED: self._on_task_completed,
            ExecutionEventType.TASK_FAILED: self._on_task_failed,
            ExecutionEventType.TASK_SKIPPED: self._on_task_skipped,
            ExecutionEventType.TASK_CANCELLED: self._on_task_cancelled,
            ExecutionEventType.TASK_RETRY_SCHEDULED: self._on_retry_scheduled,
            ExecutionEventType.TASK_RETRY_EXHAUSTED: self._on_retry_exhausted,
        }
        return handlers.get(event_type)

    # ------------------------------------------------------------------
    # Session Event Handlers
    # ------------------------------------------------------------------

    def _on_session_started(self, event: ExecutionEvent) -> None:
        with self._lock:
            self._sessions_started += 1
            self._session_start_times[event.session_id] = event.timestamp

    def _on_session_completed(self, event: ExecutionEvent) -> None:
        with self._lock:
            self._sessions_completed += 1

    def _on_session_failed(self, event: ExecutionEvent) -> None:
        with self._lock:
            self._sessions_failed += 1

    def _on_session_cancelled(self, event: ExecutionEvent) -> None:
        with self._lock:
            self._sessions_cancelled += 1

    # ------------------------------------------------------------------
    # Task Event Handlers
    # ------------------------------------------------------------------

    def _on_task_started(self, event: ExecutionEvent) -> None:
        with self._lock:
            self._tasks_started += 1
            if event.task_id:
                self._task_start_times[event.task_id] = event.timestamp

    def _on_task_retry_started(self, event: ExecutionEvent) -> None:
        with self._lock:
            self._tasks_started += 1
            self._retries_started += 1
            if event.task_id:
                self._task_start_times[event.task_id] = event.timestamp

    def _on_task_completed(self, event: ExecutionEvent) -> None:
        with self._lock:
            self._tasks_completed += 1
            self._record_task_duration(event)
            self._record_adapter_metric(event, success=True)

    def _on_task_failed(self, event: ExecutionEvent) -> None:
        with self._lock:
            self._tasks_failed += 1
            self._record_task_duration(event)
            self._record_adapter_metric(event, success=False)

    def _on_task_skipped(self, event: ExecutionEvent) -> None:
        with self._lock:
            self._tasks_skipped += 1

    def _on_task_cancelled(self, event: ExecutionEvent) -> None:
        with self._lock:
            self._tasks_cancelled += 1

    # ------------------------------------------------------------------
    # Retry Event Handlers
    # ------------------------------------------------------------------

    def _on_retry_scheduled(self, event: ExecutionEvent) -> None:
        with self._lock:
            self._retries_scheduled += 1

    def _on_retry_exhausted(self, event: ExecutionEvent) -> None:
        with self._lock:
            self._retries_exhausted += 1

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _record_task_duration(self, event: ExecutionEvent) -> None:
        """Record task duration from start time to event timestamp."""
        task_id = event.task_id
        if task_id is None:
            return
        start = self._task_start_times.pop(task_id, None)
        if start is None:
            return
        duration = (event.timestamp - start).total_seconds() * 1000
        self._task_durations[task_id] = duration

    def _record_adapter_metric(self, event: ExecutionEvent, success: bool) -> None:
        """Update per-adapter metrics from a task completion/failure event.

        TODO: Use ``adapter_name`` from event data when the pipeline
        includes it in TASK_COMPLETED / TASK_FAILED payloads. Currently
        falls back to ``task_type`` because the event data does not
        carry the resolved adapter identity.
        """
        task_type = event.data.get("task_type", "unknown")
        if task_type not in self._adapter_metrics:
            self._adapter_metrics[task_type] = {
                "tasks_completed": 0,
                "tasks_failed": 0,
                "total_duration_ms": 0.0,
                "task_count": 0,
            }
        entry = self._adapter_metrics[task_type]
        duration = self._task_durations.get(event.task_id or "", 0.0)
        if success:
            entry["tasks_completed"] += 1
        else:
            entry["tasks_failed"] += 1
        entry["total_duration_ms"] += duration
        entry["task_count"] += 1

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> MetricsSnapshot:
        """Return an immutable point-in-time snapshot of all metrics.

        Thread-safe: reads all counters and timing state under the lock.
        """
        with self._lock:
            return self._build_snapshot()

    def _build_snapshot(self) -> MetricsSnapshot:
        """Build a MetricsSnapshot from current state (caller must hold lock)."""
        task_count = self._tasks_completed + self._tasks_failed
        all_durations = list(self._task_durations.values())
        total_duration = sum(all_durations)
        average_duration = total_duration / len(all_durations) if all_durations else 0.0

        longest_id = None
        longest_dur = 0.0
        shortest_id = None
        shortest_dur = 0.0
        for tid, dur in self._task_durations.items():
            if dur > longest_dur:
                longest_dur = dur
                longest_id = tid
            if shortest_id is None or dur < shortest_dur:
                shortest_dur = dur
                shortest_id = tid

        adapter_snapshots = []
        for name, entry in sorted(self._adapter_metrics.items()):
            total = entry["total_duration_ms"]
            count = entry["task_count"]
            avg = total / count if count > 0 else 0.0
            adapter_snapshots.append(
                AdapterMetricsSnapshot(
                    adapter_name=name,
                    tasks_completed=entry["tasks_completed"],
                    tasks_failed=entry["tasks_failed"],
                    total_duration_ms=total,
                    task_count=count,
                    average_duration_ms=avg,
                )
            )

        return MetricsSnapshot(
            sessions_started=self._sessions_started,
            sessions_completed=self._sessions_completed,
            sessions_failed=self._sessions_failed,
            sessions_cancelled=self._sessions_cancelled,
            tasks_started=self._tasks_started,
            tasks_completed=self._tasks_completed,
            tasks_failed=self._tasks_failed,
            tasks_skipped=self._tasks_skipped,
            tasks_cancelled=self._tasks_cancelled,
            retries_scheduled=self._retries_scheduled,
            retries_started=self._retries_started,
            retries_exhausted=self._retries_exhausted,
            average_task_duration_ms=average_duration,
            longest_task_id=longest_id,
            longest_task_duration_ms=longest_dur,
            shortest_task_id=shortest_id,
            shortest_task_duration_ms=shortest_dur,
            adapter_metrics=tuple(adapter_snapshots),
        )
