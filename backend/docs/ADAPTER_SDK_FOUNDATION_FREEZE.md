# Adapter SDK Foundation v1 — Architecture Freeze

## Adapter SDK Version

**v1.0**

## Freeze Date

2026-07-18

## Freeze Status

**FROZEN**

No further changes to the adapter SDK foundation are permitted without an RFC.

---

## Core Architectural Principles

1. **ExecutionAdapter is the sole adapter contract.** Every adapter implements `metadata` + `execute()`. No additional required methods exist. Adding a new adapter never requires SDK changes.

2. **Adapters are stateless.** All execution state lives in `AdapterContext`. Adapters never mutate context, never hold per-execution state, and never maintain singleton caches.

3. **Models are immutable where practical.** `AdapterMetadata`, `AdapterContext`, `AdapterResult`, and `UsageInfo` are all frozen dataclasses. No code may mutate them after construction.

4. **Single responsibility per module.** `ExecutionAdapter` defines behavior. `AdapterMetadata` describes identity. `AdapterContext` carries parameters. `AdapterResult` represents output. Exceptions represent failures. No merging of concerns.

5. **Exceptions separate retryable from fatal cleanly.** `TransientAdapterError` and `RateLimitError` are retryable. `FatalAdapterError`, `AdapterExecutionError`, `ConfigurationError`, `AuthenticationError`, `AuthorizationError`, `PermissionError`, `ValidationError`, and `ResourceNotFoundError` are never retried.

6. **Runtime depends on abstractions, not implementations.** The execution runtime imports only public SDK abstractions (`ExecutionAdapter`, `AdapterContext`, `AdapterResult`, `AdapterMetadata`). No concrete adapter logic exists in the SDK.

7. **SDK has zero runtime dependencies.** The SDK package never imports `services.execution`, `services.planner`, or any runtime module. It can be imported and tested in isolation.

8. **Protocols describe behavior, not inheritance.** `Validator`, `HealthCheckable`, and `CapabilityReporter` are `@runtime_checkable` protocols. Adapters conform by defining the method — no base class required.

---

## Extension Points (non-breaking)

These changes do NOT require an RFC and may be made freely:

- Adding new exception subclasses under the existing hierarchy
- Adding new protocol definitions
- Adding new convenience methods to existing models (e.g., new factory methods on `AdapterResult`)
- Adding new optional fields to models (with defaults to preserve backward compatibility)
- Adding new test cases

---

## RFC-Required Changes

These changes DO require an RFC:

- Adding new required methods to `ExecutionAdapter`
- Removing or renaming existing fields on any frozen model
- Making any frozen model mutable
- Changing the exception hierarchy (moving classes, changing base classes)
- Adding runtime imports to any SDK module
- Adding concrete adapter logic to the SDK
- Renaming or removing public exports from `__init__.py`
- Changing protocol signatures

---

## Known Limitations (v1.0)

| Limitation | Accepted Because |
|---|---|
| No streaming execution model | `execute_stream()` can be added as an optional protocol when real streaming adapters arrive |
| No progress reporting | Can be added via optional `progress_callback` field in `AdapterContext` |
| No idempotency key in context | Can be added as an optional `AdapterContext` field when the runtime supports idempotency |
| No pagination model | `next_page_token` can be carried in `AdapterResult.metadata` without changing the result model |
| `AdapterMetadata.supported_operations` is a tuple of strings, not a typed enum | Keeps the SDK generic; adapters define their own operations |

---

## Dependency Rules

```
Execution Runtime
    │ depends on
    ▼
Adapter SDK  (this layer)
    │ depends on (stdlib only)
    ▼
stdlib (abc, dataclasses, typing, logging)

```

- The SDK must never import `services.execution`
- The SDK must never import `services.planner`
- The SDK must never import any concrete adapter
- The runtime may import any SDK public export

---

## Freeze Rationale

The Adapter SDK Foundation defines a stable contract for every future adapter. The base class is minimal (only `metadata` + `execute` required). All models are frozen. The exception hierarchy clearly separates retryable from fatal failures. Protocols describe optional behavior without forced inheritance.

The SDK is generic enough for Gmail, Slack, HTTP, Calendar, Drive, Apollo, and any future integration — without containing any concrete adapter logic.

No real adapter has yet proven any of these abstractions insufficient. Until one does, the SDK foundation is frozen.
