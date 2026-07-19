# Credential Framework v1 — Architecture Freeze

## Credential Framework Version

**v1.0**

## Freeze Date

2026-07-18

## Freeze Status

**FROZEN**

No further changes to the credential framework are permitted without an RFC.

---

## Core Architectural Principles

1. **Adapters never fetch credentials.** Credentials arrive in `AdapterContext.credentials` pre-populated by the runtime. No adapter ever calls a resolver, a secret store, or an OAuth endpoint.

2. **References carry no secrets.** `CredentialReference` is a lightweight identifier (credential_id + descriptor_name). Safe to serialize, log, and pass across boundaries.

3. **Registry stores metadata only.** `CredentialRegistry` holds `CredentialDescriptor` objects — field names, types, and flags. No secrets, no instances, no storage connections.

4. **Descriptors are immutable.** Every descriptor is a frozen dataclass. No code may mutate a descriptor after construction.

5. **Instances are immutable but maskable.** `CredentialInstance` is frozen. `mask_sensitive()` returns a *new* instance with masked values; the original is preserved.

6. **Secrets never leak in text output.** `repr()`, `str()`, and `to_safe_dict()` never expose raw secret values. Masking is automatic for `sensitive=True` fields.

7. **Resolver is a pure abstraction.** `CredentialResolver` defines three async methods (`resolve`, `validate`, `exists`). It contains no storage logic, no caching, no OAuth.

8. **Multiple auth types are supported by convention.** `CredentialType` provides well-known constants, but any string is valid.

---

## Extension Points (non-breaking)

- Adding new constants to `CredentialType`
- Adding new optional fields to `CredentialDescriptor` (with defaults)
- Adding new methods to `CredentialRegistry`
- Adding new optional fields to `CredentialInstance`
- Implementing concrete `CredentialResolver` subclasses
- Adding new test cases

---

## RFC-Required Changes

- Adding secrets or storage to `CredentialRegistry`
- Making any frozen model mutable
- Changing the masking strategy defaults
- Removing required methods from `CredentialResolver`
- Adding runtime imports to any credential module
- Removing or renaming public exports

---

## Known Limitations (v1.0)

| Limitation | Accepted Because |
|---|---|
| No concrete resolver implementations | Storage backends are a future concern |
| No credential rotation API | `rotate()` can be added to resolver when needed |
| No batch resolution | `resolve_many()` can be added when tasks need multiple credentials |
| No OAuth flow support | OAuth is a concrete concern, not platform infrastructure |
| No encrypted values | Encryption belongs in the storage layer, not the model |

---

## Dependency Rules

```
Execution Runtime
    │ depends on
    ▼
Credential Resolver (abstract)
    │ depends on
    ▼
Credential Registry
    │ depends on
    ▼
Credential Descriptor / Reference / Instance
    │ depends on (stdlib only)
    ▼
Adapter SDK exceptions

```

- Credential modules must never import `services.execution`
- Credential modules must never import `services.planner`
- Credential modules must never import any concrete adapter
- The runtime may import `CredentialResolver` and `CredentialRegistry`

---

## Freeze Rationale

The credential framework describes everything adapters need for authentication without implementing any actual secret storage. The descriptor model covers all common auth types (API keys, OAuth2, basic auth, bearer tokens, JWT). The reference abstraction keeps secrets out of the planner and capability system. The resolver interface supports any storage backend. Secret masking prevents accidental leakage in logs and serialization.

No real adapter or storage backend has yet proven any of these abstractions insufficient. Until one does, the framework is frozen.
