# Layer 1: Execution Runtime

## Purpose

The execution runtime orchestrates the lifecycle of a plan — from validation through task scheduling, adapter dispatch, retry handling, and session finalization. It is the engine that drives all execution.

## Freeze Reference

[ARCHITECTURE_FREEZE.md](../ARCHITECTURE_FREEZE.md)

## Package

`services.execution`

## Components

### ExecutionEngine (`execution_pipeline.py`)
The main entry point for executing plans. Pipeline stages:
1. **validate** — validate plan structure (DAG, dependencies, task types)
2. **create** — create session with unique ID
3. **initialize** — wrap tasks, build in-degree map, identify root tasks
4. **run** — execution loop (coordinates scheduler, dispatcher, state machine)
5. **finalize** — mark session as terminal, emit final metrics

Key methods: `execute(plan)`, `cancel(session_id)`, `pause(session_id)`, `resume(session_id)`, `approve(session_id, task_id)`, `reject(session_id, task_id)`, `recover(session_id)`.

### StateMachine (`state_machine.py`)
Sole owner of all state transitions. Both task and session states use explicit transition tables.

**Task states:** PENDING → READY → RUNNING → COMPLETED / FAILED / CANCELLED, with intermediate WAITING, WAITING_APPROVAL, RETRYING, BLOCKED, SKIPPED.

**Session states:** PENDING → RUNNING → COMPLETED / COMPLETED_WITH_ERRORS / FAILED / CANCELLED, with intermediate PAUSED, WAITING_APPROVAL.

Invalid transitions raise `ExecutionStateError`.

### Scheduler (`scheduler.py`)
DAG-aware scheduler using in-degree tracking:
- Maintains in-degree map and ready queue
- Releases tasks when all dependencies complete
- Enforces concurrency limits per session
- Detects terminal states (all tasks terminal)

**Key invariant:** The scheduler is retry-unaware. Retry logic lives exclusively in the pipeline.

### Dispatcher (`dispatcher.py`)
Adapter-independent dispatch via the `AdapterResolver` protocol:
- Resolves task type to adapter via `resolve(task_type) → ExecutionAdapter`
- Calls `adapter.execute(context)` with populated context
- Returns `TaskResult` with success/failure, output, error info

No adapter-specific logic exists in the dispatcher.

### EventBus (`event_bus.py`)
Generic pub/sub infrastructure:
- `publish(event)` — emit event to all subscribers
- `subscribe(subscriber)` — register an `EventSubscriber` protocol
- Subscribers are called in registration order
- Subscribers must not block execution or affect state

### MetricsCollector (`metrics_collector.py`)
Passive event-driven subscriber:
- Listens for `ExecutionEvent` on the event bus
- Updates `MetricsSnapshot` counters (tasks_completed, tasks_failed, tasks_cancelled, retries, etc.)
- Tracks per-adapter metrics in `AdapterMetricsSnapshot`
- Never calls the pipeline, never publishes events, never modifies tasks

### RecoveryManager (`recovery_manager.py`)
Stateless session recovery:
- `validate(sessions)` — scan for inconsistent states (e.g., RUNNING but no active tasks)
- `fix_states(sessions)` — apply corrective transitions
- `recover(session, engine)` — restart a failed/paused session
- All methods are static. No mutable state.

## Key Models

| Model | Key Fields |
|---|---|
| `ExecutionSession` | id, plan_id, plan, status, tasks, root_tasks, start_time, end_time |
| `ExecutionTask` | id, plan_task, status, attempts, max_attempts, last_error, retry_policy |
| `TaskResult` | task_id, attempt, success, output, error, error_type, duration_ms |
| `RetryPolicy` | max_attempts, backoff_base_seconds, backoff_multiplier, jitter, retryable_error_types |
| `ExecutionContext` | session_id, channel, workspace_snapshot, policies |
| `ExecutionEvent` | id, session_id, task_id, event_type, data, timestamp, sequence |
| `ExecutionMetrics` | total_tasks, completed, failed, skipped, cancelled, total_retries |

## Exception Hierarchy

```
ExecutionError
├── ExecutionValidationError    — plan/session validation
├── ExecutionSchedulingError    — scheduler errors
├── ExecutionDispatchError      — no adapter for task
├── ExecutionAdapterError       — adapter configuration
├── ExecutionRetryError         — invalid retry state
├── ExecutionStateError         — invalid state transitions
└── ExecutionSessionError       — invalid session operations
```

## Architectural Principles

1. **State Machine is the sole owner of state transitions.** No code may modify `TaskState` or `SessionState` without going through `StateMachine.transition_task()` or `StateMachine.transition_session()`.

2. **Scheduler is retry-unaware.** Retry logic lives in the pipeline.

3. **Dispatcher is adapter-independent.** Depends on `AdapterResolver` protocol only.

4. **Event Bus is generic infrastructure.** Does not import Scheduler, Dispatcher, or AdapterRegistry. Subscribers must not affect execution.

5. **Metrics are passive.** Never calls the pipeline, never publishes events, never modifies tasks.

6. **RecoveryManager is stateless.** All methods are static.

7. **ExecutionPipeline is orchestration only.** Does not execute business logic or know about concrete adapters.

## Relationship to Adapter SDK

The runtime depends on `ExecutionAdapter`, `AdapterContext`, and `AdapterResult` from the Adapter SDK. It never imports concrete adapters. Adapter resolution goes through the AdapterRegistry (Layer 5), which the runtime queries by identity. Credentials arrive via the CredentialResolver (Layer 4), which the runtime calls before injecting into context.

## Known Limitations

| Limitation | Status |
|---|---|
| No thread safety (single-threaded asyncio) | Documented |
| No persistence layer (in-memory sessions) | Anticipates Supabase backend |
| No timer wheel (retry sleep blocks loop) | Fix in v2 |
| Concurrency is per-session, not vertical | Future work |
| Legacy adapter_registry.py in execution package | Superseded by services/adapters/ |
