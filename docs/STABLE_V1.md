# Loqi V1 — Conversational Foundation

> **Tag:** `v1-conversation-stable`
> **Branch:** `stable-v1-conversational-foundation`
> **Date:** 2026-07-10

---

## Current Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                     Frontend (Next.js)                    │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  loqi-app.tsx (chat UI + session management)        │ │
│  │  LeadIntelligenceCard.tsx (intelligence display)    │ │
│  └─────────────────────────────────────────────────────┘ │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP (REST)
┌────────────────────────▼────────────────────────────────┐
│                   Backend (FastAPI)                       │
│                                                          │
│  ┌──────────────────────────────────────────────────────┐│
│  │  main.py (routes: session create, messages, status)  ││
│  └──────────────────────────────────────────────────────┘│
│                                                          │
│  ┌──────────────────────────────────────────────────────┐│
│  │  conversation_engine.py (state machine + dispatch)  ││
│  └──────────────────────────────────────────────────────┘│
│                                                          │
│  ┌──────────────────────────────────────────────────────┐│
│  │  workflows.py (orchestration layer)                  ││
│  │  ├── generate_leads → ICP → search → qualify → store││
│  │  ├── draft_message → enrich → intelligence → openai ││
│  │  └── send_outreach → enrich → intelligence → gmail  ││
│  └──────────────────────────────────────────────────────┘│
│                                                          │
│  ┌──────────────┐ ┌──────────┐ ┌──────────────────┐    │
│  │  providers/  │ │enrichment│ │ intelligence/    │    │
│  │  ├─ base     │ │ ├─ base  │ │ lead_intelligence│    │
│  │  ├─ synthetic│ │ ├─ synth │ │ (deterministic)  │    │
│  │  └─ apollo*  │ │ └─ apollo│ └──────────────────┘    │
│  └──────────────┘ └──────────┘                          │
│                                                          │
│  ┌──────────────────────────────────────────────────────┐│
│  │  ai.py (OpenAI generation + intent classification)   ││
│  │  conversational_response_generator.py (intents/verbs)││
│  │  supabase.py (persistence layer)                     ││
│  │  commercial_qualifier.py (relevance scoring)         ││
│  │  lead_provider.py (formatting + dispatch)            ││
│  │  gmail.py (email sending)                            ││
│  └──────────────────────────────────────────────────────┘│
└────────────────────────┬─────────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────────┐
│              Supabase (PostgreSQL)                        │
│  tables: conversations, leads, workflow_sessions,        │
│          workflow_messages, workflow_events, gmail_tokens │
└──────────────────────────────────────────────────────────┘
```

* = stub/not implemented

---

## Working Workflow

The end-to-end conversation flow is verified and stable:

```
User types "hello"
  → Greeting response (conversational welcome)
  → Onboarding prompt ("Tell me what you're offering")

User types "AI automations for restaurant chains"
  → ICP extraction → search expansion → synthetic provider search
  → Commercial qualification → lead list with buying potential ranking
  → "Reply with a number to pick one"

User types "5"
  → Lead selection → enrichment → intelligence scoring
  → Draft generation (OpenAI) → draft preview + refinement options

User types "shorter"
  → Refinement → OpenAI rewrite → updated draft preview

User types "send"
  → Gmail auth check → draft → send confirmation
  (Gmail error expected if not connected — graceful fallback)
```

### Verified Scenarios

| Scenario | Expected | Status |
|---|---|---|
| Fresh greeting | text + prompt | ✅ |
| Combined service+target | lead_list | ✅ |
| Lead selection | draft_preview | ✅ |
| Draft refinement | draft_preview | ✅ |
| Send intent | error (no Gmail) | ✅ |
| "let's go with 5" | lead re-selection (not send) | ✅ |
| "hello" mid-flow | ack + draft options (not restart) | ✅ |

### Key Intent Parsing

- **Send intents:** exact match for one-word triggers (`go`, `send`, `yes`); word-boundary regex for single-word phrases in context; longest-first substring for multi-word phrases (`go ahead`, `send it`, `looks good`)
- **Refine intents:** keyword detection via `conversational_response_generator.py` (`shorter`, `longer`, `more casual`, etc.)
- **Lead selection:** digits 1-20 routed to `select_lead`; `"go with 5"` triggers digit extraction via regex
- **Greeting detection:** pure greetings (`hi`, `hello`, `hey`), prefix matching, casual acknowledgements; mid-flow greetings (when `target` or `selected_lead_id` is set) are acknowledged briefly without restarting the onboarding

---

## Provider Abstraction Status

**Status: Fully abstracted with working synthetic provider**

| Component | Status | Details |
|---|---|---|
| `BaseProvider` (ABC) | ✅ Complete | Canonical lead schema (44 fields), 4 abstract methods (`capabilities`, `health_check`, `search_leads`, `get_lead`, `get_company`) |
| `SyntheticProvider` | ✅ Working | In-memory dataset from `synthetic/output/companies.json`, industry mapping, role/keyword scoring, exclusion filtering |
| `ApolloProvider` | 🔶 Stub | Instantiates but `health_check()` returns `ok: False` |
| `ProviderFactory` | ✅ Complete | Reads `LEAD_PROVIDER` env var (default `"synthetic"`), singleton caching |
| Downstream decoupling | ✅ Complete | No concrete provider imports outside the factory — `lead_provider.py` calls `get_provider()` |

---

## Synthetic Provider Status

**Status: Fully operational**

- Dataset: `synthetic/output/companies.json` (~5000 companies across 15+ industries, ~25000 decision makers)
- Generator: `synthetic/generator.py` — deterministic, seeded, templated generation
- Industry mapping: translates query terms like `"restaurants"` → `"Restaurant"` via `_INDUSTRY_MAP` (25 entries)
- Scoring: `role_score * 10 + keyword_score * 2 + buying_authority * 0.1` with role exclusion filter
- Templates: `synthetic/templates/` — cities, names, industries with pain points, buying signals, tech stacks, events

---

## Enrichment Status

**Status: Fully abstracted with working synthetic enricher**

| Component | Status | Details |
|---|---|---|
| `BaseEnricher` (ABC) | ✅ Complete | Canonical enrichment schema (10 fields), 3 abstract methods |
| `SyntheticEnricher` | ✅ Working | Deterministic, reads from canonical lead fields, confidence from data completeness, no AI calls |
| `ApolloEnricher` | 🔶 Stub | Not yet implemented |
| `EnrichmentFactory` | ✅ Complete | Reads `ENRICHMENT_PROVIDER` env var (default `"synthetic"`), singleton caching |
| Pipeline integration | ✅ Complete | Called by `workflows.py:draft_message` and `send_outreach` before intelligence and draft generation |

---

## Lead Intelligence Status

**Status: Fully operational, deterministic (no LLM)**

- Single file: `backend/services/intelligence/lead_intelligence.py`
- Input: canonical lead dict + optional enrichment
- Output: `fit_score`, `confidence`, `buying_stage` (`awareness`/`consideration`/`decision`), `urgency` (`high`/`medium`/`low`), `decision_authority_summary`, `estimated_business_need`, `objection_risk`, `best_contact_reason`, `recommended_pitch`, `summary`
- All scoring is heuristic/keyword-based — no LLM calls
- Title-based authority detection, keyword-based stage/urgency classification, pain-point-first pitch recommendation
- Integrated into `workflows.py:draft_message` and `send_outreach`

---

## Current Limitations

1. **Gmail integration requires OAuth setup** — send flow errors gracefully if not configured
2. **No live lead provider** — synthetic data only (Apollo stub)
3. **No live enrichment** — synthetic enricher reads existing fields only
4. **No live intelligence** — all deterministic heuristics, no external signals
5. **Single-select only** — users can pick one lead at a time
6. **No campaign persistence** — conversation state is ephemeral per session
7. **No follow-up automation** — one-shot outreach only
8. **No LinkedIn integration**
9. **No webhook/event system** for external integrations
10. **No rate limiting or usage tracking**

---

## Features Intentionally Postponed

These are scoped out of V1 and reserved for V1.5+:

- **Interactive lead cards** — rich, actionable lead cards with toggle/select
- **Bulk lead selection** — multiple leads at once
- **Draft queue** — review/edit/approve drafts in batch
- **Campaign state machine** — multi-step sequences
- **Rich AI cards** — embedded intelligence overlays
- **Preferences memory** — `user_preferences` table exists but Supabase schema is missing
- **Apollo live provider** — API key + search endpoint integration
- **LinkedIn enrichment** — profile scraping
- **Advanced analytics** — conversion tracking, A/B testing
- **Multi-channel send** — LinkedIn, SMS
- **Follow-up sequences** — automated 2nd/3rd touches

---

## Known Technical Debt

1. **`get_session_context()` sets `service` to first user message** — even "hello" becomes the stored service value; downstream code works around this but the data model is inaccurate
2. **`target` field stores lead selection number** — `target = user_messages[1]` can capture "5" instead of the actual audience target; intent parsing mostly works around this
3. **Duplicate service inference blocks** — lines 571-590 and 585-596 of `conversation_engine.py` have redundant/repeated `if parsed_service and not service:` blocks
4. **`import random` inside `handle_message`** — created a Python scoping bug (UnboundLocalError) that required removal; should have been module-level only
5. **`user_preferences` table missing from Supabase schema** — get/save calls return hard errors; no preference memory in V1
6. **No automatic context clearing** — after send, the session retains all context; manual `/restart` required to fully reset
7. **`lead_list_active` string check** — brittle pattern match on last assistant message text
8. **No typing/validation layer** — lead dicts are untyped dicts throughout
9. **Mixed naming conventions** — `parsed_service`/`parsed_target` in some places, `service`/`target` in others
10. **Error recovery is basic** — lead search failures show hardcoded recovery messages without retry logic

---

## Phase 2 Goals

### V1.5 — Interactive Workspace

- Interactive lead cards (click to select, inline intelligence)
- Bulk lead selection with draft queue
- Campaign state machine (draft → review → send → follow-up)
- Rich AI cards with expandable intelligence panels
- Working preferences memory (fix Supabase schema)
- Multi-step conversation workflows (edit → confirm → send)
- Session persistence improvements (context-aware resume)

### V2.0 — Connected Outbound

- Apollo live provider integration
- Gmail send (authentication + send flow fully operational)
- LinkedIn enrichment + outreach
- Analytics dashboard (send rates, reply rates, pipeline)
- Follow-up sequences (automated 2nd/3rd touches)
- Webhook system for external integrations
- Multi-tenant support
- Rate limiting + usage tracking

---

*This document captures the state of the project at the `v1-conversation-stable` tag. It serves as the recovery checkpoint before beginning Phase 2 (Interactive Workspace).*
