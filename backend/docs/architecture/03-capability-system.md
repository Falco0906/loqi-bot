# Layer 3: Capability System

## Purpose

Bridges the planner (which thinks in verbs) and the adapter registry (which manages implementations). The planner asks "who can send email?"; the capability system answers with descriptors and provider mappings — never adapter instances.

## Freeze Reference

[CAPABILITY_SYSTEM_FREEZE.md](../CAPABILITY_SYSTEM_FREEZE.md)

## Package

`services.adapters` (`capabilities.py`, `capability_registry.py`)

## Components

### CapabilityDescriptor (`capabilities.py`)

```python
@dataclass(frozen=True)
class CapabilityDescriptor:
    name: str                   # e.g. "send_email" — ^[a-z][a-z0-9_.-]*$
    display_name: str
    description: str
    category: str               # free-form; use CapabilityCategory constants
    version: str                # ^[a-zA-Z0-9._-]+$
    parameters: tuple[ParameterSpec, ...]
    returns: ReturnSpec
    requires_auth: bool
    supports_streaming: bool
    supports_batch: bool
    tags: tuple[str, ...]
```

### ParameterSpec

```python
@dataclass(frozen=True)
class ParameterSpec:
    name: str
    type: str                   # "string", "integer", "boolean", "array", "object", "number"
    description: str
    required: bool              # default True
    default: Any                # default None
```

### ReturnSpec

```python
@dataclass(frozen=True)
class ReturnSpec:
    type: str                   # "object", "string", "array", "integer", "boolean", "number"
    description: str
    fields: tuple[ParameterSpec, ...]
```

### CapabilityProvider

```python
@dataclass(frozen=True)
class CapabilityProvider:
    adapter_name: str
    adapter_version: str
    capability_names: tuple[str, ...]
    priority: int               # default 0
```

Bridges capability names to adapter identities. No adapter instances.

### CapabilityCategory

Well-known constants (free-form strings, not an enum):
- `COMMUNICATION` = "communication"
- `PRODUCTIVITY` = "productivity"
- `SEARCH` = "search"
- `FILES` = "files"
- `CRM` = "crm"
- `WEB` = "web"
- `AI` = "ai"
- `SYSTEM` = "system"

Any string is valid. Categories are extensible by convention.

### CapabilityRegistry (`capability_registry.py`)

Methods:
- `register(descriptor)` — raises on duplicate `(name, version)`
- `unregister(name, version)`
- `get(name, version)` / `exists(name, version)`
- `find_by_name(name)` — all versions (case-insensitive)
- `find_by_category(category)` — case-insensitive
- `find_by_tag(*tags)` — AND semantics
- `search(query)` — partial across name, display_name, description, tags
- `list_all()` / `count()` / `clear()`
- `register_provider(provider)` — raises on duplicate
- `unregister_provider(name, version)`
- `find_providers(capability_name)` — find adapters providing a capability
- `get_provider(adapter_name, adapter_version)`
- `list_providers()` / `provider_count()`

### Exception

`CapabilityRegistrationError` — raised on duplicate registration or invalid references.

## Design Principles

1. **Planner thinks in verbs, never implementations.** No adapter names in planner queries.
2. **Registry owns metadata only.** No adapter instantiation, runtime state, or external calls.
3. **Descriptors are frozen.** No mutation after construction.
4. **Providers bridge, not bind.** Maps capability names to adapter identities — no instances, no configuration.
5. **Categories are extensible by convention.** Any string is valid.
6. **Versions are first-class.** `(name, version)` is the unique identity. Multiple versions coexist.
7. **Search is deterministic.** Results in registration order. No scoring.
8. **Duplicate registration is impossible.** Both descriptors and providers are unique-keyed.

## Relationship to Planner

```
Planner: "I need send_email"
    → registry.find_by_name("send_email")
    → CapabilityDescriptor (parameters, returns, auth requirements)
    → planner picks parameter values, schedules task

Runtime: "resolve send_email for execution"
    → registry.find_providers("send_email")
    → [CapabilityProvider(gmail, 2.0.0, priority=10), ...]
    → AdapterRegistry.select_provider("send_email")
    → gmail v2.0.0
```

The capability system never imports planner modules. The planner depends on the capability system.

## Test Coverage

181 tests in `tests/test_capability_system.py`.
