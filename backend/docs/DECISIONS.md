# Architecture Decision Records

This document collects the key architectural decisions present in the current codebase. Each ADR describes a decision, its context, consequences, and where it is implemented.

---

## ADR-0017 — Execution Engine over Legacy Workflow System

### Metadata

| Field | Value |
|---|---|
| **Version** | v1.0 |
| **Date** | 2026-07-19 |
| **Status** | **ACTIVE** |

### Context

The Loqi backend began with a synchronous workflow system (`workflows.py`, `workflow_executor.py`, `workflow_scheduler.py`, and 12+ supporting files). This system had several limitations:

- **Synchronous execution** — `run_workflow()` blocks until completion, requiring `ThreadPoolExecutor._run_async()` bridge for async callers
- **No DAG support** — workflows are linear sequences, no parallel or conditional task execution
- **No state machine** — task states inferred from workflow status, no explicit transition validation
- **No event bus** — observability via ad-hoc logging, no subscriber pattern
- **No retry engine** — failure handling is manual
- **No recovery** — no mechanism to resume workflows after crash

### Decision

Build a new **Execution Engine** (`services/execution/`) as the primary task execution substrate:

```
Legacy:  handle_message() → run_workflow() → send_outreach()  [sync, linear]
New:     PlannerRouter.route() → ExecutionEngine.execute()  [async, DAG]
```

Key design choices:

- **DAG-based scheduling** — tasks express dependencies explicitly; scheduler resolves execution order from in-degree map
- **Formal state machine** — 11 task states (IDLE → READY → RUNNING → COMPLETED/FAILED, etc.) with explicit transition tables at `services/execution/state_machine.py`
- **8 session states** — CREATED → VALIDATED → INITIALIZED → RUNNING → PAUSED/RESUMED → COMPLETED/FAILED/CANCELED, with legal transitions enforced
- **Thread-safe adapter registry** — priority-based resolution, introspection, unregistration
- **Pub/sub event bus** — `EventBus` at `services/execution/event_bus.py` with subscriber isolation
- **Retry engine** — exponential backoff with jitter, configurable per-task `RetryPolicy`
- **Recovery manager** — validates session integrity on startup, fixes crashed states (RUNNING→READY, RETRYING→WAITING)
- **Bridge adapter pattern** — SDK adapters (Gmail, Calendar, etc.) are wrapped via `BridgeAdapter` with action mapping and credential factory injection

### Consequences

**Positive:**
- Full async execution with DAG scheduling, parallel tasks, conditional branching
- Observable via EventBus (logging subscriber, metrics collector, memory subscriber)
- Crash recovery built in
- Retry engine eliminates manual failure handling
- 420+ tests covering all execution paths

**Negative:**
- Two execution systems coexist — legacy workflows still used by `conversation_engine.py`
- Bridge adapter pattern adds indirection between SDK adapters and execution engine
- All adapter registrations happen in `main.py` (3400-line file), increasing startup complexity

### Implementation

- Execution engine: `services/execution/` (19 files)
- Bridge adapters registered in `main.py:_register_execution_adapters()`
- Planner router bridges planning to execution: `services/planner/planner_router.py`
- ADR-0010 declares the execution platform stable

---

## ADR-0018 — Capability Platform: Product Features over Provider Integrations

### Metadata

| Field | Value |
|---|---|
| **Version** | v1.0 |
| **Date** | 2026-07-20 |
| **Status** | **ACTIVE** |

### Context

As the product grew, it became necessary to define what features an organization has access to independently of which external service provides them. For example, "Email" is a product capability — it could be backed by Gmail, Outlook, or a custom SMTP server. Similarly, "Calendar" is a capability that could be backed by Google Calendar or Outlook Calendar.

Without this abstraction, access control would be tightly coupled to specific provider integrations, making it impossible to:
- Grant a feature before the user connects a provider
- Swap providers without changing permission models
- Meter usage independently of provider API costs

### Decision

Create a **Capability Platform** (`services/capabilities/`) where capabilities represent **product features**, not external integrations.

```
CapabilityDefinition { slug, name, category, description, default_enabled, beta }
    ↓
OrganizationCapability { organization_id, capability_slug, enabled, activated_at, activated_by }
    ↓
CapabilityUsage { requests, executions, storage_bytes, api_calls, last_reset }
    ↓
CapabilityLimits { max_requests, max_executions, max_storage_bytes, max_api_calls }
```

Seed capabilities (defined in `services/capabilities/config.py`):

| Slug | Category | Default | Description |
|---|---|---|---|
| memory | intelligence | Enabled | Conversation memory and recall |
| research | intelligence | Enabled | Lead and company research |
| execution | infrastructure | Enabled | Workflow execution engine |
| gmail | communication | Disabled | Gmail email integration |
| calendar | communication | Disabled | Google Calendar integration |
| crm | sales | Disabled | CRM contact and opportunity management |
| outreach | sales | Disabled | Sales outreach automation |
| drive | storage | Disabled (beta) | Google Drive integration |
| slack | communication | Disabled (beta) | Slack messaging integration |
| github | developer | Disabled (beta) | GitHub repository integration |

Key design constraints:

- **Billing plan restrictions are NOT enforced** in this layer — that belongs to a future Billing→Capability gating layer
- **Authorization checks are NOT implemented** in this layer — that belongs to the auth/RBAC layer
- **CapabilityLimits model exists but is not enforced** — reserved for future metering

### Consequences

**Positive:**
- Clean separation between product features and provider integrations
- Default-enabled capabilities (memory, research, execution) are available immediately for every org
- Usage tracking is independent of billing — enables future metering without coupling
- 54 tests covering all service operations

**Negative:**
- No enforcement yet — capabilities can be registered/used with no checks
- No persistence — all data is in-memory
- No integration with Billing platform (capability gating by plan tier)

### Implementation

- `services/capabilities/` (9 files)
- Wired in `main.py` via `register_capability_deps(CapabilityDeps(...))`
- ADR-0016 defines the conceptual architecture

---

## ADR-0019 — Repository Pattern and Dependency Inversion

### Metadata

| Field | Value |
|---|---|
| **Version** | v1.0 |
| **Date** | 2026-07-19 |
| **Status** | **ACTIVE** |

### Context

Every platform module (Identity, Billing, Capabilities, Organizations, Onboarding) needs to persist data. The codebase currently uses in-memory storage for all modules, but the long-term persistence target is Supabase (PostgreSQL). The data access code must be swappable without modifying business logic.

### Decision

Use the **Repository pattern** with **dependency inversion** throughout:

```
┌──────────────────────┐       ┌──────────────────────┐
│   Service Layer      │       │   Repository (ABC)    │
│   (business logic)   │──────▶│   (abstract contract) │
│                      │       │                       │
│   services.py        │       │   repositories.py     │
└──────────────────────┘       └───────────┬───────────┘
                                           │
                              ┌────────────┼────────────┐
                              ▼            ▼            ▼
                      ┌────────────┐ ┌────────────┐ ┌────────────┐
                      │ InMemory*  │ │ Supabase*  │ │  TestMock  │
                      │ (current)  │ │ (future)   │ │  (tests)   │
                      └────────────┘ └────────────┘ └────────────┘
```

Each repository interface extends a common `Repository[T]` base:

```python
class Repository(ABC, Generic[T]):
    @abstractmethod
    async def save(self, entity: T) -> T: ...
    @abstractmethod
    async def get(self, entity_id: str) -> T | None: ...
    @abstractmethod
    async def delete(self, entity_id: str) -> bool: ...
```

Platform-specific query methods are added to each sub-interface. For example:

```python
class CustomerRepository(Repository[Customer], ABC):
    @abstractmethod
    async def find_by_organization_id(self, organization_id: str) -> Customer | None: ...
    @abstractmethod
    async def find_by_provider_customer_id(self, provider_customer_id: str) -> Customer | None: ...
```

Services receive repositories via constructor injection:

```python
class CustomerService:
    def __init__(self, customer_repo: CustomerRepository, provider: BillingProvider) -> None:
        self._customer_repo = customer_repo
        self._provider = provider
```

### Consequences

**Positive:**
- Services are testable — inject mock repositories without touching business logic
- All 1300+ tests use `InMemory*` repositories, proving the pattern works
- Adding Supabase persistence requires only new repository classes — zero service changes
- Consistent pattern across all 6 platform modules

**Negative:**
- No Supabase repository implementations exist yet — all data is volatile
- `InMemory*Repository` implementations use `dict` stores with O(n) lookups — not suitable for production
- In-memory repositories do not enforce unique constraints (e.g., duplicate email registration)

### Implementation

Applied in every platform module:

| Module | Repository Interfaces | InMemory Implementations |
|---|---|---|
| Identity | 10 | 10 |
| Billing | 6 | 6 |
| Capabilities | 4 | 4 |
| Organizations | 3 | 3 |
| Onboarding | 2 | 2 |

---

## ADR-0020 — Event-Driven Domain Model

### Metadata

| Field | Value |
|---|---|
| **Version** | v1.0 |
| **Date** | 2026-07-19 |
| **Status** | **ACTIVE** |

### Context

Business operations in multiple platform modules produce side effects that other modules need to react to:

- A customer created in Billing → update Capabilities
- An organization activated → trigger onboarding step transition
- A subscription canceled → disable premium capabilities
- A session revoked → invalidate all tokens
- A payment succeeded → extend subscription period

Without events, these cross-module reactions require either direct coupling (Billing imports Capabilities) or polling (periodically check for changes).

### Decision

Adopt an **event-driven domain model** where services collect domain events that can be published to interested subscribers.

Each service has:

```python
class CustomerService:
    def __init__(self, ...):
        self._events: list[BillingDomainEvent] = []

    @property
    def events(self) -> list[BillingDomainEvent]:
        return list(self._events)

    def clear_events(self) -> None:
        self._events.clear()
```

Events are created through typed factory methods:

```python
self._events.append(
    BillingDomainEvent.customer_created(customer.id, organization_id, provider_name)
)
```

Each platform module defines its own event types and event dataclass:

| Module | Event Type Enum | Events |
|---|---|---|
| Identity | `IdentityEventType` (15) | UserCreated, EmailVerified, LoggedIn, SessionRevoked, etc. |
| Billing | `BillingEventType` (10) | CustomerCreated, CheckoutStarted, SubscriptionCancelled, PaymentFailed, etc. |
| Capabilities | `CapabilityEventType` (5) | CapabilityRegistered, CapabilityEnabled, CapabilityDisabled, UsageIncremented, UsageReset |
| Organizations | `OrgEventType` (11) | OrgCreated, MemberAdded, InvitationAccepted, OwnershipTransferred, etc. |
| Onboarding | `OnboardingEventType` (8) | OnboardingStarted, StepCompleted, OnboardingCompleted, etc. |
| Execution | `ExecutionEventType` (22) | SessionCreated, TaskCompleted, TaskFailed, SessionCompleted, etc. |

### Consequences

**Positive:**
- Events are explicitly typed and structured — not stringly-typed JSON blobs
- Factory methods ensure consistent event construction
- Events are testable — services expose `.events` for assertion
- The execution engine's `EventBus` provides a working pub/sub implementation that can be reused

**Negative:**
- **Events are not published.** Services collect events in memory, but there is no mechanism to dispatch them to other modules or persist them. Cross-domain reactions require manual wiring.
- The pattern is inconsistent — execution engine uses `EventBus`, platform modules use `.events` property
- No event envelope standard — each module invents its own
- No event persistence — all events are lost after the request cycle
- The `.events` list is mutable state on the service instance — requires `clear_events()` to prevent memory leaks

### Implementation

- Platform domain events: `services/*/events.py` in each platform module
- Execution engine events: `services/execution/event_bus.py`
- Memory subscriber: `services/memory/subscriber.py` (the one real subscriber, on ExecutionEventBus)
- Metrics subscriber: `services/execution/metrics_collector.py` (on ExecutionEventBus)
- Logging subscriber: `services/execution/logging_subscriber.py` (on ExecutionEventBus)

---

## ADR-0021 — Adapter SDK Abstraction

### Metadata

| Field | Value |
|---|---|
| **Version** | v1.0 |
| **Date** | 2026-07-19 |
| **Status** | **STABLE** |

### Context

The backend integrates with multiple external services (Google Gmail, Google Calendar, HTTP APIs, CRM systems, etc.). Each integration requires:
- Authentication and credential management
- Request/response serialization
- Error handling and classification
- Retry and backoff
- Operation-specific logic

Early code had ad-hoc integrations with inconsistent patterns (some used raw `httpx`, others used Google client libraries, error handling was per-integration).

### Decision

Build a layered **Adapter SDK** (`services/adapters/`) with clear abstractions:

```
┌─────────────────────────────────────────────┐
│            ExecutionAdapter (ABC)            │
│  execute(context, task) → TaskResult         │
│  validate(context, task) → ValidationResult  │
│  shutdown()                                   │
│  compensate(context, task)                    │
├─────────────────────────────────────────────┤
│               BridgeAdapter                   │
│  Wraps SDK adapters into ExecutionAdapter     │
│  Routes actions via action_mapping            │
│  Injects credentials via factory              │
├─────────────────────────────────────────────┤
│         SDK Adapters (stateless)              │
│  GmailAdapter  │  CalendarAdapter             │
│  CrmAdapter    │  MemoryAdapter               │
│  HttpAdapter   │  ReplyAnalysisAdapter        │
├─────────────────────────────────────────────┤
│            Infrastructure Layer               │
│  AdapterRegistry  │  AdapterFactory           │
│  CapabilityRegistry │  CredentialRegistry     │
│  CredentialResolver (abstract)                │
├─────────────────────────────────────────────┤
│            Transport Layer                    │
│  HttpxTransport │  Auth strategies            │
│  Serializers    │  Validators                 │
└─────────────────────────────────────────────┘
```

Key design rules (enforced by tests in `test_adapter_sdk.py`):

1. **Adapters are stateless** — no shared mutable state between invocations. Fresh instances from `AdapterFactory`.
2. **No `services.execution` imports in adapter code** — adapters must be usable independently of the execution engine. Enforced by `test_self_containment`.
3. **No retry, caching, or circuit-breaking in adapters** — reliability concerns belong to the execution engine's retry policy.
4. **`AdapterContext` is immutable** — uses `frozenset` for enforcement.
5. **Credentials are descriptors, not values** — `CredentialDescriptor` defines what a credential looks like; actual values are resolved at runtime via `CredentialResolver`.

### Consequences

**Positive:**
- 6 adapters share common infrastructure (auth, serialization, error classification)
- Adapters are independently testable — 350+ adapter tests
- New adapters can be added by implementing `ExecutionAdapter` and registering with `AdapterRegistry`
- Bridge adapter pattern enables SDK adapters to be used directly by other services without the execution engine

**Negative:**
- `CredentialResolver` remains abstract — no concrete implementation for any provider
- The two-registry system (adapter registry + capability registry + credential registry) adds complexity
- Some adapters (CRM, Memory) delegate to in-memory stores rather than real services

### Implementation

- `services/adapters/` (46+ files across 8 subdirectories)
- Registered in `main.py:_register_execution_adapters()`
- Test files: `test_adapter_sdk.py`, `test_adapter_registry_integration.py`, `test_gmail_adapter.py`, `test_calendar_adapter.py`, `test_http_adapter.py`, `test_google_api_adapter.py`, `test_capability_system.py`, `test_credential_framework.py`

---

## ADR-0022 — Three-Pipeline AI Architecture

### Metadata

| Field | Value |
|---|---|
| **Version** | v1.0 |
| **Date** | 2026-07-19 |
| **Status** | **ACTIVE** |

### Context

The original AI processing path was a single monolithic function (`reply_intelligence.py`) that ran 14 sequential steps:

```
analyze_message():
  1. intent detection
  2. buying signal detection
  3. stage classification
  4. follow-up recommendation
  5. summary generation
  6. top objection
  7. decision confidence
  8. urgency
  9. memory update
  10. timeline events
  11. key risks
  12. key opportunities
  13. workflow objective mapping
  14. human approval flag
```

This had several problems:
- All 14 steps run every time, even if only some are needed
- Steps are tightly coupled — one failure can block the entire chain
- No separation between understanding (what happened?), deciding (what to do?), and generating (how to say it?)
- LLM calls and deterministic logic are mixed

### Decision

Split AI processing into three independent pipelines:

```
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│  Intelligence    │    │   Reasoning      │    │   Generation     │
│  Pipeline        │───▶│   Pipeline       │───▶│   Pipeline       │
│                  │    │                  │    │                  │
│  Understands     │    │  Decides         │    │  Generates       │
│                  │    │                  │    │                  │
│  • Intent        │    │  • Goal          │    │  • Template      │
│  • Entities      │    │  • Priority      │    │  • Style         │
│  • Buying signal │    │  • Risk          │    │  • Prompt        │
│  • Objections    │    │  • Confidence    │    │  • LLM call      │
│  • Memory        │    │  • Policy gate   │    │  • Validation    │
│  • Health score  │    │                  │    │                  │
│  • Summary       │    │                  │    │                  │
└──────────────────┘    └──────────────────┘    └──────────────────┘
      deterministic           deterministic           LLM-powered
      (patterns/regex)        (score/threshold)       (4 providers)
```

Key design properties:

- **IntelligencePipeline** (`services/conversation_intelligence/`) — all deterministic, pattern/regex-based extraction. All business knowledge centralized in `knowledge/` subpackage. Each analyzer runs independently — partial results preserved if one fails.
- **ReasoningPipeline** (`services/reasoning/`) — deterministic decision-making from structured intelligence. Stage-based: goal → priority → risk → confidence → decision → policy. Policies are runtime-registrable and can override decisions (e.g., force `REQUEST_HUMAN_REVIEW`).
- **GenerationPipeline** (`services/reply_generation/`) — LLM-powered reply generation with provider abstraction (OpenAI, Anthropic, Gemini, DeepSeek). Auto-discovery with graceful fallback. 9 writing styles, 10 templates, 12 validation checks.

### Consequences

**Positive:**
- Clear separation of concerns — understanding, deciding, and generating are independently testable
- Deterministic pipelines are fast and testable (no LLM calls)
- Provider abstraction enables swapping LLM backends without changing prompt logic
- Knowledge is centralized and versionable in `knowledge/` subpackage
- Partial results preserved in IntelligencePipeline

**Negative:**
- No tests for Reasoning or Reply Generation pipelines
- Legacy `reply_intelligence.py` still exists and is used by `conversation_engine.py`
- The three pipelines are only partially wired — no orchestration layer connects them in production
- Knowledge layer is Python files, not externalized to YAML/JSON/DB

### Implementation

- Intelligence: `services/conversation_intelligence/` (11 files + 13 knowledge files)
- Reasoning: `services/reasoning/` (7 files)
- Generation: `services/reply_generation/` (10 files + 5 provider files)
- Legacy: `services/reply_intelligence.py` (198 lines)

---

## ADR-0023 — In-Memory Persistence as Development Substrate

### Metadata

| Field | Value |
|---|---|
| **Version** | v1.0 |
| **Date** | 2026-07-19 |
| **Status** | **ACTIVE** |

### Context

Every platform module requires persistence, but the production database (Supabase/PostgreSQL) schema and migrations have not been defined. Building production persistence before the domain models stabilize would create costly rework.

### Decision

Use **in-memory persistence** (`InMemory*Repository`) for all platform modules during development:

```
Repository (ABC)  ←  domain contract
     ↑                    ↑
     │                    │
InMemory*Repo  ──────  Supabase*Repo  (planned)
(dev/fast)             (production)
```

The pattern:
- Every repository interface has an `InMemory*` implementation using `dict` storage
- Services are wired with `InMemory*` repositories in `main.py`
- Tests use `InMemory*` repositories exclusively
- No platform module has a working Supabase/PostgreSQL repository

### Consequences

**Positive:**
- Fast iteration — no schema migrations, no database setup, no connection management
- All 1300+ tests run in milliseconds with zero external dependencies
- Domain models and services can evolve freely without persistence constraints
- Clean target for M2.1 — implementing Supabase repositories requires no service changes

**Negative:**
- **All data is lost on restart** — every platform module has volatile storage
- No unique constraint enforcement — duplicate emails, duplicate slugs, etc. are possible
- No query optimization — all lookups are O(n) scans
- In-memory state is shared across requests in the same process — no isolation guarantees
- The platform modules cannot be deployed to production in their current state

### Implementation

Every platform module uses in-memory repositories:

| Module | InMemory Classes | Data Loss Risk |
|---|---|---|
| Identity | 10 (5 migrated to Supabase via M2.1) | User, Session, RefreshToken, VerificationToken, PasswordReset persist across restarts. Remaining 5 still InMemory |
| Billing | 6 | All customers, subscriptions, invoices lost |
| Capabilities | 4 | All capability states and usage data lost |
| Organizations | 3 | All orgs, memberships, invitations lost |
| Onboarding | 2 | All onboarding sessions lost |

The Identity platform now has Supabase persistence for 5 of 10 repository interfaces via M2.1 (`services/persistence/`).

---

## ADR-0024 — Global Mutable Dependency Registry

### Metadata

| Field | Value |
|---|---|
| **Version** | v1.0 |
| **Date** | 2026-07-19 |
| **Status** | **ACTIVE** |

### Context

Platform modules need access to service instances from their API routes. FastAPI typically uses `Depends()` with factory functions that instantiate dependencies per-request. However, the platform services are long-lived singletons (in-memory state must persist across requests), and their wiring in `main.py` is complex.

### Decision

Use a **global mutable registry** pattern for dependency injection:

```python
# In api.py:
_deps_registry: BillingDeps | None = None

def register_deps(deps: BillingDeps) -> None:
    global _deps_registry
    _deps_registry = deps

async def _get_plan_service() -> PlanService:
    if _deps_registry is None:
        raise HTTPException(status_code=500, detail="Billing services not initialized")
    return _deps_registry.plan_service
```

Wiring in `main.py`:

```python
# Instantiate services
_billing_plan_svc = PlanService(_billing_plan_repo, _billing_config)
# ... more services ...

# Register in global
register_billing_deps(BillingDeps(
    plan_service=_billing_plan_svc,
    customer_service=_billing_customer_svc,
    # ...
))
```

Route handlers use FastAPI's `Depends`:

```python
@router.get("/plans")
async def list_plans(
    plan_service: PlanService = Depends(_get_plan_service),
):
    ...
```

### Consequences

**Positive:**
- Simple wiring — dependencies are set once at startup
- Fast — no per-request instantiation overhead
- Works with existing FastAPI patterns — `Depends()` is used normally
- Testable — tests can call `register_deps()` with mock services

**Negative:**
- Global mutable state — thread safety depends on single-threaded startup
- No request-scoped dependencies — every request shares the same instances
- No lifecycle management — services are never cleaned up or recreated
- Error-prone — `register_deps()` must be called before any request, or endpoints return 500
- Test isolation requires careful `registger_deps()` ordering or `dependency_overrides`

### Implementation

| Module | Registry Type | File |
|---|---|---|
| Billing | `BillingDeps` | `services/billing/api.py` |
| Capabilities | `CapabilityDeps` | `services/capabilities/api.py` |
| Organizations | `OrgDeps` | `services/organizations/api.py` |
| Identity | `_auth_service` (module-level singleton) | `services/identity/api.py` |
| Onboarding | `set_onboarding_service()` | `services/onboarding/api.py` |

---

## ADR-0027 — Configurable Billing Provider with Dual Mock/Live Implementations

### Metadata

| Field | Value |
|---|---|
| **Version** | v1.0 |
| **Date** | 2026-07-21 |
| **Status** | **ACTIVE** |

### Context

The billing platform depends on a `BillingProvider` abstraction (ADR-0019) that wraps Stripe API calls. The original implementation (`StripeBillingProvider`) was an in-memory mock — no real Stripe SDK calls, suitable for development and testing but incapable of processing real payments.

To support production deployments, a real Stripe SDK implementation is needed. However, the mock must be preserved for:
- Local development without Stripe credentials
- CI/CD pipeline where no secrets are available
- Unit tests that must run offline

### Decision

Rename the original mock to `MockStripeBillingProvider` and create a new `StripeBillingProvider` that uses the `stripe` Python SDK. Switch between them via a `provider_mode` field in `BillingConfig`:

```
BillingConfig.provider_mode = "mock" (default)
  → MockStripeBillingProvider (in-memory, no external calls)

BillingConfig.provider_mode = "live"
  → StripeBillingProvider (real Stripe SDK, requires credentials)
```

Selection happens through a factory function:

```python
def create_billing_provider(config: BillingConfig) -> BillingProvider:
    if config.provider_mode == "live":
        return StripeBillingProvider(config)
    return MockStripeBillingProvider(config)
```

Configuration is driven by environment variables:

| Env Var | Affects | Required When |
|---|---|---|
| `BILLING_PROVIDER_MODE` | Provider selection (`mock`/`live`) | Always (default: `mock`) |
| `STRIPE_SECRET_KEY` | Live provider API auth | `BILLING_PROVIDER_MODE=live` |
| `STRIPE_WEBHOOK_SECRET` | Live webhook signature verification | `BILLING_PROVIDER_MODE=live` |
| `STRIPE_PUBLISHABLE_KEY` | Client-side Stripe integration | `BILLING_PROVIDER_MODE=live` |

The `StripeBillingProvider` maps the 8 abstract `BillingProvider` methods to Stripe SDK calls:

| Provider Method | Stripe SDK Call |
|---|---|
| `create_customer` | `stripe.Customer.create()` |
| `create_checkout_session` | `stripe.checkout.Session.create()` |
| `create_customer_portal` | `stripe.billing_portal.Session.create()` |
| `get_subscription` | `stripe.Subscription.retrieve()` |
| `cancel_subscription` | `stripe.Subscription.modify()` (at_period_end) or `stripe.Subscription.delete()` (immediate) |
| `resume_subscription` | `stripe.Subscription.modify(cancel_at_period_end=False)` |
| `handle_webhook` | `stripe.Webhook.construct_event()` |

All Stripe SDK exceptions are caught and re-raised as `ProviderError` for consistent error handling. Webhook signature verification uses Stripe's own `construct_event` which validates both the signature and timestamp.

### Consequences

**Positive:**
- Production-ready billing with real Stripe API calls
- Development and CI continue to work with mock mode (no credentials needed)
- No business logic changes — both providers implement the same `BillingProvider` interface
- Configuration validation at startup warns if live mode is selected without credentials
- Existing test suite unchanged (uses mock provider); 16 new tests cover live provider with mocked SDK
- All Stripe errors are mapped to `ProviderError`, preserving the existing HTTP error map (502 Bad Gateway)

**Negative:**
- Two provider implementations must be maintained
- Live provider tests mock `import stripe` via `sys.modules` patching (brittle if import structure changes)
- The `stripe` Python package is always installed even in mock-only deployments
- No automated fallback — if live provider fails, there is no mechanism to degrade to mock

### Implementation

- `MockStripeBillingProvider` in `services/billing/stripe_provider.py`
- `StripeBillingProvider` in `services/billing/stripe_provider.py`
- Factory `create_billing_provider()` in `services/billing/api.py`
- Wiring in `main.py` reads env vars and passes to `BillingConfig`
- Config validation in `services/operations/diagnostics.py`
- Tests: `test_billing_platform.py:TestStripeBillingProvider` (16 tests)

---

## ADR-0026 — Operational Endpoints are Infrastructure Concerns

### Metadata

| Field | Value |
|---|---|
| **Version** | v1.0 |
| **Date** | 2026-07-21 |
| **Status** | **ACTIVE** |

### Context

The application needs health checks, readiness probes, and observability infrastructure for production deployment. These concerns are cross-cutting — they don't belong to any single business module (Identity, Organizations, Billing, etc.). Placing them inside a business module would violate separation of concerns and create unnecessary dependencies.

### Decision

Create a dedicated `services/operations/` module for all operational infrastructure:

```
services/operations/
    __init__.py       — Exports
    router.py         — /health, /ready, /version endpoints
    middleware.py     — RequestLoggingMiddleware (structured logging, error handling)
    diagnostics.py    — Startup diagnostics, configuration validation
```

Key design rules:

1. **`services/operations/` must never import business services.** No references to Identity, Organizations, Billing, Capabilities, Execution Engine, or any adapter. The only cross-module import is `services.persistence.config.get_repository_provider()` (a config enum, no business logic).

2. **Endpoints registered directly on the root app** — no `/api/v1` prefix. These are infrastructure endpoints, not business APIs.

3. **The RequestLoggingMiddleware uses `BaseHTTPMiddleware`** — captures all requests including those that raise exceptions. Unhandled exceptions are caught, logged with full traceback, and returned as structured JSON without exposing internals.

4. **Configuration validation is advisory at startup** — missing variables produce warning logs but do not crash the application. The `/ready` endpoint provides a formal health gate.

5. **Build metadata (git commit, timestamp) is captured at module import time** — `_read_commit()` is called once when the module loads, not on every request.

### Consequences

**Positive:**
- Clear ownership — operational concerns are in one place
- No risk of circular imports — the module explicitly avoids business services
- Easy to test — standalone FastAPI app with only the operations router
- Middleware applies to all routes including business modules
- Readiness endpoint provides a single source of truth for deployment health

**Negative:**
- The middleware catches all exceptions, which may mask bugs in business middleware
- Build metadata is frozen at import time — won't reflect hot-reloads
- Configuration validation duplicates env var checks that individual modules may also perform

### Implementation

- `services/operations/` (4 files)
- Registered in `main.py` via `app.add_middleware()` and `app.include_router()`
- Tests: `tests/test_operations.py` (23 tests)

---

## ADR-0025 — Supabase Persistence as Repository Implementation

### Metadata

| Field | Value |
|---|---|
| **Version** | v1.0 |
| **Date** | 2026-07-20 |
| **Status** | **ACTIVE** |

### Context

ADR-0019 established the Repository pattern with dependency inversion. All platform modules use in-memory repositories (ADR-0023). To move toward production readiness, in-memory repositories must be replaced with persistent storage. The production target is Supabase PostgreSQL.

The existing `services/supabase.py` provides a thin wrapper around the Supabase Python SDK (`supabase.Client`) but is tightly coupled to the Telegram bot user/lead/conversation schema, not the platform domain models.

### Decision

Create a dedicated persistence layer at `services/persistence/` that implements the existing repository interfaces using the Supabase Python SDK:

```
┌──────────────────────────────────────────────┐
│              Persistence Layer                 │
│  services/persistence/                        │
│                                                │
│  config.py        RepositoryProvider enum      │
│  database.py      SupabaseConnectionManager     │
│  base_repository.py  SupabaseRepository[T]     │
│  migrations/      SQL schema migrations        │
│  repositories/    Concrete implementations     │
│     └─ user_repository.py                      │
│     └─ session_repository.py                   │
│     └─ token_repositories.py                   │
└──────────────────────────────────────────────┘
```

Key design choices:

1. **Same interface, new implementation** — Supabase*Repository classes implement the existing Repository ABCs. Services see no change.

2. **Generic SupabaseRepository[T]** — provides `save()`, `get()`, `delete()` with upsert logic. Concrete repositories inherit from `SupabaseRepository[T]` and implement domain-specific query methods directly.

3. **`asyncio.to_thread()` bridge** — the Supabase Python SDK is synchronous. All repository calls are offloaded to a thread pool via `asyncio.to_thread()` to prevent blocking the event loop.

4. **No SQLAlchemy** — repositories use the Supabase SDK's query builder directly (`client.table("users").select("*").eq(...)`). This avoids adding an ORM dependency and keeps the persistence layer thin.

5. **Field mapping via `typing.get_type_hints()`** — domain models use `from __future__ import annotations` (string annotations). The generic serializer/deserializer resolves types at runtime using `get_type_hints()` to correctly handle `datetime`, `Enum`, and `NewType` fields.

6. **Configurable provider** — `RepositoryProvider` enum (IN_MEMORY / SUPABASE) controls which implementation is wired. Default is IN_MEMORY. Switching requires a single function call — no service code changes.

7. **Incremental migration** — M2.1 migrates only Identity Platform (5 of 10 interface types). Remaining modules (Billing, Organizations, Capabilities, Onboarding) and 5 non-migrated Identity interfaces stay InMemory.

### Consequences

**Positive:**
- Identity data persists across restarts — users, sessions, tokens survive process termination
- No service code changes — services depend only on repository interfaces
- Existing test suite (3501 tests) continues to pass with InMemory repositories
- New persistence tests (30 tests) use mock Supabase client — no real database needed for CI
- Clean target for M2.2+ — implementing Supabase for Billing/Orgs/Capabilities requires only new repository classes
- Schema is version-controlled via SQL migration files

**Negative:**
- Only 5 of 10 Identity interfaces are migrated — partial persistence coverage
- The `asyncio.to_thread()` bridge adds overhead per repository call
- No connection pooling (Supabase SDK manages its own pool internally)
- In-memory repositories for remaining modules still lose data on restart
- No migration runner — SQL must be applied manually to the Supabase project

### Implementation

- `services/persistence/` (9 files)
- Migrated repositories: User, Session, RefreshToken, VerificationToken, PasswordReset
- SQL migration: `services/persistence/migrations/001_identity_platform.sql`
- Tests: `tests/test_persistence.py` (30 tests)
- Wiring: `services/identity/api.py:_make_identity_repositories()` checks `REPOSITORY_PROVIDER`

---

## ADR-0028 — Resend for Transactional Email with Standalone Template Rendering

### Metadata

| Field | Value |
|---|---|
| **Version** | v1.0 |
| **Date** | 2026-07-21 |
| **Status** | **ACTIVE** |

### Context

The existing email infrastructure has two separate concerns:

1. **Identity email provider** (`EmailProvider` ABC in `services/identity/providers/email_provider.py`) — only defines `send_verification_email()` and `send_password_reset_email()`. The sole implementation (`ConsoleEmailProvider`) prints to stdout. No real email delivery exists.

2. **Outbound campaign engine** (`services/email/composer.py`, `renderer.py`, `templates.py`, etc.) — a full composer/renderer/brand/mailbox system for outbound sales emails, delivered via GmailAdapter. This system is concerned with marketing/campaign email composition, not transactional email delivery.

Transactional emails (verification, password reset, org invitations, billing notifications) need a production-ready delivery mechanism. The existing `services/email/` campaign engine is too heavyweight and tightly coupled to outbound concepts (mailbox, brand kit, DraftBuilder, GmailAdapter).

### Decision

Keep the two email systems separate and use **Resend** for transactional email delivery:

```
Transactional Email (Identity/Billing)
──────────────────────────────────────────
EmailProvider (ABC)                           ← 7 methods
  ├── ConsoleEmailProvider                    ← mock, prints to stdout
  └── ResendEmailProvider                     ← production, via Resend API

Template rendering: standalone functions     ← services/email/transactional_templates.py
Delivery logging: structured logger          ← services/email/delivery_log.py
Configuration: EmailConfig dataclass          ← services/email/config.py
```

Key design choices:

1. **Resend over SMTP/SendGrid** — Resend provides a modern API with built-in deliverability, open/click tracking, and simple Python SDK (`resend.Emails.send()`). No SMTP configuration (host/port/auth) needed.

2. **Templates are standalone functions** — Unlike the outbound campaign engine (which uses `DraftBuilder` + `EmailRenderer` + `TemplateRegistry` + `BrandingManager`), transactional templates are pure functions that return `TemplateResult(subject, html, plain_text)`. This avoids dependency on the entire campaign composition pipeline and keeps template rendering testable without any infrastructure.

3. **`EmailProvider` ABC expanded with 5 new methods** — `send_organization_invitation()`, `send_welcome_email()`, `send_billing_receipt()`, `send_subscription_cancelled()`, `send_subscription_renewed()`. New methods default to `raise NotImplementedError` for backward compatibility with any existing subclasses.

4. **Provider switching via factory** — `_create_email_provider(config)` in `services/identity/api.py` checks `config.provider` (default `"console"`, switch to `"resend"`). This keeps the selection logic in one place and avoids env var scattering.

5. **`asyncio.to_thread()` for SDK calls** — The Resend SDK is synchronous. All `send_*` methods call `_send_async()` which offloads the HTTP call to a thread pool executor, preventing event loop blocking.

6. **Structured delivery logging without secrets** — `log_email_sent()` and `log_email_failed()` log `request_id`, `recipient`, `template`, `provider`, `status`, `duration_ms`. Email body, verification tokens, and API keys are never logged.

### Consequences

**Positive:**
- Production-ready transactional email delivery with Resend
- Development/CI continue with `ConsoleEmailProvider` (no credentials needed)
- Templates are pure functions — easy to test, no infrastructure needed
- No dependency on the outbound campaign composition pipeline
- Configuration validation at startup catches missing credentials when in resend mode
- Existing identity tests unchanged (still use `ConsoleEmailProvider`)
- 33 new tests cover all templates, providers, config, and factory

**Negative:**
- Two separate email systems exist (transactional `ResendEmailProvider` + outbound campaign `GmailAdapter`)
- The `EmailProvider` ABC now lives in identity but is used by billing/org concepts — cross-module dependency
- No queuing/retry mechanism — if Resend is down, the email is lost (caller receives error)
- The `resend` Python package is always installed even in console-only deployments
- No email sending history or audit trail persisted

### Implementation

- Expanded `EmailProvider` ABC and `ConsoleEmailProvider`: `services/identity/providers/email_provider.py`
- `ResendEmailProvider`: `services/email/resend_provider.py`
- `EmailConfig`: `services/email/config.py`
- Template rendering: `services/email/transactional_templates.py`
- Delivery logging: `services/email/delivery_log.py`
- Provider factory: `services/identity/api.py:_create_email_provider()`
- Config validation: `services/operations/diagnostics.py`
- Tests: `tests/test_email_infrastructure.py` (33 tests)

---

## ADR-0029 — Onboarding API Uses `user_id` Query Parameter (No Session Middleware)

### Metadata

| Field | Value |
|---|---|
| **Version** | v1.0 |
| **Date** | 2026-07-24 |
| **Status** | **ACTIVE** |

### Context

The onboarding API endpoints accept `user_id` as a query parameter rather than resolving the current user from a session/authentication token. This creates a potential security concern — any authenticated client could supply an arbitrary `user_id`.

### Decision

Keep the `user_id` query parameter. The entire identity platform currently uses the same pattern (see `/me`, `/sessions`, `/logout` endpoints). There is no session resolution middleware that could automatically determine the current user. Adding one would be a cross-cutting change affecting all platform modules and is deferred to a future auth hardening phase.

### Consequences

- Onboarding follows the same pattern as the identity API — consistent, not special-cased
- No middleware dependency — onboarding endpoints are self-contained
- Auth remains a future concern; the `user_id` pattern is documented technical debt shared across all platform APIs
- The onboarding `_get_service()` in `api.py` uses the same global-registry pattern as other platform modules

### Implementation

- All onboarding endpoints read `user_id: str = ""` as a query parameter
- Validation: endpoints return 400 if `user_id` is empty
- Pattern matches identity API (`/me`, `/sessions`, etc.)

---

## ADR-0030 — Onboarding Wizard Data Stored as JSON on `User` Model

### Metadata

| Field | Value |
|---|---|
| **Version** | v1.0 |
| **Date** | 2026-07-24 |
| **Status** | **ACTIVE** |

### Context

The onboarding wizard collects structured data (industry, role, goals) that must be preserved across all authentication flows (login, refresh, OAuth, email verification). The wizard data also needs to be available independently of the onboarding session lifecycle, since the lifecycle is gated by billing steps not yet implemented.

### Decision

Store wizard data as a JSON-serialized field (`onboarding_data`) on the `User` model rather than in the onboarding session or a separate table.

Key design properties:
- **Survives auth flows** — data is part of the User record, so it persists across login, refresh, OAuth, email verification, and logout
- **Independent of lifecycle** — `save_wizard_data()` and `get_wizard_data()` work without requiring prior lifecycle steps (profile, workspace, billing)
- **Schema-flexible** — the JSON field allows the data shape to evolve without migrations during early development
- `user.set_onboarding_data()` uses `json.dumps()`, and `user.onboarding_data_dict` uses `json.loads()` — both from the User model's `services/identity/models/user.py`

### Consequences

**Positive:**
- Wizard data is available before the user reaches the billing-gated lifecycle steps
- Survives any authentication flow (no session dependency)
- No schema migration needed for field changes

**Negative:**
- JSON field means no SQL-level validation or constraints on wizard data
- `save_wizard_data` in the onboarding service must handle serialization/deserialiation
- If the data shape becomes complex, a dedicated `onboarding_wizard_data` table may be needed later

### Implementation

- `User.onboarding_data: str` — JSON string field on User model
- `User.onboarding_data_dict` property — deserializes `onboarding_data` to `dict`
- `User.set_onboarding_data(dict)` method — serializes dict to JSON string and sets `onboarding_data`
- `OnboardingService.save_wizard_data()` — calls `user.set_onboarding_data()` via `user_service`
- `OnboardingService.get_wizard_data()` — reads `user.onboarding_data_dict`
