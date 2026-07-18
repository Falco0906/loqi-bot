# Planning Engine Hardening Report — Phase 3.6.3.1

## 1. Files Modified

### New Files
- `backend/services/planner/exceptions.py` — Typed exception hierarchy.
- `backend/services/planner/payloads.py` — Typed task payload system and registry.

### Core Planner Files
- `backend/services/planner/planning_models.py` — Added `payload` field to `Task`, `get_payload()` reconstruction, synchronization between `payload` and `params`.
- `backend/services/planner/planning_pipeline.py` — Fail-fast validation, typed exception wrapping, thread-safe pipeline singleton, added `plan_or_none()` for backward-compat callers.
- `backend/services/planner/dependency_builder.py` — Removed label-based mapping; dependencies now resolved by stable task IDs; pre-existing dangling dependencies are rejected with `PlanningGraphError`.
- `backend/services/planner/plan_validator.py` — Added `suggested_fix` to `ValidationIssue`, structured error codes, payload validation, `ValidationResult.to_dict()`.
- `backend/services/planner/branching_engine.py` — `BRANCH`/`JOIN` nodes now use typed `BranchPayload` / `JoinPayload`.
- `backend/services/planner/approval_engine.py` — No logic changes; remains compatible.
- `backend/services/planner/scheduling_engine.py` — No logic changes; remains compatible.
- `backend/services/planner/task_generator.py` — No logic changes; remains compatible.
- `backend/services/planner/__init__.py` — Exports exceptions and payload classes.

### Strategy Files
- `backend/services/planner/strategies/strategy_base.py` — Documented ID-based dependency contract.
- `backend/services/planner/strategies/planning_registry.py` — Thread-safe, idempotent registration; deterministic default-strategy initialization; snapshot-based selection.
- `backend/services/planner/strategies/demo_booking.py`
- `backend/services/planner/strategies/pricing_objection.py`
- `backend/services/planner/strategies/nurture.py`
- `backend/services/planner/strategies/cold_outreach.py`
- `backend/services/planner/strategies/follow_up.py`
- `backend/services/planner/strategies/re_engagement.py`
- `backend/services/planner/strategies/general_engagement.py`
- `backend/services/planner/strategies/escalation.py`

All strategies now:
- Declare stable task IDs.
- Return ID-based dependency pairs.
- Use typed payloads instead of anonymous dictionaries.

### API Layer
- `backend/main.py` — Planner endpoint now catches `PlanningValidationError` and returns structured error responses; validation diagnostics include `suggested_fix`.

### Tests
- `backend/tests/test_planner.py` — Updated existing tests; added 17 new hardening tests covering fail-fast exceptions, typed payloads, ID-based dependencies, registry hardening, exception hierarchy, and validation diagnostics.

---

## 2. Hardening Summary

### HT-1: Validation Must Fail Fast
- `PlanningPipeline.plan()` now raises `PlanningValidationError` if validation fails.
- Validation exceptions inside `_validate()` are no longer swallowed; they are re-raised as `PlanningValidationError` with full context.
- Pipeline stage failures now raise typed exceptions (`PlanningStrategyError`, `PlanningGraphError`, `PlanningSchedulingError`, `PlanningPipelineError`) with actionable context.
- The API endpoint `/api/web/session/{token}/conversations/{id}/plan` returns `{ok: False, error, error_type, validation}` on validation failures.

### HT-2: Typed Task Payloads
- Introduced `TaskPayload` base class and concrete payloads:
  - `MessagePayload`
  - `WaitForReplyPayload`
  - `WaitDurationPayload`
  - `AnalyzeReplyPayload`
  - `EscalatePayload`
  - `UpdateCRMPayload`
  - `RequestApprovalPayload`
  - `ScheduleMeetingPayload`
  - `BranchPayload`
  - `JoinPayload`
- `Task.payload` stores the typed payload; `Task.params` is automatically synchronized to the serialized form.
- `Task.get_payload()` can reconstruct the typed payload from `params` using the payload registry.
- Payloads implement `validate()` for early parameter validation.

### HT-3: Stable ID-Based Dependencies
- Removed all label-based dependency resolution.
- Strategies declare stable task IDs and return `(source_id, target_id)` dependency pairs.
- `build_dependencies()` validates every dependency reference against known task IDs.
- Pre-existing dangling dependencies are rejected before any new edges are added.

### HT-4: Thread-Safe Strategy Registry
- Added module-level `_registry_lock` and `_default_strategies_lock`.
- `register_strategy()` is idempotent and validates input types.
- `ensure_default_strategies_registered()` initializes defaults exactly once in deterministic order.
- `select_strategy()` operates on a snapshot of the registry to avoid iteration races.

### HT-5: Exception Hierarchy
- Base `PlanningError` carries `message` and `context` and serializes via `to_dict()`.
- Subclasses:
  - `PlanningValidationError`
  - `PlanningStrategyError`
  - `PlanningGraphError`
  - `PlanningSchedulingError`
  - `PlanningPipelineError`

### HT-6: Improved Validation Diagnostics
- `ValidationIssue` now includes `severity`, `code`, `message`, `task_id`, and `suggested_fix`.
- Error codes are uppercase, stable strings (e.g., `CYCLE_DETECTED`, `DANGLING_DEPENDENCY`, `MISSING_INSTRUCTIONS`).
- Suggested fixes guide callers toward remediation.
- `ValidationResult.to_dict()` returns fully serializable diagnostics.

### HT-7: Preserved Explainability
- `reasoning_trace`, `reasoning_goal`, `reasoning_id`, and strategy name remain in every task and plan.
- Payload typing does not replace trace fields; it supplements task parameters.

---

## 3. Backward Compatibility

- `Task.params` continues to be a `dict[str, Any]` and serializes identically for existing consumers.
- The API response for a valid plan is unchanged except for the addition of `suggested_fix` inside `issues`/`warnings`, which is additive.
- `plan_or_none()` provides a non-raising helper for callers that cannot yet migrate to exception handling.
- `generate_plan()` now raises on invalid plans rather than returning `(plan, None)`; this is an intentional behavioral hardening consistent with the audit findings.
- Strategy matching behavior is unchanged; only mechanism internals changed.
- Existing DAG traversal APIs (`get_root_tasks`, `get_terminal_tasks`, etc.) are unchanged.

---

## 4. Remaining Technical Debt

These are non-blocking improvements to address in future phases:

1. **Configuration layer** — Hard-coded approval rules and confidence thresholds should be externalized into policy configuration.
2. **Deserialization robustness** — `Task.get_payload()` silently returns `None` on mismatch; future work should add strict deserialization helpers for the execution layer.
3. **Validation rule registry** — Validation checks are currently inline; a pluggable rule registry would make adding new checks easier.
4. **Payload version migration** — As payloads evolve, a migration/versioning strategy may be needed for persisted plans.
5. **Graph visualization overhaul** — The frontend still shows a linear list; a true DAG graph renderer is a feature for a future UI phase.
6. **Strategy discovery at scale** — Linear strategy scoring is fine for ~10 strategies but should be replaced with indexed/categorized lookup when the count grows past 20–30.
7. **Execution-layer integration tests** — Unit tests verify planning in isolation; integration tests with a mock Execution Engine should be added once the Execution Engine is implemented.

---

## Verification

- Backend tests: `python3 -m pytest backend/tests/test_planner.py` → **58 passed, 0 failed**.
- Backend syntax: `python3 -m py_compile` over planner modules and `main.py` → clean.
- Frontend TypeScript: `npx tsc --noEmit` → no new errors from `ExecutionPlanPanel`.

No architectural changes were made. All modifications preserve the existing planning lifecycle, DAG model, strategy interface, scheduling abstraction, and approval concepts.
