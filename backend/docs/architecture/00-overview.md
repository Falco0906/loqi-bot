# Loqi Backend Architecture

## Five-Layer Platform

The Loqi backend is organized into five frozen layers that build on one another. Each layer has a single responsibility and a stable public API. No layer may be modified without an RFC.

```
┌──────────────────────────────────────────────────────────────┐
│  Layer 5: Adapter Registry (05-adapter-registry.md)          │
│  Registration, factory, provider selection, lifecycle        │
│  Integrates: capabilities + credentials + adapters           │
├──────────────────────────────────────────────────────────────┤
│  Layer 4: Credential Framework (04-credential-framework.md)  │
│  Descriptors, references, instances, masking, resolver ABC   │
├──────────────────────────────────────────────────────────────┤
│  Layer 3: Capability System (03-capability-system.md)        │
│  Descriptors, params, providers, categories, registry        │
├──────────────────────────────────────────────────────────────┤
│  Layer 2: Adapter SDK (02-adapter-sdk.md)                    │
│  ExecutionAdapter ABC, models, context, exceptions, protocols│
├──────────────────────────────────────────────────────────────┤
│  Layer 1: Execution Runtime (01-execution-runtime.md)        │
│  Engine, scheduler, dispatcher, state machine, event bus     │
└──────────────────────────────────────────────────────────────┘
```

## Data Flow

```
User Request
    │
    ▼
Planner ────────────────────────────────────────────────┐
    │  "What adapters can send email?"                  │
    │  "Plan: send_email(to=x, body=y)"                 │
    ▼                                                   │
Capability Registry ◄───────────────────────────────────┘
    │  find_providers("send_email")                     │
    ▼                                                   │
Adapter Registry                                        │
    │  select_provider("send_email") → gmail v2.0.0    │
    │  factory.create(identity) → ExecutionAdapter      │
    ▼                                                   │
Adapter Factory                                         │
    │  fresh instance, never cached                     │
    ▼                                                   │
Execution Runtime                                       │
    │  Engine → Scheduler → Dispatcher → Adapter        │
    │  CredentialResolver → AdapterContext.credentials  │
    ▼                                                   │
ExecutionAdapter.execute(context) ──────────────────────┘
    │
    ▼
External API (Gmail, Slack, HTTP, ...)
```

## Dependency Rules

| Layer | Depends On | Never Imports |
|---|---|---|
| Execution Runtime | Adapter SDK (abstractions) | Concrete adapters, planner |
| Adapter SDK | stdlib only | Runtime, planner, concretes |
| Capability System | Adapter SDK (exceptions) | Runtime, planner, concretes |
| Credential Framework | Adapter SDK (exceptions) | Runtime, planner, concretes |
| Adapter Registry | All 4 lower layers (optional) | Runtime, planner, concretes |

## Invariants

- **Adapters never fetch credentials.** Credentials arrive pre-populated in context.
- **Adapters are stateless.** All per-execution state lives in `AdapterContext`.
- **Factories never cache.** Every `create()` returns a fresh instance.
- **Provider selection is deterministic.** Priority → version → registration order.
- **Models are frozen.** No mutation after construction.
- **Runtime depends on abstractions, not implementations.** No concrete adapter lives in the runtime.

## Freeze Status

| Component | Frozen | Since |
|---|---|---|
| Execution Runtime (Layer 1) | Yes | 2026-07-18 |
| Adapter SDK (Layer 2) | Yes | 2026-07-18 |
| Capability System (Layer 3) | Yes | 2026-07-18 |
| Credential Framework (Layer 4) | Yes | 2026-07-18 |
| Adapter Registry (Layer 5) | Yes | 2026-07-18 |
| HTTP Adapter | Yes | 2026-07-19 |
| Google API Base Adapter | Yes | 2026-07-19 |

No changes without an RFC. See individual layer docs for extension points, RFC requirements, and known limitations.

## Test Suite

| Layer | Tests | File |
|---|---|---|
| Execution Runtime | 174+ | `tests/test_execution_*.py` |
| Adapter SDK | 192 | `tests/test_adapter_sdk.py` |
| Capability System | 181 | `tests/test_capability_system.py` |
| Credential Framework | 149 | `tests/test_credential_framework.py` |
| Adapter Registry | 110 | `tests/test_adapter_registry*.py` |
| HTTP Adapter | 314 | `tests/test_http_adapter.py` |
| Google API Adapter | 169 | `tests/test_google_api_adapter.py` |
| **Total** | **2338+** | `tests/` (all) |

## File Layout

```
backend/services/
    adapters/                          # Layers 2–5
        __init__.py                    # Public API for all adapter layers
        base_adapter.py                # Layer 2 — ExecutionAdapter ABC
        models.py                      # Layer 2 — AdapterMetadata, AdapterResult, UsageInfo
        adapter_context.py             # Layer 2 — AdapterContext
        protocols.py                   # Layer 2 — Validator, HealthCheckable, CapabilityReporter
        exceptions.py                  # Layers 2–5 — Full exception hierarchy
        capabilities.py                # Layer 3 — CapabilityDescriptor, ParameterSpec, etc.
        capability_registry.py         # Layer 3 — CapabilityRegistry
        credentials.py                 # Layer 4 — CredentialDescriptor, CredentialInstance, etc.
        credential_registry.py         # Layer 4 — CredentialRegistry
        credential_resolver.py         # Layer 4 — CredentialResolver ABC
        adapter_registration.py        # Layer 5 — AdapterIdentity, AdapterRegistration
        adapter_factory.py             # Layer 5 — AdapterFactory
        adapter_registry.py            # Layer 5 — AdapterRegistry

    execution/                         # Layer 1
        __init__.py                    # Public API
        enums.py                       # TaskState, SessionState, ExecutionEventType
        exceptions.py                  # ExecutionError hierarchy
        execution_models.py            # ExecutionSession, ExecutionTask, TaskResult, RetryPolicy, etc.
        execution_context.py           # ExecutionContext
        execution_pipeline.py          # ExecutionEngine
        state_machine.py               # StateMachine — task & session transitions
        scheduler.py                   # Scheduler — DAG-aware task scheduling
        dispatcher.py                  # Dispatcher — AdapterResolver protocol
        event_bus.py                   # EventBus — pub/sub infrastructure
        metrics_collector.py           # MetricsCollector — passive metrics subscriber
        recovery_manager.py            # RecoveryManager — stateless recovery
        validation.py                  # Plan & session validation
        adapter_registry.py            # Legacy (superseded by services/adapters/)
        base_adapter.py                # Legacy (superseded by services/adapters/)
        utils.py                       # Utilities

    planner/                           # Planner
        ...                            # (separate service)

backend/docs/
    architecture/                      # This directory
        00-overview.md                 # You are here
        01-execution-runtime.md        # Layer 1
        02-adapter-sdk.md              # Layer 2
        03-capability-system.md        # Layer 3
        04-credential-framework.md     # Layer 4
        05-adapter-registry.md         # Layer 5
        architecture-diagram.drawio    # Visual architecture diagram
    ARCHITECTURE_FREEZE.md             # Layer 1 freeze declaration
    ADAPTER_SDK_FOUNDATION_FREEZE.md   # Layer 2 freeze declaration
    CAPABILITY_SYSTEM_FREEZE.md        # Layer 3 freeze declaration
    CREDENTIAL_FRAMEWORK_FREEZE.md     # Layer 4 freeze declaration
    ADAPTER_REGISTRY_FREEZE.md         # Layer 5 freeze declaration
    HTTP_ADAPTER_FREEZE.md             # HTTP Adapter freeze declaration
    GOOGLE_API_ADAPTER_FREEZE.md       # Google API Adapter freeze declaration
```
