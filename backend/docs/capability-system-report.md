# Capability System — Phase 4.2

## 1. Architecture

```
Planner (asks "what can we do?")
    │
    ▼
Capability Registry  ◄────────────────────┐
    │                                      │
    ├── find_by_name("send_email")         │
    ├── find_by_category("communication")  │
    ├── find_by_tag("email", "google")     │
    └── search("upload")                   │
    │                                      │
    ▼                                      │
CapabilityDescriptor  ◄─── registers ────┘
    (metadata only)
    │
    ▼
CapabilityProvider  ◄─── maps capability to adapter identity
    │
    ▼
Adapter Registry (Phase 4.3+)
    │
    ▼
ExecutionAdapter (Phase 4.1 SDK)
    │
    ▼
External Service
```

### Key Architectural Rules

| Layer | Knows About | Does NOT Know About |
|---|---|---|
| **Planner** | Capability names, categories, tags | Adapter names, versions, implementations |
| **Capability Registry** | Descriptors + provider mappings | Adapter instances, runtime state |
| **Capability Provider** | Adapter identity (name, version) | Adapter internals, configuration |
| **Adapter Registry** (future) | Adapter instances | Planner queries |
| **ExecutionAdapter** | External API | Planner, capabilities |

## 2. Capability Lifecycle

```
                    ┌──────────────────┐
                    │   Definition     │  Developer writes CapabilityDescriptor
                    │  (code/registry) │  with name, params, returns, tags
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │   Registration   │  registry.register(descriptor)
                    │  (CapRegistry)   │  Validates name, version, fields
                    └────────┬─────────┘    Raises CapabilityRegistrationError on dup
                             │
                    ┌────────▼─────────┐
                    │   Discovery      │  Planner queries by name/category/tag/search
                    │  (queries)       │  Returns metadata only
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │   Provider Map   │  registry.register_provider(provider)
                    │  (adapter link)  │  Links capability → adapter identity
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │   Execution      │  Runtime resolves adapter via AdapterRegistry
                    │  (future phase)  │  Instantiates adapter, passes context
                    └──────────────────┘
```

## 3. Descriptor Model

```python
@dataclass(frozen=True)
class CapabilityDescriptor:
    name: str                    # e.g. "send_email" — lowercase, alphanumeric + _ . -
    display_name: str            # e.g. "Send Email"
    description: str             # Human-readable description
    category: str                # Free-form string, use CapabilityCategory constants
    version: str                 # Semver or any [a-zA-Z0-9._-]+ string
    parameters: tuple[ParameterSpec, ...]  # Input schema
    returns: ReturnSpec          # Output schema
    requires_auth: bool          # Does this capability need authentication?
    supports_streaming: bool     # Can it stream results?
    supports_batch: bool         # Does it support batch operations?
    tags: tuple[str, ...]        # Free-form tags for discovery
```

### ParameterSpec

```python
@dataclass(frozen=True)
class ParameterSpec:
    name: str                    # Parameter identifier
    type: str                    # "string", "integer", "boolean", "array", "object", "number"
    description: str             # Human-readable description
    required: bool               # Is this parameter required? (default True)
    default: Any                 # Default value if not provided (default None)
```

### ReturnSpec

```python
@dataclass(frozen=True)
class ReturnSpec:
    type: str                    # "object", "string", "array", "integer", "boolean", "number"
    description: str             # Description of the return value
    fields: tuple[ParameterSpec, ...]  # Sub-fields for structured returns
```

### Validation Rules (enforced in `__post_init__`)

| Field | Rule |
|---|---|
| `name` | Non-empty, matches `^[a-z][a-z0-9_.-]*$` |
| `display_name` | Non-empty string |
| `description` | Non-empty string |
| `category` | Non-empty string |
| `version` | Non-empty, matches `^[a-zA-Z0-9._-]+$` |
| `parameters` | No duplicate parameter names |

### Example

```python
CapabilityDescriptor(
    name="send_email",
    display_name="Send Email",
    description="Send an email message through the configured provider",
    category=CapabilityCategory.COMMUNICATION,
    version="1.0.0",
    parameters=(
        ParameterSpec(name="to", type="string", description="Recipient email"),
        ParameterSpec(name="subject", type="string", description="Subject line"),
        ParameterSpec(name="body", type="string", description="Message body", required=True),
        ParameterSpec(name="cc", type="string", description="CC recipient", required=False),
    ),
    returns=ReturnSpec(
        type="object",
        fields=(ParameterSpec(name="message_id", type="string", description="Server message ID"),),
    ),
    requires_auth=True,
    tags=("email", "google", "outgoing"),
)
```

## 4. Registry Responsibilities

### Descriptor Management

| Method | Description |
|---|---|
| `register(descriptor)` | Register a capability. Raises on duplicate name+version. |
| `unregister(name, version)` | Remove a capability. Raises if not found. |
| `get(name, version)` | Get a descriptor by exact name+version. Returns None if not found. |
| `exists(name, version)` | Check if a capability is registered. |
| `find_by_name(name)` | Find all versions of a capability by case-insensitive name match. |
| `find_by_category(category)` | Find all capabilities in a category (case-insensitive). |
| `find_by_tag(*tags)` | Find capabilities with ALL specified tags (AND semantics). Empty tags returns all. |
| `search(query)` | Case-insensitive partial search across name, display_name, description, and tags. |
| `list_all()` | Return all registered descriptors. |
| `count()` | Number of registered descriptors. |
| `clear()` | Remove all descriptors and providers. |

### Provider Management

| Method | Description |
|---|---|
| `register_provider(provider)` | Register a capability→adapter mapping. Raises on duplicate. |
| `unregister_provider(name, version)` | Remove a mapping. Raises if not found. |
| `find_providers(capability_name)` | Find all adapters providing a capability (case-insensitive). |
| `get_provider(adapter_name, adapter_version)` | Get a specific provider by identity. |
| `list_providers()` | List all registered providers. |
| `provider_count()` | Number of registered providers. |

## 5. Capability Categories

### Predefined Constants

```python
class CapabilityCategory:
    COMMUNICATION = "communication"   # email, SMS, voice, chat
    PRODUCTIVITY  = "productivity"    # calendar, tasks, notes
    SEARCH        = "search"          # web search, contact search, email search
    FILES         = "files"           # upload, download, delete, list files
    CRM           = "crm"             # contacts, deals, accounts
    WEB           = "web"             # HTTP requests, web scraping
    AI            = "ai"              # LLM completion, embedding, classification
    SYSTEM        = "system"          # health checks, configuration, diagnostics
```

### Extensibility

Categories are free-form strings, not an enum. Any string value is valid:

```python
CapabilityDescriptor(
    name="deploy_service",
    display_name="Deploy Service",
    description="Deploy a service to Kubernetes",
    category="devops",  # Custom category — no SDK changes needed
    version="1.0.0",
)
```

## 6. Provider Model

```python
@dataclass(frozen=True)
class CapabilityProvider:
    adapter_name: str               # e.g. "gmail", "slack", "http"
    adapter_version: str            # e.g. "1.0.0"
    capability_names: tuple[str, ...]  # e.g. ("send_email", "search_email")
    priority: int                   # Higher priority = preferred provider (default 0)
```

Providers form the bridge between capabilities and adapters:

```
Capability: send_email
    │
    ├── Provider: gmail (priority 10)
    ├── Provider: outlook (priority 5)
    └── Provider: smtp (priority 1)
```

The registry stores provider **metadata** only — no adapter instances are created until execution time.

## 7. Relationship to Planner

The planner thinks in verbs (capabilities), never implementations:

```
Planner: "I need to send an email"
    │
    ▼
Planner queries: registry.find_by_name("send_email")
    │
    ▼
Returns: CapabilityDescriptor(name="send_email", ...)
    │
    ▼
Planner inspects: parameters, returns, requires_auth
    │
    ▼
Planner selects: picks parameter values, schedules task
    │
    ▼
Runtime resolves: registry.find_providers("send_email")
    │
    ▼
Runtime picks: highest-priority adapter (e.g., gmail)
    │
    ▼
Runtime dispatches: adapter.execute(context)
```

### Planner Independence

- The capability system imports **zero** planner modules.
- The planner depends on the capability system, never the reverse.

## 8. Extension Points

| Area | Future | Trigger |
|---|---|---|
| **Capability groups** | Hierarchical capabilities (e.g., `communication.email.send`) | When capability trees emerge |
| **Planner integration** | `planner.resolve_capability(name)` | Phase 4.3+ |
| **Capability versioning** | `find_by_name(name)` returns multiple versions; runtime picks latest | When version conflicts arise |
| **Provider priority** | Weighted selection, fallback chains | When multiple adapters provide same capability |
| **Capability dependencies** | `requires` field (capability A depends on B) | When composite operations emerge |
| **Capability constraints** | Rate limits, quota, region constraints on descriptors | When deployment constraints matter |
| **Capability discovery** | Auto-registration from adapter metadata | When concrete adapters register |

## 9. Package Structure

```
backend/services/adapters/
    __init__.py                    # Updated exports
    base_adapter.py                # Phase 4.1
    models.py                      # Phase 4.1
    adapter_context.py             # Phase 4.1
    protocols.py                   # Phase 4.1 (CapabilityProvider → CapabilityReporter)
    exceptions.py                  # Phase 4.1 + CapabilityRegistrationError
    capabilities.py                # NEW — CapabilityDescriptor, ParameterSpec,
                                   #         ReturnSpec, CapabilityProvider, CapabilityCategory
    capability_registry.py         # NEW — CapabilityRegistry
```

## 10. Test Coverage

Test file: `backend/tests/test_capability_system.py`

| Test Class | Domain | Tests |
|---|---|---|
| `TestCapabilityCategory` | Category constants & extensibility | 9 |
| `TestParameterSpecConstruction` | ParameterSpec creation | 9 |
| `TestParameterSpecValidation` | Empty name/type, invalid types | 8 |
| `TestParameterSpecImmutability` | Frozen enforcement | 3 |
| `TestParameterSpecSerialization` | to_dict, from_dict, pickle, equality, hash | 12 |
| `TestReturnSpecConstruction` | ReturnSpec creation | 4 |
| `TestReturnSpecValidation` | Empty type | 1 |
| `TestReturnSpecImmutability` | Frozen enforcement | 1 |
| `TestReturnSpecSerialization` | to_dict, from_dict, pickle | 7 |
| `TestCapabilityDescriptorConstruction` | Descriptor creation, qualified_name, matches_query | 21 |
| `TestCapabilityDescriptorValidation` | Name/version/field validation, error combinations | 20 |
| `TestCapabilityDescriptorImmutability` | Frozen enforcement | 3 |
| `TestCapabilityDescriptorSerialization` | to_dict, from_dict, pickle, equality, hash | 14 |
| `TestCapabilityProviderConstruction` | Provider creation | 6 |
| `TestCapabilityProviderValidation` | Empty fields | 3 |
| `TestCapabilityProviderImmutability` | Frozen enforcement | 2 |
| `TestCapabilityRegistryRegister` | Register, get, exists, duplicate detection | 10 |
| `TestCapabilityRegistryUnregister` | Unregister, re-register, error cases | 6 |
| `TestCapabilityRegistryLookup` | find_by_name, find_by_category, find_by_tag | 14 |
| `TestCapabilityRegistrySearch` | Search by name, display, description, tag, partial, case | 14 |
| `TestCapabilityRegistryListAll` | list_all, count, clear, re-register | 8 |
| `TestCapabilityRegistryProviders` | Provider register, unregister, find, independence | 13 |
| `TestCapabilityRegistryIntegration` | Full lifecycle, multi-adapter queries | 3 |
| `TestCapabilityRegistryEdgeCases` | Version ordering, large count, search across fields | 5 |
| `TestCapabilitySystemSelfContainment` | No runtime/planner dependencies | 5 |
| **Total** | | **201** |
