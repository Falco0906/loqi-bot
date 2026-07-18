# Event Bus — Phase 3.6.4G

## 1. Architecture

```
┌──────────────────┐     publish()     ┌──────────────────────┐
│  ExecutionEngine │ ────────────────▶ │       EventBus       │
│  (pipeline)      │                   │                      │
│                  │                   │  ┌─────────────────┐ │
│  Calls only      │                   │  │ Subscriber list │ │
│  event_bus.      │                   │  │ (thread-safe)   │ │
│  publish(...)    │                   │  └─────────────────┘ │
└──────────────────┘                   └──────┬───────────────┘
                                              │
                        ┌─────────────────────┼─────────────────────┐
                        │                     │                     │
                   ┌────▼────┐          ┌─────▼─────┐         ┌────▼────┐
                   │Metrics  │          │ Logger    │         │Audit   │
                   │Collector│          │Subscriber │         │System  │
                   └─────────┘          └───────────┘         └─────────┘
```

**Key constraints (verified):**
- Event Bus does **not** import Scheduler, Dispatcher, or Adapter Registry
- Subscribers do **not** know about the execution pipeline
- The pipeline calls only `event_bus.publish(...)` — no subscriber logic lives in the pipeline
- No existing subsystem gained new responsibilities beyond publishing events

## 2. Files Created

### `backend/services/execution/event_bus.py`

**`EventSubscriber` (Protocol):**

```python
class EventSubscriber(Protocol):
    def handle(self, event: ExecutionEvent) -> None: ...
```

A simple protocol. Any object with a `handle(event)` method is a valid subscriber. No base class required.

**`EventBus`:**

| Method | Description |
|---|---|
| `subscribe(subscriber)` | Register a subscriber. Duplicates are silently ignored. |
| `unsubscribe(subscriber)` | Unregister a subscriber. Silently ignores if not registered. |
| `publish(event)` | Publish to all subscribers (snapshot under lock, iterate outside). Sets `event.sequence`. |
| `clear()` | Remove all subscribers. |
| `subscriber_count` | Number of registered subscribers (property). |

Thread safety: `threading.Lock` guards `_subscribers` mutations and `_sequence` counter. `publish()` takes a snapshot under the lock, then iterates unlocked to avoid holding the lock during subscriber execution.

Failure isolation: each subscriber is wrapped in `try/except`. A crashing subscriber does not affect execution, retries, or other subscribers.

## 3. Files Modified

### `backend/services/execution/enums.py`

Added three event types to `ExecutionEventType`:

| Enum | Value |
|---|---|
| `TASK_RETRY_SCHEDULED` | `"task.retry_scheduled"` |
| `TASK_RETRY_STARTED` | `"task.retry_started"` |
| `TASK_RETRY_EXHAUSTED` | `"task.retry_exhausted"` |

### `backend/services/execution/execution_pipeline.py`

**`ExecutionEngine.__init__`** — accepts optional `event_bus` parameter. Defaults to a new `EventBus()` (backward compatible).

Pipeline publishes events at these lifecycle boundaries:

| Pipeline method | Events published |
|---|---|
| `execute()` | `SESSION_STARTED` |
| `_execute_task()` | `TASK_READY`, `TASK_STARTED` or `TASK_RETRY_STARTED` |
| `_handle_success()` | `TASK_COMPLETED` |
| `_handle_failure()` (permanent) | `TASK_FAILED`, `TASK_SKIPPED` (for downstream), and `TASK_RETRY_EXHAUSTED` if retries were attempted |
| `_handle_failure()` (retry) | `TASK_RETRY_SCHEDULED` |
| `_run_scheduler()` (after loop) | `SESSION_COMPLETED` or `SESSION_FAILED` |
| `cancel()` | `TASK_CANCELLED` (per task), `SESSION_CANCELLED` |
| `reject()` | `TASK_SKIPPED` |

### `backend/services/execution/__init__.py`

Added `EventBus` and `EventSubscriber` to exports.

## 4. Event Lifecycle

### Success flow

```
execute()
  │
  ├── SESSION_STARTED
  │
  ├── TASK_READY
  ├── TASK_STARTED
  ├── TASK_COMPLETED
  │
  └── SESSION_COMPLETED
```

### Permanent failure flow

```
execute()
  │
  ├── SESSION_STARTED
  │
  ├── TASK_READY
  ├── TASK_STARTED
  ├── TASK_FAILED
  ├── TASK_SKIPPED (downstream tasks)
  │
  └── SESSION_FAILED
```

### Retry → success flow

```
execute()
  │
  ├── SESSION_STARTED
  │
  ├── TASK_READY
  ├── TASK_STARTED          (first attempt)
  ├── TASK_RETRY_SCHEDULED  (transient failure)
  │
  ├── TASK_READY
  ├── TASK_RETRY_STARTED    (retry attempt)
  ├── TASK_COMPLETED
  │
  └── SESSION_COMPLETED
```

### Retry → exhaustion flow

```
execute()
  │
  ├── SESSION_STARTED
  │
  ├── TASK_READY
  ├── TASK_STARTED          (first attempt)
  ├── TASK_RETRY_SCHEDULED  (transient failure #1)
  │
  ├── TASK_READY
  ├── TASK_RETRY_STARTED    (retry attempt #1)
  ├── TASK_RETRY_SCHEDULED  (transient failure #2)
  │
  ├── TASK_READY
  ├── TASK_RETRY_STARTED    (retry attempt #2 — final)
  ├── TASK_RETRY_EXHAUSTED  (no more attempts)
  ├── TASK_FAILED
  │
  └── SESSION_FAILED
```

### Cancel flow

```
cancel()
  │
  ├── TASK_CANCELLED   (per active task)
  │
  └── SESSION_CANCELLED
```

## 5. Subscriber Model

Subscribers implement the `EventSubscriber` protocol:

```python
class MetricsCollector:
    def handle(self, event: ExecutionEvent) -> None:
        if event.event_type == ExecutionEventType.TASK_COMPLETED:
            self.increment_completed()
```

Registration:

```python
bus = EventBus()
bus.subscribe(MetricsCollector())
```

Subscribers can be added or removed at any time, including during publish. The `publish()` method takes a snapshot of the subscriber list under the lock, so mutations during iteration do not affect the current publish cycle.

## 6. Failure Isolation

Each subscriber is called independently. A subscriber that raises an exception is caught and logged — it never propagates:

```python
for subscriber in subscribers:
    try:
        subscriber.handle(event)
    except Exception:
        logger.exception(...)
```

This guarantees:
- Execution continues if any subscriber fails
- Retries are not interrupted by subscriber failures
- Other subscribers still receive the event
- The pipeline never sees subscriber exceptions

## 7. Thread Safety

- `subscribe()`, `unsubscribe()`, `clear()`: acquire `self._lock`
- `publish()`: acquires lock to increment sequence and snapshot subscribers, then iterates without the lock
- `subscriber_count`: acquires lock to access `len(self._subscribers)`

This allows concurrent publishing and subscription. The lock is never held during subscriber execution, avoiding deadlocks with slow subscribers.

## 8. Extension Points

Future subscribers for Phase 3.6.4H (Metrics Collector) and beyond:

| Future consumer | Events of interest |
|---|---|
| Metrics Collector | All events |
| Logger | All events |
| Dashboard SSE stream | All events |
| Audit system | `SESSION_STARTED`, `SESSION_COMPLETED`, `SESSION_FAILED` |
| Alerting | `TASK_FAILED`, `TASK_RETRY_EXHAUSTED` |
| Analytics | `TASK_COMPLETED`, `TASK_SKIPPED` |

## 9. Test Coverage

### File: `backend/tests/test_event_bus.py` — 97 tests

| Class | Tests | Coverage |
|---|---|---|
| `TestEventBusSubscribe` | 4 | subscribe, multiple, duplicate, same object |
| `TestEventBusUnsubscribe` | 4 | unsub, not subscribed, one of many, all |
| `TestEventBusClear` | 3 | clear, clear empty, clear then add |
| `TestEventBusPublish` | 9 | no subscribers, single, multiple, multiple events, data preserved, sequence, event ID, after unsubscribe |
| `TestEventBusSubscriberOrder` | 1 | call order |
| `TestEventBusExceptionIsolation` | 3 | failing doesn't block, all fail, mixed |
| `TestEventBusSubscriberMutation` | 3 | subscribe during, unsubscribe during, clear during |
| `TestEventBusThreadSafety` | 3 | concurrent publish, concurrent subscribe/unsub, concurrent publish+subscribe |
| `TestPipelineSessionStarted` | 3 | event, before task events, plan_id |
| `TestPipelineTaskStarted` | 3 | event, attempt zero, task type |
| `TestPipelineTaskCompleted` | 3 | event, after started, not on failure |
| `TestPipelineTaskFailed` | 4 | event, error data, error type, not on success |
| `TestPipelineSessionCompleted` | 4 | event, last event, status, not on failure |
| `TestPipelineSessionFailed` | 4 | event, status, not on success, last event |
| `TestPipelineTaskSkipped` | 2 | upstream failure, no deps |
| `TestPipelineTaskReady` | 2 | before started, task_id |
| `TestPipelineRetryScheduled` | 4 | transient, data, not on success, not on permanent |
| `TestPipelineRetryStarted` | 3 | retry execution, attempt > 0, not on first |
| `TestPipelineRetryExhausted` | 3 | exhaustion, not on recovery, not on perm first attempt |
| `TestPipelineEventFlow` | 6 | success flow, failure flow, retry exhaustion flow, retry success flow, event order success, event order failure |
| `TestPipelineMultipleTasks` | 2 | 2 independent, DAG chain |
| `TestPipelineSubscriberIsolation` | 4 | failing subscriber, retry, exhaustion, multiple one fails |
| `TestPipelineCancelEvents` | 2 | TASK_CANCELLED, SESSION_CANCELLED |
| `TestPipelineRejectEvents` | 1 | TASK_SKIPPED via reject |
| `TestExecutionEventDefaults` | 5 | default id, timestamp, task_id None, data empty, sequence 0 |
| `TestAllEventTypesProduced` | 14 | every event type verified emitted from pipeline |

### Total test counts:

| File | Tests |
|---|---|
| `test_execution_foundation.py` | 88 |
| `test_execution_scheduler.py` | 105 |
| `test_execution_dispatcher.py` | 72 |
| `test_execution_adapter_registry.py` | 70 |
| `test_execution_loop.py` | 86 |
| `test_retry_engine.py` | 73 |
| `test_planner.py` | 58 |
| `test_event_bus.py` | 97 |
| **Total** | **649** |

## 10. Verification

- Event bus tests: `python3 -m pytest backend/tests/test_event_bus.py` → **97 passed, 0 failed**
- All execution tests: `python3 -m pytest backend/tests/test_execution_*.py backend/tests/test_retry_engine.py backend/tests/test_planner.py backend/tests/test_event_bus.py` → **649 passed, 0 failed**
- `py_compile` over all execution modules: **clean**

## 11. Remaining Work for Phase 3.6.4H — Metrics Collector

The Metrics Collector should subscribe to the event bus and maintain aggregate counters. It is a subscriber — no pipeline changes needed.

| Metric | Derivation |
|---|---|
| `total_tasks` | Count `TASK_STARTED` events |
| `completed_tasks` | Count `TASK_COMPLETED` events |
| `failed_tasks` | Count `TASK_FAILED` events where no `TASK_RETRY_EXHAUSTED` preceded |
| `skipped_tasks` | Count `TASK_SKIPPED` events |
| `cancelled_tasks` | Count `TASK_CANCELLED` events |
| `total_attempts` | Count `TASK_STARTED` + `TASK_RETRY_STARTED` events |
| `total_retries` | Count `TASK_RETRY_STARTED` events |
| `retry_exhaustions` | Count `TASK_RETRY_EXHAUSTED` events |
| `retry_recoveries` | Count `TASK_COMPLETED` events where a `TASK_RETRY_STARTED` preceded |

The collector should be initialized per-session and produce an `ExecutionMetrics` dataclass at session end.
