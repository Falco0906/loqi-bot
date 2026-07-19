# Adapter Registry Integration — Phase 5.1

## 1. Architecture

```
Planner
    │   "I need send_email"
    ▼
Capability Registry
    │   find_providers("send_email") → [CapabilityProvider(gmail, 2.0.0)]
    ▼
Adapter Registry
    │   select_provider("send_email") → AdapterRegistration
    │   factory.create(identity) → ExecutionAdapter
    ▼
Adapter Factory
    │   creates fresh instance, never caches
    ▼
ExecutionAdapter (concrete)
    │   gmail adapter, slack adapter, etc.
    ▼
AdapterContext (injected by runtime)
    │   credentials, params, logger, etc.
    ▼
Adapter execution
```

### Component Mapping

| Component | Responsibilities | File |
|---|---|---|
| `AdapterIdentity` | Value object (name + version), comparable | `adapter_registration.py` |
| `AdapterRegistration` | Immutable registration metadata | `adapter_registration.py` |
| `AdapterFactory` | Lazy instantiation, no caching | `adapter_factory.py` |
| `AdapterRegistry` | Unified registry, provider selection, search, validation | `adapter_registry.py` |

## 2. Registration Lifecycle

```
                    ┌──────────────────┐
                    │   Define         │  Developer creates adapter class
                    │  (adapter code)  │  inheriting ExecutionAdapter
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │   Register       │  registry.register(AdapterRegistration)
                    │  (metadata)      │  Validates: duplicate identity, capability
                    │                  │  refs, credential refs (if registries given)
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │   Query          │  Planner/runtime queries by name,
                    │  (discovery)     │  capability, tag, version, enabled
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │   Select         │  registry.select_provider(capability)
                    │  (resolution)    │  Deterministic: priority, version, order
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │   Create         │  factory.create(identity)
                    │  (instantiation) │  Returns fresh ExecutionAdapter
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │   Execute        │  Runtime injects context,
                    │  (runtime)       │  calls adapter.execute(context)
                    └──────────────────┘
```

## 3. AdapterIdentity Value Object

```python
@dataclass(frozen=True)
class AdapterIdentity:
    name: str      # lowercase, ^[a-z][a-z0-9_.-]*$
    version: str   # any non-empty string
```

- Immutable (frozen dataclass)
- Used as dictionary key in registry
- Comparable (`__lt__`) for deterministic ordering
- Version-aware comparison (numeric parts compared as integers)

## 4. AdapterRegistration Model

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

### Validation (enforced in `__post_init__`)

| Field | Rule |
|---|---|
| `identity` | Must be `AdapterIdentity` |
| `adapter_class` | Must be a class (not instance) |
| `priority` | Must be `int` |
| `capability_names` | All must be non-empty strings |
| `credential_descriptor_names` | All must be non-empty strings |

## 5. AdapterFactory

```python
class AdapterFactory:
    def create(identity: AdapterIdentity) -> ExecutionAdapter
    def create_latest(name: str) -> ExecutionAdapter
    def create_for_capability(capability_name: str, providers: list[...]) -> ExecutionAdapter
```

### Rules
- **Never caches instances** — every call returns a fresh object
- **Never executes adapters** — construction only
- **Never resolves credentials** — credentials arrive via context
- Raises `AdapterNotFoundError` if not registered
- Raises `AdapterDisabledError` if registration is disabled

## 6. Provider Selection Algorithm

```
select_provider(capability_name)
    │
    ├── find_providers(capability_name)
    │       │
    │       ├── with CapabilityRegistry:
    │       │   queries capability_registry.find_providers(name)
    │       │   cross-references against registered adapters
    │       │
    │       └── without CapabilityRegistry:
    │           searches registrations by capability_names
    │
    └── _select_best(candidates)
            │
            ├── 1. Priority descending (higher = better)
            ├── 2. Version descending (newer = better, numeric-aware)
            └── 3. Registration order ascending (first registered wins ties)
```

### Determinism Guarantee

The same inputs always produce the same output:
- Priority is compared numerically (descending)
- Version uses numeric-aware comparison (e.g., "10.0.0" > "2.0.0")
- Registration order breaks remaining ties
- No randomness, no timestamps, no external state

## 7. Registry Queries

| Method | Description |
|---|---|
| `register(registration)` | Register adapter. Raises on duplicate identity or invalid refs. |
| `unregister(identity)` | Remove registration. Raises if not found. |
| `get(identity)` | Get registration by identity. Returns None if not found. |
| `exists(identity)` | Check registration existence. |
| `find_by_name(name)` | All versions of adapter by case-insensitive name. |
| `find_by_version(name, version)` | Single registration by exact name+version. |
| `find_by_capability(capability)` | All adapters advertising a capability. |
| `find_enabled()` / `find_disabled()` | Filter by enabled status. |
| `search(query)` | Case-insensitive partial search across name, display_name, description, tags. |
| `list_all()` | All registrations. |
| `count()` | Number of registrations. |
| `find_providers(capability)` | Enabled adapters providing a capability. |
| `select_provider(capability)` | Best provider per selection algorithm. |
| `highest_priority_provider(capability)` | Provider(s) with max priority. |
| `validate()` | Full validation pass. |
| `create_adapter(identity)` | Convenience: get + create. |

## 8. Integration with Capability System

```
AdapterRegistry
    │
    ├── constructor: capability_registry: CapabilityRegistry (optional)
    │
    ├── register(): validates capability_names exist in capability registry
    │
    ├── find_providers(): delegates to capability_registry.find_providers(),
    │   cross-references adapter identities against registrations
    │
    └── validate(): checks all capability references are resolvable
```

## 9. Integration with Credential Framework

```
AdapterRegistry
    │
    ├── constructor: credential_registry: CredentialRegistry (optional)
    │
    ├── register(): validates credential_descriptor_names exist in credential registry
    │
    └── validate(): checks all credential references are resolvable
```

## 10. Integration with Adapter SDK

```
AdapterRegistry
    │
    ├── AdapterRegistration.adapter_class → subclass of ExecutionAdapter
    │
    ├── AdapterRegistration.metadata → AdapterMetadata
    │
    └── factory.create() → returns ExecutionAdapter instance
```

## 11. Extension Points

| Area | Future | Trigger |
|---|---|---|
| **Alias support** | `AdapterIdentity` gains `aliases` field | When adapters need multiple names |
| **Deprecation** | `AdapterRegistration.deprecated` or `sunset` field | When adapters are phased out |
| **Version constraints** | `find_providers(cap, ">=2.0.0")` | When runtime needs version ranges |
| **Health probes** | `registry.probe(identity) -> bool` | When proactive health checking is needed |
| **Weighted selection** | Priority + optional weight factor | When more nuanced routing is needed |
| **Hot reload** | `registry.reload()` | When adapters are loaded dynamically |

## 12. Package Structure

```
backend/services/adapters/
    __init__.py                       # Updated exports
    base_adapter.py                   # Phase 4.1
    models.py                         # Phase 4.1
    adapter_context.py                # Phase 4.1
    protocols.py                      # Phase 4.1
    exceptions.py                     # Phase 4.1–5.1
    capabilities.py                   # Phase 4.2
    capability_registry.py            # Phase 4.2
    credentials.py                    # Phase 4.3
    credential_registry.py            # Phase 4.3
    credential_resolver.py            # Phase 4.3
    adapter_registration.py           # NEW  — AdapterIdentity, AdapterRegistration
    adapter_factory.py                # NEW  — AdapterFactory
    adapter_registry.py               # NEW  — AdapterRegistry
```

## 13. Test Coverage

Test file: `backend/tests/test_adapter_registry_integration.py`

| Test Class | Domain | Tests |
|---|---|---|
| `TestAdapterIdentityConstruction` | Identity creation, equality, ordering, pickle | 10 |
| `TestAdapterIdentityValidation` | Invalid names, versions | 6 |
| `TestAdapterIdentityImmutability` | Frozen enforcement | 2 |
| `TestAdapterRegistrationConstruction` | Registration creation, to_dict | 7 |
| `TestAdapterRegistrationValidation` | Invalid types, empty names | 5 |
| `TestAdapterRegistrationImmutability` | Frozen enforcement | 2 |
| `TestAdapterFactory` | Create, create_latest, error cases, freshness | 11 |
| `TestAdapterRegistryRegister` | Register, get, exists, duplicate | 7 |
| `TestAdapterRegistryUnregister` | Unregister, error cases | 3 |
| `TestAdapterRegistryWithCapabilityRegistry` | Integration with capability registry | 5 |
| `TestAdapterRegistryWithCredentialRegistry` | Integration with credential registry | 2 |
| `TestAdapterRegistryLookup` | find_by_*, search, enabled/disabled | 18 |
| `TestAdapterRegistryProviderSelection` | Provider resolution algorithm | 11 |
| `TestAdapterRegistryFactory` | Factory integration | 4 |
| `TestAdapterRegistryValidation` | validate() checks | 4 |
| `TestAdapterRegistryEdgeCases` | Clear, empty, large, search | 5 |
| `TestAdapterRegistryIntegration` | Full workflow | 2 |
| `TestAdapterRegistrySelfContainment` | No runtime/planner deps | 6 |
| **Total** | | **110** |
