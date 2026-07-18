# Execution Engine Dispatcher & Base Adapter — Phase 3.6.4C

## 1. Files Created

### `backend/services/execution/base_adapter.py`
Abstract base class `ExecutionAdapter` (ABC) defining the adapter contract:

| Method/Property | Required | Description |
|---|---|---|
| `adapter_type` | Yes (abstract property) | Unique identifier (e.g., `"telegram"`, `"gmail"`) |
| `supported_task_types` | Yes (abstract property) | List of `TaskType` enum values this adapter handles |
| `execute(task, context)` | Yes (abstract async) | Execute a task and return `TaskResult`; must be idempotent |
| `validate()` | No | Validate adapter configuration at registration time; returns `Optional[list[str]]` |
| `supports(task_type)` | No (concrete default) | Check if a task type is supported (default: list membership) |
| `shutdown()` | No | Clean up resources during engine shutdown (default: no-op) |
| `compensate(task, context)` | No | Undo side effects for rollback scenarios (default: returns `None`) |

### `backend/services/execution/dispatcher.py`
Stateless `Dispatcher` class and `AdapterResolver` protocol:

**`AdapterResolver` (Protocol)**
```python
class AdapterResolver(Protocol):
    def resolve(self, task_type: TaskType) -> Optional[ExecutionAdapter]: ...
```
Defines the contract the dispatcher expects. The implementation (`AdapterRegistry`) belongs to Phase 3.6.4D.

**`Dispatcher.dispatch()` (static async)**
```
task + context + resolver → TaskResult
```
- Resolves adapter via `resolver.resolve(task.plan_task.type)`
- Sets `task.adapter_name = adapter.adapter_type`
- Invokes `adapter.execute(task, context)`
- Returns `TaskResult` directly (no retry, no state mutation)
- Raises `ExecutionDispatchError` if no adapter is registered

---

## 2. Files Modified

### `backend/services/execution/execution_pipeline.py`
- Added `resolver: Optional[AdapterResolver]` parameter to `execute()`
- Made `_run_scheduler()` async to support `await Dispatcher.dispatch()`
- When resolver is provided: dispatches task → stores `TaskResult` on `task.result` → raises `NotImplementedError("Phase 3.6.4E")`
- When resolver is `None`: preserves old behavior (raises `NotImplementedError` at dispatch boundary for backward compatibility)

### `backend/services/execution/__init__.py`
- Added exports: `ExecutionAdapter`, `AdapterResolver`, `Dispatcher`

---

## 3. Adapter Resolution Contract

The dispatcher depends only on the `AdapterResolver` protocol — it never knows about concrete adapters or the registry implementation. This follows the architecture document's principle: "Dispatcher must never know about concrete adapters."

```python
class AdapterResolver(Protocol):
    def resolve(self, task_type: TaskType) -> Optional[ExecutionAdapter]:
        ...
```

The resolver implementation (`AdapterRegistry` with registration, priority resolution, and task-type mapping) is scoped to Phase 3.6.4D.

---

## 4. Dispatch Lifecycle

```
Scheduler.get_next_ready() → task_id
         │
         ▼
StateMachine.transition_task(task, RUNNING)
         │
         ▼
ExecutionContext(session_id=session.id)
         │
         ▼
adapter = resolver.resolve(task.plan_task.type)
         │
         ├── None → ExecutionDispatchError
         │
         └── adapter → adapter.execute(task, context)
                          │
                          ▼
                      TaskResult
                          │
                          ▼
                  task.result = TaskResult
                          │
                          ▼
              NotImplementedError (Phase 3.6.4E)
```

---

## 5. Result Handling

| Scenario | Result |
|---|---|
| Adapter returns success | `TaskResult{success=True, output=..., error=None}` |
| Adapter returns transient failure | `TaskResult{success=False, error_type="transient"}` |
| Adapter returns permanent failure | `TaskResult{success=False, error_type="permanent"}` |
| No adapter registered | `ExecutionDispatchError` raised (not a `TaskResult`) |

The dispatcher does not:
- Retry transient failures (Phase 3.6.4F)
- Transition task states (handled by pipeline and state machine)
- Emit events (Phase 3.6.4G)
- Mutate session state

---

## 6. Pipeline Integration

**Current flow (no resolver — backward compatible):**
```
Validate → Create Session → Initialize → Scheduler → STOP (NotImplementedError 3.6.4C)
```

**New flow (with resolver):**
```
Validate → Create Session → Initialize → Scheduler → Dispatcher → STOP (NotImplementedError 3.6.4E)
```

The execution loop that wires scheduler → dispatcher → result handling in a continuous loop is Phase 3.6.4E.

---

## 7. Tests

### `backend/tests/test_execution_dispatcher.py` — 72 tests

| Class | Tests | Coverage |
|---|---|---|
| `TestBaseAdapterAbstract` | 2 | Cannot instantiate abstract; abstract methods defined |
| `TestBaseAdapterConcrete` | 9 | Instance, type, supports, execute result fields |
| `TestBaseAdapterOptional` | 7 | Validate, shutdown, compensate defaults and custom |
| `TestBaseAdapterMultiType` | 2 | Multi-type support and execution |
| `TestDispatcherDispatch` | 7 | Core dispatch, result fields, output, metadata |
| `TestDispatcherUnsupported` | 5 | ExecutionDispatchError raised, context fields |
| `TestDispatcherFailureModes` | 6 | Transient/permanent propagation, error fields |
| `TestDispatcherStateless` | 3 | No side effects between calls |
| `TestDispatcherResolverInteraction` | 4 | Resolver called correctly, adapter_name set |
| `TestDispatcherContextPassthrough` | 1 | Context passed to adapter |
| `TestDispatcherMultipleTaskTypes` | 2 | Multiple types dispatched |
| `TestDispatcherTiming` | 3 | Started_at, completed_at, duration_ms |
| `TestPipelineDispatcherIntegration` | 19 | Pipeline → scheduler → dispatcher integration |

---

## 8. Verification

- Dispatcher tests: `python3 -m pytest backend/tests/test_execution_dispatcher.py` → **72 passed, 0 failed**
- Scheduler tests: `python3 -m pytest backend/tests/test_execution_scheduler.py` → **105 passed, 0 failed**
- Foundation tests: `python3 -m pytest backend/tests/test_execution_foundation.py` → **88 passed, 0 failed**
- Planner tests: `python3 -m pytest backend/tests/test_planner.py` → **58 passed, 0 failed**
- **Total: 323 passed, 0 failed**
- `py_compile` over all execution modules: **clean**

---

## 9. Remaining Work for Phase 3.6.4D

1. **Adapter Registry** — `AdapterRegistry` class with:
   - `register(adapter, priority)` — idempotent registration
   - `resolve(task_type)` — priority-based adapter resolution
   - `unregister(adapter_type)` — for testing/reconfiguration
   - `get_supported_types()` — introspection
2. **Type → Adapter Mapping** — implement the table from the architecture doc
3. **Registry tests** — registration, priority, resolution, unregistration
