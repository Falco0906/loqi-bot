# HTTP Adapter v1 — Architecture Freeze

## Adapter Version

**v1.0**

## Freeze Date

2026-07-18

## Freeze Status

**FROZEN**

No further changes to the HTTP adapter are permitted without an RFC.

---

## Core Architectural Principles

1. **Generic HTTP only.** The adapter contains zero references to Gmail, Slack, OpenAI, GitHub, or any other concrete service. All capabilities are prefixed with `http_`. No service-specific logic exists in any module.

2. **Transport abstraction.** The adapter depends on the `HttpTransport` protocol, not on httpx or any specific library. `HttpxTransport` is one concrete implementation. Switching libraries requires only a new transport implementation.

3. **Auth is injected, not fetched.** Authentication strategies consume a `dict[str, str]` of credential values provided by the runtime. The adapter never calls `CredentialResolver`, never fetches secrets, and never manages OAuth flows.

4. **Adapter remains stateless.** No mutable instance state. No caches. No connection pools. All per-request state flows through `AdapterContext`.

5. **Runtime owns retries.** The adapter never retries internally. Transport errors are mapped to exceptions and returned as `AdapterResult.failure_result()`. The runtime decides whether to retry.

6. **Runtime owns cancellation.** The adapter never swallows cancellation. It does not implement timeout logic beyond passing the timeout value to the transport.

7. **Runtime owns metrics.** The adapter does not collect or emit metrics. It returns `UsageInfo` with `api_calls` and `latency_ms` for the runtime to aggregate.

8. **Runtime owns recovery.** The adapter contains no recovery or session management logic.

9. **Request/response models are immutable.** `HttpRequest` and `HttpResponse` are frozen dataclasses. No code may mutate them after construction.

10. **Errors are mapped to adapter exceptions.** No raw `httpx` exceptions leak to the caller. Every transport error is caught and wrapped in the HTTP adapter's exception hierarchy.

---

## Extension Points (non-breaking)

- Adding new auth strategies to `_AUTH_STRATEGY_REGISTRY`
- Adding new serializers by implementing `BodySerializer` ABC
- Adding new transport implementations by implementing `HttpTransport` protocol
- Adding new constants to `SUPPORTED_METHODS`
- Adding new optional fields to `HttpRequest` or `HttpResponse` (with defaults)
- Adding new exception subclasses under `HttpError`
- Adding new validators to `validators.py`
- Adding new capability or credential descriptors
- Adding new test cases

---

## RFC-Required Changes

- Adding service-specific logic (Gmail, Slack, OpenAI, etc.) to any HTTP adapter module
- Making `HttpRequest` or `HttpResponse` mutable
- Removing or renaming public methods on `HttpAdapter`
- Adding retry logic to the adapter
- Adding caching to the adapter
- Adding metrics collection to the adapter
- Adding credential fetching to the adapter
- Changing the `HttpTransport` protocol signature
- Removing or renaming public exports from `__init__.py`
- Changing the exception hierarchy base classes
- Adding runtime or planner imports to any HTTP module

---

## Known Limitations (v1.0)

| Limitation | Accepted Because |
|---|---|
| No streaming support | `execute_stream()` can be added when streaming adapters are needed |
| No multipart upload support | Can be added as a new serializer or transport option |
| No proxy support | Can be added to `HttpxTransport` constructor |
| No mutual TLS | Can be added via config/credentials when needed |
| No WebSocket support | Out of scope for HTTP adapter |
| No GraphQL support | GraphQL queries are sent as POST with JSON; no adapter change needed |
| No redirect following customization | httpx follows redirects by default; can be exposed via config if needed |
| No cookie support | Cookies are transport-level; can be added to httpx client options |
| No rate limiting | Runtime owns rate limiting |
| No retry | Runtime owns retries |

---

## Dependency Rules

```
HttpAdapter
    │ depends on
    ├── Adapter SDK (ExecutionAdapter, AdapterContext, AdapterResult, AdapterMetadata, UsageInfo)
    ├── Capability System (CapabilityDescriptor)
    ├── Credential Framework (CredentialDescriptor, CredentialInstance — values only)
    └── httpx (via HttpxTransport only — isolated behind HttpTransport protocol)
```

```
HttpAdapter ── never ──▶ services.execution
HttpAdapter ── never ──▶ services.planner
HttpAdapter ── never ──▶ concrete adapters
HttpAdapter ── never ──▶ Gmail, Slack, OpenAI, etc.
```

---

## Freeze Rationale

The HTTP Adapter is the first production-grade adapter built on the frozen platform layers. It validates every abstraction in the Adapter SDK, Capability System, Credential Framework, and Adapter Registry with a real, testable implementation.

The adapter is fully generic — it contains no Gmail, Slack, Google, or OpenAI references. Every capability is HTTP-specific (`http_request`, `http_get`, etc.). The transport protocol isolates the adapter from any specific HTTP library. Authentication strategies consume credential values injected by the runtime.

No concrete integration (Gmail, Slack, Calendar) has yet proven any of these abstractions insufficient. Until one does, the HTTP adapter is frozen.
