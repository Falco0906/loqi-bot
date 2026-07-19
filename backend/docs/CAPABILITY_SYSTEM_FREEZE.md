# Capability System v1 — Architecture Freeze

## Capability System Version

**v1.0**

## Freeze Date

2026-07-18

## Freeze Status

**FROZEN**

No further changes to the capability system are permitted without an RFC.

---

## Core Architectural Principles

1. **Planner thinks in verbs, never implementations.** The planner queries capabilities by name, category, and tag. It never references adapter names, versions, or concrete implementations.

2. **Registry owns metadata only.** `CapabilityRegistry` stores `CapabilityDescriptor` and `CapabilityProvider` records. It never instantiates adapters, never holds runtime state, and never calls external systems.

3. **Descriptors are immutable.** Every capability descriptor is a frozen dataclass. No code may mutate a descriptor after construction.

4. **Providers bridge, not bind.** `CapabilityProvider` maps capability names to adapter identities (name + version). It does not reference adapter instances, configuration, or credentials.

5. **Categories are extensible by convention.** `CapabilityCategory` provides well-known constants, but any string is valid. No validation logic enforces a closed set of categories.

6. **Versions are first-class.** Capabilities are uniquely identified by `(name, version)`. Multiple versions of the same capability coexist. The registry stores all versions; consumers decide which to use.

7. **Search is deterministic.** `search()`, `find_by_name()`, `find_by_category()`, and `find_by_tag()` return results in registration order. No sorting, ranking, or scoring is applied.

8. **Duplicate registration is impossible.** `register()` raises `CapabilityRegistrationError` if `(name, version)` is already registered. `register_provider()` enforces the same invariant for `(adapter_name, adapter_version)`.

---

## Extension Points (non-breaking)

These changes do NOT require an RFC and may be made freely:

- Adding new constants to `CapabilityCategory`
- Adding new metadata fields to `CapabilityDescriptor` (with defaults)
- Adding new query methods to `CapabilityRegistry`
- Adding new test cases
- Adding new exception subclasses under `CapabilityRegistrationError`

---

## RFC-Required Changes

These changes DO require an RFC:

- Modifying or removing existing fields on `CapabilityDescriptor`
- Changing the `(name, version)` identity model
- Adding runtime state to `CapabilityRegistry`
- Making descriptors mutable
- Adding adapter instantiation to any capability module
- Removing or renaming public registry methods
- Adding planner-specific dependencies to the capability system
- Changing search determinism guarantees

---

## Known Limitations (v1.0)

| Limitation | Accepted Because |
|---|---|
| No hierarchical capability names (e.g., `communication.email.send`) | Not yet needed; flat names suffice for current adapters |
| No capability dependency model | Composite operations are not yet implemented |
| No auto-registration from adapter metadata | Concrete adapters do not exist yet |
| No priority-based provider selection in registry | Selection logic belongs in the runtime, not the registry |
| Descriptors do not carry rate-limit or quota metadata | Not yet needed; can be added with optional fields |

---

## Dependency Rules

```
Planner
    │ depends on
    ▼
Capability Registry
    │ depends on
    ▼
Capability Descriptor / Provider  (frozen models)
    │ depends on (stdlib only)
    ▼
Adapter SDK exceptions

```

- The capability system must never import `services.execution`
- The capability system must never import `services.planner`
- The capability system must never import any concrete adapter
- The runtime may import `CapabilityRegistry` and `CapabilityDescriptor`
- The planner may import `CapabilityRegistry`, `CapabilityDescriptor`, and `CapabilityCategory`

---

## Freeze Rationale

The capability system is complete enough to support every adapter in the roadmap (Gmail, Slack, Calendar, Drive, HTTP, Apollo). The descriptor model captures identity, parameters, returns, and discovery metadata. The registry covers all required query patterns. The provider model bridges capabilities to adapters without coupling.

No real adapter has yet proven any of these abstractions insufficient. Until one does, the system is frozen.
