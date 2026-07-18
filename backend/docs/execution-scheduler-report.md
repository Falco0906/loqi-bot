# Execution Engine Scheduler & State Machine — Phase 3.6.4B

## 1. Files Created/Modified

### New Files
- `backend/services/execution/state_machine.py` — Explicit transition tables for task (11 states) and session (8 states) state machines; `StateMachine` class with `transition_task()`, `transition_session()`, `derive_session_state()`, `is_valid_task_transition()`, `is_valid_session_transition()`.
- `backend/services/execution/scheduler.py` — `Scheduler` class managing in-degree map, FIFO ready queue, concurrency limits, dependency release on completion/failure/skip, terminal detection.

### Modified Files (Bug Fixes During Verification)
- `backend/services/execution/state_machine.py` — Added `TaskState.SKIPPED` to `PENDING` and `READY` transition sets (required for DAG skip propagation).
- `backend/services/execution/scheduler.py` — `mark_skipped()` now uses `StateMachine.transition_task()` instead of direct assignment; cleans up `_ready_queue` and `_running` set for skipped source tasks; `mark_failed()` cascades transitively through `mark_skipped`.
- `backend/tests/test_execution_foundation.py` — Updated error message assertion from `4B` to `4C` to match pipeline implementation.
- `backend/tests/test_execution_scheduler.py` — Removed invalid transition entries that became valid (`PENDING→BLOCKED`, `PENDING→SKIPPED`, `READY→SKIPPED`); added `RUNNING` transition steps before `FAILED`/`COMPLETED` in failure/completion propagation tests; added cascade propagation in terminal detection tests.

### No Changes To
- `backend/services/execution/enums.py` — Unchanged (11 `TaskState` members, 8 `SessionState` members, 19 `ExecutionEventType` members).
- `backend/services/execution/exceptions.py` — Unchanged (7 exception classes).
- `backend/services/execution/execution_models.py` — Unchanged (10 data models).
- `backend/services/execution/execution_context.py` — Unchanged.
- `backend/services/execution/utils.py` — Unchanged.
- `backend/services/execution/validation.py` — Unchanged.
- `backend/services/execution/execution_pipeline.py` — Unchanged (`_run_scheduler` already integrated with `Scheduler`).

---

## 2. State Machine Design

### Task Transitions (Explicit Table)

| From | To |
|---|---|
| `PENDING` | `READY`, `BLOCKED`, `WAITING_APPROVAL`, `SKIPPED`, `CANCELLED` |
| `READY` | `RUNNING`, `SKIPPED`, `CANCELLED` |
| `RUNNING` | `COMPLETED`, `FAILED`, `WAITING`, `WAITING_APPROVAL`, `RETRYING`, `CANCELLED` |
| `WAITING` | `READY`, `FAILED`, `CANCELLED` |
| `WAITING_APPROVAL` | `READY`, `SKIPPED`, `CANCELLED` |
| `RETRYING` | `READY`, `FAILED`, `CANCELLED` |
| `BLOCKED` | `SKIPPED`, `READY`, `CANCELLED` |
| `COMPLETED` | (terminal — no outgoing) |
| `FAILED` | (terminal — no outgoing) |
| `SKIPPED` | (terminal — no outgoing) |
| `CANCELLED` | (terminal — no outgoing) |

### Session Transitions (Explicit Table)

| From | To |
|---|---|
| `PENDING` | `RUNNING`, `CANCELLED` |
| `RUNNING` | `PAUSED`, `WAITING_APPROVAL`, `COMPLETED`, `COMPLETED_WITH_ERRORS`, `FAILED`, `CANCELLED` |
| `PAUSED` | `RUNNING`, `CANCELLED` |
| `WAITING_APPROVAL` | `RUNNING`, `COMPLETED`, `COMPLETED_WITH_ERRORS`, `FAILED`, `CANCELLED` |
| `COMPLETED` | (terminal) |
| `COMPLETED_WITH_ERRORS` | (terminal) |
| `FAILED` | (terminal) |
| `CANCELLED` | (terminal) |

### Design Decisions

1. **Explicit dict tables** — All valid transitions are enumerated in module-level dicts; no scattered conditionals.
2. **`derive_session_state()`** — Session state is derived from collective task states (source of truth), never mutated independently.
3. **Typed exceptions** — `ExecutionStateError` carries `from_state`, `to_state`, and `allowed_transitions` in context.
4. **`SKIPPED` reachable from `PENDING` and `READY`** — Added during verification to support DAG skip propagation (when all upstream tasks are terminal, pending/ready downstream tasks skip automatically).

---

## 3. Scheduler Design

### Core Operations

| Method | Purpose |
|---|---|
| `initialize()` | Build in-degree map, promote root tasks to READY, enqueue them |
| `get_next_ready()` | Pop next task from FIFO queue (respects concurrency limit) |
| `peek_ready()` | Peek without dequeuing |
| `mark_completed(task_id)` | Release downstream deps, enqueue newly-ready tasks |
| `mark_failed(task_id)` | Block downstream tasks, cascade skip if permanently blocked |
| `mark_skipped(task_id)` | Propagate skip transitively through the DAG |
| `is_terminal()` | Check if all tasks are terminal, no active/ready tasks remain |
| `get_terminal_state()` | Derive terminal session state name |

### Design Decisions

1. **Scheduler does not dispatch** — Only determines what may run; dispatch is Phase 3.6.4C.
2. **Caller owns task state transitions** — `mark_completed`/`mark_failed`/`mark_skipped` manage the scheduling data structures; the caller transitions the task's `TaskState` using `StateMachine`.
3. **FIFO ready queue** — Tasks are enqueued in initialization order; deterministic execution ordering.
4. **In-degree tracking** — `InDegreeEntry` stores `remaining` and `total`; decremented on dependency release.
5. **Concurrency limit** — `max_concurrency` bounds `_running` set; `get_next_ready()` returns `None` when at limit.
6. **Transitive cascade** — `mark_failed` transitions downstream tasks to `BLOCKED`, then `SKIPPED` if permanently blocked, then recursively cascades via `mark_skipped`.
7. **Ready queue cleanup** — `mark_skipped` removes the source task from `_ready_queue` if present, preventing orphaned entries.

---

## 4. DAG Propagation Scenarios

### Linear: a → b → c
- `a` fails → `b` blocked → `b` skipped (permanently blocked) → cascade to `c` → `c` skipped
- `a` completes → `b` ready → `b` completes → `c` ready → `c` completes → terminal

### Diamond: a → (b, c) → d
- `a` fails → `b`, `c` blocked → `b`, `c` skipped → `d` permanently blocked → `d` skipped → terminal
- `a` completes → `b`, `c` ready → both complete → `d` in-degree reaches 0 → `d` ready

### Independent: a, b, c (no deps)
- All three ready immediately; concurrency limit controls dispatch

---

## 5. Issues Discovered and Fixed During Verification

1. **Missing `PENDING→SKIPPED` transition** — DAG skip propagation required this; added to transition table.
2. **Missing `READY→SKIPPED` transition** — A task could be skipped while still in READY state (before dispatch); added to transition table.
3. **`mark_skipped()` used direct assignment** — `etask.status = TaskState.SKIPPED` bypassed state machine; changed to `StateMachine.transition_task()`.
4. **`mark_skipped()` missed ready queue cleanup** — Skipped tasks left in `_ready_queue` caused `is_terminal()` false positives; added `_ready_queue.remove()`.
5. **`mark_failed()` non-transitive cascade** — Only blocked immediate downstream; added recursive `mark_skipped()` call for full DAG propagation.
6. **Tests skipped `RUNNING` state** — `get_next_ready()` returns task ID but does not transition state; tests needed explicit `READY→RUNNING` before `RUNNING→FAILED`/`COMPLETED`.

---

## 6. Verification

- Scheduler/state machine tests: `python3 -m pytest backend/tests/test_execution_scheduler.py` → **105 passed, 0 failed**.
- Foundation tests: `python3 -m pytest backend/tests/test_execution_foundation.py` → **88 passed, 0 failed**.
- Planner tests: `python3 -m pytest backend/tests/test_planner.py` → **58 passed, 0 failed**.
- Total: **251 passed, 0 failed**.
- `py_compile` over all 10 execution modules: **clean**.

---

## 7. Next Phase (3.6.4C — Dispatcher)

The dispatcher will:
1. Accept a task ID from `scheduler.get_next_ready()`
2. Resolve the adapter via the adapter registry
3. Execute the task through the adapter
4. Handle results (success → `mark_completed`, transient failure → retry, permanent failure → `mark_failed`)
5. Emit `ExecutionEvent` for each transition
6. Loop until `scheduler.is_terminal()` returns `True`
7. Finalize the session
