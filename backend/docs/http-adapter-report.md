# HTTP Adapter — Phase 5.2

## 1. Architecture

```
Planner
    │   "I need http_request / http_get / http_post"
    ▼
Capability Registry
    │   find_providers("http_request") → CapabilityProvider(http, 1.0.0)
    ▼
Adapter Registry
    │   select_provider("http_request") → AdapterRegistration
    │   factory.create(identity) → HttpAdapter
    ▼
Adapter Factory  →  HttpAdapter
    │                    │
    │                    ▼
    │               validate_request(req)
    │                    │
    │                    ▼
    │               resolve_auth(credentials)
    │                    │
    │                    ▼
    │               inject auth headers
    │                    │
    │                    ▼
    │               detect_serializer(body, content_type)
    │                    │
    │                    ▼
    │               serialize body
    │                    │
    │                    ▼
    │               HttpTransport.send(req)        ◄─── HttpTransport protocol
    │                    │                                │
    │                    ▼                                ▼
    │               HttpResponse                 HttpxTransport (concrete)
    │                    │                       httpx.AsyncClient
    │                    ▼
    │               map errors → AdapterResult
    │                    │
    │                    ▼
    │               return AdapterResult
```

### Layer Placement

| Component | Layer | File |
|---|---|---|
| `HttpRequest` / `HttpResponse` | HTTP models | `http/models.py` |
| `HttpTransport` (Protocol) | Transport abstraction | `http/transport.py` |
| `HttpxTransport` (concrete) | httpx implementation | `http/transport.py` |
| `AuthStrategy` (ABC) | Authentication abstraction | `http/auth.py` |
| `NoAuth` / `ApiKeyAuth` / etc. | Strategy implementations | `http/auth.py` |
| `BodySerializer` (ABC) | Serialization abstraction | `http/serializers.py` |
| `JsonSerializer` / `FormSerializer` / `PlainTextSerializer` | Concrete serializers | `http/serializers.py` |
| `HttpAdapter` | ExecutionAdapter subclass | `http/http_adapter.py` |
| HTTP exceptions | Error hierarchy | `http/exceptions.py` |
| Validators | Request validation | `http/validators.py` |

## 2. Request Lifecycle

```
AdapterContext arrives
    │
    ├── context.params:       method, url, headers, query_params, body, timeout, content_type, accept
    ├── context.credentials:  auth_type + auth-specific fields (token, api_key, username, etc.)
    └── context.config:       default_method, default_timeout, default_content_type, default_accept
    │
    ▼
1. Parse params
    │   Extract method, url, headers, query_params, body, timeout
    │
    ▼
2. Resolve auth
    │   resolve_auth(credentials) → (AuthStrategy, credential_values)
    │
    ▼
3. Inject auth headers
    │   strategy.apply(creds) → auth_headers
    │   merged_headers = {**auth_headers, **user_headers}
    │
    ▼
4. Detect serializer
    │   detect_serializer(body, content_type) → BodySerializer
    │
    ▼
5. Serialize body
    │   serializer.serialize(body) → bytes
    │   (skip if body is None or already bytes)
    │
    ▼
6. Build HttpRequest
    │   HttpRequest(method, url, headers, query_params, body, timeout, content_type, accept)
    │   Validates: URL, method, timeout (in __post_init__)
    │
    ▼
7. Transport.send(request)
    │   HttpTransport protocol → HttpxTransport (or injected fake)
    │
    ▼
8. Parse HttpResponse
    │   status_code, headers, body, elapsed, content_type
    │   json property: lazy JSON parsing
    │
    ▼
9. Return AdapterResult
    │   success / failure with structured data
```

## 3. Authentication Flow

```
Credentials dict (from AdapterContext or CredentialInstance):
    {
        "auth_type": "bearer_token",    ← selects strategy
        "token": "eyJ...",              ← strategy-specific fields
        "token_type": "Bearer",
        ...
    }
    │
    ▼
resolve_auth(credentials)
    │
    ├── auth_type="no_auth"       → NoAuth()         → {} (no headers)
    ├── auth_type="api_key"       → ApiKeyAuth()      → {"X-API-Key": "..."}  (configurable header name)
    ├── auth_type="bearer_token"  → BearerTokenAuth() → {"Authorization": "Bearer ..."}
    ├── auth_type="basic_auth"    → BasicAuth()       → {"Authorization": "Basic ..."}  (base64 encoded)
    └── auth_type="custom_header" → CustomHeaderAuth()→ {"custom_name": "custom_value"}
    │
    ▼
Headers merged into HttpRequest.headers
```

### Credential Descriptors

| Descriptor | Auth Type | Key Fields |
|---|---|---|
| `http_api_key` | `api_key` | `api_key`, `header_name` (default: X-API-Key) |
| `http_bearer_token` | `bearer_token` | `token` (or `access_token`), `token_type` (default: Bearer) |
| `http_basic_auth` | `basic_auth` | `username`, `password` |
| `http_custom_header` | `custom_header` | `header_name`, `header_value` |

## 4. Serialization

```
Body type         Content type              Serializer         Output
──────────────────────────────────────────────────────────────────────
dict              application/json          JsonSerializer      bytes (JSON)
list              application/json          JsonSerializer      bytes (JSON)
dict              application/x-www-form-   FormSerializer      bytes (URL-encoded)
                  urlencoded
str               text/plain                PlainTextSerializer bytes (UTF-8)
bytes             any                       PlainTextSerializer bytes (passthrough)
None              any                       Skipped             None
Any other         (inferred)                str() → bytes       bytes

Deserialization:
    HttpResponse.json → lazy json.loads() on first access
    JsonSerializer.deserialize(data) → dict/list
    HttpResponse.body → raw bytes
```

Content type detection priority:
1. `content_type` parameter (if registered)
2. Body type inference (dict → JSON, str → PlainText)
3. Fallback: PlainText

## 5. Error Mapping

```
Transport Error                     HTTP Adapter Exception     AdapterResult
─────────────────────────────────────────────────────────────────────────────────
httpx.TimeoutException              RequestTimeoutError        failure, error_type=RequestTimeoutError
httpx.ConnectError                  ConnectionError            failure, error_type=ConnectionError
httpx.RemoteProtocolError           ConnectionError            failure, error_type=ConnectionError
httpx.DecodingError                 SerializationError         failure, error_type=SerializationError
4xx response                        HttpStatusError            failure, error_type=HttpStatusError
5xx response                        HttpStatusError            failure, error_type=HttpStatusError
Invalid URL (validation)            InvalidUrlError            failure (validated pre-transport)
Invalid method (validation)         InvalidMethodError         failure (validated pre-transport)
Invalid timeout (validation)        InvalidTimeoutError        failure (validated pre-transport)
Invalid headers (validation)        InvalidHeaderError         failure (validated pre-transport)
JSON serialize failure              SerializationError         failure (validated pre-transport)
JSON parse failure                  DeserializationError       handled gracefully (json=None)
```

All transport errors are caught and mapped to adapter exceptions. No raw httpx exceptions leak.

## 6. Exception Hierarchy

```
HttpError (extends AdapterError)
├── InvalidUrlError                 — URL validation
├── InvalidMethodError              — method validation
├── InvalidTimeoutError             — timeout validation
├── InvalidHeaderError              — header validation
├── InvalidContentTypeError         — content type validation
├── RequestTimeoutError             — transport timeout (retryable)
├── ConnectionError                 — connection failure (retryable)
├── DnsError                        — DNS failure (retryable)
├── SerializationError              — body serialization failure
├── DeserializationError            — response parsing failure
└── HttpStatusError                 — 4xx/5xx (carries status_code, body, headers)
    .status_code
    .body
    .headers
```

RequestTimeoutError, ConnectionError, and DnsError inherit from `TransientAdapterError`, making them retryable by the runtime.

## 7. Transport Abstraction

```python
class HttpTransport(Protocol):
    async def send(self, request: HttpRequest) -> HttpResponse: ...
```

The protocol allows:
- **Testing** via `FakeHttpTransport` (no network)
- **Library independence** — `HttpxTransport` is one implementation; `AiohttpTransport`, `Urllib3Transport`, etc. can be added
- **Sync/async variants** — a sync transport would conform to the same interface (though Loqi uses async throughout)

### HttpxTransport

Uses `httpx.AsyncClient`. Can be constructed with an existing client or creates a new one per request.

## 8. Request/Response Models

### HttpRequest (frozen dataclass)

| Field | Type | Default | Description |
|---|---|---|---|
| `method` | str | — | HTTP method (validated: GET/POST/PUT/PATCH/DELETE/HEAD/OPTIONS) |
| `url` | str | — | Full URL including scheme (http/https only) |
| `headers` | dict[str, str] | `{}` | Request headers |
| `query_params` | dict[str, str] | `{}` | URL query parameters |
| `body` | Any | None | Request body (dict, str, bytes, list, or None) |
| `timeout` | float | 30.0 | Request timeout in seconds (must be positive) |
| `content_type` | str | "" | Content-Type header value (auto-detected if empty) |
| `accept` | str | "" | Accept header value |

### HttpResponse (frozen dataclass)

| Field/Method | Type | Description |
|---|---|---|
| `status_code` | int | HTTP status code |
| `headers` | dict[str, str] | Response headers |
| `body` | bytes | Raw response body |
| `elapsed` | float | Request duration in seconds |
| `content_type` | str | Response Content-Type header |
| `success` | property (bool) | True if status_code < 400 |
| `json` | property (Any) | Lazily parsed JSON body; raises DeserializationError on invalid JSON; returns None for empty body |
| `is_success()` | bool | True if 200 ≤ status_code < 300 |
| `is_client_error()` | bool | True if 400 ≤ status_code < 500 |
| `is_server_error()` | bool | True if 500 ≤ status_code < 600 |

## 9. Supported Methods

| Method | Capability | Authentication |
|---|---|---|
| GET | `http_get` | Optional |
| POST | `http_post` | Required (by default) |
| PUT | `http_put` | Required (by default) |
| PATCH | `http_patch` | Required (by default) |
| DELETE | `http_delete` | Required (by default) |
| HEAD | `http_head` | Optional |
| OPTIONS | `http_options` | Optional |

The generic `http_request` capability supports all methods.

## 10. Extension Points

| Area | Future | Trigger |
|---|---|---|
| **New auth strategies** | Register in `_AUTH_STRATEGY_REGISTRY` | When new auth types are needed (e.g., Digest, AWS SigV4) |
| **New transport** | Implement `HttpTransport` protocol | When aiohttp/urllib3/custom transport is needed |
| **New serializers** | Implement `BodySerializer` ABC | When XML, YAML, multipart, or custom serialization is needed |
| **Streaming** | `execute_stream()` method on adapter | When streaming responses are needed |
| **Progress reporting** | `progress_callback` in `AdapterContext` | When long-running requests need progress |
| **Mutual TLS** | `client_cert` / `client_key` in config or credentials | When mTLS is required |
| **Proxy support** | Add proxy fields to `HttpxTransport` config | When proxied requests are needed |
| **Retry from adapter** | Must NOT be added — runtime owns retries | N/A |

## 11. Capabilities

Five capability descriptors registered:

| Name | Category | Auth Required |
|---|---|---|
| `http_request` | web | True |
| `http_get` | web | False |
| `http_post` | web | True |
| `http_put` | web | True |
| `http_delete` | web | True |

All are in `CapabilityCategory.WEB` ("web").

## 12. Package Structure

```
backend/services/adapters/http/
    __init__.py            # Public API exports
    http_adapter.py        # HttpAdapter (ExecutionAdapter)
    models.py              # HttpRequest, HttpResponse
    auth.py                # AuthStrategy, NoAuth, ApiKeyAuth, BearerTokenAuth, BasicAuth, CustomHeaderAuth
    serializers.py         # BodySerializer, JsonSerializer, FormSerializer, PlainTextSerializer
    validators.py          # URL, method, timeout, headers, content_type validation
    transport.py           # HttpTransport protocol, HttpxTransport
    exceptions.py          # Full exception hierarchy (12 classes)
```

## 13. File Sizes

| File | Lines | Purpose |
|---|---|---|
| `__init__.py` | 62 | Exports |
| `http_adapter.py` | 177 | HttpAdapter implementation |
| `models.py` | 94 | Request/response models |
| `auth.py` | 112 | Authentication strategies |
| `serializers.py` | 112 | Body serializers |
| `validators.py` | 108 | Request validators |
| `transport.py` | 113 | Transport protocol + HttpxTransport |
| `exceptions.py` | 54 | Exception hierarchy |

## 14. Test Coverage

Test file: `backend/tests/test_http_adapter.py`

| Test Class | Domain | Tests |
|---|---|---|
| `TestHttpRequestConstruction` | Request model creation | 20 |
| `TestHttpRequestValidation` | Invalid input handling | 12 |
| `TestHttpRequestImmutability` | Frozen enforcement | 7 |
| `TestHttpResponseConstruction` | Response model creation | 4 |
| `TestHttpResponseHelpers` | is_success/is_client_error/is_server_error | 12 |
| `TestHttpResponseJson` | JSON parsing | 9 |
| `TestHttpResponseImmutability` | Frozen enforcement | 2 |
| `TestSupportedMethods` | Method constants | 2 |
| `TestHttpExceptionHierarchy` | All exception classes | 14 |
| `TestNoAuth` | NoAuth strategy | 3 |
| `TestApiKeyAuth` | API key strategy | 6 |
| `TestBearerTokenAuth` | Bearer token strategy | 7 |
| `TestBasicAuth` | Basic auth strategy | 5 |
| `TestCustomHeaderAuth` | Custom header strategy | 5 |
| `TestResolveAuth` | Auth resolution | 12 |
| `TestJsonSerializer` | JSON serializer | 10 |
| `TestFormSerializer` | Form URL-encoded serializer | 11 |
| `TestPlainTextSerializer` | Plain text serializer | 9 |
| `TestDetectSerializer` | Serializer detection | 12 |
| `TestGetSerializer` | Serializer lookup | 7 |
| `TestValidateUrl` | URL validation | 12 |
| `TestValidateMethod` | Method validation | 8 |
| `TestValidateTimeout` | Timeout validation | 9 |
| `TestValidateHeaders` | Header validation | 8 |
| `TestValidateContentType` | Content type validation | 4 |
| `TestValidateFullRequest` | Complete request validation | 5 |
| `TestFakeTransport` | Fake transport for tests | 4 |
| `TestHttpAdapterMetadata` | Adapter metadata & constants | 11 |
| `TestHttpAdapterGet` | GET requests | 8 |
| `TestHttpAdapterPost` | POST requests | 3 |
| `TestHttpAdapterPut` | PUT requests | 1 |
| `TestHttpAdapterPatch` | PATCH requests | 1 |
| `TestHttpAdapterDelete` | DELETE requests | 2 |
| `TestHttpAdapterHead` | HEAD requests | 1 |
| `TestHttpAdapterOptions` | OPTIONS requests | 1 |
| `TestHttpAdapterAuth` | Authentication injection | 7 |
| `TestHttpAdapterErrorHandling` | Error mapping | 9 |
| `TestHttpAdapterConfig` | Configuration defaults | 4 |
| `TestHttpAdapterUsage` | Usage tracking | 2 |
| `TestHttpAdapterResponseParsing` | Response parsing edge cases | 4 |
| `TestHttpAdapterEdgeCases` | Large bodies, dup requests | 4 |
| `TestHttpAdapterStatelessness` | Statelessness verification | 3 |
| `TestHttpAdapterNoRetries` | No retry/cache behavior | 2 |
| `TestHttpAdapterResponseMetadata` | Response metadata | 2 |
| `TestHttpAdapterNoServiceSpecific` | No service-specific code | 6 |
| `TestHttpAdapterCredentialConsumption` | Credential consumption | 2 |
| `TestHttpAdapterRegistryIntegration` | Registry integration | 3 |
| `TestHttpAdapterCapabilityIntegration` | Capability integration | 4 |
| `TestHttpAdapterCredentialDescriptorIntegration` | Credential descriptor integration | 4 |
| `TestHttpAdapterContextBinding` | Context binding | 2 |
| `TestHttpAdapterQueryParams` | Query param handling | 3 |
| `TestHttpxTransportProtocol` | Transport protocol conformance | 3 |
| `TestHttpxTransportConstruction` | Transport construction | 1 |
| `TestHttpAdapterSelfContainment` | No runtime/planner/concrete deps | 7 |
| `TestHttpAdapterFullLifecycle` | End-to-end lifecycle | 1 |
| **Total** | | **314** |
