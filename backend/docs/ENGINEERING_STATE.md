# Loqi — Engineering State

**Version:** 1.0
**Status:** LIVE SNAPSHOT
**Generated:** 2026-07-19
**Tests:** 2674 passing, 0 failing
**Tag:** `platform-v1.1.0`

---

## 1. Current Progress

| Dimension | Value |
|---|---|
| Chapter | 5 — Adapters |
| Current Phase | 5.5 — Email Composition Engine v1.0 |
| Status | **COMPLETED AND FROZEN** |
| Platform Release | v1.1 (tagged `platform-v1.1.0`) |
| Total Tests | 2674 passing, 0 failing, 2 deprecation warnings (Supabase third-party) |
| Frozen Layers | 10 components across 2 platform releases |

The entire adapter foundation plus three production adapters and the email composition engine are complete and frozen. The platform is at a stable release point.

---

## 2. Completed Phases

### Phase 1 — Foundation (pre-v0.3)
- **Purpose:** Establish initial project structure, FastAPI app, Supabase integration, Telegram bot
- **Major components built:** `main.py`, Telegram webhook, basic Gmail send, Supabase client, conversation engine
- **Key architectural decisions:** FastAPI as web framework, Supabase as persistence layer, OpenAI for AI generation
- **Created:** `main.py`, `services/agent.py`, `services/ai.py`, `services/gmail.py`, `services/google_auth.py`, `services/supabase.py`, `services/telegram.py`, `services/conversation_engine.py`
- **Status:** Complete. Replaced by later iterations.

### Phase 2 — Workflow System (v0.3–v0.4)
- **Purpose:** Build deterministic workflow engine for lead generation, drafting, and outbound campaigns
- **Major components built:** `workflows.py`, `workflow_dispatcher.py`, `workflow_planner.py`, `workflow_executor.py`, `workflow_runtime.py`, `workflow_retry.py`, `workflow_scheduler.py`, `workflow_recovery.py`, `workflow_persistence.py`, `workflow_events.py`, `workflow_registry.py`, `workflow_models.py`, `workflow_locks.py`, `workflow_reasoner.py`
- **Key architectural decisions:** Workflows are deterministic step-by-step plans, not DAGs. Runtime owns state transitions with thread safety. Recovery is file-based JSON persistence. Retry engine supports immediate/fixed/exponential backoff. Event bus emits typed events for every transition.
- **Key sub-phases:**
  - Phase 2.7: Draft Review Workspace, CampaignPlanner polish, UX
  - Phase 3.0: Job Engine (`services/job_engine/`) — async AI workflow infrastructure with Supabase persistence
  - Phase 3.1.3: AI Writing Partner — draft intelligence, comparison, rewrite
  - Phase 3.2.2: Mission Control — workspace dashboard
  - Phase 3.4.2B: Production runtime hardening — recovery, fault tolerance
  - Phase 3.5.3: Conversation Management & Autonomous Follow-up Engine
- **Status:** Complete. All workflow components operational. File-based persistence used for crash recovery.

### Phase 3 — Communication Intelligence (v0.4)
- **Purpose:** Build conversation intelligence, reply generation, and multi-provider AI support
- **Major components built:** `services/conversation_intelligence/` (full pipeline, intent extraction, buying signal detection, entity extraction, objection detection, conversation scoring, memory), `services/conversation_intelligence/knowledge/` (patterns, technologies, companies, budgets, meeting patterns, titles, timelines, objections, buying signals), `services/reply_generation/` (generation pipeline, prompt builder, style engine, template library, 4 AI providers), `services/conversational_response_generator.py`
- **Key architectural decisions:** Knowledge registry is the single source of truth for conversation patterns. AI providers are pluggable via registry pattern. Intelligence pipeline is orchestrator-based. Reply generation supports multi-style output.
- **AI providers implemented:** OpenAI, Anthropic, Google Gemini, DeepSeek
- **Status:** Complete.

### Phase 4 — Lead Sourcing & Enrichment (v0.4–v0.5)
- **Purpose:** Build provider-agnostic lead sourcing with Apollo integration
- **Major components built:** `services/providers/` (base_provider, apollo_provider, synthetic_provider, provider_factory), `services/enrichment/` (base_enricher, apollo_enricher, synthetic_enricher, enrichment_factory), `services/lead_provider.py`, `services/search_expansion.py`, `services/icp_extractor.py`, `services/commercial_qualifier.py`
- **Key architectural decisions:** Provider abstraction via factory pattern. Synthetic provider exists for testing. ICP extraction uses AI. Commercial qualifier filters vendors/junk with multi-dimensional scoring. Search expansion uses OpenAI for query broadening.
- **Status:** Complete.

### Phase 5 — Platform Foundation & Adapters

#### Phase 5.1 — Execution Runtime (Layer 1) + Adapter SDK Foundation (Layer 2)
- **Purpose:** Build the foundational execution runtime and adapter contract
- **Major components built:** `services/execution/` (dispatcher, scheduler, event_bus, state_machine, metrics_collector, recovery_manager, pipeline), `services/adapters/base_adapter.py`, `services/adapters/adapter_context.py`, `services/adapters/models.py`, `services/adapters/exceptions.py`, `services/adapters/protocols.py`
- **Key architectural decisions:**
  - `ExecutionAdapter` is the sole contract — all adapters implement `execute(context)`
  - Models are immutable frozen dataclasses
  - Adapters are stateless — all state lives in the runtime
  - State Machine is the sole owner of state transitions
  - Scheduler is retry-unaware
  - Dispatcher is adapter-independent
  - Event Bus is generic infrastructure
  - Metrics are passive — never influence execution
- **Status:** FROZEN v1.0.

#### Phase 5.2 — Capability System (Layer 3) + Credential Framework (Layer 4) + Adapter Registry (Layer 5)
- **Purpose:** Build the capability description system, credential resolution, and adapter registry
- **Major components built:** `services/adapters/capabilities.py`, `services/adapters/capability_registry.py`, `services/adapters/credentials.py`, `services/adapters/credential_registry.py`, `services/adapters/credential_resolver.py`, `services/adapters/adapter_registry.py`, `services/adapters/adapter_factory.py`, `services/adapters/adapter_registration.py`
- **Key architectural decisions:**
  - Planner thinks in verbs, never implementations (capability-based dispatch)
  - Registry owns metadata only — does not instantiate adapters
  - Descriptors are immutable
  - Categories are extensible by convention
  - Adapters never fetch credentials — references carry no secrets
  - Secrets never leak in text output
  - Registry stores registrations only — Factory never caches
- **Status:** FROZEN v1.0.

#### Phase 5.3 — HTTP Adapter + Google API Base Adapter (Platform v1.1)
- **Purpose:** Build production HTTP transport and Google API discovery layer
- **Major components built:**
  - **HTTP Adapter:** `services/adapters/http/` (http_adapter.py, models.py, exceptions.py, auth.py, transport.py, validators.py, serializers.py) — 314 tests
  - **Google API Base Adapter:** `services/adapters/google/` (google_api_adapter.py, models.py, errors.py, urls.py, pagination.py, services.py) — 169 tests
- **Key architectural decisions:**
  - HTTP Adapter is generic-only — no domain knowledge
  - Transport abstraction via `HttpTransport` protocol (default: HttpxTransport)
  - Auth injected, not fetched (Bearer, Basic, API Key)
  - Google API Adapter delegates all HTTP to `HttpAdapter`
  - Google URLs built from service descriptors, not hardcoded
  - Structured error mapping for Google API errors
  - OAuth2 token is injected, not fetched
  - Runtime owns retries, caching, metrics, recovery
  - No streaming support, no multipart upload, no websocket (known limitations)
- **Status:** FROZEN v1.0. Part of Platform v1.1 release.

#### Phase 5.4 — Gmail Adapter v1.0
- **Purpose:** Thin domain layer for Gmail API operations on top of Google API Base Adapter
- **Major components built:** `services/adapters/google/gmail/` (gmail_adapter.py, models.py, errors.py, mime.py, queries.py, __init__.py) — 162 tests
- **8 capabilities registered:** `gmail_send_email`, `gmail_list_messages`, `gmail_get_message`, `gmail_search_messages`, `gmail_list_labels`, `gmail_get_label`, `gmail_list_threads`, `gmail_get_thread`
- **Key architectural decisions:**
  - Delegates all HTTP to `GoogleApiAdapter` — no HTTP logic duplicated
  - `GmailResourceMapper` converts raw JSON to typed domain models
  - `GmailQuery` provides type-safe Gmail search operators with escaping
  - `MimeMessage` produces RFC 2822 emails with base64url encoding
  - Gmail-specific errors subclass `GoogleApiError` — auth/quota errors propagate unchanged
  - Credential descriptor reuses `google_oauth2` — no Gmail-specific credential
- **Status:** FROZEN v1.0. Part of Platform v1.1 release.

#### Phase 5.5 — Email Composition Engine v1.0
- **Purpose:** Provider-agnostic email composition layer for preparing fully rendered, branded email drafts
- **Major components built:** `services/email/` (11 source files) — 174 tests
  - `models.py` — `EmailDraft`, `Attachment`, `CompanyMailbox`, `BrandKit`, `TemplateName`
  - `composer.py` — `EmailComposer` — top-level orchestrator with dependency injection
  - `draft.py` — `DraftBuilder` + `draft_to_gmail_params()` converter
  - `renderer.py` — `EmailRenderer` — applies template + branding + footer
  - `templates.py` — 6 responsive HTML templates (Plain, Professional, Recruiting, Newsletter, Proposal, Product Launch)
  - `template_registry.py` — metadata registry for templates
  - `branding.py` — `BrandingManager` for BrandKit lifecycle
  - `mailbox.py` — `MailboxManager` for CompanyMailbox lifecycle + sender selection
  - `attachments.py` — `AttachmentProcessor` with MIME validation + size limits (25MB per file, 50MB total)
  - `exceptions.py` — 8 exception classes in `EmailCompositionError` hierarchy
- **Key architectural decisions:**
  - Provider-agnostic — imports nothing from `services.adapters.google`, `services.adapters.http`, or any vendor
  - Future providers (Outlook, SMTP, SendGrid) reuse 100% of this layer
  - `draft_to_gmail_params()` converts draft → Gmail-compatible params dict
  - Templates use pure Python functions, not a template engine dependency
  - Builder pattern for `EmailDraft` construction
  - Frozen immutable models throughout
- **Status:** FROZEN v1.0. Part of Platform v1.1 release.

### Platform v1.1 Release
- **Purpose:** Stabilize and freeze all adapter layers with verified test suite
- **Verification results:** 2338 tests passed, 0 failed, 2 supabase deprecation warnings
- **Maintenance tasks completed:**
  - 20 unused imports removed across 9 files
  - `on_event` → `lifespan` migration in `main.py`
  - `to_exception()` reordered for `RATE_LIMIT_EXCEEDED` priority
  - `CampaignPriority.to_dict()` bugfix (missing `score`)
  - Architecture docs updated with test counts and freeze status tables
- **Documentation created:**
  - `GOOGLE_API_ADAPTER_FREEZE.md`
  - `GMAIL_ADAPTER_FREEZE.md`
  - `EMAIL_COMPOSITION_ENGINE_FREEZE.md`
  - `PLATFORM_v1.1_RELEASE.md`
- **Tag:** `platform-v1.1.0`

---

## 3. Current Phase Details

There is **no active implementation phase**. Platform v1.1 is complete and frozen. All 10 layers are stable.

The project is at a release point. The next phase has not been started.

### What exists but is NOT frozen

The following components exist in the codebase but are NOT covered by the platform freeze. They predate the adapter architecture and continue to work:

| Component | File | Notes |
|---|---|---|
| Conversation Engine | `conversation_engine.py` (1161 lines) | Multi-client message routing, workflow dispatch |
| Conversation Store | `conversation_store.py` | Supabase CRUD for sessions/messages/users |
| AI Generation | `ai.py` | OpenAI prompts, outreach generation, analysis |
| Gmail Send (legacy) | `gmail.py` | Pre-adapter direct Gmail API calls |
| Google Auth (legacy) | `google_auth.py` | OAuth flow, token refresh |
| Supabase Client | `supabase.py` | All DB operations |
| Workflow System | `workflows.py`, `workflow_dispatcher.py` | Core workflow definitions |
| Workflow Subsystem | `workflow_*.py` (14 files) | Planning, execution, runtime, retry, recovery |
| Lead Providers | `providers/` (4 files) | Apollo, synthetic |
| Enrichment | `enrichment/` (4 files) | Apollo enrichment |
| Intelligence | `conversation_intelligence/` (14+ files) | Knowledge registry, detection pipelines |
| Communication | `communication/` (8 files) | Gmail provider, sync, webhooks |
| Outbound Engine | `outbound/` (8 files) | Draft store, scheduler, executor |
| Reasoning Engine | `reasoning/` (7 files) | Pipeline, confidence, policy, priority |
| Planning Engine | `planner/` (11+ files) | Strategies, approval, scheduling |
| Reply Generation | `reply_generation/` (12 files) | Multi-provider AI replies |
| Email Composition Engine | `email/` (11 files) | FROZEN |
| Job Engine | `job_engine/` (5 files) | Async job infrastructure |
| Channel Adapters | `channel_adapters/` | Telegram adapter |
| Conversation Analysis | Various `conversation_*.py` | Classifiers, memories, timelines |
| AI-assisted features | `icp_extractor.py`, `commercial_qualifier.py` etc. | AI-powered analysis modules |

### Known Incomplete Items (intentionally postponed)

- **No Calendar Adapter** — Google Calendar operations not implemented
- **No Drive Adapter** — Google Drive operations not implemented
- **No Outlook Adapter** — Microsoft 365 email not supported
- **No SMTP Adapter** — Direct SMTP sending not implemented
- **No SendGrid Adapter** — SendGrid integration not built
- **No Web Chat UI** — Frontend chat UI exists but is not production-grade
- **No Dashboard / Analytics** — Analytics module has not been built
- **No Billing System** — Subscription management, credit tracking, payment processing not implemented
- **No Multi-tenancy** — Team collaboration not implemented (design principle: Single Player First)
- **No OAuth for non-Gmail** — Only Google OAuth2 exists

---

## 4. Architecture Snapshot

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         CHANNEL ADAPTERS                                 │
│  Telegram (channel_adapters/telegram.py)   Web (main.py routes)         │
├──────────────────────────────────────────────────────────────────────────┤
│                         CONVERSATION ENGINE                              │
│  conversation_engine.py — multi-client message routing & orchestration   │
├──────────────────────────────────────────────────────────────────────────┤
│                         WORKFLOW SYSTEM                                  │
│  workflows.py — workflow definitions                                    │
│  workflow_planner.py — plan generation from objectives                   │
│  workflow_executor.py — step-by-step execution with retry               │
│  workflow_runtime.py — thread-safe state management                     │
│  workflow_retry.py — retry policies (immediate/fixed/exponential)       │
│  workflow_scheduler.py — delayed execution                              │
│  workflow_recovery.py — crash recovery from JSON persistence            │
│  workflow_events.py — typed event emission                              │
├──────────────────────────────────────────────────────────────────────────┤
│                         AI / GENERATION                                  │
│  ai.py — OpenAI integration (outreach, analysis, answering)             │
│  reply_generation/ — multi-provider AI reply generation                 │
│  ├── providers/openai_provider.py                                       │
│  ├── providers/anthropic_provider.py                                    │
│  ├── providers/gemini_provider.py                                       │
│  └── providers/deepseek_provider.py                                     │
├──────────────────────────────────────────────────────────────────────────┤
│                         COMMUNICATION LAYER                              │
│  communication/ — Gmail provider, sync engine, webhooks                 │
│  outbound/ — Outbound email scheduler, executor, draft store            │
│  gmail_provider.py — Gmail OAuth integration and health monitoring      │
├──────────────────────────────────────────────────────────────────────────┤
│                         EMAIL COMPOSITION (FROZEN)                       │
│  email/ — EmailDraft, composer, renderer, templates, branding           │
│  └── Composer → draft_to_gmail_params() → GmailAdapter                 │
├──────────────────────────────────────────────────────────────────────────┤
│                         ADAPTER SYSTEM (FROZEN)                          │
│  adapters/                                                                 │
│  ├── ExecutionAdapter (abstract base contract)                          │
│  ├── CapabilityRegistry (maps verbs to adapters)                        │
│  ├── CredentialResolver (injects auth, never fetches)                   │
│  ├── AdapterRegistry (stores registrations, factory instantiates)       │
│  ├── HTTP Adapter — generic REST client with auth handlers              │
│  ├── Google API Base Adapter — Google service discovery layer           │
│  └── Gmail Adapter — Gmail operations (send, list, search, labels)      │
├──────────────────────────────────────────────────────────────────────────┤
│                         INTELLIGENCE LAYER                               │
│  conversation_intelligence/ — knowledge registry, detection pipelines    │
│  intent_detector.py, buying_signal.py, objection_detector.py            │
│  conversation_scoring.py, conversation_summary.py                        │
├──────────────────────────────────────────────────────────────────────────┤
│                         REASONING & PLANNING                             │
│  reasoning/ — confidence, policy, priority, risk assessment             │
│  planner/ — strategies (cold_outreach, follow_up, demo, nurture, etc.) │
│  planning_engine.md — architecture doc                                  │
├──────────────────────────────────────────────────────────────────────────┤
│                         LEAD SOURCING                                    │
│  providers/ — Apollo provider + synthetic provider (factory pattern)    │
│  enrichment/ — Apollo enrichment + synthetic enricher                   │
│  lead_provider.py, search_expansion.py, icp_extractor.py                │
│  commercial_qualifier.py, messaging_strategy.py                         │
├──────────────────────────────────────────────────────────────────────────┤
│                         PERSISTENCE                                      │
│  supabase.py — Supabase client, all DB operations                      │
│  conversation_store.py — Session/message/user CRUD                     │
│  workflow_persistence.py — JSON file-based crash recovery               │
│  outbound_persistence.py — Outbound state persistence                   │
│  migration.py — Schema migrations (jobs, search_results)                │
└──────────────────────────────────────────────────────────────────────────┘
```

### How the layers connect

1. **Channel Adapters** receive messages from external clients (Telegram, Web) and pass them to the **Conversation Engine**
2. **Conversation Engine** (1161 lines) is the central orchestrator — it routes messages, manages state, dispatches to the **Workflow System**, queries **AI providers**, and stores results in **Supabase**
3. **Workflow System** executes deterministic multi-step plans — lead generation, drafting, campaign execution — with retry, recovery, and event emission
4. **AI / Generation** layer provides prompt-based LLM interactions via multiple providers
5. **Communication Layer** handles Gmail OAuth, inbox sync, outbound email scheduling, and draft management
6. **Email Composition** engine produces fully rendered `EmailDraft` objects that are converted to Gmail API params via `draft_to_gmail_params()`
7. **Adapter System** is the foundation for all external service integration — HTTP, Google APIs, and future providers
8. **Intelligence Layer** analyzes conversations for buying signals, intent, entities, and objections using the knowledge registry
9. **Reasoning & Planning** layers evaluate confidence, assess risk, enforce policies, and select appropriate outreach strategies
10. **Lead Sourcing** discovers and enriches prospects via provider-agnostic factory pattern

---

## 5. Project Structure

```
backend/
├── main.py                     # FastAPI app — all routes, middleware, lifespan
├── workflows.py                # Workflow definitions (generate leads, draft, send)
├── workflow_dispatcher.py      # Maps workflow types to async runners
├── requirements.txt            # Python dependencies
├── RENDER_DEPLOY.md            # Deployment instructions
│
├── services/                   # All business logic
│   ├── agent.py                # Telegram message entrypoint
│   ├── ai.py                   # OpenAI integration (legacy)
│   ├── gmail.py                # Gmail API send (pre-adapter, legacy)
│   ├── google_auth.py          # Google OAuth2 flow (legacy)
│   ├── supabase.py             # Supabase client wrapper
│   ├── telegram.py             # Telegram HTTP API client
│   ├── conversation_engine.py  # Core multi-client orchestrator (1161 lines)
│   ├── conversation_store.py   # Supabase CRUD for sessions/messages
│   ├── conversation_models.py  # Pydantic models for intelligence
│   ├── conversation_memory.py  # Structured fact storage per conversation
│   ├── conversation_timeline.py# Event log per conversation
│   ├── conversation_classifier.py # Conversation stage classification
│   ├── conversational_response_generator.py # AI response generation (963 lines)
│   ├── reply_intelligence.py   # Reply Intelligence aggregator
│   ├── reply_summary.py        # Executive summaries
│   ├── intent_detector.py      # Intent classification
│   ├── buying_signal.py        # Purchase intent detection
│   ├── followup_reasoner.py    # Next-action recommendation
│   ├── lead_provider.py        # Lead sourcing orchestrator
│   ├── campaign_planner.py     # Campaign strategy generation
│   ├── search_expansion.py     # AI-powered query broadening
│   ├── icp_extractor.py        # Ideal Customer Profile extraction (690 lines)
│   ├── commercial_qualifier.py # Lead scoring / vendor filtering (619 lines)
│   ├── messaging_strategy.py   # Messaging angle selection
│   ├── framework_selector.py   # Messaging framework (PAS, AIDA, etc.)
│   ├── trust_builder.py        # Credibility element analysis
│   ├── buyer_psychology.py     # Buyer persona analysis
│   ├── cta_strategy.py         # CTA recommendation
│   ├── objection_predictor.py  # Objection prediction
│   ├── company_context.py      # Company maturity/context analysis
│   ├── strategy_comparison.py  # Messaging comparison engine
│   ├── draft_intelligence.py   # Cold email quality scoring (399 lines)
│   ├── draft_comparison.py     # Draft version diff
│   ├── rewrite_engine.py       # Strategy-aware rewrite (177 lines)
│   ├── rewrite_history.py      # Multi-level undo for rewrites
│   ├── executive_brief.py      # Workspace AI summary
│   ├── recommendation_engine.py# Next-action recommendations
│   ├── workspace_reasoner.py   # Workspace state understanding (635 lines)
│   ├── workspace_snapshot.py   # Workspace state with caching
│   ├── workspace_memory.py     # Per-session workspace state
│   ├── workspace_timeline.py   # Workspace event log
│   ├── migration.py            # Schema migrations
│   ├── workflow_registry.py    # Action → executor mapping
│   ├── workflow_planner.py     # Workflow plan generation (603 lines)
│   ├── workflow_executor.py    # Step-by-step execution (242 lines)
│   ├── workflow_models.py      # Plan/step/status models
│   ├── workflow_runtime.py     # State machine with thread safety (362 lines)
│   ├── workflow_progress.py    # Progress/ETA calculation
│   ├── workflow_events.py      # Typed event bus (148 lines)
│   ├── workflow_persistence.py # JSON file save/load
│   ├── workflow_recovery.py    # Auto-restore from persistence
│   ├── workflow_retry.py       # Retry policies
│   ├── workflow_scheduler.py   # Delayed execution
│   ├── workflow_locks.py       # Resource locking
│   ├── workflow_reasoner.py    # Workspace understanding for planning
│   │
│   ├── adapters/               # Adapter architecture (FROZEN)
│   │   ├── base_adapter.py     # ExecutionAdapter abstract class
│   │   ├── adapter_registry.py # Registry
│   │   ├── adapter_factory.py  # Factory
│   │   ├── adapter_registration.py
│   │   ├── adapter_context.py  # Execution context
│   │   ├── capabilities.py     # Capability definitions
│   │   ├── capability_registry.py
│   │   ├── credentials.py      # Credential models
│   │   ├── credential_registry.py
│   │   ├── credential_resolver.py
│   │   ├── exceptions.py       # Adapter error hierarchy
│   │   ├── models.py           # Shared models
│   │   ├── protocols.py        # Protocol contracts
│   │   │
│   │   ├── http/               # HTTP Adapter (FROZEN)
│   │   │   ├── http_adapter.py
│   │   │   ├── models.py
│   │   │   ├── exceptions.py
│   │   │   ├── auth.py
│   │   │   ├── transport.py
│   │   │   ├── validators.py
│   │   │   └── serializers.py
│   │   │
│   │   ├── google/             # Google API Base Adapter (FROZEN)
│   │   │   ├── google_api_adapter.py
│   │   │   ├── models.py
│   │   │   ├── errors.py
│   │   │   ├── urls.py
│   │   │   ├── pagination.py
│   │   │   ├── services.py
│   │   │   └── gmail/          # Gmail Adapter (FROZEN)
│   │   │       ├── gmail_adapter.py
│   │   │       ├── models.py
│   │   │       ├── errors.py
│   │   │       ├── mime.py
│   │   │       ├── queries.py
│   │   │       └── __init__.py
│   │   │
│   │   └── email/              # Email Composition Engine (FROZEN)
│   │       ├── models.py
│   │       ├── composer.py
│   │       ├── draft.py
│   │       ├── renderer.py
│   │       ├── templates.py
│   │       ├── template_registry.py
│   │       ├── branding.py
│   │       ├── mailbox.py
│   │       ├── attachments.py
│   │       ├── exceptions.py
│   │       └── __init__.py
│   │
│   ├── execution/              # Execution Runtime (FROZEN)
│   │   ├── base_adapter.py
│   │   ├── adapter_registry.py
│   │   ├── dispatcher.py
│   │   ├── scheduler.py
│   │   ├── execution_context.py
│   │   ├── execution_models.py
│   │   ├── execution_pipeline.py
│   │   ├── event_bus.py
│   │   ├── state_machine.py
│   │   ├── metrics_collector.py
│   │   ├── recovery_manager.py
│   │   ├── enums.py
│   │   ├── exceptions.py
│   │   ├── utils.py
│   │   └── validation.py
│   │
│   ├── communication/          # Communication provider layer
│   │   ├── provider_base.py
│   │   ├── provider_registry.py
│   │   ├── provider_models.py
│   │   ├── provider_events.py
│   │   ├── provider_normalizer.py
│   │   ├── communication_store.py
│   │   ├── gmail_provider.py
│   │   ├── gmail_sync.py
│   │   └── gmail_webhooks.py
│   │
│   ├── outbound/               # Outbound email engine
│   │   ├── outbound_base.py
│   │   ├── outbound_models.py
│   │   ├── outbound_registry.py
│   │   ├── outbound_executor.py
│   │   ├── outbound_scheduler.py
│   │   ├── outbound_persistence.py
│   │   ├── outbound_events.py
│   │   ├── gmail_outbound.py
│   │   └── draft_store.py
│   │
│   ├── providers/              # Lead data providers
│   │   ├── base_provider.py
│   │   ├── apollo_provider.py
│   │   ├── synthetic_provider.py
│   │   └── provider_factory.py
│   │
│   ├── enrichment/             # Lead enrichment
│   │   ├── base_enricher.py
│   │   ├── apollo_enricher.py
│   │   ├── synthetic_enricher.py
│   │   └── enrichment_factory.py
│   │
│   ├── reasoning/              # Reasoning engine
│   │   ├── reasoning_pipeline.py
│   │   ├── reasoning_models.py
│   │   ├── confidence_engine.py
│   │   ├── policy_engine.py
│   │   ├── priority_engine.py
│   │   ├── goal_selector.py
│   │   └── risk_assessor.py
│   │
│   ├── planner/                # Planning engine
│   │   ├── planning_pipeline.py
│   │   ├── planning_models.py
│   │   ├── plan_validator.py
│   │   ├── task_generator.py
│   │   ├── scheduling_engine.py
│   │   ├── branching_engine.py
│   │   ├── dependency_builder.py
│   │   ├── approval_engine.py
│   │   ├── payloads.py
│   │   ├── exceptions.py
│   │   └── strategies/         # Planning strategies
│   │       ├── strategy_base.py
│   │       ├── planning_registry.py
│   │       ├── cold_outreach.py
│   │       ├── follow_up.py
│   │       ├── demo_booking.py
│   │       ├── nurture.py
│   │       ├── re_engagement.py
│   │       ├── escalation.py
│   │       ├── pricing_objection.py
│   │       └── general_engagement.py
│   │
│   ├── reply_generation/       # AI reply generation
│   │   ├── generation_pipeline.py
│   │   ├── generation_models.py
│   │   ├── generation_context.py
│   │   ├── provider_base.py
│   │   ├── provider_registry.py
│   │   ├── prompt_builder.py
│   │   ├── style_engine.py
│   │   ├── template_library.py
│   │   ├── validation.py
│   │   └── providers/
│   │       ├── openai_provider.py
│   │       ├── anthropic_provider.py
│   │       ├── gemini_provider.py
│   │       └── deepseek_provider.py
│   │
│   ├── conversation_intelligence/  # Intelligence layer
│   │   ├── intelligence_pipeline.py
│   │   ├── intelligence_models.py
│   │   ├── buying_signal_detector.py
│   │   ├── intent_extractor.py
│   │   ├── entity_extractor.py
│   │   ├── objection_detector.py
│   │   ├── conversation_scoring.py
│   │   ├── conversation_summary.py
│   │   ├── conversation_memory.py
│   │   └── knowledge/
│   │       ├── registry.py
│   │       ├── patterns.py
│   │       ├── technologies.py
│   │       ├── companies.py
│   │       ├── budgets.py
│   │       ├── normalization.py
│   │       ├── scoring_config.py
│   │       ├── meeting_patterns.py
│   │       ├── titles.py
│   │       ├── timelines.py
│   │       ├── confidence.py
│   │       ├── objections.py
│   │       └── buying_signals.py
│   │
│   ├── conversations/          # Conversations subsystem
│   │   ├── conversation_models.py
│   │   ├── conversation_store.py
│   │   ├── classification.py
│   │   ├── integration.py
│   │   ├── followup_planner.py
│   │   ├── state_machine.py
│   │   └── timeline.py
│   │
│   ├── intelligence/           # Intelligence layer
│   │   └── lead_intelligence.py
│   │
│   ├── job_engine/             # Async job infrastructure
│   │   ├── models.py
│   │   ├── registry.py
│   │   ├── manager.py
│   │   ├── runner.py
│   │   └── storage.py
│   │
│   └── channel_adapters/       # Client-specific adapters
│       └── telegram.py
│
├── tests/                      # Test suite (2674 tests)
│   ├── conftest.py             # Fixtures
│   ├── test_adapter_sdk.py
│   ├── test_http_adapter.py
│   ├── test_google_api_adapter.py
│   ├── test_gmail_adapter.py
│   ├── test_email_composition_engine.py
│   ├── test_execution_foundation.py
│   ├── test_execution_adapter_registry.py
│   ├── test_execution_dispatcher.py
│   ├── test_execution_scheduler.py
│   ├── test_execution_loop.py
│   ├── test_event_bus.py
│   ├── test_metrics_collector.py
│   ├── test_recovery_manager.py
│   ├── test_retry_engine.py
│   ├── test_capability_system.py
│   ├── test_credential_framework.py
│   ├── test_provider_layer.py
│   ├── test_adapter_registry_integration.py
│   ├── test_planner.py
│   ├── test_workflow_planner.py
│   ├── test_workflow_executor.py
│   ├── test_workflow_phase2b.py
│   ├── test_outbound_engine.py
│   ├── test_communication_intelligence.py
│   ├── test_copilot_api.py
│   └── test_reasoner_integration.py
│
├── docs/                       # Documentation
│   ├── AGENTS.md               # AI agent handoff (workspace level)
│   ├── ARCHITECTURE_FREEZE.md
│   ├── ADAPTER_SDK_FOUNDATION_FREEZE.md
│   ├── ADAPTER_REGISTRY_FREEZE.md
│   ├── CAPABILITY_SYSTEM_FREEZE.md
│   ├── CREDENTIAL_FRAMEWORK_FREEZE.md
│   ├── HTTP_ADAPTER_FREEZE.md
│   ├── GOOGLE_API_ADAPTER_FREEZE.md
│   ├── GMAIL_ADAPTER_FREEZE.md
│   ├── EMAIL_COMPOSITION_ENGINE_FREEZE.md
│   ├── ENGINEERING_STATE.md   # This document
│   ├── PLATFORM_v1.1_RELEASE.md
│   ├── FINANCIAL_SIMULATOR.md
│   ├── email-composition-engine.md
│   ├── gmail-adapter-report.md
│   ├── http-adapter-report.md
│   ├── google-api-adapter-report.md
│   └── ... (additional implementation reports)
│
├── supabase/                   # Database migrations
│   ├── multi_client_mvp.sql    # Main schema
│   └── migrations/
│       └── 003_job_engine.sql  # Jobs + search_results tables
│
├── data/                       # Runtime data
│   └── workflows/              # Persisted workflow state (JSON)
│
└── state/                      # Session state
    └── memory.py               # Per-chat_id session tracking
```

---

## 6. Implemented Components

### Adapter System (FROZEN v1.0 — Layers 1–5)

| Component | Files | Purpose | Dependencies | Used By | Status |
|---|---|---|---|---|---|
| Execution Runtime | `execution/` (15 files) | Event-driven state machine for async execution | None | All adapters | FROZEN |
| Adapter SDK | `adapters/base_adapter.py`, `adapter_context.py`, `models.py`, `exceptions.py`, `protocols.py` | `ExecutionAdapter` contract, immutable models | None | All adapters | FROZEN |
| Capability System | `adapters/capabilities.py`, `capability_registry.py` | Maps verbs to adapters | Adapter SDK | Planner, Dispatcher | FROZEN |
| Credential Framework | `adapters/credentials.py`, `credential_registry.py`, `credential_resolver.py` | Credential metadata, resolver | Adapter SDK | All adapters | FROZEN |
| Adapter Registry | `adapters/adapter_registry.py`, `adapter_factory.py`, `adapter_registration.py` | Adapter registration, factory | Adapter SDK, Capability System | Execution Runtime | FROZEN |

### Production Adapters (FROZEN v1.0 — Platform v1.1)

| Component | Files | Purpose | Dependencies | Tests | Status |
|---|---|---|---|---|---|
| HTTP Adapter | `adapters/http/` (7 files) | Generic REST client with auth (Bearer, Basic, API Key) | Execution Runtime, Adapter SDK, httpx | 314 | FROZEN |
| Google API Base Adapter | `adapters/google/` (6 files) | Google service discovery, URL building, error mapping | Execution Runtime, HTTP Adapter | 169 | FROZEN |
| Gmail Adapter | `adapters/google/gmail/` (6 files) | Gmail send, list, get, search, labels, threads | Google API Base Adapter, MimeMessage | 162 | FROZEN |
| Email Composition Engine | `email/` (11 files) | Provider-agnostic draft composition, templates, branding | None (provider-agnostic) | 174 | FROZEN |

### Legacy / Non-Frozen Components

| Component | Files | Purpose | Status |
|---|---|---|---|
| Conversation Engine | `conversation_engine.py` | Multi-client message routing, workflow dispatch | Operational |
| Workflow System | `workflow_*.py` (14 files) | Deterministic multi-step plan execution | Operational |
| AI Generation | `ai.py` | OpenAI prompt execution | Operational |
| Google Auth | `google_auth.py` | OAuth2 flow, token management | Operational |
| Supabase Client | `supabase.py` | All DB operations | Operational |
| Reply Generation | `reply_generation/` (12 files) | Multi-provider AI reply generation | Operational |
| Conversation Intelligence | `conversation_intelligence/` (14+ files) | Intent, entity, objection detection | Operational |
| Lead Providers | `providers/` (4 files) | Apollo, synthetic lead sourcing | Operational |
| Enrichment | `enrichment/` (4 files) | Apollo enrichment | Operational |
| Outbound Engine | `outbound/` (8 files) | Draft scheduling, execution | Operational |
| Communication | `communication/` (8 files) | Gmail sync, webhooks | Operational |
| Planning Engine | `planner/` (11+ files) | Strategy selection, approval workflow | Operational |
| Reasoning Engine | `reasoning/` (7 files) | Confidence, policy, risk assessment | Operational |
| Job Engine | `job_engine/` (5 files) | Async job infrastructure | Operational |

---

## 7. Adapter Status

| Adapter | Purpose | Status | Completion | Remaining Work |
|---|---|---|---|---|
| **Execution Runtime** | State machine, dispatcher, event bus, scheduler, recovery, metrics | **FROZEN v1.0** | 100% | None |
| **Adapter SDK Foundation** | `ExecutionAdapter` contract, immutable models, protocols | **FROZEN v1.0** | 100% | None |
| **Capability System** | Capability definitions, registry, metadata | **FROZEN v1.0** | 100% | None |
| **Credential Framework** | Credential models, registry, resolver | **FROZEN v1.0** | 100% | None |
| **Adapter Registry** | Registration, factory, integration | **FROZEN v1.0** | 100% | None |
| **HTTP Adapter** | Generic HTTP REST with auth handlers | **FROZEN v1.0** | 100% | Streaming, multipart, WebSocket (RFC-required changes) |
| **Google API Base Adapter** | Google service discovery, URL building, error mapping | **FROZEN v1.0** | 100% | None |
| **Gmail Adapter** | Gmail send/list/get/search/labels/threads | **FROZEN v1.0** | 100% | Drafts, attachments, filters, watch (RFC-required) |
| **Email Composition Engine** | Provider-agnostic draft composition with templates/branding | **FROZEN v1.0** | 100% | None |
| **Calendar Adapter** | Google Calendar operations | **NOT STARTED** | 0% | Full implementation |
| **Drive Adapter** | Google Drive operations | **NOT STARTED** | 0% | Full implementation |
| **Outlook Adapter** | Microsoft 365 email | **NOT STARTED** | 0% | Full implementation |
| **SMTP Adapter** | Direct SMTP sending | **NOT STARTED** | 0% | Full implementation |
| **SendGrid Adapter** | SendGrid integration | **NOT STARTED** | 0% | Full implementation |
| **SES Adapter** | Amazon SES integration | **NOT STARTED** | 0% | Full implementation |
| **Resend Adapter** | Resend.com integration | **NOT STARTED** | 0% | Full implementation |

---

## 8. Important Design Decisions

### 8.1 Adapter Architecture

**Why Adapter Registry exists:** The registry decouples adapter registration from adapter instantiation. It stores only metadata (name, version, capabilities). The factory creates instances on demand and never caches. This prevents stale adapter state and makes dependency injection explicit.

**Why Capability System exists:** The planner operates on verbs (what needs to happen), not implementations (which adapter to use). The Capability Registry maps capabilities to adapters, enabling the planner to write `send_email` and have the runtime resolve the correct adapter. This is the foundation for multi-provider support.

**Why Credential Framework exists:** Adapters never fetch credentials themselves. The Credential Resolver injects credentials at execution time. Adaptors receive tokens, not the ability to fetch them. This ensures secrets never leak in text output and credentials can be rotated without adapter changes.

**How adapters communicate:** Adapters do not call each other directly. The Execution Runtime orchestrates all adapter calls through the Dispatcher. Each adapter receives an `AdapterContext` and returns an `AdapterResult`. Higher-level adapters (like GmailAdapter) own lower-level adapters (like GoogleApiAdapter) via composition, but the invocation still flows through the runtime.

**How providers are abstracted:** Provider abstraction uses two patterns:
1. **Adapter Pattern** (for APIs) — `ExecutionAdapter` base class with `execute(context)` method
2. **Factory Pattern** (for data providers) — `ProviderFactory` / `EnrichmentFactory` creates the configured provider

### 8.2 Execution Runtime

- **State Machine is the sole owner of state transitions** — no other component can mutate execution state
- **Scheduler is retry-unaware** — retry is handled by a separate `RetryEngine`, not the scheduler
- **Dispatcher is adapter-independent** — it routes by capability, never by adapter name
- **Event Bus is generic infrastructure** — events are typed but the bus has no domain knowledge
- **Metrics are passive** — they observe and record but never influence execution decisions

### 8.3 Adapter SDK

- `ExecutionAdapter` is the sole contract — all adapters implement `async def execute(context) -> AdapterResult`
- Models are immutable frozen dataclasses — no mutable state in the adapter layer
- Adapters are stateless — all state lives in the Runtime
- Exceptions separate retryable from fatal cleanly via `should_retry`

### 8.4 HTTP Adapter

- Generic-only — no domain knowledge about any API
- Transport abstraction via `HttpTransport` protocol (production: `HttpxTransport`)
- Auth injected, not fetched — adapter receives tokens, never requests them
- Streaming, multipart upload, WebSocket explicitly excluded from v1.0 (RFC-required)

### 8.5 Google API Base Adapter

- Service-agnostic — the same adapter works for Gmail, Calendar, Drive, etc.
- Delegates all HTTP to `HttpAdapter` — no HTTP logic
- URLs built from service descriptors, not hardcoded
- Structured error mapping — handles Google-specific error responses
- OAuth2 token injected (not fetched) — credential resolver provides it

### 8.6 Gmail Adapter

- Thin domain layer only — translates Gmail concepts to API calls
- No HTTP logic duplicated — all execution flows through `GoogleApiAdapter`
- `GmailResourceMapper` handles JSON→model conversion, keeping the adapter focused on orchestration
- Authentication and quota errors propagate from Google layer unchanged

### 8.7 Email Composition Engine

- Provider-agnostic — zero imports from Google, HTTP, or any vendor
- Future providers (Outlook, SMTP) reuse 100% of this layer
- `draft_to_gmail_params()` converts `EmailDraft` → Gmail-compatible params dict
- Templates are pure Python functions (no template engine dependency)
- All models are frozen and immutable

### 8.8 Conversation Engine Architecture

- Multi-client orchestration — Telegram and Web share the same conversation engine
- Deterministic workflow execution — no DAGs, no dynamic branching at runtime
- File-based persistence for workflow crash recovery (JSON in `data/workflows/`)
- Conversation intelligence is pipeline-based: intent → signals → stage → memory → response

### 8.9 Things That Should NEVER Be Changed Without Careful Consideration

1. **`ExecutionAdapter.execute(context)` contract** — changing the adapter interface breaks every adapter
2. **Adapter statelessness** — if adapters hold state, the runtime cannot recover them
3. **Frozen layer boundaries** — modifying a frozen layer requires an RFC and platform phase approval
4. **Credential injection model** — adapters must never fetch credentials themselves
5. **Capability-based dispatch** — the planner must think in verbs, not implementations
6. **Single-player-first architecture** — team collaboration features must not compromise the single-player experience

---

## 9. APIs

### REST Endpoints (all in `main.py`)

| Route | Method | Purpose | Request | Response | Dependencies | Status |
|---|---|---|---|---|---|---|
| `/` | GET | Health check | None | `"Loqi backend running"` | None | Operational |
| `/health` | GET | Detailed health | None | JSON with uptime, DB, providers | Supabase | Operational |
| `/webhook` | POST | Telegram webhook | Telegram Update | `{"ok": true}` | conversation_engine | Operational |
| `/api/auth/gmail/url` | GET | Gmail OAuth URL | None | `{"url": "...", "state": "..."}` | google_auth | Operational |
| `/api/auth/gmail/callback` | GET | Gmail OAuth callback | code, state | Redirect | google_auth, gmail_provider | Operational |
| `/api/web/session` | POST | Create web session | None | `{"session_token": "..."}` | conversation_store | Operational |
| `/api/web/session/{token}` | GET | Session summary | path param | JSON session | conversation_store | Operational |
| `/api/web/session/{token}/messages` | GET | List messages | path param | JSON messages | conversation_store | Operational |
| `/api/web/session/{token}/messages` | POST | Send message | `{text, copilot_context}` | JSON response | conversation_engine | Operational |
| `/api/web/session/{token}/batch-draft` | POST | Start batch draft gen | `{campaign, count}` | `{batch_id}` | job_engine | Operational |
| `/api/web/session/{token}/batch-status/{id}` | GET | Poll batch status | path params | `{status, progress}` | job_engine | Operational |
| `/api/web/session/{token}/drafts` | GET | List drafts | path param | JSON drafts | outbound | Operational |
| `/api/web/session/{token}/drafts/{id}` | PUT | Update draft | path + body | JSON draft | outbound | Operational |
| `/api/web/session/{token}/drafts/{id}/refine` | POST | Refine draft | path + body | JSON draft | rewrite_engine | Operational |
| `/api/web/session/{token}/drafts/analyze` | POST | Analyze draft | `{draft_id}` | JSON scores | draft_intelligence | Operational |
| `/api/web/session/{token}/drafts/ask` | POST | Ask about draft | `{question, draft_id}` | JSON answer | ai.py | Operational |
| `/api/web/session/{token}/analyze-campaigns` | POST | Analyze campaigns | JSON leads | JSON campaigns | campaign_planner | Operational |

### Adapter API (internal, not exposed as REST)

| Operation | Adapter | Purpose | Status |
|---|---|---|---|
| `google_request` | GoogleApiAdapter | Generic Google API call | FROZEN |
| `gmail_send_email` | GmailAdapter | Send email via Gmail | FROZEN |
| `gmail_list_messages` | GmailAdapter | List Gmail messages | FROZEN |
| `gmail_get_message` | GmailAdapter | Get single message | FROZEN |
| `gmail_search_messages` | GmailAdapter | Search messages | FROZEN |
| `gmail_list_labels` | GmailAdapter | List labels | FROZEN |
| `gmail_get_label` | GmailAdapter | Get single label | FROZEN |
| `gmail_list_threads` | GmailAdapter | List threads | FROZEN |
| `gmail_get_thread` | GmailAdapter | Get single thread | FROZEN |

### WebSocket / Async APIs

None implemented. The web chat uses polling (`batch-status`) for async job results.

---

## 10. Database

### Current Database

| Detail | Value |
|---|---|
| **Engine** | Supabase (PostgreSQL) |
| **ORM** | None — raw SQL via `supabase-py` client |
| **Client** | `services/supabase.py` — wraps Supabase client |
| **Migrations** | Manual SQL files in `supabase/` |
| **Runtime migrations** | `services/migration.py` creates `jobs` and `search_results` tables on startup |

### Existing Tables

The main schema is in `supabase/multi_client_mvp.sql`. Key tables:
- `users` — User accounts with Google OAuth tokens
- `leads` — Stored leads per user with enrichment data
- `conversations` — Conversation sessions
- `messages` — Individual messages within conversations
- `workflow_sessions` — Workflow session tracking
- `provider_credentials` — Persisted Gmail provider tokens for startup recovery
- `jobs` — Async job tracking (created by migration.py)
- `search_results` — Job search results (created by migration.py)

Additional tables from schema:
- Communication provider states
- Various preference/session tables

### Missing Tables

(Based on product design documentation — not yet implemented):
- `subscriptions` / `plans` — No billing system
- `brand_kits` — Brand kits not yet persisted (in-memory only in EmailCompositionEngine)
- `mailboxes` — Company mailboxes not yet persisted (in-memory only)
- `discovery_credits` — Credit balance tracking not implemented
- `campaigns` — Campaign persistence (partially exists in workflow sessions)
- `analytics_events` — No analytics pipeline
- `template_registry` — Template metadata not persisted

### Pending Work

- No Alembic or formal migration framework
- Migration runner is minimal (creates 2 tables, no version tracking)
- No seed data management
- No audit logging

---

## 11. Authentication

| Detail | Value |
|---|---|
| **OAuth Provider** | Google OAuth 2.0 only |
| **Flow** | `services/google_auth.py` — generate auth URL → user authorizes → exchange code for tokens → refresh as needed |
| **Endpoints** | `/api/auth/gmail/url` (GET URL), `/api/auth/gmail/callback` (OAuth callback) |
| **Token Storage** | `services/supabase.py` — `save_google_tokens()`, `update_google_access_token()` |
| **Provider Credentials** | `save_provider_credentials()`, `load_all_provider_credentials()` — persisted for startup recovery |
| **Adapter Credentials** | `services/adapters/credentials.py` — credential models; `credential_resolver.py` injects tokens at execution time |
| **HTTP Auth** | `services/adapters/http/auth.py` — Bearer token, Basic Auth, API Key header handlers |
| **JWT** | Not implemented |
| **Sessions** | Simple token-based sessions for web chat (no JWT, no session persistence) |
| **Multi-user** | Not supported — single user per workspace |

### Status

- Google OAuth 2.0 is **operational** with automatic token refresh and cross-restart persistence
- No user authentication system exists beyond Gmail OAuth
- No JWT, no API keys for programmatic access
- No role-based access control
- No session management beyond simple token creation
- Credential framework for adapters is **FROZEN** — architecture is complete but the resolver is not yet wired to the production auth flow

---

## 12. Current TODO

There is **no active phase**. Platform v1.1 is complete and frozen. The next implementation phase has not been started.

If starting a new phase, the following would need to be done:

### Immediate (0-2 weeks)

- [ ] Choose the next adapter to implement (Calendar recommended — see Section 15)
- [ ] Create phase specification document
- [ ] Initialize adapter package structure following the Gmail pattern
- [ ] Register capability descriptors
- [ ] Write test skeleton

### Next Adapter Implementation (Calendar / Drive / Outlook)

- [ ] Create `services/adapters/google/calendar/` package
- [ ] Implement `CalendarAdapter(ExecutionAdapter)` with core operations
- [ ] Implement request/response models
- [ ] Implement error mapping
- [ ] Register credential descriptor (reuse `google_oauth2`)
- [ ] Register capability descriptors
- [ ] Write 150-200 tests
- [ ] Create freeze document
- [ ] Run full test suite

### Production Hardening

- [ ] Wire credential resolver to production auth flow
- [ ] Implement Alembic for schema migrations
- [ ] Add audit logging
- [ ] Implement Analytics module (KPIs, dashboards)
- [ ] Implement Billing system (subscriptions, credits, payment processing)

---

## 13. Known Technical Debt

### Temporary Implementations

| Item | Location | Issue |
|---|---|---|
| Legacy Gmail send | `services/gmail.py` | Pre-adapter implementation still exists alongside new GmailAdapter. Should be replaced by adapter calls. |
| Legacy Google Auth | `services/google_auth.py` | Pre-adapter OAuth flow. The credential framework can potentially replace this. |
| In-memory BrandKit/Mailbox storage | `services/email/branding.py`, `mailbox.py` | Brand kits and mailboxes are registered in memory only — no persistence across restarts. |
| JSON file-based workflow persistence | `services/workflow_persistence.py` | Does not scale beyond single-instance. Should use database for multi-instance deployments. |

### Workarounds

| Item | Location | Issue |
|---|---|---|
| Supabase `SyncPostgrestClient` deprecation | Many | The `verify` parameter is deprecated but still used. Minor. |
| httpx `content` parameter deprecation | `http_adapter.py` | Uses deprecated `response.content` pattern in some places. Fixed in Platform v1.1 for most cases. |

### TODOs in Code

(Scattered throughout — no centralized TODO tracking)

### Intentionally Postponed

| Item | Why Postponed |
|---|---|
| Streaming support in HTTP Adapter | RFC-required change. Not needed until large file transfers. |
| Multipart upload | RFC-required. Not needed until attachment sending through adapters. |
| WebSocket support | Not needed — web chat uses polling. |
| Alembic migrations | Schema is small enough for manual SQL. Will need formal migrations as team grows. |
| Multi-tenancy | Product decision: Single Player First. Teams start at Scale plan. |
| Analytics dashboard | No BI infrastructure yet. Post-MVP. |
| Billing system | No subscriptions yet. Post-MVP. |
| Cache layer for adapters | Runtime owns caching per architecture. Not implemented. |
| Rate limiting per adapter | Runtime owns rate limiting per architecture. Not implemented. |

### Refactors Needed Later

| Refactor | Why |
|---|---|
| Replace `services/gmail.py` with GmailAdapter | Legacy code should be removed once the adapter is wired into the conversation engine |
| Replace `services/google_auth.py` with Credential Resolver | Auth flow should use the new credential framework |
| Remove `services/workflow_persistence.py` file-based persistence | Replace with database-backed persistence for multi-instance |
| Consolidate conversation services | Multiple conversation files (`conversation_*.py`) have overlapping responsibilities |

---

## 14. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **GmailAdapter not yet wired to conversation engine** | MEDIUM | MEDIUM | The adapter exists and is tested but the legacy `gmail.py` is still the active email sender. An integration step is needed. |
| **Credential resolver not wired to production auth** | MEDIUM | HIGH | The credential resolver is frozen but not connected to the actual OAuth flow. Auth still goes through `google_auth.py`. |
| **In-memory email composition state** | LOW | MEDIUM | Brand kits and mailboxes are lost on restart. Need persistence before production. |
| **No Alembic migrations** | LOW | MEDIUM | Schema changes are manual. Risk of drift as team grows. |
| **JSON file persistence doesn't scale** | LOW | MEDIUM | `data/workflows/` JSON persistence breaks with multiple server instances. |
| **Supabase client deprecation warnings** | LOW | LOW | Third-party library issues, not our code. Monitor. |
| **Conversation engine (1161 lines) is a monolith** | MEDIUM | HIGH | The central orchestrator is large and has many responsibilities. Refactoring risk is high. |
| **No rate limiting on AI calls** | MEDIUM | HIGH | Fair use model exists in design but no enforcement is implemented. Abuse could spike costs. |
| **No churn or upgrade tracking** | LOW | MEDIUM | Cannot validate financial simulator assumptions without telemetry. |
| **OAuth token expiry handling** | MEDIUM | HIGH | Auto-refresh exists but edge cases (concurrent refresh, revoked tokens) are not tested. |
| **Performance under heavy workflow concurrency** | LOW | MEDIUM | Workflow runtime uses threading. Lock contention at scale is untested. |

---

## 15. Next Phase

### Recommended: Calendar Adapter (Phase 5.6)

**Why it comes next:**
1. Google Calendar is the next natural Google API after Gmail — same `GoogleApiAdapter` dependency, same `google_oauth2` credential
2. Calendar integration is needed for meeting scheduling, demo booking, and the follow-up engine
3. Follows the exact same pattern as GmailAdapter — low risk, high reuse
4. Uses the same frozen foundation layers — no platform changes needed

**Prerequisites:**
- Platform v1.1 (done — FROZEN)
- Google API Base Adapter (done — FROZEN)
- Gmail Adapter as reference implementation (done — FROZEN)

**Expected outputs:**
- `services/adapters/google/calendar/` package
- `CalendarAdapter(ExecutionAdapter)` with operations: list events, get event, create event, update event, delete event, list calendars
- Request/response models for Calendar API
- Calendar-specific error mapping
- CalendarResourceMapper for JSON→model conversion
- 150–200 tests
- `CALENDAR_ADAPTER_FREEZE.md`
- Freeze declaration

### Outlook / SMTP / SendGrid (Phase 6.x)

Alternative: Build the first non-Google adapter (Outlook) to validate the provider-agnostic email composition engine. This would require a new `ExecutionAdapter` family for Microsoft Graph API.

**Prerequisites:**
- Email Composition Engine (done — FROZEN)
- HTTP Adapter (done — FROZEN)
- OAuth credential support for Microsoft

### Production Hardening (Phase 4.x)

Alternative focus: Wire adapters into production, add billing, analytics, and monitoring.

**Prerequisites:**
- All desired adapters built
- Auth resolver wired to production

---

## 16. Resume Instructions

This section is for an AI agent receiving ONLY this document.

### Where Implementation Stopped

Implementation stopped after **Phase 5.5 — Email Composition Engine v1.0** was completed and frozen as part of **Platform v1.1**. The repository is tagged `platform-v1.1.0`. All 2674 tests pass with 0 failures.

### What Has Already Been Built

#### Frozen (do NOT modify)

1. **Execution Runtime** (`services/execution/`) — state machine, dispatcher, scheduler, event bus, metrics, recovery
2. **Adapter SDK Foundation** (`services/adapters/base_adapter.py`, etc.) — `ExecutionAdapter` contract, immutable models
3. **Capability System** (`services/adapters/capabilities.py`, `capability_registry.py`) — capability definitions and registry
4. **Credential Framework** (`services/adapters/credentials.py`, `credential_registry.py`, `credential_resolver.py`) — credential models and resolver
5. **Adapter Registry** (`services/adapters/adapter_registry.py`, `adapter_factory.py`, `adapter_registration.py`) — registration and factory
6. **HTTP Adapter** (`services/adapters/http/`) — generic REST client with auth handlers (314 tests)
7. **Google API Base Adapter** (`services/adapters/google/`) — Google service discovery layer (169 tests)
8. **Gmail Adapter** (`services/adapters/google/gmail/`) — Gmail operations, MIME builder, query builder (162 tests)
9. **Email Composition Engine** (`services/email/`) — provider-agnostic draft composition, 6 HTML templates, branding, mailboxes, attachments (174 tests)

#### Non-Frozen (can be modified, but careful)

10. **Conversation Engine** (`services/conversation_engine.py`) — multi-client orchestrator (1161 lines)
11. **Workflow System** (`services/workflow_*.py`, 14 files) — deterministic plan execution
12. **AI Generation** (`services/ai.py`) — OpenAI integration
13. **Legacy Gmail** (`services/gmail.py`) — pre-adapter Gmail send (should eventually be replaced)
14. **Google Auth** (`services/google_auth.py`) — OAuth flow (should eventually use credential framework)
15. **Supabase Client** (`services/supabase.py`) — all DB operations
16. **Conversation Intelligence** (`services/conversation_intelligence/`) — knowledge registry, detection pipelines
17. **Reply Generation** (`services/reply_generation/`) — multi-provider AI replies (OpenAI, Anthropic, Gemini, DeepSeek)
18. **Lead Sourcing** (`services/providers/`, `services/enrichment/`) — Apollo provider + factory pattern
19. **Planning Engine** (`services/planner/`) — 8 outreach strategies, approval workflow
20. **Reasoning Engine** (`services/reasoning/`) — confidence, policy, risk, priority
21. **Outbound Engine** (`services/outbound/`) — draft scheduling, execution, persistence
22. **Communication Layer** (`services/communication/`) — Gmail provider, sync, webhooks
23. **Job Engine** (`services/job_engine/`) — async job infrastructure
24. **Channel Adapters** (`services/channel_adapters/telegram.py`) — Telegram adapter
25. **REST API** (`main.py`) — ~18 endpoints for health, auth, web chat, drafts, campaigns

### What Must NOT Be Rebuilt

- **Do NOT rebuild the adapter platform.** Layers 1-5 are frozen and production-quality.
- **Do NOT rebuild Gmail API integration.** GmailAdapter is complete and frozen.
- **Do NOT rebuild the email composition engine.** It is complete, tested, and provider-agnostic.
- **Do NOT rebuild HTTP transport.** HttpAdapter is frozen and covers REST, auth, and serialization.
- **Do NOT rebuild the conversation intelligence knowledge registry.** It contains carefully curated patterns.
- **Do NOT add billing, analytics, or multi-tenancy to the current phase.** These are deferred by design.

### Assumptions Already Finalized

- `ExecutionAdapter.execute(context)` is the sole adapter contract — do not change it
- Adapters are stateless — all state lives in the runtime
- Adapters never fetch credentials — they are injected
- The planner dispatches by capability (verb), not adapter name
- Email composition is provider-agnostic — zero vendor imports in `services/email/`
- New Google API adapters follow the GmailAdapter pattern (delegate to `GoogleApiAdapter`)
- New non-Google adapters (Outlook, SMTP) implement `ExecutionAdapter` directly and use `HttpAdapter` for transport
- Models are frozen dataclasses throughout the adapter layer

### What Should Be Implemented Next

**Recommended: Calendar Adapter (Phase 5.6)**

1. Create `services/adapters/google/calendar/` package
2. Implement `CalendarAdapter(ExecutionAdapter)` with operations:
   - `calendar_list_events` — list events with date range
   - `calendar_get_event` — get single event by ID
   - `calendar_create_event` — create new event
   - `calendar_update_event` — update existing event
   - `calendar_delete_event` — delete event
   - `calendar_list_calendars` — list accessible calendars
3. Implement Calendar-specific models:
   - `ListEventsRequest`, `GetEventRequest`, `CreateEventRequest`, `UpdateEventRequest`, `DeleteEventRequest`, `ListCalendarsRequest`
   - `EventSummary`, `CalendarSummary`
   - `CalendarResourceMapper`
4. Implement Calendar-specific error mapping
5. Register capability descriptors + credential descriptor (reuse `google_oauth2`)
6. Write 150-200 tests following the GmailAdapter test patterns
7. Create `CALENDAR_ADAPTER_FREEZE.md`
8. Run full test suite (2674+ tests must pass)
9. Tag next platform release

**Pattern to follow for the implementation:**

```python
# services/adapters/google/calendar/calendar_adapter.py
from services.adapters.base_adapter import ExecutionAdapter
from services.adapters.google.google_api_adapter import GoogleApiAdapter

class CalendarAdapter(ExecutionAdapter):
    def __init__(self, google_adapter: GoogleApiAdapter | None = None):
        self._google = google_adapter or GoogleApiAdapter()
        self._mapper = CalendarResourceMapper()

    async def execute(self, context: AdapterContext) -> AdapterResult:
        dispatch = {
            "calendar_list_events": self._list_events,
            # ...
        }
        handler = dispatch.get(context.action)
        return await handler(context)
```

**Do NOT modify any frozen files** during Calendar Adapter implementation. The frozen files are listed in the freeze documents under `backend/docs/`. Any violation must be flagged before making changes.

### Configuration / Env

The `.env` file contains:
- `SUPABASE_URL` / `SUPABASE_KEY` — Supabase credentials
- `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` — AI provider keys
- `TELEGRAM_TOKEN` — Telegram bot token
- `GMAIL_CREDENTIALS` / `GMAIL_TOKEN` — Gmail OAuth config
- `SERPAPI_KEY` — SerpAPI for lead sourcing
- `APOLLO_API_KEY` — Apollo.io for lead data
- `PDL_API_KEY` — People Data Labs for enrichment

Test runner: `pytest` from `backend/` directory with `PYTHONPATH` set to include `backend/`.
