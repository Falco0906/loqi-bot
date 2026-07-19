# Adapter Registry Integration v1 — Architecture Freeze

## Adapter Registry Version

**v1.0**

## Freeze Date

2026-07-18

## Freeze Status

**FROZEN**

No further changes to the adapter registry integration layer are permitted without an RFC.

---

## Core Architectural Principles

1. **Registry stores registrations only.** `AdapterRegistry` holds `AdapterRegistration` objects — metadata, class references, capability/credential mappings. No adapter instances, no runtime state, no execution.

2. **Factory never caches.** `AdapterFactory.create()` returns a fresh instance every time. No singletons, no pools, no memoization. Adapters remain stateless.

3. **Provider selection is deterministic.** `select_provider()` uses a fixed algorithm: priority descending → version descending → registration order ascending. No randomness, no timestamps, no external state.

4. **Identity is a value object.** `AdapterIdentity(name, version)` replaces raw string tuples everywhere. Enforces naming rules, supports comparison, and provides a future-proof extension point.

5. **Registrations are immutable.** Every `AdapterRegistration` is a frozen dataclass. No code may mutate a registration after construction.

6. **Integration is opt-in.** `CapabilityRegistry` and `CredentialRegistry` are optional constructor arguments. Without them, the registry works independently. With them, it validates cross-references eagerly on registration.

7. **No runtime or planner imports.** The registry layer imports zero modules from `services.execution` or `services.planner`. The runtime imports from the registry; the registry never imports from the runtime.

---

## Extension Points (non-breaking)

- Adding new query methods to `AdapterRegistry`
- Adding new optional fields to `AdapterRegistration` (with defaults)
- Adding new selection strategies (weighted, round-robin, etc.)
- Adding alias support to `AdapterIdentity`
- Adding deprecation/sunset fields to `AdapterRegistration`
- Registering new adapter classes (concrete adapters in future phases)
- Adding new test cases

---

## RFC-Required Changes

- Making `AdapterRegistration` or `AdapterIdentity` mutable
- Removing or renaming public registry methods
- Changing the identity model (name + version)
- Adding adapter execution logic to the registry or factory
- Adding runtime or planner imports to any registry module
- Introducing adapter instance caching in the factory
- Changing the provider selection algorithm

---

## Known Limitations (v1.0)

| Limitation | Accepted Because |
|---|---|
| No alias support | Can be added to `AdapterIdentity` as an optional field |
| No deprecation tracking | Can be added to `AdapterRegistration` when adapters are phased out |
| No version range queries | Runtime picks best version; consumers needing ranges can filter post-query |
| No health-aware routing | Health checks belong in the runtime, not the registry |
| No hot-reload support | Can be added as a `reload()` method when dynamic loading is needed |

---

## Dependency Rules

```
Execution Runtime
    │ depends on
    ▼
Adapter Registry
    │ depends on
    ├── AdapterIdentity
    ├── AdapterRegistration
    ├── AdapterFactory
    │
    ├── optionally: CapabilityRegistry (from capability system)
    ├── optionally: CredentialRegistry (from credential framework)
    │
    └── always: ExecutionAdapter (from adapter SDK)
```

```
Adapter Registry ── never ──▶ services.execution
Adapter Registry ── never ──▶ services.planner
Adapter Registry ── never ──▶ concrete adapters
```

---

## Freeze Rationale

The Adapter Registry Integration Layer composes all three Chapter 4 pillars — Adapter SDK, Capability System, and Credential Framework — into a single unified interface. The `AdapterIdentity` value object eliminates stringly-typed APIs. The factory enforces stateless construction. Provider selection is fully deterministic.

The runtime now needs only a single dependency: `registry.create_adapter(identity)`. Everything else — metadata, capabilities, credentials, provider selection — is managed by the registry.

No concrete adapter has yet proven any of these abstractions insufficient. Until one does, the layer is frozen.
