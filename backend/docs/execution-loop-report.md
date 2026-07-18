# Execution Engine Loop — Phase 3.6.4E

## 1. Files Modified

### `backend/services/execution/execution_pipeline.py`

Replaced the `NotImplementedError` boundary with a **full execution loop** that coordinates scheduler, dispatcher, state machine, and result handling to execute all tasks until the session reaches a terminal or stable state.

**New structure:**

```python
async def execute(plan, resolver=None):
    validate → create session → initialize → scheduler.initialize()
    await _run_scheduler(session, scheduler, resolver)
    return session   # ← now returns completed session, not NotImplementedError
```

**Two execution modes:**

| Mode | Trigger | Behavior |
|---|---|---|
| **Legacy** (backward compatible) | `resolver is None` | Single-step: stops at first runnable task, raises `NotImplementedError` with Phase 3.6.4C message |
| **Full loop** | `resolver` provided | Continuous loop until terminal or no more ready tasks |

**New methods:**

| Method | Role |
|---|---|
| `_execution_loop()` | `while not scheduler.is_terminal(): get_next_ready → _execute_task` |
| `_execute_task()` | Transition to RUNNING → create context → `_dispatch_safe` → `_handle_result` |
| `_dispatch_safe()` | Wrap `Dispatcher.dispatch()` in try/except: catches `ExecutionDispatchError` (unsupported task) and generic `Exception` (adapter crash), converts both to permanent-failure `TaskResult` |
| `_handle_result()` | Success → COMPLETED + `mark_completed`; Failure → FAILED + `mark_failed` |

**Updated `_run_scheduler()`:**
- Forks into `_legacy_scheduler_step()` (no resolver) or `_execution_loop()` (with resolver)
- After loop: calls `StateMachine.derive_session_state()` to set session status
- Sets `end_time` if terminal; sets `updated_at`

### `backend/tests/test_execution_dispatcher.py`
- `TestPipelineDispatcherIntegration` (15 tests): rewritten — all resolver-provided tests now expect completed sessions instead of `NotImplementedError`
- Legacy tests (no resolver) unchanged — preserve backward compatibility

### `backend/tests/test_execution_adapter_registry.py`
- `test_registry_with_pipeline`: updated to expect completed session instead of `NotImplementedError`

---

## 2. Execution Loop Architecture

```
                        ┌─────────────────────────────┐
                        │      Execution Loop          │
                        │  while not is_terminal():    │
                        └─────────────────────────────┘
                                      │
                          ┌───────────┴───────────┐
                          │  get_next_ready()     │
                          │  (scheduler)          │
                          └───────────┬───────────┘
                                      │ task_id or None
                                      │
                          ┌───────────▼───────────┐
                          │  RUNNING transition    │
                          │  (state machine)       │
                          └───────────┬───────────┘
                                      │
                          ┌───────────▼───────────┐
                          │  _dispatch_safe()      │
                          │  try: Dispatcher       │
                          │  except DispatchError  │
                          │  except Exception      │
                          └───────────┬───────────┘
                                      │ TaskResult
                          ┌───────────▼───────────┐
                          │  _handle_result()      │
                          │  success → COMPLETED   │
                          │          mark_completed│
                          │  failure → FAILED      │
                          │          mark_failed   │
                          └───────────────────────┘
                                      │
                                      ▼
                          (loop continues)
```

---

## 3. Error Handling Strategy

| Scenario | Detection | Result |
|---|---|---|
| Adapter returns `success=False` | Normal path | Task → FAILED; scheduler → `mark_failed` |
| No adapter registered | `ExecutionDispatchError` caught by `_dispatch_safe` | Permanent `TaskResult` with `unsupported_task=true` metadata |
| Adapter throws `RuntimeError` etc. | Generic `Exception` caught by `_dispatch_safe` | Permanent `TaskResult` with `adapter_exception` metadata |
| Downstream of failed task | `scheduler.mark_failed()` cascades | Downstream → BLOCKED → SKIPPED if all upstreams terminal |

---

## 4. Result Handling (`_handle_result`)

```
TaskResult
    │
    ├── success=True → StateMachine.transition_task(task, COMPLETED)
    │                    scheduler.mark_completed(task.id)
    │
    └── success=False → StateMachine.transition_task(task, FAILED)
                         scheduler.mark_failed(task.id)
```

Note: All failures are treated as permanent at this phase. Transient failure retry will be implemented in Phase 3.6.4F.

---

## 5. Pipeline Lifecycle (complete)

```
validate_plan_for_execution(plan)
        │
        ▼
session = _create_session(plan)
        │
        ▼
_initialize(session)
validate_session_initialization(session)
        │
        ▼
scheduler = Scheduler(session)
scheduler.initialize()
        │
        ▼
await _run_scheduler(session, scheduler, resolver)
        │
        ├── resolver=None → _legacy_scheduler_step()
        │                      │
        │                      ├── is_terminal? → _finalize()
        │                      ├── get_next_ready → task → RUNNING
        │                      └── NotImplementedError
        │
        └── resolver=✅ → _execution_loop()
                            │
                            └── while not is_terminal():
                                 get_next_ready → _execute_task
                                          │
                                    (loop repeats)
        │
        ▼
session.status = derive_session_state(session)
if terminal: session.end_time = now
session.updated_at = now
        │
        ▼
return session
```

---

## 6. Tests

### New file: `backend/tests/test_execution_loop.py` — 86 tests

| Class | Tests | Coverage |
|---|---|---|
| `TestSingleTaskSuccess` | 10 | Complete, result, output, adapter_name, timing, session lifecycle |
| `TestSingleTaskFailure` | 7 | FAILED state, session FAILED, error message, error type, end_time |
| `TestSingleTaskUnsupported` | 5 | FAILED via dispatch error, unsupported flag, no adapter_name |
| `TestSingleTaskAdapterException` | 5 | FAILED via adapter crash, error message, exception type |
| `TestLinearDagAllPass` | 6 | 3-task linear chain, ordered completion, session timing |
| `TestLinearDagFirstFails` | 7 | First fails → downstream SKIPPED, no results on skipped |
| `TestDiamondDagAllPass` | 5 | Diamond all succeed, B+C before D, adapter names |
| `TestDiamondDagOneFails` | 7 | Diamond B fails → D BLOCKED, C succeeds, session COMPLETED_WITH_ERRORS |
| `TestIndependentTasks` | 6 | 3 parallel tasks, mixed results, all fail |
| `TestSessionTiming` | 6 | End time, updated_at, plan/conversation preserved |
| `TestEngineLifecycle` | 5 | Multiple sessions, get_session, engine reuse, plan immutability |
| `TestLegacyPath` | 5 | No resolver → NotImplementedError (backward compatible) |
| `TestEdgeCases` | 6 | Empty plan, error isolation, large chain (10 tasks), diamond root fail, leaf fail |
| `TestResultContent` | 6 | Success/fail/unsupported content, timing fields |

### Test counts (all execution):

| File | Tests |
|---|---|
| `test_execution_foundation.py` | 88 |
| `test_execution_scheduler.py` | 105 |
| `test_execution_dispatcher.py` | 72 |
| `test_execution_adapter_registry.py` | 70 |
| `test_execution_loop.py` | 86 |
| **Total** | **421** |

---

## 7. Noteworthy Design Decisions

### 7a. `_dispatch_safe` — Error Boundary

Rather than forcing each adapter to handle dispatch errors, the pipeline wraps dispatch in a try/except that converts all failure modes into well-formed `TaskResult` objects. This ensures the execution loop never sees an unhandled exception from the dispatch layer.

### 7b. Legacy Mode Preserved

The no-resolver path still raises `NotImplementedError` at the dispatch boundary, maintaining backward compatibility with all Phase 3.6.4B/C tests.

### 7c. Session State Derived, Not Directly Set

After the execution loop terminates, `session.status` is set via `StateMachine.derive_session_state()` which inspects all task states rather than assuming a particular outcome. This correctly produces COMPLETED, COMPLETED_WITH_ERRORS, FAILED, or RUNNING (if blocked tasks remain).

### 7d. BLOCKED Tasks May Keep Session Active

The `derive_session_state()` method checks FAILED and SKIPPED before BLOCKED, so a session with both COMPLETED and FAILED tasks is `COMPLETED_WITH_ERRORS` even if BLOCKED tasks remain. This is a current characteristic of `derive_session_state` and may be refined in later phases.

---

## 8. Verification

- Execution loop tests: `python3 -m pytest backend/tests/test_execution_loop.py` → **86 passed, 0 failed**
- Dispatcher tests: `python3 -m pytest backend/tests/test_execution_dispatcher.py` → **72 passed, 0 failed**
- Registry tests: `python3 -m pytest backend/tests/test_execution_adapter_registry.py` → **70 passed, 0 failed**
- Scheduler tests: `python3 -m pytest backend/tests/test_execution_scheduler.py` → **105 passed, 0 failed**
- Foundation tests: `python3 -m pytest backend/tests/test_execution_foundation.py` → **88 passed, 0 failed**
- Planner tests: `python3 -m pytest backend/tests/test_planner.py` → **58 passed, 0 failed**
- **Total: 479 passed, 0 failed**
