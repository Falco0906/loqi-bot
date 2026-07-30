# Loqi Backend Architecture

> Source of truth: current backend implementation.
> Generated from codebase analysis — documents what exists, not what is planned.

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Platform Layer](#platform-layer)
3. [Execution & Planning Layer](#execution--planning-layer)
4. [Adapter Ecosystem](#adapter-ecosystem)
5. [AI / Intelligence Layer](#ai--intelligence-layer)
6. [Communication & Outbound Layer](#communication--outbound-layer)
7. [Infrastructure & Supporting Services](#infrastructure--supporting-services)
8. [Layer Dependencies](#layer-dependencies)
9. [Test Coverage Map](#test-coverage-map)

---

## System Overview

The Loqi backend is a FastAPI application organized into layered platform modules, an execution engine, an adapter ecosystem, and AI intelligence subsystems.

```
┌─────────────────────────────────────────────────────────┐
│                    FastAPI Application                    │
│                      main.py (3.4k LOC)                   │
├─────────────────────────────────────────────────────────┤
│                    ┌─── Platform Modules ───┐             │
│                    │ Identity │ Org │ Onboard │             │
│                    │ Billing  │ Capabilities │             │
│                    └────────────────────────┘             │
│                    ┌─── AI Pipeline ───┐                   │
│                    │ Intelligence →     │                   │
│                    │ Reasoning →        │                   │
│                    │ Reply Generation   │                   │
│                    └────────────────────┘                   │
│                    ┌─── Execution ───┐                      │
│                    │ Planner →        │                      │
│                    │ Execution Engine │                      │
│                    └──────────────────┘                      │
│                    ┌─── Adapters ───┐                        │
│                    │ Gmail │ Calendar│                        │
│                    │ HTTP │ CRM │ Mem │                       │
│                    └────────────────┘                        │
│                    ┌─── Outbound ───┐                         │
│                    │ Drafts │ Send │                           │
│                    │ Scheduler      │                          │
│                    └────────────────┘                          │
├─────────────────────────────────────────────────────────┤
│           Production Persistence (M2.1 Identity)          │
│   Supabase PostgreSQL for users, sessions, tokens, etc.   │
│   Remaining modules still use InMemory* repositories      │
├─────────────────────────────────────────────────────────┤
│         Billing Provider (swappable via config)           │
│     MockStripeBillingProvider (mock, default)             │
│     StripeBillingProvider (live, uses stripe SDK)         │
├─────────────────────────────────────────────────────────┤
│                In-Memory Persistence                       │
│      (Capabilities, Onboarding still InMemory)             │
└─────────────────────────────────────────────────────────┘
```

### Key Architectural Properties

- **Layered architecture** with explicit dependency direction (platform → execution → adapters)
- **Identity persistence uses Supabase PostgreSQL** (M2.1) — 5 repository implementations: User, Session, RefreshToken, VerificationToken, PasswordReset
- **All other platform modules still use in-memory** — Billing, Organizations, Capabilities, Onboarding remain InMemory*
- **Domain events collected but not published** — services accumulate events via `.events` property with no event bus or subscriber mechanism
- **Dependency injection via global mutable singletons** — `_deps_registry` pattern used across platform modules
- **Synchronous core with async bridge** — `handle_message()` and workflow dispatch run synchronously, offloaded via `ThreadPoolExecutor._run_async()`

---

## Platform Layer

### Identity Platform (`services/identity/` — 46 files)

**Purpose:** Complete authentication and authorization platform.

**Components:**
- **User model** — soft-deletable, locale-aware
- **Email+password auth** — Argon2 hashing, email verification flow (begin → verify → complete)
- **Google OAuth** — PKCE flow with state parameter, code verifier, nonce
- **Session management** — active/expired/revoked states, configurable session limits
- **Refresh token rotation** — family-based rotation with theft detection (sequence numbers)
- **Password reset** — model exists (`PasswordResetRequest`), no API endpoint

**Repositories:** 10 repository interfaces. 5 have Supabase implementations (User, Session, RefreshToken, VerificationToken, PasswordReset). 5 remain InMemory* (EmailIdentity, PasswordCredential, ExternalIdentity, RegistrationSession, OAuthSession). Mode switching via `services/persistence/config.py:RepositoryProvider`.
**Email:** `ConsoleEmailProvider` (default, development) or `ResendEmailProvider` (production via `EMAIL_PROVIDER=resend`). Switched via `_create_email_provider()` factory.
**Crypto:** `InMemoryCryptoService` — hash/verify, encrypt/decrypt, random tokens.

**Public API:**

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/auth/google/url` | Initiate Google OAuth flow |
| `GET /api/v1/auth/google/callback` | Handle Google OAuth callback |
| `POST /api/v1/auth/signup/email` | Begin email registration |
| `GET /api/v1/auth/signup/email/status` | Check registration status |
| `POST /api/v1/auth/signup/email/verify` | Verify email with token |
| `POST /api/v1/auth/signup/email/complete` | Complete registration with password |
| `POST /api/v1/auth/login` | Authenticate with email+password |
| `POST /api/v1/auth/refresh` | Rotate refresh token |
| `POST /api/v1/auth/logout` | Revoke session and refresh token family |
| `GET /api/v1/auth/sessions` | List active sessions |
| `POST /api/v1/auth/sessions/{id}/revoke` | Revoke specific session |

**AuthService** orchestrates 9 sub-services through `begin_registration()`, `login()`, `oauth_login()`, `refresh()`, `logout()`, `list_sessions()`, `revoke_session()`.

**Exception handler** in `main.py` maps `IdentityException` subclasses to HTTP 401/404/409/410/400 and records auth metrics.

### Onboarding Platform (`services/onboarding/` — 9 files)

**Purpose:** Guided user lifecycle state machine.

```
VISITOR → AUTHENTICATED → PROFILE_SETUP → WORKSPACE_SETUP →
PLAN_SELECTION → CHECKOUT_PENDING → SUBSCRIPTION_ACTIVE →
ONBOARDING_COMPLETE → ACTIVE
```

**Components:**
- `LifecycleService` — state machine with 9 states, 5 step IDs
- `OnboardingService` — wraps lifecycle, handles profile and workspace setup steps
- `PLAN_SELECTION`/`CHECKOUT_PENDING`/`SUBSCRIPTION_ACTIVE` steps have **no billing integration**

**Public API:**

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/onboarding` | Get current onboarding state |
| `POST /api/v1/onboarding/profile` | Complete profile setup step |
| `POST /api/v1/onboarding/workspace` | Create organization workspace |
| `POST /api/v1/onboarding/complete-step` | Advance to next lifecycle step |

### Organizations Platform (`services/organizations/` — 9 files)

**Purpose:** Multi-tenant organization management.

**Components:**
- `Organization` — name, slug, owner, soft-deletable
- `Membership` — user-org mapping with role (owner/admin/member), status (active/suspended/inactive)
- `Invitation` — invite by email, accept/revoke lifecycle
- `CurrentOrganizationResolver` — resolves a user's active org from request context

**Public API:** 15+ endpoints under `/api/v1/organizations` covering CRUD, member management, invitations, ownership transfer.

### Billing Platform (`services/billing/` — 12 files)

**Purpose:** Subscription billing with Stripe integration.

**Components:**
- **`PlanService`** — seeds 6 default plans (Starter/Pro/Enterprise × monthly/yearly)
- **`CustomerService`** — creates Stripe customer mapping per organization
- **`CheckoutService`** — creates Stripe checkout sessions with configurable trials
- **`SubscriptionService`** — cancel/resume subscription lifecycle
- **`WebhookService`** — processes Stripe webhooks: checkout completed, subscription created/updated/deleted, invoice paid/failed
- **`MockStripeBillingProvider`** — in-memory mock (default, no real Stripe calls)
- **`StripeBillingProvider`** — live Stripe SDK implementation (uses `import stripe`)

**Provider mode switching:**
- `BillingConfig.provider_mode = "mock"` (default) → `MockStripeBillingProvider`
- `BillingConfig.provider_mode = "live"` → `StripeBillingProvider` (requires STRIPE_SECRET_KEY)
- Selected via `create_billing_provider(config)` factory in `api.py`
- Env var `BILLING_PROVIDER_MODE` controls the mode in production

**Live StripeBillingProvider supports:**
- Customer creation via `stripe.Customer.create()`
- Checkout sessions via `stripe.checkout.Session.create()` (with trial support)
- Customer Portal via `stripe.billing_portal.Session.create()`
- Subscription retrieval via `stripe.Subscription.retrieve()`
- Subscription cancellation via `stripe.Subscription.modify()` (at_period_end) or `stripe.Subscription.delete()` (immediate)
- Subscription resumption via `stripe.Subscription.modify(cancel_at_period_end=False)`
- Webhook verification via `stripe.Webhook.construct_event()` with signature validation

**Webhook flow:**
1. Stripe sends event to `POST /api/v1/billing/webhooks/stripe`
2. `StripeBillingProvider.handle_webhook()` calls `stripe.Webhook.construct_event()` for signature verification
3. Known event types are returned as structured dicts with `event_id`, `event_type`, `provider_event_id`, `data`
4. Unknown event types are silently ignored
5. `WebhookService._process_single_event()` checks for duplicates via `BillingEventRepository.find_by_provider_event_id()`
6. Events are routed to domain handlers: `_handle_checkout_completed`, `_handle_subscription_*`, `_handle_invoice_*`

**Public API:**

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/billing/plans` | List available plans |
| GET | `/api/v1/billing/subscription` | Get organization's subscription |
| POST | `/api/v1/billing/checkout` | Create checkout session |
| POST | `/api/v1/billing/customer-portal` | Get Stripe Customer Portal URL |
| POST | `/api/v1/billing/cancel` | Cancel subscription |
| POST | `/api/v1/billing/resume` | Resume canceled subscription |
| POST | `/api/v1/billing/webhooks/stripe` | Receive Stripe webhook events |

**Key limitation:** All persistence is in-memory unless `REPOSITORY_PROVIDER=supabase` is set. Billing provider defaults to mock — set `BILLING_PROVIDER_MODE=live` and configure `STRIPE_SECRET_KEY` for real Stripe integration.

### Capability Platform (`services/capabilities/` — 9 files)

**Purpose:** Product feature abstraction layer — represents what a product can do, not what external service it integrates with.

**Seed capabilities:**

| Slug | Category | Default Enabled | Beta |
|---|---|---|---|
| memory | intelligence | Yes | No |
| gmail | communication | No | No |
| calendar | communication | No | No |
| drive | storage | No | Yes |
| slack | communication | No | Yes |
| github | developer | No | Yes |
| crm | sales | No | No |
| outreach | sales | No | No |
| research | intelligence | Yes | No |
| execution | infrastructure | Yes | No |

**Components:**
- `CapabilityDefinition` — slug, name, category, default_enabled, beta
- `OrganizationCapability` — per-org activation state with audit trail
- `CapabilityUsage` — tracks requests, executions, storage_bytes, api_calls
- `CapabilityLimits` — model exists, limits not enforced

**Service methods:** `register_capability`, `seed_capabilities`, `enable_capability`, `disable_capability`, `get_organization_capabilities`, `get_usage`, `increment_usage`, `reset_usage`, `validate_capability_exists`

**Public API:**

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/capabilities` | List all registered capabilities |
| GET | `/api/v1/organizations/{id}/capabilities` | Get org's capability states |
| POST | `/api/v1/organizations/{id}/capabilities/{slug}/enable` | Enable capability for org |
| POST | `/api/v1/organizations/{id}/capabilities/{slug}/disable` | Disable capability for org |
| GET | `/api/v1/organizations/{id}/capabilities/{slug}/usage` | Get usage for a capability |

**Restrictions explicitly not enforced:** billing plan gating, authorization checks.

---

## Execution & Planning Layer

### Execution Engine (`services/execution/` — 19 files)

**Purpose:** DAG-based async task execution engine. Full session lifecycle with scheduling, dispatch, retry, eventing, and metrics.

```
[Validated Plan]
     ↓
┌──────────────────────┐
│   ExecutionEngine     │
│  (execution_pipeline) │
│                       │
│  1. validate          │
│  2. create session    │
│  3. initialize DAG    │
│  4. EXECUTION LOOP    │
│     ├─ Scheduler      │  ← DAG dependency resolution
│     ├─ Dispatcher     │  ← Adapter resolution & invocation
│     ├─ StateMachine   │  ← Task/Session state transitions
│     ├─ Retry Engine   │  ← Exponential backoff + jitter
│     └─ EventBus       │  ← Pub/sub for observability
│  5. finalize          │
└──────────────────────┘
```

**Core components:**

| Component | File | Purpose |
|---|---|---|
| `StateMachine` | `state_machine.py` | 11×11 task states, 8×8 session states, explicit transition tables |
| `Scheduler` | `scheduler.py` | DAG scheduler: in-degree map, FIFO ready queue, concurrency (default 5), fail/skip cascade |
| `Dispatcher` | `dispatcher.py` | Resolves `TaskType` → `ExecutionAdapter`, dispatches execution |
| `AdapterRegistry` | `adapter_registry.py` | Thread-safe registry with priority resolution, introspection |
| `BridgeAdapter` | `bridge_adapter.py` | Wraps SDK adapters (Gmail, Calendar) into `ExecutionAdapter` interface |
| `EventBus` | `event_bus.py` | In-process pub/sub, thread-safe, subscriber isolation |
| `Validation` | `validation.py` | Pre-execution plan validation: cycles, dangling deps, payload integrity |
| `RecoveryManager` | `recovery_manager.py` | Crash recovery: fixes stuck states, rebuilds scheduler |
| `MetricsCollector` | `metrics_collector.py` | Passive event-driven metrics: sessions, tasks, retries, per-adapter timing |
| `CredentialFactory` | `credential_factory.py` | Per-user OAuth2 credential resolution with serialized token refresh |

**Session lifecycle states:** CREATED → VALIDATED → INITIALIZED → RUNNING → PAUSED/RESUMED → COMPLETED/FAILED/CANCELED

**Registered execution adapters** (from `main.py`):
- `GmailAdapter` — SEND_EMAIL task type
- `CalendarAdapter` — 5 calendar task types
- `ReplyAnalysisAdapter` — ANALYZE_REPLY task type
- `CrmAdapter` — 10 CRM task types
- `MemoryAdapter` — 6 memory task types

### Planner (`services/planner/` — 29 files)

**Purpose:** Transforms reasoning decisions into validated execution plans.

```
[Reasoning Decision]
     ↓
┌──────────────────────────┐
│    PlanningPipeline       │
│                           │
│  1. Goal Analysis         │
│  2. Strategy Selection    │  ← 17 strategies with best-match scoring
│  3. Task Generation       │
│  4. Dependency Resolution │
│  5. Scheduling            │  ← Trigger assignment, business hours
│  6. Branching             │  ← BRANCH/JOIN for conditional paths
│  7. Approval Annotation   │  ← Based on confidence/risk/strategy rules
│  8. Validation            │  ← Structural + scheduling + integrity
└───────────┬───────────────┘
            ↓
   [Validated Plan]
            ↓
   PlannerRouter.route()
            ↓
   ExecutionEngine.execute()
```

**17 implemented strategies:**

| Strategy | File | Purpose |
|---|---|---|
| `cold_outreach` | `strategies/cold_outreach.py` | First contact to new leads |
| `follow_up` | `strategies/follow_up.py` | Standard follow-up sequence |
| `follow_up_v2` | `strategies/follow_up_v2.py` | Enhanced follow-up with branching |
| `nurture` | `strategies/nurture.py` | Long-term lead nurturing |
| `re_engagement` | `strategies/re_engagement.py` | Re-activate cold leads |
| `demo_booking` | `strategies/demo_booking.py` | Schedule product demos |
| `booking` | `strategies/booking.py` | General meeting booking |
| `draft_revision` | `strategies/draft_revision.py` | Revise existing drafts |
| `escalation` | `strategies/escalation.py` | Escalate to human |
| `general_engagement` | `strategies/general_engagement.py` | Default fallback |
| `next_best_action` | `strategies/next_best_action.py` | Next action selection |
| `pricing_objection` | `strategies/pricing_objection.py` | Handle pricing objections |
| `opportunity_development` | `strategies/opportunity_development.py` | Develop existing opportunities |
| `memory_aware` | `strategies/memory_aware.py` | Context-aware from memory |
| `memory_nba` | `strategies/memory_nba.py` | Memory-driven next best action |
| `memory_outreach` | `strategies/memory_outreach.py` | Memory-driven outreach |
| `pipeline_outreach` | `strategies/pipeline_outreach.py` | Pipeline-specific outreach |

**Task types** (30+): SEND_EMAIL, DRAFT_REPLY, SCHEDULE_MEETING, CREATE_CONTACT, STORE_MEMORY, ANALYZE_REPLY, CALENDAR_LIST_EVENTS, ESCALATE_TO_HUMAN, WAIT_FOR_REPLY, NOTIFY, BRANCH, JOIN, and more.

---

## Adapter Ecosystem

### Invocation pattern

```
ExecutionEngine
  → Dispatcher.dispatch(task, context, resolver)
    → AdapterRegistry.resolve(task_type, context)
      → ExecutionAdapter.execute(context, task)
```

### Registered adapters

| Adapter | Path | Operations | Status |
|---|---|---|---|
| GmailAdapter | `adapters/google/gmail/` | 8: send, reply, draft, trash, untrash, modify_labels, get_thread, get_message | Production-ready |
| CalendarAdapter | `adapters/google/calendar/` | 5: list, get, create, update, delete | Production-ready |
| HttpAdapter | `adapters/http/` | 4 auth strategies, 3 serializers | Production-ready |
| CrmAdapter | `adapters/crm/` | 10: CRUD contacts, companies, opportunities, activities | Implemented |
| MemoryAdapter | `adapters/memory/` | 6: store, retrieve, search, update, delete, summarize | Implemented |
| ReplyAnalysisAdapter | `adapters/analysis/` | 1: classify email replies (10 categories) | Implemented |

### Infrastructure layers

| Component | Path | Purpose |
|---|---|---|
| Base adapter | `adapters/base_adapter.py` | `ExecutionAdapter` ABC with `execute()`, optional `validate()`, `shutdown()`, `compensate()` |
| Capability registry | `adapters/capability_registry.py` | Descriptor-based capability management |
| Capability descriptors | `adapters/capabilities.py` | 15+ capability categories (COMMUNICATION, CRM, SCHEDULING, etc.) |
| Credential registry | `adapters/credential_registry.py` | Descriptor-based credential management |
| Credential resolver | `adapters/credential_resolver.py` | Abstract `CredentialResolver` — no concrete implementation |
| Credential descriptors | `adapters/credentials.py` | 5 credential types (OAUTH2, API_KEY, BASIC_AUTH, etc.) |
| Adapter factory | `adapters/adapter_factory.py` | Lazy adapter instantiation |
| Adapter registration | `adapters/adapter_registration.py` | Registration workflow |
| Protocols | `adapters/protocols.py` | Type protocols for structural typing |
| Exceptions | `adapters/exceptions.py` | Adapter-specific exception hierarchy |
| Models | `adapters/models.py` | `AdapterResult`, `AdapterMetadata`, `AdapterContext` |
| Google API | `adapters/google/` | Shared Google infra: 7-service registry, error classification, pagination, URL building |

### Agent SDK (`services/agent_sdk/` + `services/agents/`)

5 concrete agents wrap adapter operations:
- `OutreachAgent` — send/reply/draft via GmailAdapter
- `ResearchAgent` — lead research operations
- `SchedulingAgent` — calendar operations
- `CrmAgent` — CRM operations
- `MemoryAgent` — memory operations

---

## AI / Intelligence Layer

### Three-Pipeline Architecture

```
[Raw Message]
     ↓
┌─────────────────────────────┐
│  IntelligencePipeline        │  ← understands
│  (services/conversation_    │
│   intelligence/)             │
│  • Intent extraction         │
│  • Entity extraction         │
│  • Buying signal detection   │
│  • Objection detection       │
│  • Memory extraction         │
│  • Health scoring (0-100)    │
│  • Summary (4 levels)        │
└───────────┬─────────────────┘
            ↓
   [ConversationIntelligence]
            ↓
┌─────────────────────────────┐
│  ReasoningPipeline           │  ← decides
│  (services/reasoning/)       │
│  • Goal selection            │
│  • Priority assessment       │
│  • Risk assessment           │
│  • Confidence assessment     │
│  • Policy evaluation         │
└───────────┬─────────────────┘
            ↓
      [ReasoningResult]
            ↓
┌─────────────────────────────┐
│  GenerationPipeline          │  ← generates
│  (services/reply_generation/)│
│  • Template selection        │
│  • Style selection           │
│  • Prompt building           │
│  • Provider invocation       │
│  • Validation (12 checks)    │
└───────────┬─────────────────┘
            ↓
       [Reply Draft]
```

**All extraction is deterministic** — pattern/regex-based, no LLM calls in the Intelligence pipeline. LLM calls occur only in `ReplyGeneration`.

### Knowledge Layer (`services/conversation_intelligence/knowledge/`)

13 data files centralizing business knowledge:

| File | Content |
|---|---|
| `buying_signals.py` | 15 signal definitions with keywords and weights |
| `companies.py` | Company name patterns and normalization |
| `budgets.py` | Budget range patterns |
| `timelines.py` | Timeline expression patterns |
| `meeting_patterns.py` | Meeting scheduling language |
| `patterns.py` | General conversation patterns |
| `titles.py` | Job title patterns and seniority levels |
| `technologies.py` | Technology name patterns |
| `objections.py` | Objection categories and patterns |
| `confidence.py` | Confidence scoring defaults |
| `scoring_config.py` | Health score weights and thresholds |
| `normalization.py` | Text normalization rules |
| `registry.py` | Singleton `KnowledgeRegistry` providing access |

### Supporting Intelligence

| Component | Path | Lines | Purpose |
|---|---|---|---|
| `reply_intelligence.py` | Legacy | 198 | 14-step monolithic function — being superseded by pipeline |
| `buying_signal.py` | Legacy | 39 | Thin wrapper delegating to knowledge layer |
| `lead_intelligence.py` | `services/intelligence/` | 337 | Fit score, buying stage, urgency, objection risk |
| `account_intelligence.py` | `services/intelligence/` | — | Account tier classification, buying intent |
| `contact_intelligence.py` | `services/intelligence/` | — | Decision authority, role relevance |
| `activity_intelligence.py` | `services/intelligence/` | — | Next activity suggestion, priority |

### Memory System (`services/memory/`)

8 memory types stored/retrieved/consolidated:

| Type | Key Fields |
|---|---|
| Account | company_id, industry, size, revenue |
| Contact | email, name, role, company_id |
| Conversation | conversation_id, participants, summary |
| Meeting | meeting_id, attendees, notes, decisions |
| Opportunity | opportunity_id, value, stage, close_date |
| Decision | decision_id, context, rationale |
| Preference | user_id, key, value |
| Outcome | outcome_id, type, result |

Memory is event-driven — `MemorySubscriber` listens on the execution engine's `EventBus` for `TASK_COMPLETED`/`SESSION_COMPLETED` events and persists memories automatically.

### Conversation Engine (`services/conversation_engine.py` — 1198 lines)

Shared multi-client orchestration for Telegram and Web interfaces. `handle_message()` is the main dispatcher:

```
handle_message(channel, external_user_id, text)
  → greetings check
  → field extraction (service, target, name, tone, length)
  → AI intent classification (classify_intent + classify_natural_action fallback)
  → lead selection
  → draft generation (via run_workflow)
  → refinement loop
  → send
```

**Key property:** `handle_message()` and `run_workflow()` are **synchronous** — async bridge via `ThreadPoolExecutor`.

---

## Communication & Outbound Layer

### Communication Providers (`services/communication/`)

| Component | Purpose |
|---|---|
| `provider_base.py` | Abstract `CommunicationProvider` |
| `provider_registry.py` | Provider class + instance registration |
| `gmail_provider.py` | Gmail API communication provider |
| `gmail_sync.py` | Inbox sync engine |
| `gmail_webhooks.py` | Gmail push notification handling |
| `communication_store.py` | Provider instance persistence |
| `provider_events.py` | Provider lifecycle events |
| `provider_models.py` | ProviderType (GMAIL, OUTLOOK, SLACK), ProviderStatus |
| `provider_normalizer.py` | Provider data normalization |

### Outbound System (`services/outbound/`)

```
Planner / Conversation Engine
     ↓
OutboundExecutor
     ↓
┌───────────────────────────────────────┐
│  OutboundRegistry (provider routing)   │
│       ↓                                │
│  GmailOutboundProvider                  │
│  (implements OutboundProviderBase)      │
│       ↓                                │
│  DraftStore (lifecycle + versions)      │
│  OutboundPersistence (send history)     │
└───────────────────────────────────────┘
     ↓
OutboundScheduler (polls every 15s)
```

**Key components:**

| Component | Purpose |
|---|---|
| `OutboundProviderBase` | ABC: create_draft, update_draft, send, schedule, cancel, get_status |
| `GmailOutboundProvider` | Real Gmail transport with OAuth, token refresh, MIME building |
| `DraftStore` | In-memory CRUD with approvals, version history, multi-index querying |
| `OutboundExecutor` | Single entry point: dispatches action types through provider chain |
| `OutboundScheduler` | Polls every 15s for due scheduled drafts |
| `OutboundPersistence` | Send history and delivery state |

**Draft states:** DRAFT → PENDING_APPROVAL → APPROVED/AUTO_APPROVED/REJECTED → SENDING/SENT/SCHEDULED/FAILED/CANCELLED/ARCHIVED

---

## Operational Infrastructure (`services/operations/`)

**Purpose:** Production readiness — health checks, observability, startup diagnostics, and configuration validation. This layer must never import business services.

**Components:**

| Component | File | Purpose |
|---|---|---|
| `RequestLoggingMiddleware` | `middleware.py` | Structured request logging (request_id, method, path, status, duration_ms) + structured error responses for unhandled exceptions |
| `operations_router` | `router.py` | Three operational endpoints (see below) |
| `startup_diagnostics()` | `diagnostics.py` | Single-call function logging app version, env, provider, routes count, startup duration |
| `validate_config()` | `diagnostics.py` | Checks required env vars based on current `RepositoryProvider` |

### Health Checks

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | GET | Liveness probe — always responds `{"status": "healthy"}` with no DB access |
| `/ready` | GET | Readiness probe — verifies DB connection, repository provider, config; returns 503 with `failures` list on failure |
| `/version` | GET | Application metadata — name, semver, git commit SHA, build timestamp, environment, repository provider |

Readiness response (healthy):

```json
{"status": "ready"}
```

Readiness response (unhealthy — HTTP 503):

```json
{
    "status": "unready",
    "failures": [
        "database_connection_failed: connection refused",
        "configuration_missing: SUPABASE_KEY"
    ]
}
```

### Observability

- **Request logging:** `RequestLoggingMiddleware` logs every request: `request_id=<id> method=<method> path=<path> status=<code> duration_ms=<ms>`
- **Error logging:** Unhandled exceptions log request_id, exception type, message, and stack trace — stack traces are never returned to the client
- **Structured error responses:** All unhandled exceptions return `{"error": {"code": "INTERNAL_ERROR", "message": "...", "request_id": "..."}}`
- **Request ID header:** Every response includes `X-Request-ID` header (8-character hex)

### Startup Diagnostics

On application startup, the lifespan callback calls `startup_diagnostics(app)` which logs:

```
============================================================
Loqi Backend Startup Diagnostics
============================================================
Application:      Loqi
Version:          0.2.0
Environment:      development
Repository:       in_memory
Commit:           0df76d3f3403
Build Timestamp:  2026-07-21T12:00:00.000000+00:00
Configuration issues:
  - OPENAI_API_KEY: OpenAI API key for AI generation (missing)
Routes:           42
Startup duration: 0.152s
============================================================
```

### Configuration Validation

On startup, `log_config_warnings()` validates required environment variables:

| Variable | Required When | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | Always | AI generation |
| `SUPABASE_URL` | `RepositoryProvider.SUPABASE` | DB connection |
| `SUPABASE_KEY` | `RepositoryProvider.SUPABASE` | DB authentication |

Missing variables produce warning logs. The `/ready` endpoint returns 503 with specific failure details.

---

## Infrastructure & Supporting Services

### Transactional Email (`services/email/` — new production infrastructure)

**EmailProvider** abstract base class at `services/identity/providers/email_provider.py` defines 7 email methods:

| Method | Purpose |
|---|---|
| `send_verification_email(to, verification_url)` | Email address verification (used by `AuthService.begin_registration()`) |
| `send_password_reset_email(to, reset_url)` | Password reset link |
| `send_organization_invitation(to, inviter_name, organization_name, accept_url)` | Invite user to org |
| `send_welcome_email(to, name)` | Post-registration welcome |
| `send_billing_receipt(to, recipient_name, amount, plan_name, invoice_url)` | Payment receipt |
| `send_subscription_cancelled(to, recipient_name, plan_name, effective_date)` | Subscription cancellation notice |
| `send_subscription_renewed(to, recipient_name, plan_name, amount, next_billing_date)` | Subscription renewal notice |

**Two implementations:**

| Provider | Mode | Description |
|---|---|---|
| `ConsoleEmailProvider` | `console` (default) | Prints to stdout — development/testing, no external calls |
| `ResendEmailProvider` | `resend` | Real transactional email via Resend API (requires `EMAIL_API_KEY`) |

**Configuration (`services/email/config.py:EmailConfig`):**

| Field | Env Var | Default | Purpose |
|---|---|---|---|
| `provider` | `EMAIL_PROVIDER` | `console` | `console` or `resend` |
| `api_key` | `EMAIL_API_KEY` | `""` | Resend API key |
| `from_email` | `EMAIL_FROM` | `noreply@loqi.ai` | Sender address |
| `from_name` | `EMAIL_FROM_NAME` | `Loqi` | Sender display name |
| `reply_to` | `EMAIL_REPLY_TO` | `""` | Reply-to address |
| `app_url` | `APP_URL` | `http://localhost:3000` | Base URL for email links |

**Provider switching:** `_create_email_provider(config)` factory in `services/identity/api.py` returns `ConsoleEmailProvider` when `config.provider == "console"` and `ResendEmailProvider` when `"resend"`.

**Template system:** `services/email/transactional_templates.py` — standalone render functions (no composer/renderer dependency). Each returns `TemplateResult(subject, html, plain_text)`:

| Function | Renders |
|---|---|
| `render_verification_email()` | "Verify your email" with CTA button |
| `render_password_reset_email()` | "Reset your password" with CTA button |
| `render_invitation_email()` | "You've been invited to {org}" with accept button |
| `render_welcome_email()` | Getting-started checklist |
| `render_billing_receipt_email()` | Receipt with plan/amount table |
| `render_subscription_cancelled_email()` | Cancellation notice with effective date |
| `render_subscription_renewed_email()` | Renewal details with next billing date |

All templates produce both HTML (responsive inline-styled) and plain text, with a shared `_base_html()` layout wrapper.

**Delivery logging:** `services/email/delivery_log.py` — structured `log_email_sent()` / `log_email_failed()` that log `request_id`, `recipient`, `template`, `provider`, `status`, `duration_ms` without exposing body, tokens, or API keys.

**Resend provider details:**
- Calls `resend.Emails.send()` via `asyncio.to_thread()` (SDK is synchronous)
- Sets `from: "{from_name} <{from_email}>"`, `to`, `subject`, `html`, `text`
- Passes `reply_to` when configured
- Attaches `tags` for Resend analytics (`name: "template", value: "{template_name}"`)
- All exceptions propagate (logged, not silently swallowed)

**Configuration validation:** `services/operations/diagnostics.py` validates `EMAIL_API_KEY`, `EMAIL_FROM`, `EMAIL_REPLY_TO` when `EMAIL_PROVIDER=resend`. Missing vars appear as warnings at startup and cause `/ready` to return 503.

### Email Composition (`services/email/` — existing outbound campaign engine)

Fluent builder pattern for email drafting:

```
DraftBuilder()
  .with_subject()
  .with_recipient()
  .with_body()
  .with_template("professional")
  .with_branding(company_brand)
  .with_attachment(file)
  .build()
```

6 HTML email templates: plain, professional, recruiting, newsletter, proposal, product_launch. Inline CSS, brand-aware headers/footers, preview text.

### Persistence Layer (`services/persistence/` — 9 files)

**Purpose:** Production-ready Supabase/PostgreSQL persistence replacing in-memory repositories.

**Components:**

| File | Purpose |
|---|---|
| `config.py` | `RepositoryProvider` enum: IN_MEMORY or SUPABASE. Global singleton with `get/set/reset` |
| `database.py` | `SupabaseConnectionManager` — lazy client creation from `SUPABASE_URL`/`SUPABASE_KEY` env vars |
| `base_repository.py` | `SupabaseRepository[T]` — generic async CRUD with upsert logic, datetime serialization, `get_type_hints`-resolved field mapping |

**Implemented repositories (Identity Platform — 5 of 10 interfaces, Organizations — 3 of 3, Billing — 6 of 6):**

| Repository | Table | Methods |
|---|---|---|
| `SupabaseUserRepository` | `users` | save, get, delete |
| `SupabaseSessionRepository` | `sessions` | save, get, delete, find_by_user_id, find_active_by_user_id, revoke_all_for_user, revoke_all_for_org, count_active_by_user_id |
| `SupabaseRefreshTokenRepository` | `refresh_tokens` | save, get, delete, find_active_by_session_id, find_by_family, find_by_hash, revoke_all_for_session, revoke_all_for_user, revoke_family |
| `SupabaseVerificationTokenRepository` | `verification_tokens` | save, get, delete, find_valid_by_target_and_purpose, find_by_target, find_by_hash, invalidate_all_for_target |
| `SupabasePasswordResetRepository` | `password_reset_requests` | save, get, delete, find_valid_by_user_id, invalidate_all_for_user |
| `SupabaseOrganizationRepository` | `organizations` | save, get, delete, find_by_slug, find_by_name, find_owned_by |
| `SupabaseMembershipRepository` | `memberships` | save, get, delete, find_by_user_and_org, find_by_org_id, find_by_user_id, count_owners, find_active_by_user_id |
| `SupabaseInvitationRepository` | `invitations` | save, get, delete, find_by_org_id, find_pending_by_email, find_by_token |
| `SupabasePlanRepository` | `billing_plans` | save, get, delete, find_by_code, list_active |
| `SupabaseCustomerRepository` | `billing_customers` | save, get, delete, find_by_organization_id, find_by_provider_customer_id |
| `SupabaseSubscriptionRepository` | `billing_subscriptions` | save, get, delete, find_by_organization_id, find_active_by_organization_id, find_by_provider_subscription_id |
| `SupabaseCheckoutRepository` | `billing_checkout_sessions` | save, get, delete, find_by_organization_id, find_by_provider_checkout_id |
| `SupabaseInvoiceRepository` | `billing_invoices` | save, get, delete, find_by_organization_id, find_by_provider_invoice_id |
| `SupabaseBillingEventRepository` | `billing_events` | save, get, delete, find_by_provider_event_id, find_by_idempotency_key |

**Mode switching:**

```python
from services.persistence.config import RepositoryProvider, set_repository_provider

set_repository_provider(RepositoryProvider.SUPABASE)  # → use Supabase repos
set_repository_provider(RepositoryProvider.IN_MEMORY)  # → use InMemory repos (default)
```

`services/identity/api.py`, `services/organizations/api.py`, and `services/billing/api.py` are aware of this switch — no service code changes required.

**Migrations:**

| File | Module | Tables |
|---|---|---|
| `001_identity_platform.sql` | Identity | users, email_identities, password_credentials, sessions, refresh_tokens, verification_tokens, password_reset_requests |
| `002_organizations.sql` | Organizations | organizations, memberships, invitations |
| `003_billing.sql` | Billing | billing_plans, billing_customers, billing_subscriptions, billing_checkout_sessions, billing_invoices, billing_events |

### Legacy Workflow System (`workflows.py`, `workflow_*` — 15+ files)

The legacy synchronous workflow system is being superseded by the Execution Engine. Key files:

| File | Purpose |
|---|---|
| `workflows.py` | Core orchestration — `run_workflow()`, `send_outreach()`, `_run_async()` bridge |
| `workflow_dispatcher.py` | Workflow dispatch |
| `workflow_executor.py` | Workflow execution |
| `workflow_planner.py` | Workflow planning |
| `workflow_runtime.py` | Runtime management |
| `workflow_recovery.py` | Crash recovery (separate from ExecutionEngine's RecoveryManager) |
| `workflow_scheduler.py` | Scheduling |
| `workflow_registry.py` | Workflow type registry |
| `workflow_models.py` | `WorkflowPlan`, planning models |
| `workflow_events.py` | Event logging |
| `workflow_progress.py` | Progress calculation |
| `workflow_locks.py` | Distributed locking |
| `workflow_persistence.py` | In-memory persistence |
| `workflow_retry.py` | Retry logic |
| `workflow_reasoner.py` | Workflow reasoning |

### Supporting Files

| File | Purpose |
|---|---|
| `services/ai.py` | OpenAI generation/personalization |
| `services/lead_provider.py` | Lead sourcing |
| `services/job_engine/` | Background job manager |
| `services/enrichment/` | Apollo + synthetic enrichers |
| `services/providers/` | Apollo + synthetic lead providers |
| `services/security/crypto/` | Encryption/hashing utilities |
| `services/supabase.py` | Supabase client (legacy — connection test only) |
| `services/persistence/` | Production persistence layer (M2.1 — Identity only) |
| `services/google_auth.py` | Google OAuth token exchange |
| `services/migration.py` | Data migration runner |

---

## Layer Dependencies

```
main.py
  ├── Identity Platform (self-wired, InMemory* repos)
  ├── Onboarding Platform (wired → OrganizationService)
  ├── Organization Platform (wired via register_deps)
  ├── Billing Platform (wired via register_deps)
  ├── Capability Platform (wired via register_deps)
  ├── ConversationEngine
  │     └── workflows.run_workflow (sync via ThreadPoolExecutor)
  │           ├── services.ai (OpenAI)
  │           ├── services.conversational_response_generator
  │           └── services.outbound.*
  ├── ExecutionEngine
  │     └── PlannerRouter
  │           └── PlanningPipeline
  │                 └── Strategy Registry (17 strategies)
  └── Adapters (registered on startup)
        ├── GmailAdapter → GoogleServiceRegistry → HttpAdapter
        ├── CalendarAdapter → GoogleServiceRegistry → HttpAdapter
        ├── CrmAdapter
        ├── MemoryAdapter → services.memory.memory_store
        └── ReplyAnalysisAdapter
```

---

## Test Coverage Map

| Test File | Module | Tests | Status |
|---|---|---|---|
| `test_identity_platform_p1.py` | Identity (models) | ~60 | ✅ |
| `test_identity_platform_p2.py` | Identity (services) | ~50 | ✅ |
| `test_billing_platform.py` | Billing | 82 | ✅ |
| `test_capability_platform.py` | Capabilities | 54 | ✅ |
| `test_execution_foundation.py` | Execution models/engine | ~100 | ✅ |
| `test_execution_dispatcher.py` | Dispatcher | ~80 | ✅ |
| `test_execution_scheduler.py` | Scheduler/state machine | ~80 | ✅ |
| `test_execution_adapter_registry.py` | Adapter registry | ~80 | ✅ |
| `test_execution_loop.py` | Full execution loop | ~80 | ✅ |
| `test_planner.py` | Planner pipeline | ~70 | ✅ |
| `test_planner_router.py` | Planner routing | ~57 | ✅ |
| `test_adapter_sdk.py` | Adapter SDK base | ~40 | ✅ |
| `test_adapter_registry_integration.py` | Full registry integration | ~50 | ✅ |
| `test_gmail_adapter.py` | Gmail adapter | ~60 | ✅ |
| `test_calendar_adapter.py` | Calendar adapter | ~40 | ✅ |
| `test_http_adapter.py` | HTTP adapter | ~60 | ✅ |
| `test_google_api_adapter.py` | Google API infra | ~50 | ✅ |
| `test_capability_system.py` | Capability descriptors | ~30 | ✅ |
| `test_credential_framework.py` | Credential descriptors | ~25 | ✅ |
| `test_email_composition_engine.py` | Email composition | varies | ✅ |
| `test_sales_intelligence.py` | Lead/account intelligence | varies | ✅ |
| `test_organizational_memory.py` | Memory system | varies | ✅ |
| `test_outbound_engine.py` | Outbound system | varies | ✅ |
| `test_email_infrastructure.py` | Email infrastructure | 33 | ✅ |
| `test_onboarding.py` | Onboarding | varies | ✅ |
| `test_organization_platform.py` | Organizations | varies | ✅ |
| `test_workflow_*.py` (3 files) | Legacy workflows | varies | ✅ |
| `test_auth_api.py` | Auth API | varies | ✅ |
| `test_copilot_api.py` | Copilot | varies | ✅ |
| `test_google_oauth.py` | Google OAuth | varies | ✅ |
| `test_multi_agent.py` | Agent SDK | varies | ✅ |
| `test_heterogeneous_execution.py` | Multi-adapter execution | varies | ✅ |
| `test_reasoner_integration.py` | Reasoner integration | varies | ✅ |
| `test_provider_layer.py` | Lead providers | varies | ✅ |
| `test_booking_strategy.py` | Booking strategy | varies | ✅ |
| `test_communication_intelligence.py` | Comm intelligence | varies | ✅ |
| `test_retry_engine.py` | Retry engine | varies | ✅ |
| `test_recovery_manager.py` | Recovery manager | varies | ✅ |
| `test_metrics_collector.py` | Metrics collector | varies | ✅ |
| `test_planner_router.py` | Planner router | varies | ✅ |
| `test_event_bus.py` | Event bus | varies | ✅ |
| `test_persistence.py` | Persistence layer | 30 | ✅ |

**Total: ~3500+ tests across 38+ test files**

---

## CI Pipeline

**File:** `.github/workflows/ci.yml`

**Trigger:** push/PR to `main`, `develop`, `feature/**`.

**Job:** `test` — single job, no deployment.

**Execution order:**

| Step | Action | Offline? |
|---|---|---|
| 1 | Checkout repository | Yes |
| 2 | Setup Python 3.12 with pip cache | Yes |
| 3 | Install dependencies from `requirements.txt` | Yes |
| 4 | Format check (black) — skipped if not configured | Yes |
| 5 | Import sort check (isort) — skipped if not configured | Yes |
| 6 | Lint (ruff or flake8) — skipped if not configured | Yes |
| 7 | Type check (mypy or pyright) — skipped if not configured | Yes |
| 8 | Validate migration directory structure and file naming | Yes |
| 9 | Run full test suite (`pytest`) with empty env vars | Yes |
| 10 | Upload pytest artifacts on failure | Yes |

**Quality gates (fail-fast):**
- Any test failure → pipeline red
- No secrets or external services required

**Expected runtime:** ~2–4 minutes (test suite: ~2 min, setup: ~1 min)
**Excluded tests (require Supabase):** `test_copilot_api.py`, `test_reasoner_integration.py`

### Test coverage gaps

- **AuthService orchestrator** — no direct unit tests (tested only through end-to-end lifecycle)
- **Identity API endpoints** — no HTTP-level tests
- **Conversation Intelligence Pipeline** — no dedicated test file (partial coverage via `test_communication_intelligence.py`)
- **Reasoning Engine** — no tests
- **Reply Generation Engine** — no tests
- **Conversation Engine** (1198 lines) — no tests
- **Onboarding Platform** — no dedicated test file
- **All platform API endpoints** — only billing has HTTP integration tests (`TestBillingAPI`)
