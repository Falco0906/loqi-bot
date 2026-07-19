# Google API Base Adapter v1 — Architecture Freeze

## Adapter Version

**v1.0**

## Freeze Date

2026-07-19

## Freeze Status

**FROZEN**

No further changes to the Google API Base Adapter are permitted without an RFC.

---

## Core Architectural Principles

1. **Service-agnostic only.** The adapter contains zero Gmail-, Calendar-, Drive-, Docs-, or Sheets-specific logic. All Google API interactions go through `GoogleServiceDescriptor` and `GoogleServiceRegistry`. Adding a new service requires only registering a new descriptor.

2. **Delegates HTTP to HttpAdapter.** The adapter never constructs or sends raw HTTP requests. It translates `GoogleApiRequest` to `HttpRequest` and delegates execution to `HttpAdapter`, which uses the `HttpTransport` protocol.

3. **Google error mapping is structured.** `parse_google_error_body()` extracts `code`, `message`, `status`, and `errors` from Google's JSON error payloads. `GoogleApiErrorInfo.to_exception()` maps status-first (preferring `RATE_LIMIT_EXCEEDED` → `GoogleRateLimitError` over generic `code == 429` → `GoogleQuotaExceededError`).

4. **OAuth2 is injected, not fetched.** The adapter expects `access_token` and `token_type` in `context.credentials`. It never calls `CredentialResolver`, never initiates OAuth flows, and never refreshes tokens.

5. **URLs are built, not hardcoded.** `GoogleServiceDescriptor.build_url()` constructs the URL from base URL, service name, version, and resource path. No URL templates or string constants specific to any service.

6. **Adapter remains stateless.** No mutable instance state. No caches. All per-request state flows through `GoogleApiRequest` and `AdapterContext`.

7. **Runtime owns retries, caching, metrics.** The adapter inherits the same contract as `HttpAdapter` — it never retries, caches, or collects metrics internally.

8. **Pagination is a helper, not a feature.** `next_page_token()` extracts pagination tokens from response JSON. It is a pure function, not middleware. The caller decides whether to paginate.

---

## Extension Points (non-breaking)

- Adding new service descriptors to `DEFAULT_GOOGLE_SERVICES` in `services.py`
- Adding new URL helpers in `urls.py` (e.g., `sheets()`, `docs()`)
- Adding new exception subclasses under `GoogleApiError` in `errors.py`
- Adding new pagination helpers in `pagination.py`
- Adding new optional fields to `GoogleApiRequest` or `GoogleApiResponse` (with defaults)
- Adding new test cases

---

## RFC-Required Changes

- Adding Gmail-, Calendar-, Drive-, or any service-specific logic to any Google adapter module
- Making `GoogleApiRequest` or `GoogleApiResponse` mutable
- Removing or renaming public methods on `GoogleApiAdapter`
- Adding retry, caching, or metrics logic to the adapter
- Adding credential fetching or OAuth token refresh to the adapter
- Changing the `HttpTransport` dependency
- Changing the `GoogleServiceDescriptor` or `GoogleServiceRegistry` public API
- Removing or renaming public exports from `__init__.py`
- Adding runtime or planner imports to any Google adapter module

---

## Known Limitations (v1.0)

| Limitation | Accepted Because |
|---|---|
| No service-specific response parsing | Gmail/Calendar/Drive adapters will own their response models |
| No batch request support | Google batch endpoints require multipart/mixed; can be added as a transport feature |
| No upload support | Google upload endpoints need separate handling in service adapters |
| No discovery API integration | Service descriptors are manually defined; auto-discovery via `https://www.googleapis.com/discovery/v1/apis` could be added later |
| No quota management | Runtime owns rate limiting and quota tracking |
| No retry | Runtime owns retries (via RetryEngine) |

---

## Dependency Rules

```
GoogleApiAdapter
    │ depends on
    ├── Adapter SDK (ExecutionAdapter, AdapterContext, AdapterResult, AdapterMetadata)
    ├── Http Adapter (HttpAdapter via delegation)
    └── HttpTransport protocol (indirectly via HttpAdapter)
```

```
GoogleApiAdapter ── never ──▶ services.execution
GoogleApiAdapter ── never ──▶ services.planner
GoogleApiAdapter ── never ──▶ Gmail, Calendar, Drive, etc.
GoogleApiAdapter ── never ──▶ CredentialResolver
```

---

## Freeze Rationale

The Google API Base Adapter is the second production-grade adapter and the first domain-specific adapter built on the frozen platform layers. It validates that the `HttpAdapter` abstraction is sufficient for Google REST APIs and that the platform's error mapping, pagination, and URL-building patterns work with a real external API.

The adapter is completely service-agnostic — it contains no references to Gmail, Calendar, Drive, or any other Google service beyond the URL and descriptor in `services.py`. All service-specific logic will live in dedicated adapter modules that depend on this base.
