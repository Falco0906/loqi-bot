# Credential Framework — Phase 4.3

## 1. Architecture

```
Execution Runtime
    │
    ▼
Credential Resolver (abstract)  ◄── resolves references into instances
    │
    ├── resolve(CredentialReference) → CredentialInstance
    ├── validate(CredentialReference) → bool
    └── exists(CredentialReference) → bool
    │
    ▼
Credential Registry              ◄── manages descriptors only
    │
    ├── register(descriptor)
    ├── get(name) → descriptor
    ├── find_by_auth_type(type) → [...]
    └── find_by_tag(*tags) → [...]
    │
    ▼
CredentialDescriptor             ◄── immutable, describes a credential type
    │  (name, display_name, description, auth_type,
    │   required_fields, optional_fields, ...)
    │
    ▼
CredentialReference              ◄── lightweight identifier (no secrets)
    │  (credential_id, descriptor_name)
    │
    ▼
CredentialInstance               ◄── runtime credential values
       (credential_id, descriptor_name, values,
        expires_at, ...)
```

### Key Architectural Rules

| Layer | Stores | Never Stores |
|---|---|---|
| **CredentialDescriptor** | Field names, types, metadata | Actual secret values |
| **CredentialReference** | Credential ID, descriptor name | Secret values |
| **CredentialInstance** | Secret values (in memory) | Persisted state |
| **CredentialRegistry** | Descriptors only | Secrets, instances |
| **CredentialResolver** | (abstract — storage unknown) | (depends on impl) |

### The CredentialReference Abstraction

```
Planner / Capability System
    │   "adapter X needs credential Y"
    ▼
CredentialReference(credential_id="gmail_primary", descriptor_name="gmail_oauth")
    │   lightweight, no secrets, serializable
    ▼
CredentialResolver.resolve(reference)
    │   fetches from storage (Supabase, Vault, env, etc.)
    ▼
CredentialInstance(values={...})   ← actual secrets, in memory only
    │
    ▼
AdapterContext.credentials
    │   adapter receives populated credentials
    ▼
ExecutionAdapter.execute(context)
```

## 2. Resolver Lifecycle

```
                    ┌────────────────────┐
                    │   Resolver Setup   │  Concrete resolver instantiated
                    │  (future phase)    │  with storage backend config
                    └────────┬───────────┘
                             │
                    ┌────────▼───────────┐
                    │   Reference        │  Runtime creates CredentialReference
                    │  (lightweight)     │  from task/capability requirements
                    └────────┬───────────┘
                             │
                    ┌────────▼───────────┐
                    │   Resolve          │  resolver.resolve(reference)
                    │  (fetch secrets)   │  Returns CredentialInstance
                    └────────┬───────────┘
                             │
                    ┌────────▼───────────┐
                    │   Inject           │  Values placed in AdapterContext
                    │  (context.fill)    │  Adapter never calls resolver
                    └────────┬───────────┘
                             │
                    ┌────────▼───────────┐
                    │   Execute          │  adapter.execute(context)
                    │  (adapter uses)    │  Reads from context.credentials
                    └────────────────────┘
```

## 3. Descriptor Model

```python
@dataclass(frozen=True)
class CredentialDescriptor:
    name: str                        # e.g. "gmail_oauth"
    display_name: str                # e.g. "Gmail OAuth2"
    description: str                 # Human-readable purpose
    auth_type: str                   # One of CredentialType constants
    required_fields: tuple[CredentialField, ...]  # Mandatory fields
    optional_fields: tuple[CredentialField, ...]  # Optional fields
    supports_refresh: bool           # Can the token be refreshed?
    supports_expiry: bool            # Does the credential expire?
    version: str                     # Descriptor version
    tags: tuple[str, ...]           # Discovery tags
```

```python
@dataclass(frozen=True)
class CredentialField:
    name: str                        # Field identifier
    type: str                        # "string", "password", "token", etc.
    description: str                 # Human-readable field purpose
    required: bool                   # Is this field mandatory?
    sensitive: bool                  # Should this field be masked in output?
```

### Validation Rules

| Field | Rule |
|---|---|
| `name` | Non-empty, `^[a-z][a-z0-9_.-]*$` |
| `display_name` | Non-empty |
| `description` | Non-empty |
| `auth_type` | Non-empty |
| `required_fields` / `optional_fields` | No duplicate field names across both lists |

### Example: Gmail OAuth2 Descriptor

```python
CredentialDescriptor(
    name="gmail_oauth",
    display_name="Gmail OAuth2",
    description="OAuth2 credentials for Gmail API access",
    auth_type=CredentialType.OAUTH2,
    required_fields=(
        CredentialField(name="client_id", type="string", sensitive=False,
                        description="OAuth client ID"),
        CredentialField(name="client_secret", type="password",
                        description="OAuth client secret"),
        CredentialField(name="access_token", type="token",
                        description="OAuth access token"),
        CredentialField(name="refresh_token", type="token",
                        description="OAuth refresh token"),
    ),
    optional_fields=(
        CredentialField(name="scope", type="string", required=False,
                        sensitive=False, description="OAuth scopes"),
    ),
    supports_refresh=True,
    supports_expiry=True,
    tags=("google", "email", "oauth2"),
)
```

### Example: API Key Descriptor

```python
CredentialDescriptor(
    name="openai_api_key",
    display_name="OpenAI API Key",
    description="API key for OpenAI",
    auth_type=CredentialType.API_KEY,
    required_fields=(
        CredentialField(name="api_key", type="password",
                        description="OpenAI API key"),
    ),
)
```

## 4. Credential Type Constants

```python
class CredentialType:
    API_KEY      = "api_key"       # Static API key
    OAUTH2       = "oauth2"        # OAuth2 tokens (access + refresh)
    BASIC_AUTH   = "basic_auth"    # Username + password
    BEARER_TOKEN = "bearer_token"  # Static bearer token
    JWT          = "jwt"           # JSON Web Token
    CUSTOM       = "custom"        # Custom auth mechanism
```

Any string is accepted — these are conventions, not a closed set.

## 5. Reference Model

```python
@dataclass(frozen=True)
class CredentialReference:
    credential_id: str              # Logical name, e.g. "gmail_primary"
    descriptor_name: str            # Points to a CredentialDescriptor
    metadata: dict                  # Additional context (user_id, scope, etc.)
```

References are the currency of the credential system. They are:
- **Lightweight** — no secrets, just identifiers
- **Serializable** — can be passed across process boundaries
- **Safe to log** — no masked values needed
- **Planner-friendly** — the planner works with references, not secrets

## 6. Instance Model

```python
@dataclass(frozen=True)
class CredentialInstance:
    credential_id: str
    descriptor_name: str
    values: dict[str, str]          # The actual secret values
    expires_at: datetime | None     # Expiration time
    created_at: datetime | None     # Creation time
    metadata: dict                  # Additional runtime metadata
```

### Security Features

```
CredentialInstance
    │
    ├── values → raw secrets (in memory, never persisted)
    │
    ├── mask_sensitive(descriptor) → new instance with masked values
    │   Uses descriptor.sensitive_field_names to determine which fields to mask.
    │   Original instance is unchanged (frozen).
    │
    ├── to_safe_dict(descriptor) → dict with masked values
    │   Safe for logging, serialization, and debugging.
    │
    ├── __repr__ → "CredentialInstance(id=..., descriptor=..., values={...})"
    │   Never exposes secret values in representation.
    │
    └── __str__ → "CredentialInstance(id, descriptor, N fields)"
        Human-readable summary, no secrets.
```

### Masking Strategy

| Condition | Behavior |
|---|---|
| Value is empty | Return empty string |
| `len(value) <= show_first` | Return `********` (8+ chars) |
| `len(value) > show_first` | Show first N chars, mask rest |

Default `show_first = 4`. Customize via parameter.

```
"sk_live_abcdef123456" → "sk_l***************"
"abc"                 → "********"
"abcdefgh"            → "abcd****"
```

## 7. Registry Responsibilities

| Method | Description |
|---|---|
| `register(descriptor)` | Register a credential descriptor. Raises on duplicate name. |
| `unregister(name)` | Remove a descriptor. Raises if not found. |
| `get(name)` | Get a descriptor by name. Returns None if not found. |
| `exists(name)` | Check if a descriptor is registered. |
| `find_by_auth_type(type)` | Find all descriptors with a given auth type (case-insensitive). |
| `find_by_tag(*tags)` | Find descriptors with ALL specified tags (AND semantics). |
| `list_all()` | Return all registered descriptors. |
| `count()` | Number of registered descriptors. |
| `clear()` | Remove all descriptors. |

The registry stores **metadata only**. No secrets, no instances, no connections.

## 8. Resolver Interface

```python
class CredentialResolver(ABC):
    async def resolve(reference: CredentialReference) -> CredentialInstance:
        """Resolve a reference into a populated credential instance."""

    async def validate(reference: CredentialReference) -> bool:
        """Check whether a reference is resolvable (lightweight)."""

    async def exists(reference: CredentialReference) -> bool:
        """Check whether a reference exists in storage."""
```

Concrete implementations (future phases):
- `SupabaseCredentialResolver`
- `VaultCredentialResolver`
- `EnvironmentCredentialResolver`
- `FileCredentialResolver`

The runtime depends on the abstract resolver interface. No adapter ever calls the resolver directly — credentials arrive via `AdapterContext`.

## 9. Security Principles

1. **Adapters never fetch credentials.** Credentials arrive pre-populated in `AdapterContext.credentials`. The adapter's only responsibility is *using* them.

2. **References are secret-free.** `CredentialReference` contains identifiers only — never values. Safe to log, serialize, and pass across service boundaries.

3. **Instances mask on demand.** `CredentialInstance` holds raw values in memory but provides `mask_sensitive()` and `to_safe_dict()` for safe output. The original instance is never mutated (frozen).

4. **repr() and str() strip secrets.** Both representations omit raw values. `repr()` shows `values={...}``. `str() shows a count.

5. **Registry knows nothing.** The credential registry stores descriptors only — field names, types, metadata. No secrets ever enter the registry.

## 10. Extension Points

| Area | Future | Trigger |
|---|---|---|
| **Concrete resolvers** | `SupabaseCredentialResolver`, `VaultResolver`, etc. | When storage backends are implemented |
| **Credential rotation** | `resolver.rotate(reference) → CredentialInstance` | When automated rotation is needed |
| **Encrypted values** | Add encryption layer to `CredentialInstance.values` | When in-memory encryption matters |
| **Credential health** | `resolver.health(reference) → dict` | When monitoring credential expiry |
| **Batch resolution** | `resolver.resolve_many(references) → dict` | When multiple credentials per task |
| **OAuth flows** | `OAuth2Resolver(redirect_uri, ...)` | When interactive auth is needed |
| **Audit logging** | `masked.to_safe_dict()` → structured audit log | When compliance is required |

## 11. Package Structure

```
backend/services/adapters/
    __init__.py                    # Updated exports
    base_adapter.py                # Phase 4.1
    models.py                      # Phase 4.1
    adapter_context.py             # Phase 4.1
    protocols.py                   # Phase 4.1
    exceptions.py                  # Phase 4.1 + 4.2 + 4.3 + CredentialNotFoundError
    capabilities.py                # Phase 4.2
    capability_registry.py         # Phase 4.2
    credentials.py                 # NEW — CredentialDescriptor, CredentialField,
                                   #         CredentialReference, CredentialInstance,
                                   #         CredentialType, mask_value, mask_sensitive_values
    credential_registry.py         # NEW — CredentialRegistry
    credential_resolver.py         # NEW — CredentialResolver (abstract)
```

## 12. Test Coverage

Test file: `backend/tests/test_credential_framework.py`

| Test Class | Domain | Tests |
|---|---|---|
| `TestCredentialType` | Auth type constants | 8 |
| `TestMaskValue` | Value masking function | 7 |
| `TestMaskSensitiveValues` | Dict masking | 6 |
| `TestCredentialFieldConstruction` | Field creation | 5 |
| `TestCredentialFieldValidation` | Invalid field names/types | 10 |
| `TestCredentialFieldImmutability` | Frozen enforcement | 2 |
| `TestCredentialFieldSerialization` | to_dict, from_dict, pickle, equals, hash | 7 |
| `TestCredentialDescriptorConstruction` | Descriptor creation, fields, flags | 10 |
| `TestCredentialDescriptorValidation` | Name/field validation, errors | 9 |
| `TestCredentialDescriptorImmutability` | Frozen enforcement | 2 |
| `TestCredentialDescriptorSerialization` | to_dict, from_dict, pickle, equals, hash | 8 |
| `TestCredentialReferenceConstruction` | Reference creation | 2 |
| `TestCredentialReferenceValidation` | Empty/missing fields | 3 |
| `TestCredentialReferenceImmutability` | Frozen enforcement | 1 |
| `TestCredentialReferenceSerialization` | to_dict, from_dict, pickle | 4 |
| `TestCredentialInstanceConstruction` | Instance creation, dates, metadata | 3 |
| `TestCredentialInstanceValidation` | Empty/missing fields | 3 |
| `TestCredentialInstanceImmutability` | Frozen enforcement | 2 |
| `TestCredentialInstanceExpiry` | Expiry logic | 3 |
| `TestCredentialInstanceMasking` | mask_sensitive, to_safe_dict, repr, str | 8 |
| `TestCredentialRegistryRegister` | Register, get, exists, duplicate | 6 |
| `TestCredentialRegistryUnregister` | Unregister, re-register | 3 |
| `TestCredentialRegistryLookup` | find_by_auth_type, find_by_tag, list_all, count, clear | 14 |
| `TestCredentialResolverAbstract` | Abstract interface, concrete impl, errors | 6 |
| `TestSecurityNoLeakage` | repr, str, logs, safe dict, masking | 14 |
| `TestCredentialFrameworkSelfContainment` | No runtime/planner/adapter deps | 6 |
| **Total** | | **149** |
