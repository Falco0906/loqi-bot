# Execution Engine Architecture

> **Phase:** 3.6.4
> **Status:** Architecture Design
> **Upstream Dependency:** Planning Engine (Phase 3.6.3) — architecturally frozen
> **Downstream Consumers:** Reflection Engine, Human Approval UI, Workflow Analytics

---

## Table of Contents

1. [Architectural Principles](#1-architectural-principles)
2. [Position in the Stack](#2-position-in-the-stack)
3. [Execution Lifecycle](#3-execution-lifecycle)
4. [Core Models](#4-core-models)
5. [State Machine](#5-state-machine)
6. [Scheduler](#6-scheduler)
7. [Dispatcher](#7-dispatcher)
8. [Adapter System](#8-adapter-system)
9. [Retry System](#9-retry-system)
10. [Approval Integration](#10-approval-integration)
11. [Observability](#11-observability)
12. [Failure Handling](#12-failure-handling)
13. [Extension Points](#13-extension-points)
14. [Integration with Existing Systems](#14-integration-with-existing-systems)
15. [Folder Structure](#15-folder-structure)
16. [Runtime Flow Diagrams](#16-runtime-flow-diagrams)
17. [Constraints and Non-Goals](#17-constraints-and-non-goals)

---

## 1. Architectural Principles

1. **Execution is not reasoning.** The engine executes a plan; it does not think, strategize, or generate content. All intelligence lives upstream.

2. **The Plan is immutable.** Once an `ExecutionSession` begins, the `Plan` is read-only. All mutable state lives in the `ExecutionTask` and `ExecutionSession`. The engine never calls back into the planner.

3. **Adapters encapsulate side effects.** The engine routes typed tasks to adapters. Adapters call external systems. The engine never calls Gmail, Telegram, or any provider directly.

4. **Persistence before action.** Every state transition is persisted before the action it enables executes. This ensures crash recovery does not double-execute or lose state.

5. **Events are the integration layer.** Downstream systems (Reflection Engine, Analytics, Approval UI) consume events. They never couple to engine internals.

6. **Failures are typed.** Every error is classified as transient or permanent. Transient failures retry. Permanent failures do not. The engine never loops.

7. **Concurrency is safe by default.** Parallel execution is bounded by a per-session semaphore. Dependency ordering is enforced by topological sort. Thread safety is explicit.

8. **Relative timing resolves at execution time.** The planner emits relative triggers (`AFTER_REPLY`, `AFTER_DURATION`). The execution engine resolves them to absolute times when a task enters READY.

---

## 2. Position in the Stack

```
┌─────────────────────────────────────────┐
│           Conversation Engine            │
│  (Message routing, session management)  │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│            Reasoning Engine              │
│   (Intent classification, decisions)    │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│             Planning Engine              │
│  (Strategy, DAG, triggers, approvals)   │
│  ───→ Output: Plan (read-only)          │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│           EXECUTION ENGINE              │◂─── THIS LAYER
│  (Session, scheduler, dispatcher,       │
│   adapters, retry, state machine)       │
└──┬──────┬──────┬──────┬──────┬──────────┘
   │      │      │      │      │
   ▼      ▼      ▼      ▼      ▼
┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌──────────┐
│Tel │ │Web │ │Email│ │CRM │ │ Calendar │
│Adap│ │Adap│ │Adap │ │Adap│ │ Adapter  │
└────┘ └────┘ └────┘ └────┘ └──────────┘
   │      │      │      │      │
   ▼      ▼      ▼      ▼      ▼
 External APIs (Telegram, HTTP, Gmail, HubSpot, Google Calendar...)

 Downstream Event Consumers (decoupled):
 ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
 │   Reflection │ │  Approval UI │ │   Analytics  │
 │    Engine    │ │  (Websocket) │ │   Pipeline   │
 └──────────────┘ └──────────────┘ └──────────────┘
```

---

## 3. Execution Lifecycle

### 3.1 Lifecycle Stages

```
ExecutionPlan (from Planner)
    │
    ▼
┌─────────────────────────────────────┐
│  1. RECEPTION                       │
│  Validate plan structure            │
│  Create ExecutionSession            │
│  Assign session ID                  │
└────────────────┬────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────┐
│  2. INITIALIZATION                  │
│  Wrap each Task → ExecutionTask     │
│  Initialize in-degree map           │
│  Identify root tasks                │
│  Persist session                    │
└────────────────┬────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────┐
│  3. DISPATCH LOOP                   │
│  ┌─────────────────────────────┐    │
│  │ Scheduler: pop ready tasks  │────┼──→ [Scheduler section]
│  │   Dispatcher: typeresolve   │────┼──→ [Dispatcher section]
│  │   Adapter: execute          │────┼──→ [Adapter section]
│  │   ResultHandler: collect    │────┼──→ [Retry section]
│  │   StateMachine: transition  │────┼──→ [State Machine section]
│  │   EventEmitter: emit        │────┼──→ [Observability section]
│  │   DAG: propagate completion │────┼──→ back to Scheduler
│  └─────────────────────────────┘    │
└────────────────┬────────────────────┘
                 │
    (no tasks remaining)
                 │
                 ▼
┌─────────────────────────────────────┐
│  4. TERMINATION                     │
│  Detect terminal state              │
│  Finalize session                   │
│  Emit SESSION_COMPLETED event       │
│  Prepare reflection input           │
└─────────────────────────────────────┘
```

### 3.2 Stage Details

#### 3.2.1 Reception

The engine receives a validated `Plan` (status `VALIDATED`) from the Planning Pipeline. The engine does not re-validate the full plan; it performs a lightweight structural check:

- All task IDs are unique within the plan.
- All dependency references resolve to existing task IDs.
- The DAG contains no cycles (the planner already guarantees this, but the check is a safety net).
- All tasks have a `TaskType` and `TaskPayload` the engine can handle.

If any structural check fails, the engine rejects the plan with an `ExecutionRejectedError` and does not create a session.

On success, an `ExecutionSession` is created with status `PENDING`.

#### 3.2.2 Initialization

Each `Task` from the plan is wrapped in an `ExecutionTask`:

- `status` ← `PENDING`
- `attempts` ← `0`
- `retry_policy` ← from task metadata or default
- `adapter_name` ← resolved during dispatch, not now

The in-degree map is built: for each task, count how many dependencies are not yet satisfied. Root tasks (in-degree 0) are immediately promoted to `READY`.

The session is persisted to the session store.

#### 3.2.3 Dispatch Loop

The core execution loop runs until the session is terminal:

1. **Scheduler** — takes ready tasks from the queue, respecting concurrency limits.
2. **Dispatcher** — for each ready task, resolves `TaskType` → adapter via `AdapterRegistry`.
3. **Adapter** — calls `adapter.execute(task, context)`.
4. **Result Handler** — evaluates the result:
   - Success → transition to `COMPLETED`.
   - Transient failure → schedule retry.
   - Permanent failure → transition to `FAILED`.
5. **State Machine** — performs the transition, persists the new state.
6. **Event Emitter** — emits a structured event for each transition.
7. **DAG Propagation** — decrements downstream in-degrees; newly-ready tasks added to scheduler.

If the session is paused (approval, external pause), the loop pauses. External events (`approve`, `resume`) re-enter the loop.

#### 3.2.4 Termination

The session reaches a terminal state when:

- All tasks are `COMPLETED` → session `COMPLETED`.
- Some tasks `FAILED`, remaining `SKIPPED` → session `COMPLETED_WITH_ERRORS`.
- All remaining tasks are `BLOCKED` by failed dependencies → session `FAILED`.
- External cancellation → session `CANCELLED`.

On termination, the engine emits `SESSION_COMPLETED` with the full task result map, timeline, and metrics. This event is consumed by the Reflection Engine and Analytics.

---

## 4. Core Models

### 4.1 ExecutionSession

```python
@dataclass
class ExecutionSession:
    id: str                              # Unique session ID (uuid hex)
    plan_id: str                         # References Plan.id
    plan: Plan                           # The original plan (read-only)
    conversation_id: str                 # References Conversation.id
    status: ExecutionSessionStatus       # PENDING → RUNNING → terminal
    tasks: dict[str, "ExecutionTask"]    # task_id → ExecutionTask
    root_tasks: list[str]                # Task IDs with in-degree 0 at start
    start_time: datetime
    end_time: Optional[datetime]
    metadata: dict                       # Workspace snapshot, policies
    created_at: datetime
    updated_at: datetime
```

**Lifecycle:**
- `PENDING` — session created, initialization in progress
- `RUNNING` — dispatch loop active
- `WAITING_APPROVAL` — one or more tasks awaiting human approval
- `PAUSED` — externally paused
- `COMPLETED` — all tasks completed or skipped
- `COMPLETED_WITH_ERRORS` — some tasks failed, session completed partially
- `FAILED` — session could not complete
- `CANCELLED` — externally cancelled

### 4.2 ExecutionTask

```python
@dataclass
class ExecutionTask:
    id: str                              # Matches Task.id from the plan
    plan_task: Task                      # Reference to the immutable Plan Task
    status: ExecutionTaskStatus          # Current execution state
    attempts: int                        # Execution attempt count
    max_attempts: int                    # From retry policy
    last_error: Optional[str]            # Last error message
    last_error_type: Optional[str]       # "transient" | "permanent"
    result: Optional[TaskResult]         # Result of successful execution
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    retry_policy: RetryPolicy            # The retry policy for this task
    adapter_name: Optional[str]          # Resolved adapter name
```

### 4.3 ExecutionTaskStatus

```python
class ExecutionTaskStatus(str, Enum):
    PENDING             = "pending"              # Waiting for dependency resolution
    READY               = "ready"                # Dependencies satisfied, queued
    RUNNING             = "running"              # Currently executing
    RETRYING            = "retrying"             # Waiting for backoff before re-run
    WAITING_APPROVAL    = "waiting_approval"     # Paused for human approval
    WAITING             = "waiting"              # Waiting for external trigger (reply, duration)
    COMPLETED           = "completed"            # Executed successfully
    FAILED              = "failed"               # Execution failed (permanent)
    CANCELLED           = "cancelled"            # Cancelled by operator
    SKIPPED             = "skipped"              # Skipped due to failed upstream dependency
    BLOCKED             = "blocked"              # Upstream dependency failed but not yet skipped
```

### 4.4 TaskResult

```python
@dataclass
class TaskResult:
    task_id: str                         # References ExecutionTask.id
    attempt: int                         # Which attempt produced this result
    success: bool                        # True if execution completed normally
    output: Optional[dict]               # Adapter-specific output data
    error: Optional[str]                 # Error message (if failed)
    error_type: Optional[str]            # "transient" | "permanent" (if failed)
    metadata: dict                       # Adapter-specific metadata
    started_at: datetime
    completed_at: datetime
    duration_ms: int                     # Wall-clock execution time
```

### 4.5 RetryPolicy

```python
@dataclass
class RetryPolicy:
    max_attempts: int = 3
    backoff_base_seconds: float = 1.0    # Initial backoff
    backoff_multiplier: float = 2.0      # Exponential factor
    max_backoff_seconds: float = 300.0   # Cap at 5 minutes
    jitter: bool = True                  # Add random jitter to backoff
    retryable_error_types: set[str] = field(
        default_factory=lambda: {"transient"}
    )
```

### 4.6 ExecutionEvent

```python
@dataclass
class ExecutionEvent:
    id: str                              # Unique event ID
    session_id: str                      # References ExecutionSession.id
    task_id: Optional[str]               # References ExecutionTask.id (None for session-level events)
    event_type: ExecutionEventType       # Structured event type
    data: dict                           # Event-specific payload
    timestamp: datetime
    sequence: int                        # Monotonic sequence within session
```

### 4.7 ExecutionEventType

```python
class ExecutionEventType(str, Enum):
    # Session-level events
    SESSION_CREATED         = "session.created"
    SESSION_STARTED         = "session.started"
    SESSION_PAUSED          = "session.paused"
    SESSION_RESUMED         = "session.resumed"
    SESSION_COMPLETED       = "session.completed"
    SESSION_FAILED          = "session.failed"
    SESSION_CANCELLED       = "session.cancelled"

    # Task-level events
    TASK_READY              = "task.ready"
    TASK_STARTED            = "task.started"
    TASK_COMPLETED          = "task.completed"
    TASK_FAILED             = "task.failed"
    TASK_RETRYING           = "task.retrying"
    TASK_CANCELLED          = "task.cancelled"
    TASK_SKIPPED            = "task.skipped"

    # Approval events
    APPROVAL_REQUESTED      = "approval.requested"
    APPROVAL_GRANTED        = "approval.granted"
    APPROVAL_REJECTED       = "approval.rejected"

    # Wait events
    WAITING_STARTED         = "waiting.started"
    WAITING_COMPLETED       = "waiting.completed"
```

### 4.8 ExecutionContext

```python
@dataclass
class ExecutionContext:
    session: ExecutionSession            # The current session
    channel: str                         # The channel identifier (telegram, web, ...)
    workspace_snapshot: dict             # Frozen workspace state at session start
    policies: dict                       # Execution policies from workspace config
    idempotency_store: IdempotencyStore  # Tracks completed attempt IDs
```

The `ExecutionContext` is built once at session initialization and passed (read-only) to every adapter invocation. Adapters may read workspace config but never modify it.

### 4.9 ExecutionMetrics

```python
@dataclass
class ExecutionMetrics:
    session_id: str
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    skipped_tasks: int
    cancelled_tasks: int
    total_attempts: int
    total_retries: int
    approval_count: int
    start_time: datetime
    end_time: Optional[datetime]
    duration_seconds: Optional[float]
    adapter_stats: dict[str, dict]       # Per-adapter: count, errors, avg_duration_ms
```

### 4.10 ValidationResult (internal)

```python
@dataclass
class ValidationResult:
    valid: bool
    errors: list[str]
    warnings: list[str]
```

---

## 5. State Machine

### 5.1 Task State Transitions

```
                         ┌────────────────────────────────────────────┐
                         │                                            │
                         ▼                                            │
                    ┌─────────┐                                       │
         ┌─────────►│ PENDING │                                       │
         │          └────┬────┘                                       │
         │               │                                            │
         │      (deps satisfied, no block)                            │
         │               │                                            │
         │               ▼                                            │
         │          ┌─────────┐                                       │
         │          │  READY  │                                       │
         │          └────┬────┘                                       │
         │               │                                            │
         │      (dispatched by scheduler)                             │
         │               │                                            │
         │               ▼                                            │
         │   ┌──────────────────────┐                                 │
         │   │       RUNNING       │──────────────┐                   │
         │   └──┬───────┬───────┬──┘              │                   │
         │      │       │       │                  │                   │
         │      │       │       │         (permanent fail)            │
         │      │       │       │                  │                   │
         │      │       │       │                  ▼                  │
         │      │       │       │            ┌──────────┐             │
         │      │       │       │            │  FAILED  │             │
         │      │       │       │            └──────────┘             │
         │      │       │       │                                      │
         │      │       │       │          (upstream fail)            │
         │      │       │       │              │                      │
         │      ▼       ▼       ▼              ▼                      │
         │  ┌────────┐ ┌──────────┐      ┌──────────┐                 │
         │  │RETRYING│ │ WAITING_ │      │  BLOCKED │────► SKIPPED    │
         │  │        │ │APPROVAL  │      └──────────┘                 │
         │  └───┬────┘ └────┬─────┘                                   │
         │      │            │                                         │
         │(backoff└  (approved)                                        │
         │ expires)   │                                                │
         │      │      │                                               │
         │      ▼      │                                               │
         │    ┌────────┐│                                              │
         └────┤ READY  ◄┘                                              │
              │        │                                               │
              └────────┘                                               │
                                                                       │
         ┌──────────┐   ┌───────────┐                                  │
         │ WAITING  │──►│   READY   │──────────────────────────────────┘
         │(reply/   │   │(condition │
         │ duration)│   │  met)     │
         └──────────┘   └───────────┘
```

### 5.2 Session State Transitions

```
  PENDING ──► RUNNING ──► COMPLETED
                  │
                  ├──► WAITING_APPROVAL ──► RUNNING
                  │
                  ├──► PAUSED ──► RUNNING
                  │
                  ├──► FAILED
                  │
                  └──► CANCELLED
```

### 5.3 Transition Rules

| From | To | Trigger |
|---|---|---|
| `PENDING` | `READY` | All dependencies satisfied, not blocked |
| `READY` | `RUNNING` | Dispatcher picks up the task |
| `RUNNING` | `COMPLETED` | Adapter returns success |
| `RUNNING` | `FAILED` | Adapter returns permanent failure |
| `RUNNING` | `RETRYING` | Adapter returns transient failure, attempts < max |
| `RUNNING` | `WAITING_APPROVAL` | Task requires approval, approval not yet granted |
| `RUNNING` | `WAITING` | Task is WAIT_FOR_REPLY or WAIT_DURATION |
| `RETRYING` | `READY` | Backoff timer expires |
| `RETRYING` | `FAILED` | Max attempts reached (transition evaluated on entry) |
| `WAITING_APPROVAL` | `READY` | External approval signal received |
| `WAITING_APPROVAL` | `SKIPPED` | External rejection signal received |
| `WAITING` | `READY` | Wait condition met (reply received or duration elapsed) |
| `BLOCKED` | `SKIPPED` | Upstream dependency permanently failed |
| `BLOCKED` | `READY` | Upstream dependency recovers (rare; currently not implemented) |
| Any | `CANCELLED` | External cancellation signal |

---

## 6. Scheduler

### 6.1 Responsibility

The scheduler determines which tasks are eligible for execution at any point in time, respecting DAG ordering, concurrency limits, and waiting states.

### 6.2 Data Structures

```
InDegreeMap: dict[str, int]
    Key: Task ID
    Value: Number of unsatisfied dependencies

ReadyQueue: asyncio.PriorityQueue[tuple[int, ExecutionTask]]
    Priority 0 = immediately executable
    Priority 1 = executable but lower priority (future: priority levels from plan)

ConcurrencySemaphore: asyncio.Semaphore
    Per-session limit (default: 5 parallel tasks)

RunningTasks: set[str]
    Task IDs currently in RUNNING status
```

### 6.3 Algorithm

```
function initialize(plan: Plan):
    for each task in plan.tasks:
        execution_tasks[task.id] = new ExecutionTask(task)
        in_degree[task.id] = len(task.dependencies)

    for each task_id where in_degree[task_id] == 0:
        if not requires_approval(execution_tasks[task_id]):
            transition(execution_tasks[task_id], PENDING → READY)
            ready_queue.put((0, execution_tasks[task_id]))
        else:
            transition(execution_tasks[task_id], PENDING → WAITING_APPROVAL)
            emit(APPROVAL_REQUESTED, task_id)

function on_task_completed(task_id: str, result: TaskResult):
    downstream = plan.get_downstream_tasks(task_id)

    for each downstream_id in downstream:
        if execution_tasks[downstream_id].status in {CANCELLED, SKIPPED}:
            continue

        in_degree[downstream_id] -= 1

        if result.status == "failed":
            # Upstream failure — block downstream
            transition(execution_tasks[downstream_id], ..., BLOCKED)
            # After BLOCKED evaluation, transition to SKIPPED
            transition(execution_tasks[downstream_id], BLOCKED → SKIPPED)
            continue

        if in_degree[downstream_id] == 0:
            if requires_approval(execution_tasks[downstream_id]):
                transition(execution_tasks[downstream_id], ..., WAITING_APPROVAL)
                emit(APPROVAL_REQUESTED, downstream_id)
            elif requires_wait(execution_tasks[downstream_id]):
                transition(execution_tasks[downstream_id], ..., WAITING)
                schedule_wait_timer(execution_tasks[downstream_id])
            else:
                transition(execution_tasks[downstream_id], ..., READY)
                ready_queue.put(execution_tasks[downstream_id])

function dispatch_loop():
    while session.status == RUNNING:
        task = await ready_queue.get()
        async with concurrency_semaphore:
            transition(task, READY → RUNNING)
            emit(TASK_STARTED, task.id)
            result = await dispatcher.dispatch(task, context)
            handle_result(task, result)

function handle_result(task: ExecutionTask, result: TaskResult):
    if result.success:
        task.result = result
        transition(task, RUNNING → COMPLETED)
        emit(TASK_COMPLETED, task.id)
        on_task_completed(task.id, result)
    elif result.error_type == "transient" and task.attempts < task.max_attempts:
        task.attempts += 1
        delay = calculate_backoff(task)
        transition(task, RUNNING → RETRYING)
        emit(TASK_RETRYING, task.id, {"delay": delay, "attempt": task.attempts})
        schedule_retry(task.id, delay)
    else:
        task.attempts += 1
        task.last_error = result.error
        task.last_error_type = result.error_type
        transition(task, RUNNING → FAILED)
        emit(TASK_FAILED, task.id, {"error": result.error, "error_type": result.error_type})
        on_task_completed(task.id, result)

    # Check terminal condition
    if is_terminal():
        finalize_session()
```

### 6.4 Parallel Execution Rules

- Tasks with independent dependency chains execute in parallel.
- `BRANCH` and `JOIN` nodes are internal and execute instantly — they do not count against the concurrency limit.
- Concurrency limit is per-session, configurable via workspace policies (default: 5).
- The scheduler respects `asyncio.Semaphore` fairness (FIFO ordering among parallel-task candidates).

### 6.5 Terminal Detection

The session is terminal when all tasks are in one of: `COMPLETED`, `FAILED`, `CANCELLED`, `SKIPPED`. The `ready_queue` is empty, `running_tasks` is empty, and no `WAITING` or `WAITING_APPROVAL` tasks exist (or the session is externally cancelled).

---

## 7. Dispatcher

### 7.1 Responsibility

The dispatcher receives a `READY` task and resolves it to an adapter. It performs no business logic — it is a pure routing layer.

### 7.2 Resolution Algorithm

```
function dispatch(task: ExecutionTask, context: ExecutionContext) -> TaskResult:
    adapter = adapter_registry.resolve(task.plan_task.type)
    if adapter is None:
        return TaskResult(
            task_id=task.id,
            attempt=task.attempts,
            success=False,
            error=f"No adapter registered for task type: {task.plan_task.type}",
            error_type="permanent",
            ...
        )

    task.adapter_name = adapter.adapter_type
    return await adapter.execute(task, context)
```

### 7.3 Type → Adapter Mapping

| TaskType | Adapter | Internal/External |
|---|---|---|
| `SEND_MESSAGE` | `ChannelAdapter` | External |
| `SEND_EMAIL` | `EmailAdapter` | External |
| `SCHEDULE_MEETING` | `CalendarAdapter` | External |
| `WAIT_FOR_REPLY` | `WaitAdapter` | Internal |
| `WAIT_DURATION` | `WaitAdapter` | Internal |
| `ANALYZE_REPLY` | `AnalysisAdapter` | Internal |
| `UPDATE_CRM` | `CRMAdapter` | External |
| `ESCALATE` | `ChannelAdapter` | External |
| `REQUEST_APPROVAL` | `ApprovalAdapter` | Internal |
| `BRANCH` | `BranchAdapter` | Internal |
| `JOIN` | `BranchAdapter` | Internal |

**Internal adapters** execute within the engine process. They have no side effects beyond state changes and event emission.

**External adapters** call external APIs (Telegram, Gmail, HubSpot, etc.) and may have side effects. They must implement idempotency.

---

## 8. Adapter System

### 8.1 Adapter Interface

```python
class ExecutionAdapter(ABC):
    @property
    @abstractmethod
    def adapter_type(self) -> str:
        """Unique identifier for this adapter (e.g., 'telegram', 'gmail')."""

    @property
    @abstractmethod
    def supported_task_types(self) -> list[TaskType]:
        """Task types this adapter can handle."""

    @abstractmethod
    async def execute(
        self,
        task: ExecutionTask,
        context: ExecutionContext,
    ) -> TaskResult:
        """Execute a task and return a result.

        Must be idempotent — may be called multiple times for the
        same task attempt (see Retry section). The adapter should
        check the idempotency store before performing side effects.
        """

    def compensate(
        self,
        task: ExecutionTask,
        context: ExecutionContext,
    ) -> Optional[TaskResult]:
        """Optional compensating action for rollback scenarios.

        Called when a downstream task fails and the engine decides
        to undo this task's side effects (e.g., delete a scheduled
        meeting). Returns None if no compensation is needed.
        """
        return None
```

### 8.2 Adapter Registry

```python
@dataclass
class AdapterRegistration:
    adapter: ExecutionAdapter
    priority: int = 0          # Higher priority wins when multiple adapters handle the same TaskType

class AdapterRegistry:
    _adapters: dict[str, AdapterRegistration]     # adapter_type → registration
    _task_type_map: dict[TaskType, list[str]]     # TaskType → list of adapter_type

    def register(self, adapter: ExecutionAdapter, priority: int = 0) -> None:
        """Register an adapter. Idempotent — re-registration updates priority."""

    def resolve(self, task_type: TaskType) -> Optional[ExecutionAdapter]:
        """Resolve the best adapter for a task type."""

    def unregister(self, adapter_type: str) -> None:
        """Remove an adapter (for testing or live reconfiguration)."""

    def get_supported_types(self) -> dict[str, list[TaskType]]:
        """Return all registered adapters and their supported types."""
```

### 8.3 Internal Adapters

#### 8.3.1 BranchAdapter

Handles `BRANCH` and `JOIN` tasks.

**BRANCH logic:**
- Reads `BranchPayload` from the task.
- Evaluates the branch condition against the current execution context.
- Marks only the relevant branch's downstream tasks as eligible.
- Other branches' downstream tasks are transitioned to `SKIPPED`.

**JOIN logic:**
- All upstream branches must be `COMPLETED` or `SKIPPED` before `JOIN` becomes `READY`.
- `JOIN` executes instantly as a synchronization barrier.

#### 8.3.2 WaitAdapter

Handles `WAIT_FOR_REPLY` and `WAIT_DURATION`.

**WAIT_FOR_REPLY:**
- Registers a listener for incoming messages on the conversation.
- Task stays in `WAITING` until a reply is received.
- On reply received, transitions to `READY`.
- If `timeout` is specified, transitions to `FAILED` (timeout) if no reply arrives within the window.

**WAIT_DURATION:**
- Schedules an asyncio timer for the specified duration.
- Task stays in `WAITING` until the timer fires.
- On timer fire, transitions to `READY`.

#### 8.3.3 ApprovalAdapter

Handles `REQUEST_APPROVAL`.

- Transitions the task to `WAITING_APPROVAL`.
- Emits `APPROVAL_REQUESTED` with the task context.
- Waits for external `approve(task_id)` or `reject(task_id)` signal.

### 8.4 External Adapters

External adapters follow the same `ExecutionAdapter` interface but implement side-effectful operations.

**Example ChannelAdapter:**

```python
class ChannelAdapter(ExecutionAdapter):
    def __init__(self, channel_type: str, messenger_service):
        self._channel_type = channel_type
        self._messenger = messenger_service

    @property
    def adapter_type(self) -> str:
        return self._channel_type  # "telegram", "web", "whatsapp"

    @property
    def supported_task_types(self) -> list[TaskType]:
        return [TaskType.SEND_MESSAGE]

    async def execute(self, task: ExecutionTask, context: ExecutionContext) -> TaskResult:
        payload = task.plan_task.get_payload()  # MessagePayload
        if payload is None:
            return TaskResult(task_id=task.id, ..., success=False, error="No payload")

        # Idempotency check
        attempt_key = f"{context.session.id}:{task.id}:{task.attempts}"
        if context.idempotency_store.exists(attempt_key):
            return TaskResult(task_id=task.id, ..., success=True, metadata={"idempotent_replay": True})

        try:
            message_id = await self._messenger.send(
                recipient=task.plan_task.params.get("channel_user_id"),
                text=payload.text,
                thread_id=task.plan_task.params.get("thread_id"),
            )
            context.idempotency_store.record(attempt_key)
            return TaskResult(
                task_id=task.id,
                attempt=task.attempts,
                success=True,
                output={"message_id": message_id},
                ...
            )
        except Exception as e:
            return TaskResult(
                task_id=task.id,
                attempt=task.attempts,
                success=False,
                error=str(e),
                error_type=self._classify_error(e),
                ...
            )

    def _classify_error(self, error: Exception) -> str:
        if isinstance(error, (ConnectionError, TimeoutError)):
            return "transient"
        return "permanent"
```

### 8.5 Adapter Composition

An adapter may delegate to sub-adapters. For example, a `MessageAdapter` might wrap both `ChannelAdapter` and `EmailAdapter`, selecting by channel parameter at runtime. This is implemented by registering the delegation layer as an adapter that resolves internally — no core engine changes needed.

---

## 9. Retry System

### 9.1 Retry Decision Flow

```
Adapter returns TaskResult { success: false }
    │
    ▼
Is error_type in retry_policy.retryable_error_types?
    │                │
   YES               NO
    │                │
    ▼                ▼
attempts < max     PERMANENT FAILURE
attempts?          → Task → FAILED
    │       │
   YES      NO
    │       │
    ▼       ▼
RETRY     PERMANENT FAILURE
    │     → Task → FAILED
    ▼
Calculate backoff
    │
    ▼
Schedule retry after delay
    → Task → RETRYING
```

### 9.2 Backoff Calculation

```python
def calculate_backoff(task: ExecutionTask) -> float:
    policy = task.retry_policy
    delay = policy.backoff_base_seconds * (policy.backoff_multiplier ** (task.attempts - 1))
    delay = min(delay, policy.max_backoff_seconds)
    if policy.jitter:
        delay *= random.uniform(0.5, 1.5)
    return delay
```

### 9.3 Retry Scheduling

When a task enters `RETRYING`:

1. The backoff delay is computed.
2. An `asyncio` timer is scheduled for `now + delay`.
3. The timer callback transitions the task from `RETRYING` to `READY`.
4. The task re-enters the `ready_queue`.
5. The dispatcher picks it up and the adapter executes again.
6. The adapter must be idempotent — it may see the same `attempt` value.

### 9.4 Retry Classification

| Error Pattern | Classification | Examples |
|---|---|---|
| Network timeout | transient | `ConnectionError`, `TimeoutError`, `asyncio.TimeoutError` |
| Rate limited | transient | HTTP 429, "too many requests" |
| Service unavailable | transient | HTTP 503, SMTP temporarily unavailable |
| Invalid credentials | permanent | HTTP 401, 403, OAuth token expired |
| Invalid payload | permanent | HTTP 400, validation errors |
| Resource not found | permanent | HTTP 404, user/channel no longer exists |

Adapters classify errors internally. The engine only reads `error_type`.

### 9.5 Permanent Failure Propagation

When a task enters `FAILED` (permanent):

1. Downstream tasks that depend exclusively on this task are marked `BLOCKED`.
2. `BLOCKED` tasks are immediately evaluated: if all upstream dependencies are `FAILED` or `SKIPPED`, the task is transitioned to `SKIPPED`.
3. `SKIPPED` tasks propagate the same logic downstream (cascade).

---

## 10. Approval Integration

### 10.1 Approval Flow

```
Task.plan_task.approval.required == True
    │
    ▼
Task → WAITING_APPROVAL
    │
    ▼
Emit APPROVAL_REQUESTED event
    │
    ▼
External system (API endpoint + UI) displays approval request
    │
    ├── approve(task_id) called → Task → READY → normal dispatch
    │
    └── reject(task_id) called → Task → SKIPPED → propagate downstream
```

### 10.2 Approval-Aware Scheduling

The scheduler checks `task.plan_task.approval` when a task becomes ready (in-degree 0):

```python
if task.plan_task.approval and task.plan_task.approval.required:
    if not is_pre_approved(task):
        transition(task, ..., WAITING_APPROVAL)
        emit(APPROVAL_REQUESTED, task.id, ...)
        return  # Don't add to ready_queue
```

### 10.3 Approval API Surface

The execution engine exposes these operations (via events + API, not direct function calls):

- `approve(session_id, task_id, approver)` → transitions `WAITING_APPROVAL` → `READY`
- `reject(session_id, task_id, approver, reason)` → transitions `WAITING_APPROVAL` → `SKIPPED`
- `get_pending_approvals(session_id)` → returns all tasks in `WAITING_APPROVAL`

These are called externally. The engine itself does not render approval UI.

### 10.4 Session-Level Pause

If a `WAITING_APPROVAL` task is present, the session transitions to `WAITING_APPROVAL` status. New tasks may still execute if they do not depend on the pending approval. The session is only blocked from terminal detection while approval tasks are pending.

---

## 11. Observability

### 11.1 Execution Logs

Every state transition and adapter invocation is logged at structured-log level:

```json
{
    "timestamp": "...",
    "session_id": "...",
    "task_id": "...",
    "event_type": "task.started",
    "data": { "task_type": "SEND_MESSAGE", "attempt": 1, "adapter": "telegram" }
}
```

Logs are persisted alongside the session for post-mortem analysis.

### 11.2 Metrics

Collected per-session and accessible via `ExecutionMetrics`:

| Metric | Type | Description |
|---|---|---|
| `total_tasks` | counter | Total tasks in the plan |
| `completed_tasks` | counter | Tasks completed successfully |
| `failed_tasks` | counter | Tasks permanently failed |
| `skipped_tasks` | counter | Tasks skipped due to upstream failure |
| `total_retries` | counter | Total retry attempts across all tasks |
| `approval_count` | counter | Total approval requests made |
| `session_duration` | timer | Wall-clock session duration |
| `per_adapter` | gauge | Per-adapter execution count, errors, avg duration |

Metrics are exposed for Prometheus scraping and surfaced in the Analytics extension point.

### 11.3 Audit Trail

The `ExecutionEvent` stream serves as the complete audit trail. Every state change is captured with:

- Who/What caused the change (adapter execution, external approval, scheduler decision)
- The previous state and new state
- The timestamp (with nanosecond precision where available)
- A monotonic sequence number for ordering

### 11.4 Event History

Events are persisted in the session store and queryable by:

- `session_id` — all events for a session
- `task_id` — all events for a specific task
- `event_type` — filter by event type
- `time_range` — filter by timestamp

### 11.5 Execution Timeline

The timeline is a derived view: events sorted by sequence number. Each task's lifecycle forms a sub-timeline:

```
Task "send_invitation":
  [1] task.ready         2026-07-18T10:00:00Z
  [2] task.started       2026-07-18T10:00:01Z
  [3] task.completed     2026-07-18T10:00:02Z  (duration: 1.2s)
```

The timeline is consumed by the Reflection Engine and the Web UI for live progress tracking.

---

## 12. Failure Handling

### 12.1 Rollback Philosophy

Loqi operates in an append-only action space (sending messages, scheduling meetings). There is no transaction rollback for sent messages. Instead, the system uses **compensating actions**:

- If a downstream task fails, the engine does not "unsend" upstream messages.
- The plan's strategy handles failure by routing to escalation or recovery tasks (defined at plan time).
- The execution engine's role is to faithfully execute the plan and report failures; compensating logic lives in the plan structure.

### 12.2 Partial Failures

When some tasks succeed and others fail:

- The session completes with status `COMPLETED_WITH_ERRORS`.
- All tasks downstream of the failure are `SKIPPED` (unless they have alternative dependency paths).
- The final event includes the full success/failure map.
- The Reflection Engine receives the partial result and can generate a new plan.

### 12.3 Compensating Actions

Adapters may optionally implement `compensate()`:

- If a meeting was scheduled and a downstream task fails, the `CalendarAdapter.compensate()` could cancel the meeting.
- Compensation is called per-failed-task, not per-session.
- Compensation is best-effort; it does not block the session.
- Compensation events are logged but failures during compensation are not retried.

### 12.4 Idempotency

Every adapter execution attempt receives a unique `attempt_key`:

```
attempt_key = f"{session_id}:{task_id}:{attempt_number}"
```

Adapters check `idempotency_store.exists(attempt_key)` before performing side effects:

- If the key exists: return the stored result (replay).
- If it does not: perform the action, store the key + result.
- The store must survive process restarts (Supabase-backed).

This ensures that retries do not cause duplicate sends, even across crash recovery.

### 12.5 Crash Recovery

The `RecoveryEngine` runs at startup:

```python
async def recover_all():
    active_sessions = await session_store.find_by_status(
        ExecutionSessionStatus.RUNNING,
        ExecutionSessionStatus.WAITING_APPROVAL,
        ExecutionSessionStatus.PAUSED,
    )

    for session in active_sessions:
        for task in session.tasks.values():
            if task.status in {ExecutionTaskStatus.RUNNING, ExecutionTaskStatus.RETRYING}:
                # These tasks may have been mid-execution — retry from start
                task.attempts += 1
                transition(task, ..., READY)
                ready_queue.put(task)

        session.start_time = now()  # Reset start time to recovery time
        if session.status in {ExecutionSessionStatus.WAITING_APPROVAL}:
            # Re-emit pending approval requests
            emit(APPROVAL_REQUESTED, task.id, {"recovered": True})

        transition(session, ..., RUNNING)
        dispatch_loop(session)
```

### 12.6 Timeouts

Each adapter execution has a configurable timeout (default: 30 seconds). If the adapter does not return within the timeout:

- The task result is treated as a transient failure.
- The task enters `RETRYING`.
- After max retries, the task enters `FAILED`.

---

## 13. Extension Points

### 13.1 Reflection Engine

The Reflection Engine subscribes to `SESSION_COMPLETED` events. The event payload includes:

- Full task result map (task_id → TaskResult)
- Execution timeline (all events)
- ExecutionMetrics
- The original Plan (for context)

The Reflection Engine uses this data to evaluate outcome quality and generate follow-up plans.

**Integration:** Event subscription. No engine changes needed.

### 13.2 Policy Engine

A `PolicyAdapter` can be registered to check execution policies before dispatching tasks:

- Rate limits
- Time-of-day restrictions
- Channel-eligibility rules
- Budget constraints

The `PolicyAdapter` wraps the actual adapter:

```python
class PolicyAdapter(ExecutionAdapter):
    def __init__(self, inner_adapter: ExecutionAdapter, policy_service):
        self._inner = inner_adapter
        self._policy = policy_service

    async def execute(self, task, context):
        if not await self._policy.allows(task, context):
            return TaskResult(
                success=False,
                error=f"Policy denied: {self._policy.reason}",
                error_type="permanent",
            )
        return await self._inner.execute(task, context)
```

**Integration:** Register `PolicyAdapter` wrapping the real adapter. No engine changes needed.

### 13.3 Human Approval UI

The engine emits `APPROVAL_REQUESTED` events with task context. The Web UI subscribes to these events (via WebSocket or polling) and renders approval cards. User actions (`approve`, `reject`) call the engine's approval API.

**Integration:** Event subscription + external API call. No engine changes needed.

### 13.4 Workflow Analytics

The engine emits all events to an event bus. An Analytics service consumes the event stream independently, computing:

- Average task completion time per type
- Error rate per adapter
- Approval response time
- Session completion rate
- Common failure patterns

**Integration:** Event subscription. No engine changes needed.

### 13.5 External Integrations

New external services integrate by implementing `ExecutionAdapter`:

1. Create a class implementing `ExecutionAdapter`.
2. Register it with the `AdapterRegistry` for the relevant `TaskType`s.
3. The engine dispatches to it automatically.

**Integration:** Adapter registration. No engine changes needed.

### 13.6 Custom Task Types

If the planner generates a new `TaskType` that no adapter handles:

- The dispatcher returns a permanent failure with "No adapter registered".
- The session continues; downstream tasks are skipped.
- New adapters can be registered at any time without restarting the engine (hot-pluggable via adapter registry).

### 13.7 Idempotency Store Abstraction

The `IdempotencyStore` is an interface:

```python
class IdempotencyStore(ABC):
    @abstractmethod
    async def exists(self, key: str) -> bool: ...
    @abstractmethod
    async def record(self, key: str, result: dict) -> None: ...
    @abstractmethod
    async def get(self, key: str) -> Optional[dict]: ...
    @abstractmethod
    async def cleanup(self, session_id: str) -> None: ...
```

Default implementation uses Supabase (transactional, survives restarts). Alternative implementations can use Redis for higher throughput.

---

## 14. Integration with Existing Systems

### 14.1 Conversation Engine Integration

The `ConversationEngine` currently dispatches workflows via `workflows.py`. The Execution Engine will replace this path:

```
Current: ConversationEngine → workflows.py → direct function calls
Future:  ConversationEngine → PlanningPipeline → Plan → ExecutionEngine → adapters
```

The ConversationEngine calls `PlanningPipeline.generate_plan()` to get a `Plan`, then calls `ExecutionEngine.execute(plan)` to run it. The engine returns an `ExecutionSession` ID. The ConversationEngine monitors session status via events.

### 14.2 Existing Outbound Executor

The existing `outbound_executor.py` (Gmail integration) becomes an adapter:

```python
class GmailAdapter(ExecutionAdapter):
    def __init__(self):
        self._delegate = outbound_executor

    async def execute(self, task, context):
        payload = task.plan_task.get_payload()
        if isinstance(payload, MessagePayload):
            result = self._delegate.execute("send_reply", {
                "to": payload.recipient,
                "subject": payload.subject,
                "body": payload.text,
            })
            return TaskResult(success=result.ok, output=result.data)
```

No changes to `outbound_executor.py` are required — it is wrapped, not modified.

### 14.3 Legacy Workflow Executor

The existing `workflow_executor.py` (stub-based, unused by real code) is superseded by the Execution Engine. It can be left in place until the migration is complete, then removed.

---

## 15. Folder Structure

```
backend/services/execution/
├── __init__.py                          # Package exports

├── execution_models.py                  # Core data models
│   # ExecutionSession, ExecutionTask, TaskResult, RetryPolicy,
│   # ExecutionEvent, ExecutionContext, ExecutionMetrics
│   # Enums: ExecutionSessionStatus, ExecutionTaskStatus, ExecutionEventType

├── execution_pipeline.py                # Main orchestration entry point
│   # ExecutionEngine class
│   # execute(plan) → ExecutionSession
│   # cancel(session_id), pause(session_id), resume(session_id)
│   # approve(session_id, task_id), reject(session_id, task_id)

├── scheduler.py                         # DAG-aware task scheduling
│   # Scheduler class
│   # Topological ordering, in-degree resolution
│   # Concurrency semaphore, ready queue
│   # Terminal detection

├── dispatcher.py                        # Task dispatch routing
│   # Dispatcher class
│   # TaskType → adapter resolution
│   # Adapter invocation wrapper

├── state_machine.py                     # Task and session state transitions
│   # StateMachine class
│   # Transition validation
│   # TaskStateTransition, SessionStateTransition models

├── retry_engine.py                      # Retry policy evaluation
│   # RetryEngine class
│   # Backoff calculation, jitter
│   # Retry scheduling

├── adapter_registry.py                  # Pluggable adapter registration
│   # AdapterRegistry class
│   # AdapterRegistration model
│   # TaskType → Adapter mapping

├── execution_context.py                 # Context builder
│   # build_context(session) → ExecutionContext
│   # Workspace snapshot, policy loading

├── events.py                            # Event emitter and store
│   # EventEmitter class
│   # emit(event) → persist + notify subscribers
│   # EventStore: query by session/task/type/range

├── metrics.py                           # Execution metrics collector
│   # MetricsCollector class
│   # Per-session and global counters
│   # Prometheus export

├── exceptions.py                        # Execution-specific exceptions
│   # ExecutionError (base)
│   # ExecutionRejectedError (plan rejected at reception)
│   # ExecutionDispatchError (no adapter for task type)
│   # ExecutionAdapterError (adapter execution failure)
│   # ExecutionTimeoutError (adapter timeout)
│   # ExecutionStateError (invalid transition)

├── validation.py                        # Plan reception validation
│   # validate_plan_for_execution(plan) → ValidationResult
│   # ID uniqueness, dependency resolution, task type coverage, cycle detection

├── recovery.py                          # Crash recovery
│   # recover_all() → recover active sessions
│   # recover_session(session_id) → resume single session

├── persistence/
│   ├── __init__.py
│   ├── session_store.py                 # CRUD for ExecutionSession + tasks
│   │   # create_session(session) → session
│   │   # update_session(session) → None
│   │   # get_session(session_id) → Optional[ExecutionSession]
│   │   # find_by_status(statuses) → list[ExecutionSession]
│   │   # delete_session(session_id) → None
│   └── event_store.py                   # CRUD for ExecutionEvent
│       # append_event(event) → None
│       # get_events(session_id, ...) → list[ExecutionEvent]
│       # get_timeline(session_id) → list[ExecutionEvent]

└── adapters/
    ├── __init__.py                      # Auto-register built-in adapters
    ├── base_adapter.py                  # ExecutionAdapter ABC
    ├── branch_adapter.py                # BRANCH / JOIN internal execution
    ├── wait_adapter.py                  # WAIT_FOR_REPLY / WAIT_DURATION execution
    ├── approval_adapter.py              # REQUEST_APPROVAL gate handling
    ├── analysis_adapter.py              # ANALYZE_REPLY internal analysis
    ├── channel_adapter.py               # Base for channel message adapters
    ├── email_adapter.py                 # Gmail/Outlook email sending
    ├── crm_adapter.py                   # CRM update actions
    ├── calendar_adapter.py              # Meeting scheduling
    └── policy_adapter.py                # Policy enforcement wrapper
```

---

## 16. Runtime Flow Diagrams

### 16.1 Single Task Execution

```
ExecutionTask (READY)
    │
    ▼
Dispatcher.dispatch(task, context)
    │
    ├─► adapter_registry.resolve(task.plan_task.type)
    │       │
    │       ▼
    │   adapter (e.g., ChannelAdapter)
    │       │
    │       ▼
    │   adapter.execute(task, context)
    │       │
    │       ├─► idempotency_store.exists(attempt_key)
    │       │       │
    │       │       ├─ YES → return cached result (replay)
    │       │       │
    │       │       └─ NO  → perform side effect
    │       │                   │
    │       │                   ▼
    │       │               store result in idempotency_store
    │       │                   │
    │       │                   ▼
    │       │               return TaskResult
    │       │
    │       ▼
    │   TaskResult { success: true/false, error_type: transient/permanent }
    │
    ▼
ResultHandler.handle(task, result)
    │
    ├─ success → task → COMPLETED → emit TASK_COMPLETED → propagate DAG
    │
    ├─ transient fail → task → RETRYING → schedule backoff → emit TASK_RETRYING
    │
    └─ permanent fail → task → FAILED → emit TASK_FAILED → propagate DAG → block downstream
```

### 16.2 Full Session Lifecycle

```
┌──────────────┐
│ Plan received│
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Reception:   │
│ validate     │
│ structure    │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Initialize:  │
│ wrap tasks,  │
│ build in-    │
│ degree map   │
└──────┬───────┘
       │
       ▼
┌───────────────────────────────────────────────────────────────┐
│                    DISPATCH LOOP                              │
│                                                               │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐  │
│  │Scheduler │──►│Dispatcher│──►│ Adapter  │──►│  Result  │  │
│  │pop ready │   │resolve   │   │execute   │   │ evaluate │  │
│  │task      │   │ type     │   │          │   │          │  │
│  └──────────┘   └──────────┘   └──────────┘   └────┬─────┘  │
│       ▲                                             │        │
│       │                  ┌──────────┐               │        │
│       │◄─────────────────│ DAG      │◄──────────────┘        │
│       │                  │ propagate│                        │
│       │                  └──────────┘                        │
│       │                           │                          │
│       │         ┌─────────────────┼──────────────┐           │
│       │         │ success         │ transient    │ permanent │
│       │         ▼                 ▼              ▼           │
│       │   ┌──────────┐   ┌────────────┐   ┌──────────┐      │
│       │   │COMPLETED │   │ RETRYING   │   │  FAILED  │      │
│       │   └──────────┘   └─────┬──────┘   └──────────┘      │
│       │                       │                              │
│       │                       ▼                              │
│       │                  (backoff timer)                     │
│       │                       │                              │
│       └───────────────────────┘   (backoff done → READY)     │
│                                                               │
│  ┌──────────┐   ┌──────────┐                                  │
│  │ APPROVAL │   │ WAITING  │                                  │
│  │ gate     │   │ (reply/  │                                  │
│  │          │   │ duration)│                                  │
│  └──────────┘   └──────────┘                                  │
│       │               │                                       │
│       │     (external │ signal received)                      │
│       │               │                                       │
│       └───────┬───────┘                                       │
│               │                                               │
│               ▼                                               │
│           ┌──────────┐                                        │
│           │  READY   │─────────► (back to scheduler)          │
│           └──────────┘                                        │
└───────────────────────────────────────────────────────────────┘
       │
       │  (no tasks remaining)
       ▼
┌──────────────┐
│ Termination: │
│ finalize     │
│ session      │
│ emit event   │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Event        │
│ Consumers:   │
│ Reflection   │
│ Engine,      │
│ Analytics,   │
│ UI           │
└──────────────┘
```

---

## 17. Constraints and Non-Goals

### The Execution Engine will never:

1. **Call the Planning Engine.** Plans are received once. The engine never requests plan modifications.

2. **Modify the Plan.** The Plan object is immutable once execution starts.

3. **Generate replies or content.** All content is pre-generated by the Reasoning Engine and embedded in task payloads.

4. **Make strategic decisions.** Branch evaluation is deterministic (payload-driven), not strategic.

5. **Render UI.** Approval UI, progress UI, and timeline visualization are frontend concerns.

6. **Handle auth or permissions.** The workspace snapshot contains pre-resolved credentials.

7. **Do transaction rollback for sent messages.** Compensation is at the adapter level, not the engine level.

8. **Support real-time plan modification during execution.** Plans are static for the duration of a session.

9. **Rewrite the existing `workflows.py` or `conversation_engine.py`.** Migration is incremental; the engine coexists with legacy systems.

10. **Implement channel-specific logic.** All channel behavior lives in adapters.

---

## Appendix A: Integration Interface Summary

| Integration | Mechanism | Direction |
|---|---|---|
| Planning Engine → Execution Engine | `Plan` object (dataclass) | Input |
| Execution Engine → Reflection Engine | `ExecutionEvent.SESSION_COMPLETED` (event) | Output |
| Execution Engine → Approval UI | `ExecutionEvent.APPROVAL_REQUESTED` (event) | Output |
| Approval UI → Execution Engine | `approve()` / `reject()` (API) | Input |
| Execution Engine → Analytics | All `ExecutionEvent` types (event stream) | Output |
| Channel Providers → Execution Engine | Reply messages trigger wait resolution (event) | Input (via Conversation Engine) |
| Execution Engine → Adapters | `ExecutionAdapter.execute(task, context)` (Python interface) | Internal |

## Appendix B: Key Design Decisions

| Decision | Rationale |
|---|---|
| Separate session from plan | The Plan is immutable; the Session carries runtime state. Clear ownership. |
| Internal adapters for BRANCH/JOIN/WAIT | These have no side effects and must execute synchronously within the engine's flow. |
| Per-session concurrency semaphore | Prevents one session from flooding the system. Limit is configurable. |
| Idempotency by attempt key | Ensures retries do not cause duplicate side effects even across restarts. |
| Event-driven external integration | Downstream systems never import engine internals. Event schema is the contract. |
| Crash recovery by status scan | `find_by_status(RUNNING)` is a simple query. No write-ahead log needed. |
| Adapter registry as hot-pluggable | New channels (WhatsApp, Slack) register without engine changes. |
| Transient vs permanent error classification | Single bit that determines retry eligibility. Eliminates guesswork. |
| No transaction rollback | Email/message sends are append-only. Compensation is best-effort at the adapter level. |

## Appendix C: Comparison to Existing Systems

| Concern | Legacy `workflows.py` | Existing `workflow_executor.py` (stubs) | New Execution Engine |
|---|---|---|---|
| Input type | Flat dict | `WorkflowPlan` | `Plan` (from planner) |
| Execution model | Direct function call | Step-based with pause/resume | DAG-based with topological scheduler |
| State machine | None | `RuntimeEntry` states | Full `ExecutionSessionStatus` + `ExecutionTaskStatus` |
| Retry | None | Retry policies (immediate, fixed, exponential) | Per-task `RetryPolicy` with exponential backoff + jitter |
| Approvals | None | Pause/resume on steps | Dedicated `WAITING_APPROVAL` state with `APPROVAL_REQUESTED` events |
| Persistence | None | JSON file-based | Supabase (via `session_store`) |
| Adapter model | None | `ActionType` → stub executor | `ExecutionAdapter` ABC with registry |
| Event system | None | `WorkflowEvent` with sequence numbers | Rich `ExecutionEventType` enum with typed events |
| Crash recovery | None | `recover_all()` from persistence | `RecoveryEngine` reloads RUNNING sessions and retries in-flight tasks |
| Idempotency | None | None | Per-attempt key in `IdempotencyStore` |
