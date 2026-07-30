# Loqi Backend — Roadmap

> Generated from current implementation state.
> Updated after every milestone.

---

## Milestone Legend

| Icon | Meaning |
|---|---|
| ✅ | Completed |
| 🟡 | Active / In Progress |
| 🔴 | Blocked |
| ⬜ | Planned |

---

## M1 — Platform Foundation (Completed)

### M1.1 — Identity Platform
| Status | Component | Notes |
|---|---|---|
| ✅ | User model & value types | Soft-delete, locale, email value object |
| ✅ | Email+password authentication | Argon2 hashing, email verification flow |
| ✅ | Google OAuth (PKCE) | State parameter, code verifier, nonce, replay detection |
| ✅ | Session management | Active/expired/revoked, configurable session limits |
| ✅ | Refresh token rotation | Family-based, sequence numbering, theft detection |
| ✅ | Exception hierarchy | 17 typed exceptions, mapped to HTTP status codes in main.py |
| ✅ | Domain events | 15 event types, collected via `.events` property |
| ✅ | Auth metrics | Counter dataclass (signup, login, refresh, logout, revoke) |
| ✅ | Crypto service | Hash/verify (Argon2), encrypt/decrypt (AES), random tokens |
| 🟡 | AuthService orchestrator | Implemented but no unit tests |
| ⬜ | Password reset API | Model exists (`PasswordResetRequest`), no endpoint |
| ✅ | Supabase repository implementations (5/10) | User, Session, RefreshToken, VerificationToken, PasswordReset |
| ✅ | Production email provider | `ResendEmailProvider` via Resend API (M2.5) |

### M1.2 — Onboarding Platform
| Status | Component | Notes |
|---|---|---|
| ✅ | Lifecycle state machine | 9 states: VISITOR → AUTHENTICATED → ... → ACTIVE |
| ✅ | Profile setup step | Endpoint: POST /onboarding/profile |
| ✅ | Workspace setup step | Endpoint: POST /onboarding/workspace |
| ✅ | Step progression | POST /onboarding/complete-step |
| ⬜ | PLAN_SELECTION step integration | No billing platform integration |
| ⬜ | CHECKOUT_PENDING step | No Stripe checkout integration |
| ⬜ | SUBSCRIPTION_ACTIVE transition | No subscription verification |

### M1.3 — Organizations Platform
| Status | Component | Notes |
|---|---|---|
| ✅ | Organization CRUD | 15+ endpoints covering full lifecycle |
| ✅ | Membership management | Roles: owner/admin/member, status: active/suspended/inactive |
| ✅ | Invitation system | Create, accept, revoke, list |
| ✅ | Ownership transfer | Endpoint exists |
| ✅ | Organization resolver | `CurrentOrganizationResolver` |
| ⬜ | RBAC enforcement in API | Resolver exists, endpoints don't require role checks |
| ✅ | Supabase repository implementations | All 3 org repos migrated (M2.2) |

### M1.4 — Execution Engine
| Status | Component | Notes |
|---|---|---|
| ✅ | State machine | 11×11 task states, 8×8 session states, explicit transition tables |
| ✅ | DAG scheduler | In-degree map, FIFO queue, concurrency limits, fail/skip cascade |
| ✅ | Task dispatcher | `TaskType` → `ExecutionAdapter` resolution |
| ✅ | Adapter registry | Thread-safe, priority-based, introspection |
| ✅ | Bridge adapter | Wraps SDK adapters into ExecutionAdapter interface |
| ✅ | Execution pipeline | validate → create → initialize → run → finalize |
| ✅ | Retry engine | Exponential backoff, jitter, configurable policies |
| ✅ | Event bus | In-process pub/sub, subscriber isolation |
| ✅ | Metrics collector | Passive event-driven, per-adapter timing |
| ✅ | Recovery manager | Crash recovery, stuck state resolution |
| ✅ | Credential factory | Per-user OAuth2 with serialized refresh |
| ✅ | Validation | Cycle detection, payload integrity, dependency integrity |
| ✅ | Session lifecycle | Pause/resume/cancel/approve/reject |

### M1.5 — Organization Platform (M1.5 complete)
- Identity + Onboarding + Organizations all wired.

### M1.6 — Billing Platform
| Status | Component | Notes |
|---|---|---|
| ✅ | Plan service | 6 seed plans (3 tiers × 2 intervals) |
| ✅ | Customer service | Stripe customer mapping per org |
| ✅ | Checkout service | Checkout session creation with trials |
| ✅ | Subscription lifecycle | Cancel (at_period_end or immediate), resume |
| ✅ | Webhook service | 6 event types: checkout, subscription CRUD, invoice |
| ✅ | Stripe provider (mock) | In-memory mock — no real Stripe SDK calls |
| ✅ | API endpoints | 7 endpoints under /api/v1/billing |
| ✅ | Tests | 66 tests covering all layers |
| ✅ | Real Stripe SDK integration | `StripeBillingProvider` uses `import stripe` via live mode |
| ✅ | Supabase repository implementations | All 6 billing repos migrated (M2.3) |
| ⬜ | Event bus integration | Domain events collected but never published |

### M1.7 — Capability Platform
| Status | Component | Notes |
|---|---|---|
| ✅ | CapabilityDefinition model | Slug, name, category, default_enabled, beta |
| ✅ | OrganizationCapability model | Per-org activation with audit trail |
| ✅ | CapabilityUsage model | Requests, executions, storage, api_calls |
| ✅ | CapabilityLimits model | Defined, limits not enforced |
| ✅ | Seed capabilities | 10 capabilities across 6 categories |
| ✅ | Service layer | Register, seed, enable, disable, usage CRUD |
| ✅ | API endpoints | 5 endpoints |
| ✅ | Tests | 54 tests |
| ⬜ | Billing plan → capability gating | Explicitly excluded from M1.7 |
| ⬜ | Authorization checks | Explicitly excluded from M1.7 |
| ⬜ | Supabase persistence | All repos are `InMemory*` |
| ⬜ | Usage-based metering | No billing integration |

---

## Active Development

### M1.8 — Concrete Credential Resolver

| Status | Component | Notes |
|---|---|---|
| 🟡 | `CredentialResolver` implementation | Abstract interface exists in `adapters/credential_resolver.py`, no concrete implementation |
| ⬜ | OAuth2 credential refresh | Token refresh exists in credential_factory, not in resolver |
| ⬜ | API key credential store | Descriptor exists, store does not |

### M1.9 — Sync→Async Migration

| Status | Component | Notes |
|---|---|---|
| 🟡 | `handle_message()` async-native | Currently sync via `ThreadPoolExecutor._run_async()` bridge |
| 🟡 | `run_workflow()` async propagation | All workflow functions need async propagation |
| 🟡 | `GmailAdapter` async calls | Adapter calls offloaded to worker thread |

---

## Blocked

| Item | Blocker | Impact |
|---|---|---|
| 🟡 Supabase repository implementations | Identity (5/10), Organizations (3/3), Billing (6/6) migrated. Capabilities + Onboarding pending | Identity, Org, Billing data persists. Capabilities/Onboarding still volatile |
| 🔴 Supabase: remaining identity repos | 5 interfaces (EmailIdentity, PasswordCredential, ExternalIdentity, RegistrationSession, OAuthSession) not migrated | Partial Supabase coverage for Identity |
| 🔴 Supabase: remaining non-Identity repos | Capabilities (4 repos), Onboarding (2 repos) not started | Those modules still lose data on restart |
| 🟡 Live Stripe integration | `StripeBillingProvider` implemented with real SDK. Requires `BILLING_PROVIDER_MODE=live` and `STRIPE_SECRET_KEY` env vars. Missing: invoice lifecycle automation, subscription renewal background jobs | Billing platform can process real payments with live mode enabled |
| 🟡 Production email delivery | `ResendEmailProvider` implemented. Requires `EMAIL_PROVIDER=resend` and `EMAIL_API_KEY` env vars | Verification emails go to console unless resend mode is enabled |

---

## M2 — Production Platform

### M2.1 — Supabase Persistence Layer (In Progress)

Replace all `InMemory*Repository` implementations with Supabase-backed repositories.

**Identity Platform migrated (5 of 10 interfaces):**

| Status | Repository | Notes |
|---|---|---|
| ✅ | `SupabaseUserRepository` | Full CRUD, soft-delete aware |
| ✅ | `SupabaseSessionRepository` | CRUD + find active/by user, revoke, count |
| ✅ | `SupabaseRefreshTokenRepository` | CRUD + find by hash, find by family, revoke all |
| ✅ | `SupabaseVerificationTokenRepository` | CRUD + find valid by target/purpose, invalidate all |
| ✅ | `SupabasePasswordResetRepository` | CRUD + find valid by user, invalidate all |
| ⬜ | `SupabaseEmailIdentityRepository` | Not yet migrated |
| ⬜ | `SupabasePasswordCredentialRepository` | Not yet migrated |
| ⬜ | `SupabaseExternalIdentityRepository` | Not yet migrated |
| ⬜ | `SupabaseRegistrationSessionRepository` | Not yet migrated |
| ⬜ | `SupabaseOAuthSessionRepository` | Not yet migrated |

**Organizations Platform migrated (3 of 3 interfaces):**

| Status | Repository | Notes |
|---|---|---|
| ✅ | `SupabaseOrganizationRepository` | Full CRUD, find by slug/name, find owned by |
| ✅ | `SupabaseMembershipRepository` | CRUD + find by user/org, count owners, find active |
| ✅ | `SupabaseInvitationRepository` | CRUD + find by org, find pending by email, find by token |

**Billing Platform migrated (6 of 6 interfaces):**

| Status | Repository | Notes |
|---|---|---|
| ✅ | `SupabasePlanRepository` | CRUD + find by code, list active |
| ✅ | `SupabaseCustomerRepository` | CRUD + find by org, find by provider customer ID |
| ✅ | `SupabaseSubscriptionRepository` | CRUD + find by org, find active, find by provider ID |
| ✅ | `SupabaseCheckoutRepository` | CRUD + find by org, find by provider checkout ID |
| ✅ | `SupabaseInvoiceRepository` | CRUD + find by org, find by provider invoice ID |
| ✅ | `SupabaseBillingEventRepository` | CRUD + find by provider event ID, find by idempotency key |

**Remaining modules (not migrated — still InMemory*):**

| Module | Repositories |
|---|---|
| Capabilities | CapabilityDefinitionRepository, OrganizationCapabilityRepository, CapabilityUsageRepository, CapabilityLimitsRepository |
| Onboarding | LifecycleRepository, OnboardingSessionRepository |

**Configuration:** Mode switching via `RepositoryProvider` enum — no service code changes.
**Schemas:** `001_identity_platform.sql` (7 identity tables), `002_organizations.sql` (3 org tables), `003_billing.sql` (6 billing tables) — all with indexes, FKs, unique constraints, soft-delete support.
**Tests:** 81 integration tests with mock Supabase client.

### M2.1.1 — CI Foundation (Complete)

| Status | Component | Notes |
|---|---|---|
| ✅ | GitHub Actions workflow | `.github/workflows/ci.yml` |
| ✅ | Backend-only pipeline | No frontend, no deployment |
| ✅ | Python 3.12 with pip cache | Cached via `actions/setup-python@v5` |
| ✅ | Format check | Black — skipped if not configured |
| ✅ | Import sort check | isort — skipped if not configured |
| ✅ | Lint | ruff or flake8 — skipped if not configured |
| ✅ | Type check | mypy or pyright — skipped if not configured |
| ✅ | Migration validation | Directory structure + file naming convention |
| ✅ | Full test suite | 3466 tests offline, 35 excluded (require Supabase) |
| ✅ | Failure artifact upload | pytest output uploaded on failure |
| ✅ | Concurrency | Cancel in-progress for same ref |
| ✅ | Zero secrets | `SUPABASE_URL=""`, `SUPABASE_KEY=""` |
| ✅ | Documentation | ARCHITECTURE.md updated with CI Pipeline section |

**Trigger:** push/PR to `main`, `develop`, `feature/**`
**Expected runtime:** ~2–4 minutes
**Quality gate:** pipeline must be green before merge to main

### M2.2.1 — Production Readiness (Complete)

| Status | Component | Notes |
|---|---|---|
| ✅ | `/health` endpoint | Liveness probe, no DB access |
| ✅ | `/ready` endpoint | Readiness probe — DB, provider, config verification |
| ✅ | `/version` endpoint | Application metadata (name, version, commit, env, provider) |
| ✅ | Structured request logging | request_id, method, path, status, duration_ms |
| ✅ | Error response format | Consistent `{"error": {"code": "...", "message": "...", "request_id": "..."}}` |
| ✅ | Unhandled exception handling | Logged with stack trace, never exposed to client |
| ✅ | `X-Request-ID` header | Every response includes 8-char hex ID |
| ✅ | Startup diagnostics | Single startup log: version, env, provider, routes, duration |
| ✅ | Configuration validation | Required vars checked at startup (OPENAI_API_KEY always; SUPABASE_URL/KEY conditionally) |
| ✅ | `services/operations/` module | Infrastructure-only — must not import business services |
| ✅ | Tests | 23 tests covering all endpoints, middleware, validation, diagnostics |
| ✅ | Documentation | ARCHITECTURE.md updated with Operational Infrastructure section |

### M2.2 — Production Billing (Complete)

| Item | Description |
|---|---|
| ✅ | Real StripeBillingProvider implemented using `stripe` Python SDK for all 7 provider methods |
| ✅ | Webhook signature verification via `stripe.Webhook.construct_event()` |
| ✅ | Billing portal via `stripe.billing_portal.Session.create()` |
| ✅ | Provider mode switching: `create_billing_provider()` factory checks `BillingConfig.provider_mode` |
| ✅ | Stripe config validation at startup when `BILLING_PROVIDER_MODE=live` |
| ✅ | 16 new integration tests for live provider (mocked Stripe SDK) |
| ⬜ | Invoice lifecycle — automated dunning, failed payment retry |
| ⬜ | Subscription renewals — background job for renewal processing |

### M2.3 — Production Email (Complete)

| Item | Description |
|---|---|
| ✅ | ResendEmailProvider — real transactional email via Resend API |
| ✅ | ConsoleEmailProvider — mock provider preserved for development/CI |
| ✅ | Provider switching via `EMAIL_PROVIDER` env var (`console`/`resend`) |
| ✅ | HTML + plain text templates for 7 email types: verification, password reset, invitation, welcome, billing receipt, subscription cancelled/renewed |
| ✅ | Shared template layout with inline CSS, responsive design, branded header/footer |
| ✅ | Structured delivery logging (recipient, template, provider, status, duration — no body/keys) |
| ✅ | Resend SDK offloaded via `asyncio.to_thread()` — non-blocking |
| ✅ | Tags/metadata support for Resend analytics |
| ✅ | Reply-To, custom from name/address support |
| ✅ | Configuration validation at startup when `EMAIL_PROVIDER=resend` |
| ✅ | 33 new tests covering templates, console provider, resend provider (mocked), config, factory |

### M2.4 — Authorization & Access Control

| Item | Description |
|---|---|
| RBAC enforcement | Apply role checks to organization API endpoints |
| Capability gating | Wire CapabilityPlatform into BillingPlatform: plan → capabilities |
| Auth middleware | Consistent `_get_current_user` pattern across all endpoints |

### M2.5 — Cross-Domain Event Bus

| Item | Description |
|---|---|
| Domain event publisher | Replace `.events` property accumulation with actual publish mechanism |
| Event subscribers | Wire MemorySubscriber, LoggingSubscriber, MetricsCollector to domain events |
| Cross-platform events | Identity events → Billing (trial start), Billing events → Capabilities (limit enforcement) |

### M2.6 — Legacy Retirement

| Item | Description |
|---|---|
| Deprecate `workflow_*` (15 files) | All workloads migrated to ExecutionEngine |
| Deprecate `reply_intelligence.py` | Replaced by IntelligencePipeline → ReasoningPipeline → GenerationPipeline |
| Deprecate legacy `conversation_memory.py` | Replaced by `services/memory/` |
| Remove `main.py` redundancy | 3400-line file needs decomposition into routers |

### M2.7 — AI Testing & Hardening

| Item | Description |
|---|---|
| Reasoning pipeline tests | No tests exist |
| Reply generation tests | No tests exist |
| Conversation intelligence tests | Dedicated test suite |
| Conversation engine tests | 1198-line file with zero tests |

---

## Product Backlog (Unordered)

| Priority | Item | Source |
|---|---|---|
| High | Reliable lead sourcing | AGENTS.md |
| High | Better personalization quality | AGENTS.md |
| High | Web UI polish | AGENTS.md |
| Medium | Gmail inbox sync reliability | AGENTS.md |
| Medium | Reply detection | AGENTS.md |
| Medium | Preference memory | AGENTS.md |
| Low | WhatsApp adapter | Product direction |
| Low | Mobile app API | Product direction |
| Low | Slack adapter | Product direction |
