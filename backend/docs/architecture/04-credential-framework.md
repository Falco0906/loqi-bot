# Layer 4: Credential Framework

## Purpose

Describes what credentials adapters need and provides abstractions for resolving them at runtime. The framework stores metadata only — no secrets, no storage, no OAuth flows. Concrete resolvers are implemented in future phases.

## Freeze Reference

[CREDENTIAL_FRAMEWORK_FREEZE.md](../CREDENTIAL_FRAMEWORK_FREEZE.md)

## Package

`services.adapters` (`credentials.py`, `credential_registry.py`, `credential_resolver.py`)

## Components

### CredentialDescriptor (`credentials.py`)

```python
@dataclass(frozen=True)
class CredentialDescriptor:
    name: str                    # e.g. "gmail_oauth" — ^[a-z][a-z0-9_.-]*$
    display_name: str
    description: str
    auth_type: str               # CredentialType constant or any string
    required_fields: tuple[CredentialField, ...]
    optional_fields: tuple[CredentialField, ...]
    supports_refresh: bool
    supports_expiry: bool
    version: str
    tags: tuple[str, ...]

@dataclass(frozen=True)
class CredentialField:
    name: str
    type: str                    # "string", "password", "token", etc.
    description: str
    required: bool
    sensitive: bool              # masked in repr/str/to_safe_dict
```

### CredentialType

Well-known constants (free-form strings, not an enum):
- `API_KEY` = "api_key"
- `OAUTH2` = "oauth2"
- `BASIC_AUTH` = "basic_auth"
- `BEARER_TOKEN` = "bearer_token"
- `JWT` = "jwt"
- `CUSTOM` = "custom"

Any string is accepted.

### CredentialReference

```python
@dataclass(frozen=True)
class CredentialReference:
    credential_id: str          # logical name, e.g. "gmail_primary"
    descriptor_name: str        # points to a CredentialDescriptor
    metadata: dict              # additional context (user_id, scope, etc.)
```

Lightweight identifier with no secrets. Safe to log, serialize, pass across boundaries.

### CredentialInstance

```python
@dataclass(frozen=True)
class CredentialInstance:
    credential_id: str
    descriptor_name: str
    values: dict[str, str]      # actual secret values (in memory only)
    expires_at: datetime | None
    created_at: datetime | None
    metadata: dict
```

Security features:
- `mask_sensitive(descriptor)` — returns new instance with sensitive fields masked. Original unchanged (frozen).
- `to_safe_dict(descriptor)` — dict with masked values, safe for logging
- `repr()` and `str()` never expose raw secret values

Masking: shows first 4 characters by default, replaces rest with `*`. Values ≤4 chars show `********`.

### CredentialRegistry (`credential_registry.py`)

Stores descriptors only — no secrets, no instances, no connections.

Methods: `register`, `unregister`, `get`, `exists`, `find_by_auth_type`, `find_by_tag`, `list_all`, `count`, `clear`.

### CredentialResolver (`credential_resolver.py`)

```python
class CredentialResolver(ABC):
    async def resolve(reference: CredentialReference) -> CredentialInstance: ...
    async def validate(reference: CredentialReference) -> bool: ...
    async def exists(reference: CredentialReference) -> bool: ...
```

Pure abstraction. No storage logic, no caching, no OAuth. Concrete implementations (future): SupabaseCredentialResolver, VaultCredentialResolver, EnvironmentCredentialResolver.

### Exception

`CredentialNotFoundError` — raised when a credential descriptor or reference cannot be resolved.

## Security Principles

1. **Adapters never fetch credentials.** Credentials arrive pre-populated in `AdapterContext.credentials`.
2. **References carry no secrets.** `CredentialReference` is safe to log, serialize, and pass across boundaries.
3. **Registry knows nothing.** Stores descriptors only — field names, types, metadata. No secrets ever enter the registry.
4. **Instances mask on demand.** `mask_sensitive()` returns new instance with masked values. Original is preserved.
5. **Text output strips secrets.** `repr()` and `str()` never expose raw values.

## Design Principles

1. **Secrets never leak in text output.** Masking is automatic for `sensitive=True` fields.
2. **Resolver is a pure abstraction.** No storage, caching, or OAuth logic.
3. **Multiple auth types supported by convention.** Any string is valid.
4. **Descriptors are frozen.** No mutation after construction.
5. **Instances are frozen but maskable.** `mask_sensitive()` returns a new instance.

## Flow

```
Runtime knows reference: CredentialReference(credential_id="gmail_primary", descriptor_name="gmail_oauth")
    → resolver.resolve(reference)
    → CredentialInstance(values={client_id, client_secret, access_token, ...})
    → runtime populates AdapterContext.credentials
    → adapter.execute(context) reads context.credentials
```

The adapter never calls the resolver. Credentials are injected.

## Test Coverage

149 tests in `tests/test_credential_framework.py`.
