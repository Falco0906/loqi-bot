# Layer 5: Adapter Registry Integration

## Purpose

Composes Layers 2–4 into a single unified interface for the execution runtime. Manages registration, query, provider selection, and factory instantiation of all adapters. The runtime needs only one dependency: `registry.create_adapter(identity)`.

## Freeze Reference

[ADAPTER_REGISTRY_FREEZE.md](../ADAPTER_REGISTRY_FREEZE.md)

## Package

`services.adapters` (`adapter_registration.py`, `adapter_factory.py`, `adapter_registry.py`)

## Components

### AdapterIdentity (`adapter_registration.py`)

```python
@dataclass(frozen=True)
class AdapterIdentity:
    name: str       # lowercase, ^[a-z][a-z0-9_.-]*$
    version: str    # any non-empty string
```

Immutable value object used as dictionary key. Comparable (`__lt__`) for deterministic ordering. Version-aware comparison (numeric parts compared as integers). Pickleable.

### AdapterRegistration (`adapter_registration.py`)

```python
@dataclass(frozen=True)
class AdapterRegistration:
    identity: AdapterIdentity
    adapter_class: type[ExecutionAdapter]
    metadata: AdapterMetadata
    capability_names: tuple[str, ...]
    credential_descriptor_names: tuple[str, ...]
    priority: int
    enabled: bool
```

Validation in `__post_init__`: identity must be AdapterIdentity, adapter_class must be a class, priority must be int, capability/credential names must be non-empty strings.

### AdapterFactory (`adapter_factory.py`)

```python
class AdapterFactory:
    def create(identity: AdapterIdentity) -> ExecutionAdapter
    def create_latest(name: str) -> ExecutionAdapter
    def create_for_capability(capability_name: str, providers: list) -> ExecutionAdapter
```

Rules:
- **Never caches instances** — every call returns a fresh object
- **Never executes adapters** — construction only
- **Never resolves credentials** — credentials arrive via context at runtime
- Raises `AdapterNotFoundError` if not registered
- Raises `AdapterDisabledError` if registration is disabled

### AdapterRegistry (`adapter_registry.py`)

Unified registry integrating with CapabilityRegistry and CredentialRegistry (both optional).

**Registration:** `register(registration)`, `unregister(identity)`, `get(identity)`, `exists(identity)`

**Query:** `find_by_name(name)`, `find_by_version(name, version)`, `find_by_capability(capability)`, `find_enabled()`, `find_disabled()`, `search(query)`, `list_all()`, `count()`

**Provider selection:** `find_providers(capability)` — enabled adapters providing a capability. `select_provider(capability)` — best provider per selection algorithm.

**Validation:** `validate()` — full pass checking all capability/credential refs and adapter class types.

**Factory:** `create_adapter(identity)` — convenience method (get + create).

## Provider Selection Algorithm

```
select_provider(capability_name)
    → find_providers(capability_name)
        → with CapabilityRegistry:
            query capability_registry.find_providers(name)
            cross-reference against registered adapters
        → without CapabilityRegistry:
            search registrations by capability_names
    → _select_best(candidates)
        1. Priority descending (higher = better)
        2. Version descending (newer = better, numeric-aware)
        3. Registration order ascending (first registered wins ties)
```

**Deterministic:** same inputs always produce same output. No randomness, no timestamps, no external state.

## Integration Points

| System | Integration | Optional? |
|---|---|---|
| Adapter SDK | AdapterRegistration.adapter_class → ExecutionAdapter subclass | No |
| Capability System | Validates capability_names exist in CapabilityRegistry | Yes (constructor) |
| Credential Framework | Validates credential_descriptor_names exist in CredentialRegistry | Yes (constructor) |

Without CapabilityRegistry and CredentialRegistry, the AdapterRegistry works independently — just registration, query, factory, and standalone provider selection by capability_names string matching.

## Registration Lifecycle

```
Define adapter class (extends ExecutionAdapter)
    → Create AdapterRegistration with metadata, capabilities, credential refs
    → registry.register(registration) [validates all refs]
    → runtime queries registry.select_provider("send_email")
    → registry returns best AdapterRegistration
    → factory.create(identity) → fresh ExecutionAdapter instance
    → runtime injects context, calls adapter.execute(context)
```

## Exceptions

| Exception | When |
|---|---|
| `AdapterNotFoundError` | Identity not registered |
| `AdapterDisabledError` | Registration exists but disabled |
| `AdapterRegistrationError` | Duplicate identity or invalid data |

## Design Principles

1. **Registry stores registrations only.** No instances, no runtime state, no execution.
2. **Factory never caches.** Fresh instance every time. Adapters remain stateless.
3. **Provider selection is deterministic.** Priority → version → registration order.
4. **Identity is a value object.** Replaces stringly-typed APIs. Comparable, version-aware.
5. **Registrations are immutable.** No code may mutate a registration after construction.
6. **Integration is opt-in.** Capability/Credential registries are optional constructor args.
7. **No runtime or planner imports.** The registry layer imports zero modules from `services.execution` or `services.planner`.

## Test Coverage

110 tests in `tests/test_adapter_registry_integration.py`.
