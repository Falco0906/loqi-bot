# Retry Engine — Phase 3.6.4F

## 1. Files Modified

### `backend/services/execution/execution_pipeline.py`

**`execute()`** — added optional `retry_policy: Optional[RetryPolicy]` parameter. When provided, overrides `RetryPolicy.default()` for all tasks in the session.

**`_initialize()`** — accepts optional `retry_policy` parameter forwarded from `execute()`.

**`_handle_result()`** — refactored from `@staticmethod` to instance method. Forks into `_handle_success()` / `_handle_failure()`.

**New methods:**

| Method | Visibility | Role |
|---|---|---|
| `_handle_success()` | instance | Transitions COMPLETED, calls `scheduler.mark_completed()` |
| `_handle_failure()` | instance | Calls `_should_retry()`. Retries via `_schedule_retry()` or fails permanently via `StateMachine.transition_task(FAILED)` + `scheduler.mark_failed()` |
| `_should_retry()` | static | Evaluates `RetryDecision` from task + result |
| `_schedule_retry()` | static | Increments `task.attempts`, transitions RUNNING→RETRYING→WAITING, sleeps, calls `scheduler.requeue()` |

### `backend/services/execution/execution_models.py`

**New dataclass:**

```python
@dataclass
class RetryDecision:
    should_retry: bool = False
    delay_seconds: float = 0.0
    remaining_attempts: int = 0
```

Encapsulates retry calculations so eventing and metrics layers can observe why a retry occurred without scattering retry logic throughout the pipeline.

### `backend/services/execution/scheduler.py`

**New method:**

```python
def requeue(self, task_id: str) -> None:
```

Generic retry-unaware operation: releases the running slot, transitions the task to READY via `StateMachine`, and appends it to the ready queue. The scheduler does not track why the task is being requeued.

### `backend/services/execution/state_machine.py`

Added `TaskState.WAITING` to the `RETRYING` transition set:

```
RETRYING → {READY, WAITING, FAILED, CANCELLED}
```

The full retry cycle transitions are now:

```
RUNNING → RETRYING → WAITING → READY → RUNNING
```

All were already permitted by the existing transition table except `RETRYING → WAITING`.

---

## 2. Retry Lifecycle

### Success path (unchanged)

```
READY → RUNNING → COMPLETED
```

### Permanent failure (unchanged)

```
READY → RUNNING → FAILED
```

### Transient failure — retry

```
READY → RUNNING → RETRYING → WAITING → (sleep) → READY → RUNNING → COMPLETED
```

### Transient failure — exhaustion

```
READY → RUNNING → RETRYING → WAITING → (sleep) → READY → RUNNING → ...
                                                              ↓
                                                          FAILED
```

---

## 3. Retry Decision Logic

```
result.success == True         → no retry (handled by _handle_success)
result.error_type not in policy.retryable_error_types → no retry (non-retryable error)
task.attempts + 1 >= task.max_attempts → no retry (exhausted)
otherwise                      → retry with computed backoff delay
```

**Backoff calculation** (implemented in `ExecutionEngine._compute_backoff`):

```
raw_delay = backoff_base_seconds * (backoff_multiplier ** task.attempts)
capped    = min(raw_delay, max_backoff_seconds)
final     = capped * random.uniform(0.5, 1.5)  if jitter=True
```

All `RetryPolicy` fields are honored:
- `backoff_base_seconds` — initial delay
- `backoff_multiplier` — exponential factor (applied per prior attempt)
- `max_backoff_seconds` — ceiling on the raw exponential delay
- `jitter` — when True, adds ±50% uniform random jitter to the capped delay
- `retryable_error_types` — replaces the old hardcoded `"transient"` check

**Retry exhaustion boundary:** `max_attempts` includes the initial execution. With `max_attempts=3`:
- Attempt 0 (initial): `remaining = 3 - 1 = 2` → retry allowed
- Attempt 1: `remaining = 3 - 2 = 1` → retry allowed  
- Attempt 2: `remaining = 3 - 3 = 0` → retry **not** allowed → FAILED

Total executions = 3 (initial + 2 retries).

---

## 4. Execution Flow with Retry

```
_execute_task(task, session, scheduler, resolver)
  │
  ├── StateMachine.transition_task(task, RUNNING)
  ├── result = await _dispatch_safe(task, context, resolver)
  └── await _handle_result(task, scheduler, result)
        │
        ├── result.success == True
        │     └── _handle_success → COMPLETED → scheduler.mark_completed()
        │
        └── result.success == False
              └── _handle_failure
                    │
                    ├── _should_retry → RetryDecision
                    │     │
                    │     ├── should_retry=True
                    │     │     └── _schedule_retry
                    │     │           ├── transition RUNNING → RETRYING
                    │     │           ├── transition RETRYING → WAITING
                    │     │           ├── task.attempts += 1   ← after successful transitions
                    │     │           ├── await asyncio.sleep(delay)
                    │     │           └── scheduler.requeue(task.id)
                    │     │                  ├── _running.discard(task.id)
                    │     │                  ├── transition WAITING → READY
                    │     │                  └── _ready_queue.append(task.id)
                    │     │
                    │     └── should_retry=False
                    │           └── transition RUNNING → FAILED
                    │               scheduler.mark_failed(task.id)
                    │
                    └── (returned to execution loop)
```

---

## 5. Scheduler Interaction

The scheduler remains retry-unaware. The `requeue()` method is a generic scheduling operation:

```python
def requeue(self, task_id: str) -> None:
    self._running.discard(task_id)
    etask = self.session.tasks[task_id]
    StateMachine.transition_task(etask, TaskState.READY)
    self._ready_queue.append(task_id)
```

The scheduler sees a READY task in the queue with no knowledge of retries. All retry logic lives in the pipeline.

---

## 6. Retry Policy Behavior

| Policy field | Used by retry engine |
|---|---|---|
| `max_attempts` | Yes — determines exhaustion boundary |
| `backoff_base_seconds` | Yes — initial delay in backoff calculation |
| `backoff_multiplier` | Yes — exponential factor in `delay = base × (multiplier ** attempts)` |
| `max_backoff_seconds` | Yes — ceiling on raw exponential delay before jitter |
| `jitter` | Yes — adds ±50% uniform random jitter when True |
| `retryable_error_types` | Yes — replaces hardcoded `"transient"` check |

---

## 7. Tests

### New file: `backend/tests/test_retry_engine.py` — 73 tests

| Class | Tests | Coverage |
|---|---|---|
| `TestRetryDecision` | 10 | `_should_retry` unit tests: success, permanent, transient, exhaustion, last attempt, remaining counts, delay from policy, `RetryDecision` dataclass |
| `TestNoRetryOnSuccess` | 4 | Success stays COMPLETED, no RETRYING/WAITING state, result correct, attempts not incremented |
| `TestPermanentFailure` | 7 | FAILED state, no retry transitions, error preserved, attempts unchanged, downstream blocked, session FAILED, end_time |
| `TestTransientSingleRetrySucceeds` | 5 | Retry then success, COMPLETED final, attempts incremented, result shows success |
| `TestTransientRetrySucceedsOnSecondAttempt` | 3 | Fail twice then succeed, 2 retries, final COMPLETED |
| `TestTransientRetrySucceedsOnFinalAttempt` | 2 | Fail to last allowed attempt then succeed |
| `TestRetryExhaustion` | 6 | FAILED after exhaustion, attempts == max-1, downstream blocked only after exhaustion |
| `TestRetryTiming` | 3 | Zero delay, delay honored, different delay values |
| `TestRetryPolicyVariants` | 5 | Default max=3, max=1 unit test, zero delay execution, custom max, default policy |
| `TestMixedDagWithRetry` | 6 | Retry + independent, retry fail + downstream skip, retry recover + downstream exec, independent unaffected, chain retry middle recovers, chain retry middle exhausts |
| `TestEdgeCases` | 7 | Multiple retrying tasks, independent retry chains, transient→permanent, session isolation, zero-delay retry |
| `TestSchedulerInteraction` | 4 | Requque releases slot, transitions to READY, available in queue, concurrency slot released |
| `TestRetryStateTransitions` | 7 | RUNNING→RETRYING, RETRYING→WAITING, WAITING→READY, READY→RUNNING, full cycle, RETRYING→FAILED, pipeline-level retry state, exhaustion |
| `TestRetryDecisionDataclass` | 5 | Construction, defaults, partial construction, mutable fields, integration with `_should_retry` |

Total execution tests: **759** (includes foundation, scheduler, dispatcher, adapter registry, execution loop, retry engine, event bus, metrics collector, and recovery manager tests).

---

## 8. Verification

- Retry tests: `python3 -m pytest backend/tests/test_retry_engine.py` → **73 passed, 0 failed**
- All execution tests: `python3 -m pytest backend/tests/test_execution_*.py backend/tests/test_retry_engine.py backend/tests/test_event_bus.py backend/tests/test_metrics_collector.py backend/tests/test_recovery_manager.py` → **759 passed, 0 failed**
- `py_compile` over all execution modules: **clean**

---

## 9. Limitations (reserved for future phases)

| Capability | Future phase |
|---|---|---|
| Non-blocking retry scheduling (timer wheel / `asyncio.create_task`) | Future runtime v2 |
| Circuit breakers for persistently failing adapters | Future |
| Persistence of retry state across engine restarts | Future |
| Distributed retry queues | Future |
| Event bus notifications for retry lifecycle events | 3.6.4G |
| Circuit breakers for persistently failing adapters | Future |
| Persistence of retry state across engine restarts | Future |
| Distributed retry queues | Future |
| Per-task retry policy from plan definition (currently all tasks share the policy from `RetryPolicy.default()` or the `execute()` override) | Future |
