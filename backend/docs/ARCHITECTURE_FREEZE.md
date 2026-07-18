# Execution Runtime v1 — Architecture Freeze

## Runtime Version

**v1.0**

## Freeze Date

2026-07-18

## Freeze Status

**FROZEN**

No further architectural changes to the execution runtime are permitted without an RFC.

---

## Core Architectural Principles

1. **State Machine is the sole owner of state transitions.** No code may modify `TaskState` or `SessionState` without going through `StateMachine.transition_task()` or `StateMachine.transition_session()`.

2. **Scheduler is retry-unaware.** The scheduler manages DAG scheduling (in-degree, ready queue, concurrency). Retry logic lives exclusively in the pipeline.

3. **Dispatcher is adapter-independent.** The dispatcher depends on the `AdapterResolver` protocol only. No adapter-specific logic exists in the dispatcher.

4. **Event Bus is generic infrastructure.** The bus does not import Scheduler, Dispatcher, or AdapterRegistry. Subscribers must not affect execution.

5. **Metrics are passive.** `MetricsCollector` never calls the pipeline, never publishes events, never modifies tasks. It is a pure event-driven subscriber.

6. **RecoveryManager is stateless.** All methods are static. No mutable state is maintained.

7. **ExecutionPipeline is orchestration only.** The pipeline validates, creates, initializes, runs, and finalizes. It does not execute business logic or know about concrete adapters.

8. **Scheduler and Pipeline have no thread safety.** All access must be serialized through the single-threaded asyncio event loop. Multi-threaded access to `ExecutionEngine._sessions`, `ExecutionEngine._schedulers`, or `Scheduler` mutable state is unsafe.

---

## Public Extension Points

| Extension Point | Mechanism | Requires |
|---|---|---|
| New adapter | Implement `ExecutionAdapter` + `register()` on `AdapterRegistry` | New adapter implementation |
| Custom resolver | Implement `AdapterResolver` protocol | Resolver implementation |
| Event subscriber | Implement `EventSubscriber` protocol + `subscribe()` on `EventBus` | Subscriber implementation |
| New task type | Add to `TaskType` enum + register adapter for it | Enum change + adapter |
| Session persistence | Implement store + pass to `RecoveryManager` | External persistence layer |

---

## Rules for Future Modifications

### RFC Required (architecture board review)

- Changes to scheduler semantics (in-degree, ready queue, dependency release, terminal detection)
- Changes to state machine transition tables
- Changes to the `Dispatcher.dispatch()` contract
- Changes to `EventBus` publish/subscribe semantics
- Changes to `RecoveryManager.validate()` or `fix_states()` semantics
- Adding thread safety to Scheduler or ExecutionEngine
- New execution phases between existing ones

### Allowed Without RFC (bug fixes only)

- Bug fixes in backoff calculation logic
- Bug fixes in state transition validation
- Bug fixes in dependency release propagation
- Adding missing event types to `ExecutionEventType`
- Adding missing fields to `MetricsSnapshot`
- Adding missing fields to event data payloads
- Adding new `ExecutionAdapter` subclasses

### Prohibited

- Adding new dependencies from foundation modules (enums, models, exceptions) to orchestration modules
- Bypassing `StateMachine.transition_task()` for task state changes
- Adding business logic to `Dispatcher`
- Making `MetricsCollector` no longer passive
- Making `RecoveryManager` stateful

---

## Known Limitations (Documented, Not Blocking)

| Limitation | Tracked |
|---|---|
| Scheduler has no thread safety | `scheduler.py` — `_ready_queue`, `_running`, `in_degree` unprotected |
| ExecutionEngine has no thread safety | `execution_pipeline.py` — `_sessions`, `_schedulers` dicts unprotected |
| Retry `asyncio.sleep()` blocks execution loop | Not a problem for V1 task counts; fix in v2 with timer wheel |
| No persistence layer | Sessions are in-memory only; RecoveryManager anticipates a Supabase backend |
| Single-threaded execution loop per session | Concurrency is horizontal (multiple sessions); vertical is future work |
| `AdapterMetricsSnapshot` keyed by `task_type`, not `adapter_name` | Pipeline event payload does not yet carry resolved adapter name |

---

## Committed Behavior

### RetryPolicy fields are all honored

- `backoff_base_seconds` — initial delay
- `backoff_multiplier` — exponential factor
- `max_backoff_seconds` — delay ceiling before jitter
- `jitter` — ±50% uniform random variation
- `retryable_error_types` — replaces hardcoded `"transient"` check

### Cancellation is not failure

`TASK_CANCELLED` increments `tasks_cancelled` in MetricsSnapshot, not `tasks_failed`.

### Session start_time is always populated

Both `execute()` and `recover()` set `session.start_time` before entering the execution loop.

### Attempt is incremented after state transitions

`_schedule_retry` transitions RUNNING→RETRYING→WAITING before incrementing `task.attempts`.
