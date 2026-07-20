# Gmail Adapter v1.0 — Implementation Report

## Architecture

```
ExecutionAdapter (Adapter SDK, Layer 2)
    │
    ├── HttpAdapter (HTTP Adapter v1.0)
    │       │
    │       └── HttpTransport protocol → HttpxTransport
    │
    └── GoogleApiAdapter (Google API Base Adapter v1.0)
            │
            └── GmailAdapter (this)
                    │
                    └── Gmail REST API
```

`GmailAdapter(ExecutionAdapter)` is a thin domain layer that translates Gmail concepts into Google API requests. It owns a `GoogleApiAdapter` instance and delegates all HTTP execution to it — no HTTP logic is duplicated, no Google infrastructure is reimplemented.

## Package Structure

```
backend/services/adapters/google/gmail/
    __init__.py          # Public API, metadata, capabilities, credential descriptors
    errors.py            # Gmail-specific exception hierarchy
    gmail_adapter.py     # GmailAdapter — main adapter class
    mime.py              # MimeMessage — RFC 2822 email builder
    models.py            # Request/response models, GmailResourceMapper
    queries.py           # GmailQuery — type-safe search query builder
```

## Inheritance

```
services.adapters.exceptions
    └── AdapterError
        └── HttpError
            └── GoogleApiError (google/errors.py)
                ├── GmailError
                │   ├── MessageNotFoundError
                │   ├── ThreadNotFoundError
                │   ├── LabelNotFoundError
                │   └── InvalidQueryError
                ├── GoogleAuthenticationError
                ├── GooglePermissionError
                ├── GoogleQuotaExceededError
                └── GoogleRateLimitError
```

Gmail-specific exceptions inherit from `GoogleApiError`. Authentication and quota errors continue to come from the Google API layer — the Gmail adapter does not re-map them.

## Request Lifecycle

```
GmailAdapter.execute(context)
    │
    ├── Dispatch by action (gmail_send_email, gmail_list_messages, ...)
    │
    ├── Build typed request model (SendEmailRequest, ListMessagesRequest, ...)
    │
    ├── Build AdapterContext for GoogleApiAdapter
    │   ├── service="gmail"
    │   ├── resource="users/me/messages/send"
    │   ├── credentials from context (OAuth2 access_token)
    │   └── body = {"raw": MimeMessage.encode()}
    │
    ├── GoogleApiAdapter.execute(context)
    │   ├── Resolve "gmail" → GoogleServiceDescriptor
    │   ├── Build URL: https://gmail.googleapis.com/gmail/v1/...
    │   ├── Inject OAuth2 Bearer token
    │   ├── HttpAdapter.execute(http_context)
    │   │   └── HttpTransport.send(request) → HttpResponse
    │   └── Post-process: parse Google error body, extract pagination
    │
    ├── Map result with GmailResourceMapper
    │   ├── to_message_summary()
    │   ├── to_message_detail()
    │   ├── to_thread_summary()
    │   └── to_label_summary()
    │
    └── Return AdapterResult with typed Gmail models
```

## MIME Generation

`MimeMessage` in `mime.py` uses Python's `email.mime` standard library to produce RFC 2822-compliant messages.

```
MimeMessage()
    .to(["alice@example.com"])
    .cc(["bob@example.com"])
    .subject("Weekly Report")
    .plain("Hello Alice!")
    .html("<p>Hello Alice!</p>")
    .reply_to("support@example.com")
    .encode()  # → base64url-encoded string for Gmail API raw field
```

Features:
- Plain text only, HTML only, or multipart/alternative
- CC, BCC, Reply-To, From headers
- Custom headers via `.header(name, value)`
- Base64url encoding for Gmail API compatibility
- Chainable builder API
- `.reset()` for reuse

## Gmail Query Builder

`GmailQuery` in `queries.py` provides a type-safe builder for Gmail search operators.

Supported operators:
| Method | Produces | Example |
|--------|----------|---------|
| `.from_(addr)` | `from:addr` | `from:alice@example.com` |
| `.to(addr)` | `to:addr` | `to:bob@example.com` |
| `.subject(text)` | `subject:text` | `subject:"meeting notes"` |
| `.label(name)` | `label:name` | `label:INBOX` |
| `.has_attachment()` | `has:attachment` | |
| `.is_unread()` | `is:unread` | |
| `.is_read()` | `is:read` | |
| `.is_starred()` | `is:starred` | |
| `.is_important()` | `is:important` | |
| `.in_(folder)` | `in:folder` | `in:inbox`, `in:sent` |
| `.after(date)` | `after:date` | `after:2026/01/01` |
| `.before(date)` | `before:date` | `before:2026/12/31` |
| `.newer_than(n, unit)` | `newer_than:n{unit}` | `newer_than:7d` |
| `.older_than(n, unit)` | `older_than:n{unit}` | `older_than:3m` |
| `.cc(addr)` | `cc:addr` | `cc:carol@example.com` |
| `.bcc(addr)` | `bcc:addr` | `bcc:dave@example.com` |
| `.larger(bytes)` | `larger:bytes` | `larger:1024` |
| `.smaller(bytes)` | `smaller:bytes` | `smaller:5120` |
| `.filename(name)` | `filename:name` | `filename:report.pdf` |
| `.raw(text)` | text | raw expression passthrough |

Values containing spaces or quotes are automatically escaped.

## GmailResourceMapper

`GmailResourceMapper` in `models.py` converts raw Gmail API JSON responses into typed domain models. This keeps `GmailAdapter` focused on orchestration and makes response transformation independently testable.

| Method | Input | Output |
|--------|-------|--------|
| `to_message_summary(raw)` | Message list item | `MessageSummary` |
| `to_message_detail(raw)` | Full message | `MessageDetail` |
| `to_thread_summary(raw)` | Thread object | `ThreadSummary` |
| `to_label_summary(raw)` | Label object | `LabelSummary` |

The mapper handles:
- Header extraction (`From`, `To`, `Subject`, `Date`)
- Multipart body parsing (text/plain + text/html from nested parts)
- Base64url decoding of body data
- Color extraction for labels

## Request Models

All request models are immutable frozen dataclasses with validation in `__post_init__`.

| Model | Key Fields | Validation |
|-------|-----------|------------|
| `SendEmailRequest` | `to`, `subject`, `body_plain`, `body_html`, `cc`, `bcc`, `reply_to` | Required: to/cc/bcc, subject, body; email format |
| `ListMessagesRequest` | `max_results`, `label_ids`, `query`, `include_spam_trash` | max_results 1-500 |
| `GetMessageRequest` | `message_id`, `format` | format in (minimal, full, metadata, raw) |
| `SearchMessagesRequest` | `query`, `max_results`, `label_ids` | query required, max_results 1-500 |
| `ListLabelsRequest` | (empty) | — |
| `GetLabelRequest` | `label_id` | label_id required |
| `ListThreadsRequest` | `max_results`, `label_ids`, `query` | max_results 1-500 |
| `GetThreadRequest` | `thread_id`, `format` | thread_id required, format validation |

## Response Models

All response models are immutable frozen dataclasses.

| Model | Key Fields |
|-------|-----------|
| `MessageSummary` | `id`, `thread_id`, `snippet`, `from_`, `to`, `subject`, `date`, `label_ids` |
| `MessageDetail` | `id`, `thread_id`, `snippet`, `body_plain`, `body_html`, `headers`, `size_estimate`, `history_id`, `internal_date` |
| `ThreadSummary` | `id`, `snippet`, `history_id`, `messages` (tuple of MessageSummary) |
| `LabelSummary` | `id`, `name`, `type`, `color`, `message_list_visibility`, `messages_total`, `messages_unread` |

## Error Exceptions

| Exception | When |
|-----------|------|
| `GmailError` | Base Gmail error, unexpected failures |
| `MessageNotFoundError` | 404 on a message resource |
| `ThreadNotFoundError` | 404 on a thread resource |
| `LabelNotFoundError` | 404 on a label resource |
| `InvalidQueryError` | 400 with invalid query |

Google-layer errors (authentication, permission, quota, rate limit) propagate through `GoogleApiAdapter` unchanged.

## Capabilities

8 granular capabilities registered:

| Capability | Description |
|-----------|-------------|
| `gmail_send_email` | Send an email via Gmail |
| `gmail_list_messages` | List Gmail messages with optional filters |
| `gmail_get_message` | Retrieve a single Gmail message by ID |
| `gmail_search_messages` | Search Gmail messages using Gmail search syntax |
| `gmail_list_labels` | List all Gmail labels for the authenticated user |
| `gmail_get_label` | Retrieve a single Gmail label by ID |
| `gmail_list_threads` | List Gmail threads with optional filters |
| `gmail_get_thread` | Retrieve a single Gmail thread by ID |

## Credential Descriptors

Reuses `google_oauth2` from the Google API Base Adapter. No Gmail-specific credential descriptor is introduced.

## Extension Points (non-breaking)

- Adding new Gmail operation handlers in `GmailAdapter`
- Adding new request/response models in `models.py`
- Adding new search operators to `GmailQuery`
- Adding new exception subclasses in `errors.py`
- Extending `GmailResourceMapper` with new `to_*` methods
- Adding new MIME features to `MimeMessage`
- Adding new test cases

## RFC-Required Changes

- Adding OAuth flow or token refresh logic
- Adding retry, caching, or metrics to the adapter
- Adding drafts, attachments, filters, settings, or admin APIs
- Adding Gmail watch or push notification support
- Changing the `GoogleApiAdapter` dependency
- Adding imports from `services.execution` or `services.planner`
- Making request or response models mutable

## Test Coverage

162 tests across 20 test classes:

| Test Class | Tests |
|-----------|-------|
| TestMimeMessage | 16 |
| TestGmailQuery | 31 |
| TestSendEmailRequest | 8 |
| TestListMessagesRequest | 3 |
| TestGetMessageRequest | 5 |
| TestSearchMessagesRequest | 3 |
| TestListLabelsRequest | 1 |
| TestGetLabelRequest | 2 |
| TestListThreadsRequest | 2 |
| TestGetThreadRequest | 3 |
| TestMessageSummary | 4 |
| TestMessageDetail | 2 |
| TestThreadSummary | 2 |
| TestLabelSummary | 2 |
| TestGmailResourceMapper | 9 |
| TestGmailAdapterErrorMapping | 7 |
| TestGmailAdapterSendEmail | 8 |
| TestGmailAdapterListMessages | 6 |
| TestGmailAdapterGetMessage | 3 |
| TestGmailAdapterSearch | 3 |
| TestGmailAdapterLabels | 4 |
| TestGmailAdapterThreads | 4 |
| TestGmailAdapterMetadata | 9 |
| TestGmailAdapterStateless | 3 |
| TestGmailAdapterNoLowerDependencies | 3 |
| TestGmailAdapterInjection | 2 |
| TestGmailAdapterAllFlowsThroughGoogle | 5 |
| TestSendEmailRequestErrors | 3 |
| TestMimeMessageEdgeCases | 3 |
| TestGmailQueryComplex | 2 |
| **Total** | **162** |
