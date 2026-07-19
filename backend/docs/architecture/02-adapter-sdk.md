# Layer 2: Adapter SDK Foundation

## Purpose

Defines the contract every adapter must satisfy. The SDK is the only dependency the execution runtime has on the adapter ecosystem. Concrete adapters implement `ExecutionAdapter`; the SDK never imports concrete adapters, the runtime, or the planner.

## Freeze Reference

[ADAPTER_SDK_FOUNDATION_FREEZE.md](../ADAPTER_SDK_FOUNDATION_FREEZE.md)

## Package

`services.adapters` (base modules only)

## Components

### ExecutionAdapter (`base_adapter.py`)
The sole adapter contract. Two required members:

```python
class ExecutionAdapter(ABC):
    @property
    @abstractmethod
    def metadata(self) -> AdapterMetadata: ...

    @abstractmethod
    async def execute(self, context: AdapterContext) -> AdapterResult: ...

    async def validate(self) -> list[str] | None: ...       # optional
    async def health(self) -> dict: ...                      # optional
    async def capabilities(self) -> list[str]: ...           # optional
```

- Minimal: only `metadata` + `execute` required
- All async (adapters are I/O-bound)
- No `adapter_type` — `metadata.name` is the identifier
- No `shutdown()` — resource cleanup is a concrete concern
- No `compensate()` — rollback is a runtime concern

### Models (`models.py`)

```python
@dataclass(frozen=True)
class AdapterMetadata:
    name: str                     # unique identifier
    display_name: str
    version: str
    description: str
    author: str                   # default ""
    supported_operations: tuple[str, ...]  # default ()
    requires_auth: bool           # default False
    supports_streaming: bool      # default False
    supports_batch: bool          # default False
    supports_retry: bool          # default True
    tags: tuple[str, ...]         # default ()

@dataclass(frozen=True)
class AdapterResult:
    success: bool
    data: Any                     # default None
    metadata: dict                # default {}
    warnings: list[str]           # default []
    usage: UsageInfo              # default UsageInfo()
    error: str | None             # default None

@dataclass(frozen=True)
class UsageInfo:
    tokens_in: int                # default 0
    tokens_out: int               # default 0
    api_calls: int                # default 0
    cost_usd: float               # default 0.0
    latency_ms: float             # default 0.0
    extra: dict                   # default {}
```

### AdapterContext (`adapter_context.py`)

```python
@dataclass(frozen=True)
class AdapterContext:
    execution_session_id: str
    execution_task_id: str
    action: str                   # operation to perform ("send", "read", "search")
    params: dict                  # task payload
    credentials: dict             # pre-populated by runtime
    config: dict                  # adapter configuration
    user_context: dict            # user/environment metadata
    logger: Logger | None
    runtime_metadata: dict        # attempt number, source, etc.
```

All state for a single execution. Adapters never mutate context.

### Protocols (`protocols.py`)

```python
@runtime_checkable
class Validator(Protocol):
    async def validate(self) -> list[str] | None: ...

@runtime_checkable
class HealthCheckable(Protocol):
    async def health(self) -> dict: ...

@runtime_checkable
class CapabilityReporter(Protocol):
    async def capabilities(self) -> list[str]: ...
```

Protocols describe optional behavior without forced inheritance.

### Exception Hierarchy (`exceptions.py`)

```
AdapterError
├── ConfigurationError            # non-retryable
├── ValidationError               # non-retryable
├── AuthenticationError           # non-retryable
├── AuthorizationError            # non-retryable
├── PermissionError               # non-retryable
├── RateLimitError                # RETRYABLE
├── ResourceNotFoundError         # non-retryable
├── TransientAdapterError         # RETRYABLE
├── FatalAdapterError             # non-retryable
└── AdapterExecutionError         # non-retryable
```

Clean separation: `TransientAdapterError` and `RateLimitError` are retryable; everything else is fatal.

## Design Principles

1. **Single adapter contract.** Adding a new adapter never requires SDK changes.
2. **Adapters are stateless.** All execution state lives in `AdapterContext`.
3. **Models are frozen.** No mutation after construction.
4. **Single responsibility per module.** Behavior, description, parameters, output, failures — each in its own module.
5. **Exceptions separate retryable from fatal.** Clear catch strategy.
6. **Runtime depends on abstractions.** No concrete adapter logic in SDK.
7. **Zero runtime dependencies.** SDK never imports `services.execution`, `services.planner`, or concrete adapters.
8. **Protocols over inheritance.** Optional behavior is structural.

## Test Coverage

192 tests in `tests/test_adapter_sdk.py`.
