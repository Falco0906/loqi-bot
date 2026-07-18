# Metrics Collector — Phase 3.6.4H

## 1. Architecture

```
┌──────────────┐   publish()   ┌──────────────────┐   handle()   ┌───────────────────┐
│  Execution   │ ────────────▶ │    EventBus      │ ──────────▶  │ MetricsCollector  │
│  Engine      │               │                  │              │                   │
│  (pipeline)  │               │  (fan-out to     │              │  session counters  │
│              │               │   subscribers)   │              │  task counters     │
└──────────────┘               └──────────────────┘              │  retry counters    │
                                                                  │  timing state      │
                                                                  │  adapter metrics   │
                                                                  └────────┬──────────┘
                                                                           │
                                                                   snapshot()
                                                                           │
                                                                           ▼
                                                                  ┌──────────────────┐
                                                                  │ MetricsSnapshot  │
                                                                  │ (frozen, read-   │
                                                                  │  only)           │
                                                                  └──────────────────┘
```

**Key constraints (verified):**
- MetricsCollector is a passive subscriber — never calls the pipeline
- Never publishes events
- Never modifies tasks
- Never influences execution
- No changes to: ExecutionPipeline, Scheduler, Dispatcher, Registry, Retry Engine, Event Bus

## 2. Files Created

### `backend/services/execution/metrics_collector.py`

**`MetricsCollector`** — the only new file. Contains:
- Event handlers for each `ExecutionEventType` of interest
- Thread-safe counters and state
- `subscribe()` / `unsubscribe()` for EventBus integration
- `start()` / `stop()` (lifecycle symmetry, no-ops)
- `reset()` — clears all counters and state
- `snapshot()` — returns immutable `MetricsSnapshot`

**`MetricsSnapshot`** (frozen dataclass) — read-only point-in-time view:

| Field | Type | Source |
|---|---|---|
| `sessions_started` | `int` | `SESSION_STARTED` count |
| `sessions_completed` | `int` | `SESSION_COMPLETED` count |
| `sessions_failed` | `int` | `SESSION_FAILED` count |
| `sessions_cancelled` | `int` | `SESSION_CANCELLED` count |
| `tasks_started` | `int` | `TASK_STARTED` + `TASK_RETRY_STARTED` count |
| `tasks_completed` | `int` | `TASK_COMPLETED` count |
| `tasks_failed` | `int` | `TASK_FAILED` count |
| `tasks_cancelled` | `int` | `TASK_CANCELLED` count |
| `tasks_skipped` | `int` | `TASK_SKIPPED` count |
| `retries_scheduled` | `int` | `TASK_RETRY_SCHEDULED` count |
| `retries_started` | `int` | `TASK_RETRY_STARTED` count |
| `retries_exhausted` | `int` | `TASK_RETRY_EXHAUSTED` count |
| `average_task_duration_ms` | `float` | Mean of all completed/failed task durations |
| `longest_task_id` | `Optional[str]` | Task ID with max duration |
| `longest_task_duration_ms` | `float` | Max duration in ms |
| `shortest_task_id` | `Optional[str]` | Task ID with min duration |
| `shortest_task_duration_ms` | `float` | Min duration in ms |
| `adapter_metrics` | `tuple[AdapterMetricsSnapshot, ...]` | Per-adapter stats (sorted by name) |

**`AdapterMetricsSnapshot`** (frozen dataclass):

| Field | Type | Source |
|---|---|---|
| `adapter_name` | `str` | From event `data["task_type"]` |
| `tasks_completed` | `int` | `TASK_COMPLETED` for this adapter |
| `tasks_failed` | `int` | `TASK_FAILED` for this adapter |
| `total_duration_ms` | `float` | Sum of all task durations |
| `task_count` | `int` | Total tasks for this adapter |
| `average_duration_ms` | `float` | `total_duration_ms / task_count` |

## 3. Event → Metric Mapping

| Event | Counters incremented |
|---|---|
| `SESSION_STARTED` | `sessions_started` |
| `SESSION_COMPLETED` | `sessions_completed` |
| `SESSION_FAILED` | `sessions_failed` |
| `SESSION_CANCELLED` | `sessions_cancelled` |
| `TASK_STARTED` | `tasks_started`, record `task_start_time[task_id]` |
| `TASK_RETRY_STARTED` | `tasks_started`, `retries_started`, record `task_start_time[task_id]` |
| `TASK_COMPLETED` | `tasks_completed`, compute duration, update adapter |
| `TASK_FAILED` | `tasks_failed`, compute duration, update adapter |
| `TASK_SKIPPED` | `tasks_skipped` |
| `TASK_CANCELLED` | `tasks_cancelled` |
| `TASK_RETRY_SCHEDULED` | `retries_scheduled` |
| `TASK_RETRY_EXHAUSTED` | `retries_exhausted` |

## 4. Timing Calculation

Duration is computed at `TASK_COMPLETED` or `TASK_FAILED`:

```
duration_ms = (event.timestamp - task_start_time[task_id]).total_seconds() * 1000
```

- `task_start_time` is recorded on `TASK_STARTED` or `TASK_RETRY_STARTED`
- The start time is popped from the dict when the duration is recorded
- If the start time is missing (e.g., event ordering issue), duration defaults to 0.0

Average, longest, and shortest are computed on `snapshot()` from the stored per-task durations dict.

## 5. Adapter Metrics

Adapter metrics use `event.data["task_type"]` as the adapter name. This comes from the pipeline's event data — the collector never queries adapters directly.

```
adapter_name = event.data.get("task_type", "unknown")
```

Per adapter:
- `tasks_completed`: count of `TASK_COMPLETED` events for this adapter
- `tasks_failed`: count of `TASK_FAILED` events for this adapter
- `total_duration_ms`: sum of all task durations for this adapter
- `task_count`: total tasks (completed + failed)
- `average_duration_ms`: `total_duration_ms / task_count`

Adapter snapshots are sorted alphabetically by name in the snapshot for deterministic output.

## 6. Snapshot Design

`snapshot()` returns an immutable frozen dataclass. Internal mutable state (`_task_start_times`, `_adapter_metrics` dict) is never exposed. The snapshot is a pure value object.

Consumers (dashboards, test assertions, log formatters) access only the snapshot. There is no way to modify internal collector state through the snapshot.

Thread safety: the snapshot is built entirely under the collector's `_lock`. All counters, dicts, and computed values are read atomically.

## 7. Thread Safety

- A single `threading.Lock` protects all mutable state
- Every event handler acquires the lock before mutating counters/dicts
- `snapshot()` acquires the lock and builds the snapshot atomically
- `reset()` acquires the lock and clears everything
- The lock is never held during external calls (the handler just updates state, then returns)
- Concurrent publishing is safe: verified by 5 thread safety tests with up to 200 concurrent events

## 8. Failure Isolation

The Event Bus already wraps each subscriber's `handle()` call in `try/except`. The MetricsCollector also internally wraps its handler dispatch in `try/except` as a defensive measure. Even if an unexpected exception occurs, it never propagates to the pipeline.

## 9. Test Coverage

### File: `backend/tests/test_metrics_collector.py` — 91 tests

| Class | Tests | Coverage |
|---|---|---|
| `TestSessionMetrics` | 10 | started, completed, failed, cancelled, multiples, only started, none, without start, all types |
| `TestTaskMetrics` | 10 | started, completed, failed, skipped, multiples, mixed results, cancelled separate counter, none, without start |
| `TestRetryMetrics` | 8 | scheduled, started, exhausted, also tasks_started, multiples, none, full flow, exhaustion flow |
| `TestTimingMetrics` | 9 | duration, zero-duration, average, longest, shortest, multiple tasks, failed task duration, no tasks |
| `TestAdapterMetrics` | 8 | single success, single failure, multiple adapters, averages, none, unknown adapter, counts |
| `TestSnapshot` | 10 | is dataclass, values, immutable, no internal state, adapter immutable, consistency, retries, after reset |
| `TestReset` | 6 | counters, then continue, timing, adapter, subscription preserved |
| `TestSubscription` | 5 | subscribe, unsubscribe, subscribe twice, not subscribed, resubscribe |
| `TestLifecycle` | 3 | start, stop, start+stop no side effects |
| `TestEdgeCases` | 9 | no events, unrelated ignored, skip without start, session without tasks, same task twice, adapter durations, handler not found, no data, duplicate session |
| `TestThreadSafety` | 5 | concurrent publish, concurrent tasks, concurrent snapshot, concurrent reset, mixed 4-thread |
| `TestAdapterMetricsSnapshot` | 4 | attributes, frozen, defaults, integrity |
| `TestMetricsSnapshotDataclass` | 4 | defaults, frozen, adapter tuple, sorted adapters |

Total metrics tests: **91**

Total execution tests: **759** (includes foundation, scheduler, dispatcher, adapter registry, execution loop, retry engine, event bus, metrics collector, and recovery manager tests).

## 10. Verification

- Metrics collector tests: `python3 -m pytest backend/tests/test_metrics_collector.py` → **91 passed, 0 failed**
- All execution tests: `python3 -m pytest backend/tests/test_execution_*.py backend/tests/test_retry_engine.py backend/tests/test_event_bus.py backend/tests/test_metrics_collector.py backend/tests/test_recovery_manager.py` → **759 passed, 0 failed**
- `py_compile backend/services/execution/*.py` → **clean**

## 11. Remaining Work for Phase 3.6.4I — Recovery & Approval Integration

Phase 3.6.4I should focus on:
- **Recovery**: resume sessions after engine restart using persisted session state
- **Approval integration**: wire approval/rejection events through the pipeline to the state machine
- The Metrics Collector is complete and requires no changes for these phases
- The Event Bus is complete and ready for any additional subscribers (logging, dashboards, audit)
