# Planning Engine Architecture

## Overview

The Planning Engine sits between the Reasoning Engine and the Execution Layer.

```
Conversation Intelligence
         │
         ▼
   Reasoning Engine
         │  (what to do)
         ▼
┌─────────────────────┐
│   PLANNING ENGINE   │  ← you are here
│  (how to do it)     │
└─────────────────────┘
         │  (executable plan)
         ▼
   Execution Layer
         │  (doing it)
         ▼
   Reflection
```

The planner never executes actions.
It never generates replies.
It never calls providers.

Its sole responsibility is constructing structured execution plans from reasoning results.

---

## Planning Lifecycle

```
        Reasoning Result
              │
              ▼
    ┌─────────────────┐
    │  1. Goal        │  Normalize reasoning into a planning goal
    │     Analysis    │  Extract target state, constraints, priority
    └────────┬────────┘
             ▼
    ┌─────────────────┐
    │  2. Strategy    │  Select a plan template (strategy)
    │     Selection   │  Match reasoning to known strategies
    └────────┬────────┘
             ▼
    ┌─────────────────┐
    │  3. Task        │  Expand strategy into concrete tasks
    │     Generation  │  Each task = one atomic unit of work
    └────────┬────────┘
             ▼
    ┌─────────────────┐
    │  4. Dependency  │  Wire task dependencies into a DAG
    │     Resolution  │  Detect ordering, parallelism, branching
    └────────┬────────┘
             ▼
    ┌─────────────────┐
    │  5. Scheduling  │  Attach timing constraints to each task
    │                 │  (relative triggers, never absolute times)
    └────────┬────────┘
             ▼
    ┌─────────────────┐
    │  6. Approval    │  Mark tasks needing human approval
    │     Annotation  │  Annotate with policy reasoning
    └────────┬────────┘
             ▼
    ┌─────────────────┐
    │  7. Validation  │  Check structural integrity of plan
    │                 │  No cycles, no orphans, no impossible schedules
    └────────┬────────┘
             ▼
    ┌─────────────────┐
    │  8. Final Plan  │  Return executable Plan object
    └─────────────────┘
              │
              ▼
        Execution Layer
              │
              ▼
         Reflection
```

### Stage Responsibilities

| Stage | Responsibility |
|-------|---------------|
| **Goal Analysis** | Extract planning goal from reasoning result. Determine target outcome, success criteria, priority level, and constraints. |
| **Strategy Selection** | Match the goal to a registered strategy. Strategy provides task templates, dependency topology, and scheduling constraints. |
| **Task Generation** | Instantiate concrete tasks from strategy templates. Each task has a type, target, input parameters, and success criteria. |
| **Dependency Resolution** | Build the DAG. Wire prerequisites, detect parallelism opportunities, establish ordering. |
| **Scheduling** | Assign timing constraints. All times are relative triggers (never absolute datetimes). |
| **Approval Annotation** | Apply policy rules to determine which tasks need human approval before execution. |
| **Validation** | Check the complete plan for structural soundness. |
| **Final Plan** | Package and return the validated plan. |

---

## Data Model

### Enums

```python
class PlanStatus(str, Enum):
    DRAFT = "draft"                 # Being constructed
    VALIDATED = "validated"         # Passed validation
    ACTIVE = "active"               # Handed to execution
    COMPLETED = "completed"         # All tasks done
    FAILED = "failed"               # Unrecoverable error
    CANCELLED = "cancelled"         # Explicitly stopped

class TaskStatus(str, Enum):
    PENDING = "pending"             # Not yet ready
    BLOCKED = "blocked"             # Dependencies not met
    READY = "ready"                 # Dependencies met, waiting
    IN_PROGRESS = "in_progress"     # Being executed
    AWAITING_APPROVAL = "awaiting_approval"  # Human review needed
    COMPLETED = "completed"         # Done successfully
    FAILED = "failed"               # Failed
    SKIPPED = "skipped"             # Conditionally skipped

class TaskType(str, Enum):
    SEND_MESSAGE = "send_message"
    SEND_EMAIL = "send_email"
    SCHEDULE_MEETING = "schedule_meeting"
    WAIT_FOR_REPLY = "wait_for_reply"
    WAIT_DURATION = "wait_duration"
    REQUEST_APPROVAL = "request_approval"
    UPDATE_CRM = "update_crm"
    ANALYZE_REPLY = "analyze_reply"
    ESCALATE = "escalate"
    BRANCH = "branch"                # Conditional fork
    JOIN = "join"                    # Synchronization point

class TriggerType(str, Enum):
    IMMEDIATELY = "immediately"
    AFTER_REPLY = "after_reply"
    AFTER_DURATION = "after_duration"
    AFTER_TASK = "after_task"
    BUSINESS_HOURS = "business_hours"
    SPECIFIC_TIME = "specific_time"   # Rare — only for confirmed events
    ON_CONDITION = "on_condition"     # Wait for a condition to be true

class BranchCondition(str, Enum):
    REPLY_RECEIVED = "reply_received"
    REPLY_NOT_RECEIVED = "reply_not_received"
    OBJECTION_RAISED = "objection_raised"
    MEETING_BOOKED = "meeting_booked"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_DENIED = "approval_denied"
    CONFIDENCE_THRESHOLD = "confidence_threshold"
    HUMAN_DECISION = "human_decision"

class ApprovalRequirement(str, Enum):
    NONE = "none"
    RECOMMENDED = "recommended"
    REQUIRED = "required"
    POLICY_MANDATED = "policy_mandated"
```

### Core Models

```python
@dataclass
class Plan:
    """A complete execution plan derived from reasoning."""
    id: str                           # Unique plan ID
    conversation_id: str              # Source conversation
    reasoning_id: str                 # Source reasoning result
    status: PlanStatus                # Current lifecycle state
    tasks: list[Task]                 # All tasks in the plan
    goal: PlanGoal                    # The planning goal
    strategy: str                     # Strategy used
    version: str                      # Planner version
    created_at: datetime
    validated_at: datetime | None
    metadata: dict                    # Extensible metadata

@dataclass
class PlanGoal:
    """The goal this plan is trying to achieve."""
    outcome: str                      # Human-readable description
    target_action: str                # e.g. "book_demo", "send_proposal"
    success_criteria: list[str]       # How to know it's done
    priority: str                     # critical / high / medium / low
    constraints: list[str]            # e.g. "no_weekend", "business_hours_only"

@dataclass
class Task:
    """One atomic unit of work in a plan."""
    id: str
    plan_id: str
    type: TaskType                    # What kind of task
    status: TaskStatus                # Current state
    label: str                        # Human-readable short description
    instructions: str                 # What to do (consumed by execution)
    params: dict                      # Type-specific parameters
    dependencies: list[str]           # Task IDs that must complete first
    trigger: Trigger | None           # When to execute
    approval: ApprovalRequirement     # Human approval needed?
    branch: Branch | None             # Conditional branching info
    reasoning_trace: str              # Why this task exists
    reasoning_goal: str               # What reasoning goal it serves
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    result: dict | None               # Execution result (populated later)
    metadata: dict                    # Extensible

@dataclass
class Trigger:
    """Timing constraint — never an absolute datetime."""
    type: TriggerType
    value: str | int | None           # "3d", "2h", task_id, condition_key
    window_start: str | None          # "09:00" for business hours
    window_end: str | None            # "17:00" for business hours

@dataclass
class Branch:
    """Conditional fork in the plan."""
    condition: BranchCondition
    true_task_ids: list[str]          # Tasks if condition is met
    false_task_ids: list[str]         # Tasks if condition is not met
    evaluation_task_id: str | None    # Task that evaluates the condition

@dataclass
class Dependency:
    """Explicit dependency between two tasks."""
    source_id: str                    # Must complete first
    target_id: str                    # Can start after source
    type: str                         # "finish_to_start", "start_to_start"
    metadata: dict

@dataclass
class Schedule:
    """Overall scheduling constraints for the plan."""
    timezone: str                     # e.g. "America/New_York"
    business_hours_only: bool
    min_delay_between_tasks: int      # Minutes
    max_daily_tasks: int
    preferred_days: list[int]         # 0=Monday, 6=Sunday
    blackout_periods: list[tuple]     # Date ranges to avoid

@dataclass
class Approval:
    """Approval gate state."""
    task_id: str
    requirement: ApprovalRequirement
    status: str                       # pending / granted / denied
    requested_at: datetime | None
    decided_at: datetime | None
    decided_by: str | None
    reason: str | None
```

---

## Graph Representation — DAG

Plans use a **Directed Acyclic Graph (DAG)**.

### Why not a linear list?

Linear lists cannot represent:
- Parallel execution paths
- Conditional branching
- Dependency ordering
- Join points after parallel work

### Why not a full state machine?

State machines are correct but heavyweight. The Planning Engine produces plans — it doesn't execute them. A DAG is the right level of abstraction for plan construction. The execution layer may convert the DAG into a state machine internally, but that is outside the planner's scope.

### Why not a workflow graph?

Workflow graphs (BPMN, AWS Step Functions) add orchestration semantics that belong in the execution layer, not the planner. The planner produces a static plan; the executor interprets it.

### DAG Properties

```
     [Task A]          [Task C]
        │                 │
        ▼                 ▼
     [Task B] ◄────── [Task D]
        │
        ├── condition? ── yes ──► [Task E]
        │
        └── no ──► [Task F]
                       │
                       ▼
                    [Task G]  ← join point
```

- **Nodes** = Tasks
- **Edges** = Dependencies (finish-to-start)
- **Branches** = Conditional forks (not cycles — branches converge at join points)
- **Guarantees**: No cycles. Exactly one root (no-dependency task) or multiple roots possible. At least one terminal node (no downstream tasks). Weakly connected.

### Validation Rules for DAG

```
- No directed cycles
- No orphan tasks (unreachable from any root)
- At least one terminal node
- All branch paths eventually converge or terminate
- No dangling dependencies (must reference existing task IDs)
```

---

## Planning Pipeline

### Stage 1 — Goal Analysis

**Input**: `ReasoningResult`
**Output**: `PlanGoal`

Transforms a reasoning decision into a structured planning goal:

```
ReasoningResult.decision.type = "book_meeting"
  → PlanGoal.outcome = "Schedule and confirm a product demonstration"
  → PlanGoal.target_action = "book_demo"
  → PlanGoal.success_criteria = [
       "Meeting confirmed with date and time",
       "Prospect confirmed attendance",
       "Calendar invitation sent"
     ]
  → PlanGoal.priority = reasoning.decision.priority
  → PlanGoal.constraints = extract from reasoning and policies
```

Extracts constraints from:
- Reasoning risk level (high risk → more approval gates)
- Policy results (failed policies → required approvals)
- Confidence score (low confidence → human review)
- Decision priority (critical → expedited scheduling)

### Stage 2 — Strategy Selection

**Input**: `PlanGoal`
**Output**: `Strategy` (registered template)

Strategy registry maps goals to plan templates.

Selection logic:
```
1. Match PlanGoal.target_action to strategy registrations
2. If multiple matches, score by priority and confidence
3. Fall back to "general_engagement" strategy
4. Strategy provides:
   - Task template list
   - Default dependency topology
   - Scheduling constraints
   - Approval rules
   - Success criteria
```

### Stage 3 — Task Generation

**Input**: `PlanGoal` + `Strategy`
**Output**: `list[Task]`

Strategy templates are parameterized with context from the reasoning result:

- Prospect name, company, role
- Objections detected
- Buying signals
- Conversation history summary
- Preferred channel (from reasoning or defaults)

Each template produces concrete `Task` objects:
- `type` set from template
- `params` filled with context
- `instructions` rendered with context
- `reasoning_trace` linked to reasoning evidence
- `reasoning_goal` linked to the specific goal this task serves

### Stage 4 — Dependency Resolution

**Input**: `list[Task]`
**Output**: `list[Task]` with resolved `dependencies`

Builds the DAG:

1. Start from template-provided dependency hints
2. Add implicit dependencies (e.g., "send_message" depends on "wait_for_reply" completing)
3. Detect parallelism opportunities (tasks with no shared dependencies can run in parallel)
4. Insert branch/join nodes for conditional paths
5. Verify no cycles

### Stage 5 — Scheduling

**Input**: `list[Task]` with dependencies
**Output**: `list[Task]` with triggers

Attach timing constraints:

- Root tasks: `IMMEDIATELY` or `AFTER_DURATION` (from strategy)
- Follow-on tasks: `AFTER_TASK` (implicit from dependency)
- Wait-for-reply tasks: `AFTER_REPLY` with timeout config
- Business hours: wrap triggers with business-hour-aware constraints
- Blackout periods: annotate tasks that should skip blackout dates

All times are relative. No absolute datetimes.

### Stage 6 — Approval Annotation

**Input**: `list[Task]`
**Output**: `list[Task]` with approval annotations

Apply approval rules:

| Condition | Rule |
|-----------|------|
| Confidence < 0.4 | All send/commit tasks: REQUIRED |
| Confidence 0.4–0.7 | Send tasks: RECOMMENDED |
| Policy "requires_review" | Matching tasks: POLICY_MANDATED |
| Budget > $50k mention | Approval tasks: REQUIRED |
| First outreach to executive | Approval: RECOMMENDED |
| Risk = "high" | All commit tasks: REQUIRED |

### Stage 7 — Validation

**Input**: `Plan` (pre-validation)
**Output**: `PlanStatus.VALIDATED` or rejection with reasons

Validation rules:

```
Structural:
- No cycles in dependency graph
- All task IDs in dependencies exist
- At least one terminal node (no outgoing deps)
- All branch paths terminate or converge
- No disconnected subgraphs

Scheduling:
- No conflicting trigger types on same path
- Wait-for-reply has a timeout defined
- Business-hours tasks have window_start/window_end
- No task scheduled before its dependencies

Approval:
- POLICY_MANDATED tasks have an associated Approval record
- REQUIRED approvals have a fallback for denial

Integrity:
- Every task has a reasoning_trace
- Every task has a reasoning_goal
- No duplicate task IDs
- Strategy template is fully expanded (no unresolved placeholders)
```

### Stage 8 — Final Plan

**Output**: `Plan` with `status=VALIDATED`

Packages the completed plan:

```python
Plan(
    id=uuid,
    conversation_id=...,
    reasoning_id=...,
    status=PlanStatus.VALIDATED,
    tasks=[...],
    goal=PlanGoal(...),
    strategy="demo_booking",
    version=PLANNER_VERSION,
    created_at=now,
    validated_at=now,
    metadata={"task_count": 7, "estimated_duration": "5d"},
)
```

---

## Strategy System

Strategies are pluggable registrations.

### Registration

```python
def register_strategy(name: str, strategy_class: type[Strategy]) -> None:
    STRATEGY_REGISTRY[name] = strategy_class
```

### Strategy Interface

```python
class Strategy(ABC):
    @property
    def name(self) -> str: ...

    def matches(self, goal: PlanGoal) -> float:
        """Return match score 0.0–1.0 for the given goal."""

    def generate_tasks(self, goal: PlanGoal, context: dict) -> list[Task]:
        """Generate task list from goal and context."""

    def dependencies(self, tasks: list[Task]) -> list[Dependency]:
        """Return dependency topology hints."""

    def scheduling(self, goal: PlanGoal) -> SchedulingHints:
        """Return default scheduling constraints."""

    def approval_rules(self, tasks: list[Task]) -> list[ApprovalRule]:
        """Return approval rules for generated tasks."""
```

### Built-in Strategies

| Strategy | Triggers | Task Topology |
|----------|----------|---------------|
| **Demo Booking** | Reply → Schedule → Confirm → Remind | Linear + reminder branch |
| **Pricing Objection** | Acknowledge → Address → CTA → Follow-up | Branch on acceptance |
| **Nurture** | Value-add → Wait → Check-in → Repeat | Cyclical (via reflection) |
| **Cold Outreach** | Initial → Follow-up 1 → Follow-up 2 → Final | Linear with timeout branches |
| **Follow-up** | Context → Value → CTA → Wait | Linear, short |
| **Re-engagement** | Hook → Value → Offer → CTA | Branch on reply |
| **General Engagement** | Respond → Analyze → Next action | Single task + reflect |
| **Escalation** | Identify → Route → Notify → Handoff | Fork + notify path |

Strategies are independent of channels. The same strategy works for email, LinkedIn, Slack, etc. Channel selection is a parameter, not a strategy concern.

---

## Scheduling Model

All timing is relative. The scheduler produces trigger constraints, not absolute timestamps.

### Trigger Types

```python
@dataclass
class Trigger:
    type: TriggerType

    # Type-specific value:
    #   IMMEDIATELY     → value=None
    #   AFTER_REPLY     → value=timeout_duration ("3d", "5d")
    #   AFTER_DURATION  → value=duration ("30m", "2h", "3d")
    #   AFTER_TASK      → value=task_id
    #   BUSINESS_HOURS  → window_start="09:00", window_end="17:00"
    #   SPECIFIC_TIME   → value=datetime (only for confirmed events)
    #   ON_CONDITION    → value=condition_key
    value: str | int | datetime | None = None

    window_start: str | None = None   # "09:00"
    window_end: str | None = None      # "17:00"
    timezone: str = "UTC"
```

### Duration Format

Standardized duration strings:
- `"30m"` — 30 minutes
- `"2h"` — 2 hours
- `"3d"` — 3 days
- `"1w"` — 1 week
- `"2w"` — 2 weeks

### Scheduling Constraints

Applied by the scheduler stage, not stored in tasks:

```python
@dataclass
class ScheduleConstraints:
    timezone: str
    business_hours_only: bool = True
    min_delay_between_tasks_minutes: int = 30
    max_tasks_per_day: int = 3
    preferred_days: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])  # Mon-Fri
    blackout_periods: list[tuple[datetime, datetime]] = field(default_factory=list)
```

The execution layer resolves relative triggers to absolute times using these constraints.

---

## Validation Rules

### Structural Validation

| Rule | Code | Severity |
|------|------|----------|
| Dependency graph contains a cycle | `cycle_detected` | ERROR |
| Task references unknown dependency ID | `dangling_dependency` | ERROR |
| No terminal node in graph | `no_terminal_node` | ERROR |
| Branch path does not converge | `unterminated_branch` | ERROR |
| Disconnected subgraph | `disconnected_graph` | WARNING |
| More than 50 tasks in single plan | `plan_too_large` | WARNING |
| Branch condition has no evaluation task | `branch_no_evaluator` | WARNING |

### Scheduling Validation

| Rule | Code | Severity |
|------|------|----------|
| AFTER_REPLY task has no timeout | `reply_no_timeout` | ERROR |
| BUSINESS_HOURS task has no window | `business_hours_no_window` | WARNING |
| SPECIFIC_TIME in non-confirmed path | `specific_time_unconfirmed` | WARNING |
| wait_duration has no duration value | `duration_missing` | ERROR |
| Task trigger references non-existent task | `trigger_task_missing` | ERROR |

### Approval Validation

| Rule | Code | Severity |
|------|------|----------|
| POLICY_MANDATED task has no approval record | `policy_mandated_missing_approval` | ERROR |
| REQUIRED approval lacks denial fallback | `approval_no_fallback` | WARNING |
| Multiple conflicting approval requirements | `conflicting_approvals` | WARNING |

### Integrity Validation

| Rule | Code | Severity |
|------|------|----------|
| Task missing reasoning_trace | `missing_reasoning_trace` | WARNING |
| Task missing reasoning_goal | `missing_reasoning_goal` | WARNING |
| Duplicate task IDs | `duplicate_task_id` | ERROR |
| Unresolved template placeholder in instructions | `unresolved_placeholder` | ERROR |

---

## Explainability

Every task in a plan must answer:

1. **Why does this task exist?**
   - `task.reasoning_trace`: "Confidence was 0.45 (< 0.75 policy threshold). Policy 'confidence_check' returned 'requires_review'. Approval gate inserted before send."

2. **What reasoning created it?**
   - `task.reasoning_goal`: "Goal: book_demo. Strategy: demo_booking. This task sends the confirmation email after the prospect agrees to a time."

3. **What goal does it support?**
   - `task.goal_link`: References the parent `PlanGoal.target_action` and `PlanGoal.outcome`.

4. **What are the consequences of skipping it?**
   - Computed by the validation layer from dependency chain.

### Trace Chain

```
Conversation Intelligence
  → Evidence: "Prospect mentioned budget of $50k"
    → Reasoning
      → Decision: book_meeting
        → Planning
          → Goal: Schedule and confirm demo
            → Task: send_demo_confirmation
              → reasoning_trace: "Derived from strategy demo_booking,
                 step 2 of 4. Reasoning decided book_meeting with
                 confidence 0.82. Priority: high."
```

This chain is visible in the plan metadata and can be rendered in the frontend for human review.

---

## Folder Structure

```
services/planner/
├── __init__.py                  # Public exports, version constants
├── planner_models.py            # Plan, Task, Trigger, Branch, etc.
├── planner_pipeline.py          # Orchestrates all stages
│
├── stages/
│   ├── __init__.py
│   ├── goal_analysis.py         # Stage 1
│   ├── strategy_selector.py     # Stage 2
│   ├── task_generator.py        # Stage 3
│   ├── dependency_resolver.py   # Stage 4
│   ├── scheduler.py             # Stage 5
│   ├── approval_annotator.py    # Stage 6
│   ├── plan_validator.py        # Stage 7
│   └── plan_assembler.py        # Stage 8
│
├── strategies/
│   ├── __init__.py
│   ├── strategy_base.py         # Strategy ABC
│   ├── strategy_registry.py     # Registration + selection
│   ├── demo_booking.py
│   ├── pricing_objection.py
│   ├── nurture.py
│   ├── cold_outreach.py
│   ├── follow_up.py
│   ├── re_engagement.py
│   ├── general_engagement.py
│   └── escalation.py
│
├── validation/
│   ├── __init__.py
│   ├── rules.py                 # Individual validation rules
│   ├── graph.py                 # DAG cycle detection, connectivity
│   └── scheduler_checks.py      # Schedule integrity checks
│
└── docs/
    └── extension-points.md      # How to add new strategies/channels
```

---

## Extension Points

### Adding a New Strategy

1. Create `services/planner/strategies/my_strategy.py`
2. Implement `Strategy` ABC
3. Call `register_strategy("my_strategy", MyStrategy)` in `strategy_registry.py` or at startup

No changes to pipeline stages. No changes to other strategies.

### Adding a New Channel

Channels are not part of the planner. They belong in the execution layer.

The planner produces `Task` objects with:
- `type` (e.g., `SEND_MESSAGE`)
- `params` (e.g., `{"channel": "linkedin", "template": "connection_request"}`)

The execution layer reads `params.channel` and selects the appropriate channel adapter. Adding a new channel requires:
1. Adding the channel to the execution layer
2. (Optional) Adding a new `TaskType` if the channel has unique task semantics

No changes to planner internals.

### Adding a New Validation Rule

Add a function to `services/planner/validation/rules.py` following the existing pattern:

```python
def check_no_cycles(plan: Plan) -> list[ValidationIssue]:
    """Detect cycles in task dependency graph."""
```

Register it in `plan_validator.py`.

### Custom Scheduling Constraints

Scheduling constraints are parameters, not code. Change them via config:

```python
# config/scheduling.py
SCHEDULE_CONSTRAINTS = {
    "default": {
        "timezone": "America/New_York",
        "business_hours_only": True,
        "min_delay_between_tasks_minutes": 30,
    },
    "expedited": {
        "business_hours_only": False,
        "min_delay_between_tasks_minutes": 5,
    },
}
```

### Integration with External Systems

The planner produces plans. It never calls external systems.

External integrations (CRM, Calendar, Gmail, LinkedIn, WhatsApp, Slack) belong in the execution layer. The planner annotates tasks with channel and type information. The executor dispatches to the appropriate adapter.

```
Planner
  │  plan.tasks[0] = {type: "send_email", params: {channel: "gmail", ...}}
  ▼
Executor
  │  reads params.channel → routes to GmailAdapter
  ▼
GmailAdapter  ← in channel_adapters/
  │  sends the email
  ▼
Reflection
  │  result = {sent: true, message_id: "..."}
  ▼
Next planning cycle
```

---

## Constraints

- Never executes actions
- Never generates replies
- Never calls providers
- Never accesses external systems
- Never produces absolute datetimes
- Never modifies reasoning results
- Never modifies conversation intelligence
- Never imports from channel adapters
- Never imports from execution layer
- Plans are always validated before being returned
- All tasks are traceable to reasoning
- Strategies are pluggable — engine never knows which strategy is active
- Scheduling is relative — execution layer resolves to absolute times

---

## Implementation Report

### Package Structure

```
services/planner/
├── __init__.py                  # Public exports
├── planning_models.py           # All data models and enums
├── planning_pipeline.py         # Pipeline orchestrator + goal analysis + strategy selection
├── task_generator.py            # Task generation from strategy templates
├── dependency_builder.py        # DAG building, implicit dependencies, cycle detection
├── scheduling_engine.py         # Relative trigger assignment, business hours constraints
├── branching_engine.py          # Branch/join node insertion, branch condition resolution
├── approval_engine.py           # Approval rules based on confidence, risk, strategy rules
├── plan_validator.py            # Full structural/scheduling/approval/integrity validation
└── strategies/
    ├── __init__.py
    ├── strategy_base.py         # Strategy ABC + SchedulingHints, ApprovalRule
    ├── planning_registry.py     # Registration + scoring selection + fallback
    ├── demo_booking.py          # 4 tasks: invite → wait → confirm → remind
    ├── pricing_objection.py     # 3 tasks: acknowledge → value → CTA
    ├── nurture.py               # 4 tasks: value → wait → check-in → analyze
    ├── cold_outreach.py         # 4 tasks: initial → f/u 1 → f/u 2 → final
    ├── follow_up.py             # 3 tasks: context → value → CTA
    ├── re_engagement.py         # 4 tasks: hook → value → offer → wait
    ├── general_engagement.py    # 2 tasks: reply → analyze
    └── escalation.py            # 4 tasks: identify → route → notify → handoff
```

### API Endpoint

```
POST /api/web/session/{session_token}/conversations/{conversation_id}/plan
```

Returns:
- `plan` — Serialized Plan with all tasks, goal, strategy, status
- `graph` — Nodes (id, type, status, label, dependencies, approval) + Edges (source, target)
- `explainability` — Goal, strategy, task_chain (id, label, type, reason, goal, approval), total_tasks
- `validation` — valid (bool), issues[], warnings[]

### Frontend

- `ExecutionPlanPanel` component added to conversation detail sidebar
- Displays: goal card, task list with expandable details, validation status, reasoning trace chain
- Visualization only — no action buttons
- Integrated into `conversations/[id]/page.tsx`

### Deviations from Architecture Design

None intentional. Notes on minor implementation choices:

1. **`branching_engine.py` as separate file** — Architecture shows branching within dependency/scheduling stages, but a dedicated module keeps branch/join logic isolated and testable.

2. **Goal analysis inlined in pipeline** — Goal Analysis (Stage 1) and Strategy Selection (Stage 2) are implemented as methods on `PlanningPipeline` rather than separate files, since they are tightly coupled to the pipeline's input transformation.

3. **Strategy dependencies use label matching** — `strategy.dependencies()` returns pairs by task label rather than task ID, since IDs are assigned at creation time. The `build_dependencies` stage resolves labels to IDs via `task_map`.

4. **Pipeline stage error isolation** — Each stage is wrapped in try/except so a failure in one stage (e.g., scheduling) does not prevent other stages from running. Defaults/fallbacks are used when stages fail.

5. **Validation severity** — Architecture describes errors vs warnings. Implementation adds `ValidationIssue` with `severity` field. Structural issues are errors; missing reasoning_trace/goal are warnings.

### Test Coverage

Tests in `backend/tests/test_planner.py`:

| Category | Tests | Coverage |
|----------|-------|----------|
| DAG Cycle Detection | 6 | Linear, cyclic, empty, singleton, diamond, self-reference |
| DAG Validation | 5 | Valid, cyclic, dangling, terminal, unreachable |
| Plan Validation | 5 | Valid, empty, duplicates, trace warnings, missing instructions, branch structure |
| Strategy Selection | 7 | All 8 strategies match correctly, fallback, custom registration |
| Task Generation | 3 | Count, reasoning trace, reasoning goal |
| Full Pipeline | 8 | Produces plan, strategy populated, triggers, status, approvals, minimal input, acyclic DAG, plan_id |
| Pipeline Isolation | 1 | Produces plan not reply |
| DAG Properties | 5 | Roots, terminals, downstream, pairs, task map |

Total: 40 tests

### Success Criteria Verification

| Criteria | Status |
|----------|--------|
| Valid ReasoningResult produces valid ExecutionPlan | ✓ |
| Plans represented as DAGs with validated dependencies | ✓ |
| Strategies are pluggable and isolated | ✓ |
| Frontend visualizes plan without executing | ✓ |
| Planning Engine fully decoupled from execution/generation | ✓ |
