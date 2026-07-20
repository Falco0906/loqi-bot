# ADR-0010 — Execution Platform Stability

## Metadata

| Field | Value |
|---|---|
| **Version** | v1.0 |
| **Date** | 2026-07-19 |
| **Status** | **STABLE** |

---

## Decision

The execution platform is declared stable.

Future development should extend the platform through its documented extension points rather than modifying its core execution architecture.

Changes to the execution core require an RFC or ADR as described in this document.

---

## Rationale

The execution platform has been validated through Phases 1–9:

- Production registry integration
- Heterogeneous multi-task execution
- Planner routing and strategy resolution
- Credential factory integration with per-user token refresh
- Production event bus subscription
- Metrics collection
- A production readiness audit covering all 10 architecture areas
- A comprehensive automated test suite validating the execution platform

No architectural deficiencies requiring architectural redesign were identified during the production readiness audit.

This ADR marks the transition from **building infrastructure** to **building on infrastructure**.

---

## Relationship to Existing Freeze Documents

Component freeze documents remain authoritative for implementation details.

This ADR establishes the stability contract across the platform as a whole — it complements rather than replaces the existing per-component freezes.

| Freeze Document | Covers |
|---|---|
| `ARCHITECTURE_FREEZE.md` | Execution Engine runtime, Scheduler, Dispatcher, State Machine, RecoveryManager |
| `ADAPTER_SDK_FOUNDATION_FREEZE.md` | Adapter SDK base classes, models, exception hierarchy |
| `ADAPTER_REGISTRY_FREEZE.md` | Registry registration and discovery contract |
| `CREDENTIAL_FRAMEWORK_FREEZE.md` | Credential resolution lifecycle and factory contract |

---

## Platform Stability Matrix

| Component | Status | Reference | Stability Guarantee |
|---|---|---|---|
| **Execution Engine** | Stable | `ARCHITECTURE_FREEZE.md` | Execution semantics, state machine transitions, and DAG scheduling are stable. |
| **Dispatcher** | Stable | (engine) | Adapter resolution and dispatch contract is stable. |
| **Adapter Registry** | Stable | `ADAPTER_REGISTRY_FREEZE.md` | Registration and discovery contract is stable. |
| **BridgeAdapter** | Stable | (engine) | Bridge adapter pattern for wrapping SDK adapters is stable. |
| **Adapter SDK** | Stable | `ADAPTER_SDK_FOUNDATION_FREEZE.md` | `ExecutionAdapter` contract and model hierarchy are stable. |
| **Planner Router** | Stable | (engine) | Planning entrypoint and strategy resolution contract is stable. |
| **Credential Factory** | Stable | `CREDENTIAL_FRAMEWORK_FREEZE.md` | Per-user credential resolution lifecycle is stable. |
| **Event Bus** | Stable | (engine) | Publish/subscribe semantics are stable. |
| **Payload Validation** | Stable | (engine) | Plan and session validation contracts are stable. |
| **MetricsCollector** | Stable | (engine) | Event-driven, passive observability contract is stable. |

---

## What Stability Means

### Allowed (no RFC required)

- Bug fixes
- Performance improvements
- Internal refactoring without public API changes
- New adapter implementations
- New strategy implementations
- New `TaskType` enum members
- New `EventBus` subscribers
- Additional metrics fields
- New payload models that extend existing validation
- Backward-compatible model fields

### Requires RFC / ADR

- Changes to execution semantics (scheduler behavior, state machine transitions)
- Changes to `Dispatcher.dispatch()` contract or adapter resolution
- Changes to `ExecutionAdapter` interface or SDK models that break existing adapters
- Changes to credential resolution lifecycle (factory signature, token refresh semantics)
- Changes to `PlannerRouter.route()` or strategy resolution protocol
- Changes to `EventBus` publish/subscribe semantics or subscriber error handling
- Changes to plan or session validation contracts
- Changes to the `MetricsCollector` passive subscriber model

---

## Boundary (Out of Scope)

The following systems intentionally remain outside this stability declaration because they are expected to evolve with product capabilities. No stability guarantees are made about these systems, and no RFC is required for changes within them.

| System | Rationale |
|---|---|
| **Conversation Engine** | Message routing, intent classification, and session management are product-facing and will change as interfaces evolve. |
| **Workflow implementations** | `workflows.py` and `run_workflow()` contain product-specific logic for lead generation, draft creation, and sending. |
| **Strategy implementations** | Per-strategy logic inside `services/planner/strategies/` is the primary extension point for new outreach patterns. |
| **AI prompts and personalization** | Prompt engineering and personalization logic evolve continuously with model capabilities. |
| **Gmail synchronization** | Sync scheduling, conflict resolution, and pagination are infrastructure concerns that may need redesign as data volume grows. |
| **Outbound scheduler** | Scheduling heuristics, polling intervals, and provider selection are product tuning concerns. |
| **Provider implementations** | `GmailProvider`, `GmailOutboundProvider`, and credential provider instances are integration adapters. |
| **Product-specific business logic** | Lead scoring, enrichment, ICP extraction, and campaign logic are product-domain code. |

---

## Approved Extension Points

The execution platform is stable *because* it has well-defined extension mechanisms. Future development should prefer these mechanisms over modifying the execution core.

| Extension Point | Mechanism |
|---|---|
| **New adapter** | Implement `ExecutionAdapter` + `register()` on `AdapterRegistry` |
| **New strategy** | Implement `StrategyBase` + `register_strategy()` on planning registry |
| **New `TaskType`** | Add enum member + register an adapter for it |
| **New payload model** | Define model + extend `validate_plan_for_execution` |
| **New event subscriber** | Implement `EventSubscriber` protocol + `subscribe()` on `EventBus` |
| **New credential provider** | Implement a credentials factory + register via `credentials_factory` |
| **New metrics collector** | Implement `EventSubscriber` + derive from the event stream |
| **New recovery strategy** | Extend `RecoveryManager` with additional `fix_states()` handlers |

---

## Conclusion

The execution platform is considered stable. Future work should primarily extend platform capabilities through the approved extension points while preserving the execution contracts defined in this ADR.
