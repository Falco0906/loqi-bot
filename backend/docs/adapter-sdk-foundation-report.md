# Adapter SDK Foundation — Phase 4.1

## 1. Architecture Overview

```
┌──────────────────────────────────────────────────────────┐
│                    Execution Runtime                      │
│  (scheduler, dispatcher, pipeline, recovery, metrics)     │
│                         │ depends on public abstractions  │
│                         ▼                                 │
├──────────────────────────────────────────────────────────┤
│                   Adapter SDK (this layer)                │
│  ┌──────────────┐  ┌──────────┐  ┌────────────────────┐  │
│  │ base_adapter │  │  models  │  │  adapter_context   │  │
│  │ ExecutionAdapter│ │Metadata │  │  AdapterContext    │  │
│  │ (abstract)    │  │ Result   │  │  (frozen)          │  │
│  └──────────────┘  │ UsageInfo│  └────────────────────┘  │
│                     └──────────┘                         │
│  ┌──────────────┐  ┌──────────┐  ┌────────────────────┐  │
│  │  protocols   │  │exceptions│  │     __init__        │  │
│  │ Validator    │  │hierarchy │  │   (public API)      │  │
│  │ HealthCheck  │  │10 classes│  │                     │  │
│  │ Capabilities │  └──────────┘  └────────────────────┘  │
│  └──────────────┘                                         │
├──────────────────────────────────────────────────────────┤
│                Concrete Adapters (Phase 4.2+)             │
│  Gmail │ Slack │ HTTP │ Calendar │ Drive │ Apollo │ ...  │
└──────────────────────────────────────────────────────────┘
```

## 2. Dependency Graph

```
Execution Runtime
    │
    ▼
Adapter SDK ────────────────────────────────────────┐
    │                                                 │
    ├── base_adapter.py        ─── models.py         │
    │                            ─── adapter_context.py│
    │                                                 │
    ├── exceptions.py          (no dependencies)      │
    ├── protocols.py           (stdlib only)          │
    ├── models.py              (stdlib, dataclasses)  │
    ├── adapter_context.py     (stdlib, logging)      │
    └── base_adapter.py        ─── models.py          │
                                 ─── adapter_context.py│
                                                       │
    ◆ The SDK never imports from services.execution   │
    ◆ The SDK never imports from services.planner     │
    ◆ The SDK never imports from services.* (runtime) │
                                                       │
Concrete Adapters ───────────────────────────────────┘
    │
    ▼
External APIs (Gmail, Slack, HTTP, etc.)
```

### Dependency Rules

| Direction | Allowed? |
|---|---|
| Runtime → Adapter SDK | ✅ Yes |
| Adapter SDK → Runtime | ❌ Never |
| Concrete Adapter → SDK | ✅ Yes |
| Concrete Adapter → Runtime | ✅ Yes (via SDK abstractions) |
| Concrete Adapter ↔ Concrete Adapter | ❌ Never |

## 3. Adapter Lifecycle

```
                    ┌──────────────┐
                    │  Discovery   │  Runtime inspects metadata without instantiation
                    │  (metadata)  │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │ Registration │  Adapter registered by type/name
                    │  (validate)  │  Optional: validate() checks config
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │  Execution   │  Runtime calls execute(context)
                    │  (execute)   │  Returns structured AdapterResult
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │  Health      │  Optional: runtime polls health()
                    │  (health)    │
                    └──────────────┘
```

### Lifecycle Methods

| Method | Required | Purpose |
|---|---|---|
| `metadata` (property) | ✅ Yes | Describe adapter identity and capabilities |
| `execute(context)` | ✅ Yes | Execute the operation |
| `validate()` | Optional | Validate configuration at registration |
| `health()` | Optional | Return health status |
| `capabilities()` | Optional | Report dynamic capabilities |

## 4. Metadata Model

```python
@dataclass(frozen=True)
class AdapterMetadata:
    name: str
    display_name: str
    version: str
    description: str
    author: str                          # default ""
    supported_operations: tuple[str, ...] # default ()
    requires_auth: bool                   # default False
    supports_streaming: bool              # default False
    supports_batch: bool                  # default False
    supports_retry: bool                  # default True
    tags: tuple[str, ...]                 # default ()
```

### Design Decisions

- **Immutable** — frozen dataclass prevents accidental mutation during runtime inspection.
- **Tuple over list** — `supported_operations` and `tags` use tuples to enforce immutability.
- **`to_dict()` / `from_dict()`** — enables serialization for storage and wire transfer.
- **`supports_retry` defaults True** — most adapters benefit from retry; opt out explicitly.
- **No `adapter_type` string** — the `name` field serves as the unique identifier.

## 5. Context Model

```python
@dataclass(frozen=True)
class AdapterContext:
    execution_session_id: str
    execution_task_id: str
    action: str
    params: dict[str, Any]            # default {}
    credentials: dict[str, Any]       # default {}
    config: dict[str, Any]            # default {}
    user_context: dict[str, Any]      # default {}
    logger: Logger | None             # default None
    runtime_metadata: dict[str, Any]  # default {}
```

### Design Decisions

- **Immutable** — adapters must not mutate execution state.
- **`build()` factory method** — converts `None` arguments to empty dicts for ergonomic construction.
- **Structured, not loose dicts** — each concern has a dedicated field (auth, config, operational params, user context).
- **`action` field** — tells the adapter what operation to perform (e.g., `"send"`, `"read"`, `"search"`), rather than encoding it in the method name.

### Runtime—Context Relationship

| Field | Provenance |
|---|---|
| `execution_session_id` | Set by runtime when session is created |
| `execution_task_id` | Set by runtime when task is dispatched |
| `action` | Derived from task type |
| `params` | Task payload |
| `credentials` | Resolved from credential store by runtime |
| `config` | Adapter configuration loaded by runtime |
| `user_context` | User/environment metadata |
| `logger` | Runtime-provided logger, adapter-injected |
| `runtime_metadata` | Runtime state (attempt number, source, etc.) |

## 6. Result Model

```python
@dataclass(frozen=True)
class AdapterResult:
    success: bool
    data: Any                          # default None
    metadata: dict[str, Any]           # default {}
    warnings: list[str]                # default []
    usage: UsageInfo                   # default UsageInfo()
    error: str | None                  # default None
```

```python
@dataclass(frozen=True)
class UsageInfo:
    tokens_in: int       # default 0
    tokens_out: int      # default 0
    api_calls: int       # default 0
    cost_usd: float      # default 0.0
    latency_ms: float    # default 0.0
    extra: dict[str, Any]# default {}
```

### Design Decisions

- **Single result type** — success and failure share `AdapterResult`. Consumers check `result.success`.
- **Immutable** — frozen dataclass ensures results are not modified after return.
- **Factory methods** — `AdapterResult.success_result()` and `AdapterResult.failure_result()` provide ergonomic construction.
- **UsageInfo separate** — cost/token tracking is a separate concern; naturally extensible without touching `AdapterResult`.
- **`warnings` field** — captured separately from errors (non-fatal diagnostics).
- **Structured `usage.extra`** — adapter-specific telemetry (model name, cache hit, region, etc.).

### Factory Method Examples

```python
# Success
AdapterResult.success_result(data={"id": "msg_123"})
AdapterResult.success_result(data=message, usage=UsageInfo(tokens_in=50))

# Failure
AdapterResult.failure_result(error="rate limit exceeded")
AdapterResult.failure_result(error="timeout", warnings=["degraded performance"])
```

## 7. Exception Hierarchy

```
AdapterError                          # base — catch-all for adapter failures
├── ConfigurationError                # misconfigured adapter (non-retryable)
├── ValidationError                   # invalid input (non-retryable)
├── AuthenticationError               # bad/missing credentials (non-retryable)
├── AuthorizationError                # insufficient permissions (non-retryable)
├── PermissionError                   # resource access denied (non-retryable)
├── RateLimitError                    # API rate limit hit (retryable)
├── ResourceNotFoundError             # resource doesn't exist (non-retryable)
├── TransientAdapterError             # temporary failure, retryable
├── FatalAdapterError                 # permanent failure, never retry
└── AdapterExecutionError             # unexpected bug/invariant violation
```

### Retryable vs Fatal Classification

| Exception | Retryable? | Rationale |
|---|---|---|
| `TransientAdapterError` | ✅ Yes | Network timeouts, server 503s |
| `RateLimitError` | ✅ Yes | Backoff + retry may succeed |
| `ConfigurationError` | ❌ No | Config won't change mid-execution |
| `AuthenticationError` | ❌ No | Credentials won't auto-fix |
| `AuthorizationError` | ❌ No | Permissions won't auto-fix |
| `ValidationError` | ❌ No | Input won't change mid-execution |
| `PermissionError` | ❌ No | Access denied is permanent |
| `ResourceNotFoundError` | ❌ No | Missing resource won't appear |
| `FatalAdapterError` | ❌ No | Explicit fatal marker |
| `AdapterExecutionError` | ❌ No | Unexpected bug, needs fix |

### Catching Strategy

```python
try:
    result = await adapter.execute(context)
except TransientAdapterError:
    # Retry with backoff
except RateLimitError:
    # Retry with longer backoff
except AuthenticationError:
    # Flag credential refresh
except AdapterError:
    # Generic adapter failure — do not retry
```

## 8. Base Adapter Interface

```python
class ExecutionAdapter(ABC):
    @property
    @abstractmethod
    def metadata(self) -> AdapterMetadata: ...

    @abstractmethod
    async def execute(self, context: AdapterContext) -> AdapterResult: ...

    async def validate(self) -> Optional[list[str]]: ...       # default: None
    async def health(self) -> dict: ...                         # default: {"status": "unknown"}
    async def capabilities(self) -> list[str]: ...              # default: []
```

### Design Decisions

- **Minimal interface** — only `metadata` and `execute` are required. Adding a new adapter should never require changes to the SDK.
- **All async** — adapters are inherently I/O-bound. Async is the default.
- **No `adapter_type` property** — the `metadata.name` field serves as the unique identifier.
- **No `shutdown()`** — lifecycle management (connection pooling, resource cleanup) is a concrete adapter concern, not SDK-level.
- **No `compensate()`** — compensation/rollback is a runtime concern, not an adapter contract.

## 9. Protocols

```python
class Validator(Protocol):
    async def validate(self) -> Optional[list[str]]: ...

class HealthCheckable(Protocol):
    async def health(self) -> dict: ...

class CapabilityProvider(Protocol):
    async def capabilities(self) -> list[str]: ...
```

### Design Decisions

- **Protocols over base classes** — optional behavior is described structurally. Adapters implement the protocol by defining the method, without forced inheritance.
- **Runtime checking** — `isinstance(obj, Validator)` works via structural subtyping.
- **Async** — all protocol methods are async for consistency with the base adapter.

## 10. Design Principles

### 1. Stateless Adapters
Adapters hold no mutable execution state. All state is passed via `AdapterContext`. Adapters may hold immutable configuration (loaded at construction), but never per-execution state.

### 2. Immutable Models
`AdapterMetadata`, `AdapterContext`, `AdapterResult`, and `UsageInfo` are all frozen dataclasses. This prevents accidental mutation by adapters or the runtime.

### 3. Single Responsibility
- `ExecutionAdapter` → behavior
- `AdapterMetadata` → description
- `AdapterContext` → execution parameters
- `AdapterResult` → output
- Exception classes → failures

### 4. Extensibility Without SDK Changes
Adding a new adapter is always:
```python
class MyAdapter(ExecutionAdapter):
    @property
    def metadata(self): ...
    async def execute(self, context): ...
```

### 5. Runtime Independence
The SDK can be imported and tested without starting the execution runtime. Adapters can be unit-tested in isolation.

### 6. No Concrete Logic
The SDK contains zero external API calls, zero HTTP requests, and zero service-specific logic.

## 11. Future Extension Points

| Area | Future Extension | Trigger |
|---|---|---|
| **Streaming** | `async def execute_stream(context) -> AsyncIterator[AdapterResult]` | When real streaming adapters arrive |
| **Progress** | `progress_callback` in `AdapterContext` | When long-running adapters need progress reporting |
| **Idempotency** | `idempotency_key` in `AdapterContext` | When runtime adds idempotency support |
| **Pagination** | `next_page_token` in `AdapterResult.metadata` | When search adapters need pagination |
| **Capability discovery** | `adapter_registry.capabilities()` index | Phase 4.2 — Capability System |
| **Auth** | Credential resolver abstraction | When multiple auth flows are needed |
| **Rate limiting** | Rate limit bucket integration | When rate limiting is extracted from adapters |
| **Attachments** | `AdapterResult.attachments` field | When file/attachment support is needed |

## 12. Package Structure

```
backend/services/adapters/
    __init__.py            # Public API exports
    base_adapter.py        # ExecutionAdapter (abstract)
    models.py              # AdapterMetadata, AdapterResult, UsageInfo
    adapter_context.py     # AdapterContext (frozen)
    protocols.py           # Validator, HealthCheckable, CapabilityProvider
    exceptions.py          # Full exception hierarchy (10 classes)
```

### File Sizes

| File | Lines | Purpose |
|---|---|---|
| `__init__.py` | 36 | Exports |
| `base_adapter.py` | 69 | Abstract base class |
| `models.py` | 113 | Data models (Metadata, Result, UsageInfo) |
| `adapter_context.py` | 59 | Execution context |
| `protocols.py` | 33 | Structural protocols |
| `exceptions.py` | 42 | Exception hierarchy |

## 13. Test Coverage

Test file: `backend/tests/test_adapter_sdk.py`

| Test Class | Domain | Tests |
|---|---|---|
| `TestExceptionHierarchy` | Exception inheritance | 14 |
| `TestExceptionCatching` | Exception catching hierarchy | 16 |
| `TestExceptionRetryableFatal` | Retryable vs fatal classification | 16 |
| `TestAdapterMetadataConstruction` | Metadata creation | 14 |
| `TestAdapterMetadataImmutability` | Metadata frozen enforcement | 8 |
| `TestAdapterMetadataSerialization` | to_dict / from_dict round-trip | 10 |
| `TestAdapterMetadataValidation` | Equality, hash, repr | 8 |
| `TestUsageInfoConstruction` | UsageInfo creation | 9 |
| `TestAdapterResultSuccess` | Success results | 11 |
| `TestAdapterResultFailure` | Failure results | 8 |
| `TestAdapterResultSerialization` | Serialization | 7 |
| `TestAdapterResultImmutability` | Frozen enforcement | 6 |
| `TestAdapterResultUsage` | Usage/warnings/metadata interaction | 7 |
| `TestAdapterContextConstruction` | Context creation | 8 |
| `TestAdapterContextBuildFactory` | build() factory | 4 |
| `TestAdapterContextImmutability` | Frozen enforcement | 7 |
| `TestAdapterContextOptionalFields` | Optional field defaults | 6 |
| `TestExecutionAdapterAbstract` | Abstract class constraints | 4 |
| `TestExecutionAdapterConcrete` | Concrete implementation | 15 |
| `TestProtocolValidator` | Validator protocol conformance | 5 |
| `TestProtocolHealthCheckable` | HealthCheckable protocol | 4 |
| `TestProtocolCapabilityProvider` | CapabilityProvider protocol | 5 |
| `TestProtocolMultipleProtocols` | Multi-protocol conformance | 5 |
| `TestSdkSelfContainment` | Independence verification | 5 |
| **Total** | | **192** |
