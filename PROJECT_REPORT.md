# Loqi — Complete Architecture Report

Generated from the live codebase on 2026-07-10. This report covers every subsystem, service, and configuration file in the repository.

---

## 1. Project Overview

Loqi is an AI-native outbound operating system. It helps users find leads, generate personalized outreach drafts, and send emails — all through a conversational interface (web chat UI or Telegram).

**Current interfaces:** Web chat UI (primary), Telegram (legacy/deprecated)
**Future interfaces:** WhatsApp, Mobile, Slack

Core philosophy: the backend is the product. Interfaces are thin adapters. Business logic lives in the orchestration layer, not in channel-specific code.

---

## 2. Repository Structure

```
loqi-bot/
├── backend/                          # FastAPI Python backend
│   ├── main.py                       # Entry point: routes, webhooks, OAuth callbacks
│   ├── workflows.py                  # Workflow orchestration (generate_leads, draft, send)
│   ├── services/                     # 16 service modules
│   │   ├── agent.py                  # Telegram message entry via ConversationEngine
│   │   ├── ai.py                     # OpenAI generation (intent, draft, rewrite)
│   │   ├── commercial_qualifier.py   # Lead scoring (buyer, authority, drift detection)
│   │   ├── conversation_engine.py    # Multi-client orchestration hub (500+ lines)
│   │   ├── conversation_store.py     # Supabase persistence for workflow sessions
│   │   ├── conversational_response_generator.py  # AI response + fallback pools
│   │   ├── gmail.py                  # Gmail API send (21 lines, minimal)
│   │   ├── google_auth.py            # OAuth2 flow for Gmail
│   │   ├── icp_extractor.py          # Dual-mode ICP extraction (AI + deterministic)
│   │   ├── lead_provider.py          # Lead search orchestration + filtering/ranking
│   │   ├── search_expansion.py       # Semantic search query expansion
│   │   ├── supabase.py               # Supabase client + all CRUD operations
│   │   ├── telegram.py               # Raw Telegram send_message helper
│   │   ├── providers/                # Lead provider abstraction layer
│   │   │   ├── base_provider.py      # Abstract BaseProvider (+ canonical lead schema)
│   │   │   ├── provider_factory.py   # Reads LEAD_PROVIDER, caches singleton
│   │   │   ├── synthetic_provider.py # In-memory index over 5k companies
│   │   │   └── apollo_provider.py    # Stub for future Apollo integration
│   │   └── channel_adapters/         # Thin response formatters
│   │       ├── __init__.py
│   │       └── telegram.py           # Converts engine response dict -> Telegram send
│   ├── state/
│   │   └── memory.py                 # Legacy in-memory session store (DEPRECATED)
│   └── supabase/
│       └── multi_client_mvp.sql      # Database schema (workflow_sessions, messages, events)
│
├── frontend/                         # Next.js 15 web chat UI
│   ├── app/
│   │   ├── layout.tsx                # Root layout with dark theme
│   │   ├── page.tsx                  # Home page -> renders LoqiApp
│   │   └── globals.css               # Tailwind + custom dark theme CSS
│   ├── components/chat/
│   │   └── loqi-app.tsx              # Complete SPA chat app (sidebar, messages, composer)
│   ├── lib/
│   │   ├── api.ts                    # Fetch wrapper for all backend endpoints
│   │   └── types.ts                  # TypeScript types (LoqiMessage, LoqiSessionSummary)
│   ├── package.json                  # Next.js 15, React 19, Tailwind CSS 3
│   ├── tailwind.config.ts
│   └── next.config.js
│
├── synthetic/                        # Deterministic data generation engine
│   ├── generator.py                  # Main generator (10k+ companies in <1s)
│   ├── build_anchors.py              # Legacy anchor company builder (superseded)
│   ├── build_full.py                 # Legacy full company builder (superseded)
│   ├── templates/                    # 5 JSON vocabulary files
│   │   ├── industries.json           # 20 industries with sub_industries, roles, pain_points, etc.
│   │   ├── cities.json               # ~140 cities across 8 world regions
│   │   ├── first_names.json          # 8 demographic name pools
│   │   ├── last_names.json           # 7 cultural last name pools
│   │   └── extra.json                # Growth stages, online presence, automation levels
│   ├── data/                         # Legacy data files
│   └── output/
│       └── companies.json            # Generated output (5k companies, 13.6 MB)
│
├── docs/                             # 14 markdown documentation files
├── .env.example
├── AGENTS.md                         # OpenCode agent instructions
├── MULTICLIENT_MVP.md                # Multi-client architecture spec
├── SUPABASE_MIGRATION_GUIDE.md       # DB migration notes
├── README.md
├── render.yaml                       # Render deployment config
└── 3-n8n.json                        # Legacy n8n workflow export
```

---

## 3. Backend Architecture

### 3.1 Entry Point: `backend/main.py`

FastAPI application with CORS enabled (all origins). Routes are defined directly (no router modules):

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Health check |
| POST | `/webhook` | Telegram bot webhook |
| POST | `/api/web/session` | Create new web chat session |
| GET | `/api/web/session/{token}` | Get session summary + messages |
| GET | `/api/web/session/{token}/messages` | List messages |
| POST | `/api/web/session/{token}/messages` | Send message to engine |
| GET | `/api/web/session/{token}/gmail` | Gmail connection status |
| GET | `/google/callback` | Gmail OAuth callback |

### 3.2 Conversation Engine (`conversation_engine.py`)

The central orchestration hub (500+ lines). Channel-agnostic — handles both web and Telegram via the `channel` parameter.

**Key behaviors:**
- `create_web_session()` — creates user + workflow session, returns welcome messages + prompt
- `handle_message()` — main message processing pipeline:
  1. Get/create user by `channel:external_user_id`
  2. Load session context from Supabase
  3. Parse message for service/target signals using `_extract_single_message_fields()`
  4. Classify intent using `_classify_natural_action()`
  5. Route to workflow or conversation stage
  6. Route through greeting detection, lead selection, draft refinement, or send confirmation
- `/restart` command resets session context
- `/connect` command returns Gmail OAuth URL
- `/start` command resumes from stored context

**Conversation flow states:**
1. `session_start` — welcome message + prompt for service
2. `ask_service` — "What do you sell?"
3. `ask_target` — "Who are you trying to reach?"
4. `after_leads` — lead list shown, prompt to select
5. `after_draft` — draft ready, prompt to send/refine
6. `after_send` — email sent, offer next step
7. `refining` — user requested edits

### 3.3 Workflow Engine (`workflows.py`)

Three workflow functions called from conversation_engine:

| Workflow | Input | Output |
|----------|-------|--------|
| `generate_leads()` | service, target, user_id | Lead list + stored leads + ICP |
| `draft_message()` | lead, edit_request, tone, length | Draft text + metadata |
| `send_outreach()` | lead, user_id | Send result |

**Key detail:** `draft_message()` supports refinement — if `edit_request` and `previous_message` are present, it calls `rewrite_message()` instead of generating fresh. Tone and length are inferred from context.

### 3.4 Service Modules

#### ai.py
OpenAI wrapper using the `/v1/responses` endpoint with `gpt-4o-mini`. Three functions:
- `classify_intent()` — classifies user intent into {new_search, refine_message, select_lead, send}
- `rewrite_message()` — rewrites cold email per instruction
- `generate_outreach_email()` — generates personalized email with subject + body

All raise `OpenAIError` on failure (invalid key, quota, timeout, connection errors). No fake data fallback — failures propagate to calling code.

#### icp_extractor.py (690 lines)
Dual-mode ICP extraction. **Critical: extracts WHO BUYS, not what is sold.**

**AI mode:** Sends structured prompt to OpenAI, returns buyer_industries, buyer_roles, excluded_roles, keywords, search_hints
**Fallback mode:** Deterministic industry-first role mapping using 20 industry -> role mappings. Extracts offer via "for/to" separators, maps buyer industries from keyword lists, generates buyer-focused keywords.

Both modes return: `{offer, service_category, buyer_industries, buyer_roles, excluded_roles, company_types, pain_points, keywords, search_hints, mode}`

#### search_expansion.py (275 lines)
Takes service + target + ICP -> generates LinkedIn search queries. AI mode expands semantically, fallback mode uses ICP keywords directly. Output includes `roles`, `industries`, `keywords`, `search_queries` (formatted as `site:linkedin.com/in "query"`).

#### lead_provider.py (200 lines)
Orchestrates the full lead search pipeline:
1. Extract ICP from user input
2. Expand search intent into queries
3. Execute queries via the configured provider (SyntheticProvider, ApolloProvider, etc.)
4. Apply commercial qualification filtering
5. Fallback: soft filtering -> raw lead return if everything rejected

Also exports `format_leads_message()` — the lead list formatter previously in `apollo.py`.

#### providers/ (4 files)
Provider abstraction layer. `BaseProvider` defines the interface; `ProviderFactory` reads `LEAD_PROVIDER` env var and caches the singleton. `SyntheticProvider` indexes 5,000 companies in memory for sub-50ms searches. `ApolloProvider` is a stub for future integration. See `docs/PROVIDER_ARCHITECTURE.md`.

#### commercial_qualifier.py (400+ lines)
Multi-dimensional lead scoring system. Each lead gets:
- `buyer_score` (0-40): owner/founder/ops/HR keyword matching
- `company_score` (-30 to +20): chain indicators, hospitality keywords, solo operator penalties
- `authority_score` (0-30): decision-making level (CEO > VP > Director > Manager)
- `relevance_score` (0-20): ICP role/industry match
- `drift_penalty` (0 to -100): vendor title/company detection

Final score = `max(0, buyer_score + company_score + authority_score + relevance_score + drift_penalty)`

Leads below threshold are excluded. `qualify_and_rank_leads()` sorts by score descending.

#### supabase.py (609 lines)
Complete CRUD layer for all Supabase tables. Functions:
- `get_or_create_user()` — upsert by telegram_id
- `get_session_context()` — reconstructs session from conversation history + lead status
- `store_leads()`, `get_pending_leads()`, `select_lead()`, `get_selected_lead()`, `clear_session_context()`
- `log_conversation()` — append to conversation history
- `get_user_preferences()`, `save_user_preference()` — tone/length/style/industry memory
- Google token management: `save_google_tokens()`, `update_google_access_token()`, `is_token_expired()`

#### conversation_store.py (257 lines)
Thin wrapper around `supabase.py` for workflow session management:
- `create_lightweight_web_session()` — generates token, creates user
- `get_web_session()` / `get_channel_user()` — user lookup
- `ensure_workflow_session()` — find or create workflow session
- `record_workflow_message()` / `record_workflow_event()` — durable event logging
- `list_conversation_messages()` / `list_workflow_sessions()` — queries

#### conversational_response_generator.py (646 lines)
AI response generation with fallback to variation pools. Key components:
- `RESPONSE_VARIATIONS` dict — 10 pools (greeting, onboarding, ask_service, ask_target, after_lead_list, after_draft, confirming_send, select_lead_confirm, session_start, refine_options)
- `_extract_single_message_fields()` — parses service/target from single message using "for/to" separators
- `_classify_natural_action()` — maps user text to {send, refine_shorter, refine_longer, refine_casual, refine_formal, refine_another, select_number, select_recent, defer, new_search, unknown}
- `generate_conversational_response()` — AI generation with stage-aware prompts, falls back to `_get_fallback_variation()`
- `build_classification_context()` — enriches context for intent classification
- `should_skip_question()` — detects if user already provided enough info
- `detect_preferences_from_refinement()` — extracts tone/length/style from refine messages

#### google_auth.py (90 lines)
Gmail OAuth2 implementation:
- `get_google_auth_url()` — builds OAuth URL with scopes (gmail.send, userinfo.email)
- `exchange_code_for_tokens()` — code -> access_token + refresh_token + email
- `refresh_access_token()` — refresh expired tokens

#### gmail.py (21 lines)
Minimal Gmail send: builds RFC 2822 message, base64 encodes, POSTs to Gmail API.

#### telegram.py (22 lines)
Simple `send_message(chat_id, text)` POST to Telegram Bot API.

#### providers/ (4 files)
Provider abstraction layer. `BaseProvider` defines the interface with `health_check()`, `search_leads()`, `get_lead()`, `get_company()`, and a `capabilities` property. `ProviderFactory` reads `LEAD_PROVIDER` env var and caches the singleton. `SyntheticProvider` indexes 5,000 companies in memory for sub-50ms searches. `ApolloProvider` is a stub for future integration. See `docs/PROVIDER_ARCHITECTURE.md`.

#### state/memory.py (DEPRECATED)
Legacy in-memory session store with `{chat_id: {step, service, target}}`. Superseded by Supabase persistence. Still present but not used by conversation_engine.

---

## 4. Frontend Architecture

### 4.1 Stack
- Next.js 15 (App Router)
- React 19.1
- TypeScript 5.8
- Tailwind CSS 3.4
- No additional UI libraries

### 4.2 Key Files

**`lib/types.ts`** — 2 types:
- `LoqiMessage`: `{id, role, type, text, data?, created_at?}`
- `LoqiSessionSummary`: `{ok, session_token, user_id, display_name, gmail_connected, workflow_sessions, messages}`

**`lib/api.ts`** — 4 fetch wrappers to `NEXT_PUBLIC_LOQI_API_BASE_URL` (default `http://127.0.0.1:10000`):
- `createSession(displayName?)` -> POST /api/web/session
- `getSession(token)` -> GET /api/web/session/{token}
- `sendMessage(token, text)` -> POST /api/web/session/{token}/messages
- `getGmailStatus(token)` -> GET /api/web/session/{token}/gmail

**`components/chat/loqi-app.tsx`** — Single large component (~450 lines) containing the entire chat UI:
- Left sidebar: session list (localStorage-persisted, up to 50), Gmail connect button, new chat button
- Main chat area: message feed with `MessageBlock` rendering (leads, drafts, Gmail action links)
- Bottom composer: textarea with Enter-to-send
- Session lifecycle: localStorage persistence across reloads, auto-creates session on first visit
- `MessageBlock` sub-component renders message types: plain text, lead cards (grid of 2), draft preview (green tinted), Gmail connect URL as button

**`app/layout.tsx`** — Root layout with dark theme metadata.

**`app/globals.css`** — Custom dark theme with CSS variables (--loqi-bg, --loqi-accent, --loqi-muted), radial gradient backgrounds, custom scrollbar.

**`app/page.tsx`** — Simply renders `<LoqiApp />`.

---

## 5. Database Schema

Defined in `backend/supabase/multi_client_mvp.sql`. Three custom tables beyond standard Supabase:

### workflow_sessions
```sql
id            uuid PK (gen_random_uuid)
user_id       uuid FK -> users(id) ON DELETE CASCADE
channel       text        -- "web" or "telegram"
session_key   text        -- external_user_id or session_token
title         text?       -- session display name
status        text        -- "active" (default)
created_at    timestamptz
updated_at    timestamptz
```
Indexes: `(user_id, updated_at desc)`, unique `(user_id, channel, session_key, status)`

### workflow_messages
```sql
id                    uuid PK
workflow_session_id   uuid FK -> workflow_sessions(id) ON DELETE CASCADE
role                  text    -- "user" or "assistant"
message_type          text    -- "text", "prompt", "action", "error"
content               text
metadata              jsonb   -- channel info, etc.
created_at            timestamptz
```
Index: `(workflow_session_id, created_at)`

### workflow_events
```sql
id                    uuid PK
workflow_session_id   uuid FK -> workflow_sessions(id) ON DELETE CASCADE
event_type            text    -- "session.created", "session.reset", "gmail.connect.requested", "icp.extracted"
payload               jsonb   -- structured data (ICP object, URLs, etc.)
created_at            timestamptz
```
Index: `(workflow_session_id, created_at)`

### Existing tables (not in migration, created earlier):
- `users` — `{id, telegram_id, username, email, google_access_token, google_refresh_token, token_expiry, telegram_chat_id, created_at}`
- `leads` — `{id, user_id, name, company, email, linkedin_url, status (pending/selected/contacted/cleared), created_at}`
- `conversations` — `{id, user_id, role, message, created_at}` (legacy — being superseded by workflow_messages)
- `user_preferences` — `{id, user_id, tone?, length?, style?, industry_focus?, created_at, updated_at}`

---

## 6. Synthetic Data System

### 6.1 Current Generator (`synthetic/generator.py`)
Deterministic template-driven company generator. Uses `random.Random(seed)` for reproducibility.

**CLI:**
```bash
python3 generator.py --companies 5000 --seed 42
python3 generator.py --industries Restaurant,Cafe,Gym --seed 42
```

**Performance:** 5,000 companies with 22,502 decision makers in 0.197s.

**Generated company schema:**
```json
{
  "company_id": "cmp_000001",
  "name": "string",
  "industry": "string (20 options)",
  "sub_industry": "string",
  "description": "string (template-based)",
  "website": "string",
  "city": "string",
  "country": "string",
  "employees": "int",
  "locations": "int",
  "founded": "int (year)",
  "growth_stage": "string (weighted random)",
  "revenue_band": "string",
  "business_profile": {
    "franchise": "bool",
    "expanding_locations": "bool",
    "hiring": "bool",
    "online_presence": "string",
    "delivery": "bool",
    "multi_location": "bool"
  },
  "technology": {
    "crm": "string?",
    "website_platform": "string",
    "marketing_platform": "string",
    "automation_level": "string"
  },
  "pain_points": ["string", ...],
  "buying_signals": ["string", ...],
  "recent_events": ["string", ...],
  "decision_makers": [{
    "lead_id": "string",
    "name": "string",
    "title": "string",
    "department": "string",
    "email": "string",
    "linkedin_url": "string",
    "buying_authority": "int (50-100)"
  }, ...]
}
```

### 6.2 Template Files
| File | Contents |
|------|----------|
| `industries.json` | 20 industries: Cafe, Restaurant, Hotel, Gym, Dental, Healthcare, Spa, Salon, Retail, E-commerce, Manufacturing, Logistics, Construction, Real Estate, Legal, Accounting, Marketing Agency, IT Services, Auto Dealership, Education. Each has: sub_industries, name_prefixes/suffixes, roles (title/dept/authority triplets), pain_points, technologies, buying_signals, events, description_templates, employee/location/founded ranges, revenue_bands. |
| `cities.json` | ~140 cities across 8 regions: US (40), Canada (10), UK (15), Europe (25), Asia (25), Oceania (8), LATAM (12), Africa (8). Each with city, country, region. |
| `first_names.json` | 8 pools: male, female, south_asian, east_asian, european, african, latino, middle_eastern |
| `last_names.json` | 7 pools: american, british, german, french, spanish, asian, indian |
| `extra.json` | Weights and lists for random selection: growth_stages (seed/pre-seed/seed/growing/scaling/established/mature), online_presence_levels, automation_levels, industry-specific description_adjectives/focuses/audiences/features/origins |

### 6.3 Legacy Files (superseded)
`build_anchors.py` and `build_full.py` — hand-crafted 8 anchor companies with detailed metadata. Superseded by the deterministic generator. `data/` directory contains intermediate files from the old approach.

---

## 7. API Endpoints

All routes defined in `backend/main.py`:

### System
| Endpoint | Method | Response |
|----------|--------|----------|
| `/` | GET | `"Loqi backend running"` |

### Telegram
| Endpoint | Method | Handler |
|----------|--------|---------|
| `/webhook` | POST | `telegram_webhook` — parses message, calls `process_message()` |

### Web Session
| Endpoint | Method | Handler |
|----------|--------|---------|
| `/api/web/session` | POST | `create_web_session` — creates user + session, returns token + welcome messages |
| `/api/web/session/{token}` | GET | `get_web_session` — full session summary with messages |
| `/api/web/session/{token}/messages` | GET | `get_web_session_messages` — message list |
| `/api/web/session/{token}/messages` | POST | `post_web_session_message` — send message, returns response messages |
| `/api/web/session/{token}/gmail` | GET | `get_web_gmail_status` — connection status + connect URL |

### Gmail OAuth
| Endpoint | Method | Handler |
|----------|--------|---------|
| `/google/callback` | GET | `google_callback` — exchanges code for tokens, saves to user record |

---

## 8. Workflow Engine

### 8.1 Lead Search Pipeline
```
User input ("CRM for startups")
  |
  v
extract_structured_icp()          -- AI or deterministic
  |                                  returns {offer, buyer_industries, buyer_roles, keywords, ...}
  v
expand_search_intent()            -- AI or deterministic
  |                                  returns {roles, industries, keywords, search_queries}
  v
Provider.search_leads()           -- SyntheticProvider / ApolloProvider / etc.
  |                                  returns canonical lead schema
  v
_filter_and_rank_leads()          -- commercial_qualifier scoring
  |                                  returns sorted leads
  v
Soft fallback if all excluded     -- _filter_and_rank_leads_soft()
  |
  v
Raw fallback if still empty       -- return first 5 raw leads
  |
  v
store_leads() in Supabase          -- status: "pending"
```

### 8.2 Draft Generation Pipeline
```
Lead selected
  |
  v
generate_outreach_email(lead)     -- OpenAI
  |                                  returns {subject, body}
  v
User requests edit
  |
  v
rewrite_message(instruction,      -- OpenAI
  previous_message)
  |
  v
detect_preferences_from_refinement() -- extracts tone/length preferences
  |
  v
save_user_preference()             -- persists for future drafts
```

### 8.3 Send Pipeline
```
User confirms send
  |
  v
Get user from Supabase
  |
  v
Check google_refresh_token exists
  |
  v
Check token expiry -> refresh if needed
  |
  v
generate_outreach_email(lead)     -- fresh draft for send
  |
  v
send_email(access_token, to,      -- Gmail API
  subject, body)
  |
  v
Return success/failure
```

---

## 9. Lead Sourcing Pipeline

### 9.1 Provider Architecture
`LEAD_PROVIDER` env var controls which provider is used:
- `synthetic` (default) — in-memory index over 5,000 synthetic companies, sub-50ms searches
- `apollo` — stub, returns `{"ok": False}` until implemented

Adding a new provider requires writing one class and registering it in `provider_factory.py` — zero changes elsewhere.

See `docs/PROVIDER_ARCHITECTURE.md` for the full provider abstraction layer design, including the canonical lead schema, capabilities system, and how to add new providers.

### 9.3 Commercial Qualification
Applied AFTER lead search, powered by `commercial_qualifier.py`:

| Score Component | Range | What It Measures |
|-----------------|-------|-----------------|
| buyer_score | 0-50+ | Owner/Founder/Operations/HR title match |
| company_score | -30 to +50 | Chain indicators, real business keywords, solo operator penalty |
| authority_score | 0-30 | Decision-making level (CEO > VP > Director > Manager) |
| relevance_score | 0-20 | ICP buyer_roles and buyer_industries match |
| drift_penalty | -100 | Vendor/service provider detection |

**Exclusion patterns:** junk entities (mangled names, placeholders), vendor companies (agency/consulting/solutions), vendor titles (developer/designer/freelancer/coach).

---

## 10. AI Integration

### 10.1 Provider
OpenAI API via `/v1/responses` endpoint. Model: `gpt-4o-mini` (configurable via `OPENAI_MODEL`).

### 10.2 AI Call Points

| Call Point | Module | Input | Output | Fallback |
|-----------|--------|-------|--------|----------|
| Intent classification | ai.py | user_message + context | "new_search", "refine_message", "select_lead", "send" | OpenAIError (no fallback) |
| Outreach email generation | ai.py | lead data | {subject, body} | OpenAIError |
| Message rewrite | ai.py | instruction + message | rewritten text | OpenAIError |
| ICP extraction | icp_extractor.py | user input | structured ICP | Deterministic fallback |
| Search expansion | search_expansion.py | service + target + ICP | roles, keywords, queries | Deterministic fallback |
| Conversational response | conversational_response_generator.py | stage + context | response text | Variation pool fallback |

### 10.3 Error Handling Pattern
AI services follow a consistent pattern:
- If `OPENAI_API_KEY` is missing — deterministic fallback (for ICP/extraction) or OpenAIError (for generation/rewrite)
- HTTP 401 (invalid key) -> deterministic fallback or OpenAIError
- HTTP 429 (quota exceeded) -> deterministic fallback or OpenAIError
- HTTP 5xx (server error) -> deterministic fallback or OpenAIError
- Timeout -> deterministic fallback or OpenAIError
- JSON parse failure -> deterministic fallback or OpenAIError

**Key principle:** Lead search NEVER fails (deterministic fallback always works). Email generation CAN fail (OpenAIError propagates up — no fake emails).

---

## 11. Email Integration

### 11.1 Gmail OAuth
- OAuth scope: `gmail.send`, `userinfo.email`
- Tokens stored in `users` table: `google_access_token`, `google_refresh_token`, `token_expiry`
- Token refresh handled automatically in `send_outreach` workflow
- `/connect` command returns OAuth URL
- `/google/callback` exchanges code, saves tokens, notifies user

### 11.2 Send
Minimal implementation: builds raw RFC 2822 message, base64 encodes, sends via `POST /gmail/v1/users/me/messages/send`.

### 11.3 Known Gaps
- **Inbox sync: NOT implemented** — no polling, no webhook, no reply detection
- **Reply detection: NOT implemented** — can't detect when leads respond
- **Send status tracking: NOT implemented** — no delivery confirmation
- **Draft management: NOT implemented** — no Gmail draft creation

---

## 12. State Management

### 12.1 Current: Supabase-Based
Session state is reconstructed from:
1. `conversations` table — message history
2. `leads` table — lead status (pending/selected/contacted/cleared)
3. `workflow_sessions` — session metadata
4. `workflow_messages` — workflow message log
5. `workflow_events` — structured event log (ICP, Gmail connect requests)
6. `user_preferences` — tone/length/style settings

`get_session_context()` in `supabase.py` reconstructs session by:
1. Finding the last "/start" or terminal message as boundary
2. Collecting user/assistant messages after boundary
3. Mapping first user messages as `service` and `target`
4. Looking up selected lead from `leads` table

### 12.2 Legacy: In-Memory
`state/memory.py` — `{chat_id: {step, service, target}}` dict. DEPRECATED — not used by conversation_engine.

---

## 13. Configuration

### 13.1 Backend `.env`
| Variable | Required | Purpose |
|----------|----------|---------|
| SUPABASE_URL | Yes | Supabase project URL |
| SUPABASE_KEY | Yes | Supabase anon key |
| OPENAI_API_KEY | No | OpenAI API key (fallback works without) |
| OPENAI_MODEL | No | Model name (default: gpt-4o-mini) |
| SERPAPI_API_KEY | No (if using Apollo) | SerpAPI key |
| APOLLO_API_KEY | No | Apollo API key |
| GOOGLE_CLIENT_ID | No (sans Gmail) | Google OAuth client ID |
| GOOGLE_CLIENT_SECRET | No | Google OAuth client secret |
| GOOGLE_REDIRECT_URI | No | OAuth redirect URI |
| SESSION_SECRET | Yes | Session secret |
| LEAD_PROVIDER | No | "free" or "apollo" (default: free) |
| BOT_TOKEN | No | Telegram bot token |
| PORT | No | Server port (default: 10000) |

### 13.2 Frontend `.env.local`
| Variable | Purpose |
|----------|---------|
| NEXT_PUBLIC_LOQI_API_BASE_URL | Backend URL (default: http://127.0.0.1:10000) |

### 13.3 Dependencies
**Backend** (`requirements.txt`): fastapi, uvicorn, requests, python-dotenv, supabase, serpapi
**Frontend** (`package.json`): next@15.3.8, react@19.1.0, react-dom@19.1.0; dev: typescript, tailwindcss, postcss, autoprefixer

---

## 14. Deployment

### 14.1 Backend: Render
Config in `render.yaml`:
- Type: web service
- Runtime: Python
- Build: `pip install -r requirements.txt`
- Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Root dir: `backend/`

### 14.2 Frontend: Vercel
Standard Next.js deployment. Root dir: `frontend/`. Build: `next build`. Environment: `NEXT_PUBLIC_LOQI_API_BASE_URL` points to Render backend.

---

## 15. Documentation

14 markdown files in `docs/`:

| File | Purpose |
|------|---------|
| ARCHITECTURE.md | High-level architecture overview — product philosophy, stack, backend structure, multi-client direction |
| STACK.md | Tech stack summary — backend, frontend, AI, DB, auth, hosting |
| WORKFLOWS.md | Detailed workflow documentation — lead search, ICP extraction, search expansion, lead selection, draft generation, email send, session management |
| CURRENT_STATE.md | What works RIGHT NOW — operational endpoints, working features, partial features, unimplemented features |
| KNOWN_ISSUES.md | Honest technical debt — partial Gmail sync, missing lead ranking, no enrichment, quota issues, session security, rate limiting |
| SETUP.md | Complete setup guide for Mac, Windows, WSL2 — prerequisites, Supabase, OpenAI, SerpAPI, Gmail OAuth, Render/Vercel deployment |
| ENVIRONMENT.md | Environment variable reference by category |
| ROADMAP.md | Completed, in-progress, and future priorities |
| AI_SYSTEM.md | AI system documentation |
| DATABASE.md | Database schema |
| DEBUGGING.md | Debugging guide |
| DEPLOYMENT.md | Deployment instructions |
| MIGRATION.md | Migration notes |
| NEXT_STEPS.md | Next development priorities |

Root docs: `README.md`, `AGENTS.md`, `MULTICLIENT_MVP.md`, `SUPABASE_MIGRATION_GUIDE.md`, `RENDER_DEPLOY.md`, `PROJECT_REPORT.md` (this file).

---

## 16. Implementation Status

### 16.1 Fully Implemented
- Web chat UI (Next.js SPA with sidebar, message feed, composer)
- Session creation and persistence (Supabase + localStorage)
- ICP extraction — dual mode (AI + deterministic fallback)
- Semantic search expansion — dual mode
- SerpAPI LinkedIn lead search with validation
- Commercial qualification scoring (multi-dimensional)
- Lead deduplication, filtering, and ranking
- AI draft generation with refinement support
- Gmail OAuth connect flow
- Gmail send (basic)
- Tone/length inference from user input
- User preference memory (tone, length, style)
- Greeting detection and conversational variation
- Natural language intent classification (keyword + AI)
- Session reset (/restart) and resume (/start)
- Synthetic data generator (10k companies in <1s)
- Full documentation (14 markdown files)
- Workflow event logging (ICP, sessions, Gmail connect)

### 16.2 Partially Implemented
- **Gmail inbox sync** — OAuth works, sending works. No inbox polling, no reply detection.
- **Lead ranking** — commercial_qualifier scores leads but still returns all qualified results (no minimum score threshold enforced in workflow).
- **Preference memory** — supabase.py has CRUD for user_preferences table but conversation_engine only reads in `_get_after_draft_variation()`.

### 16.3 Not Implemented (Stub Exists)
- **Apollo.io integration** — `ApolloProvider` stub exists at `backend/services/providers/apollo_provider.py`. Set `LEAD_PROVIDER=apollo` and implement its four methods to wire Apollo through the full ICP/expansion/qualification pipeline.

### 16.4 Not Implemented (No Code)
- **Lead enrichment** — no company data, email finding, or social profile enrichment beyond what providers return
- **Reply engine** — no inbox polling, reply classification, or auto-followup triggers
- **Analytics dashboard** — no metrics tracking
- **Authentication** — simple UUID session tokens, no Supabase Auth or JWT
- **Rate limiting** — no middleware
- **Caching** — no Redis or in-memory caching for provider results
- **Stripe/subscriptions** — no payment integration
- **WebSockets/SSE** — REST-only, no real-time
- **WhatsApp/Slack/Mobile** — only web and Telegram interfaces

### 16.5 Deprecated/Superseded
- `state/memory.py` — in-memory session store (replaced by Supabase)
- `synthetic/build_anchors.py` / `build_full.py` — manual company builders (replaced by `generator.py`)
- `synthetic/data/` — hand-crafted anchor companies (replaceable by generator output)
- Telegram as primary interface (web chat UI is now primary; Telegram code still present but not actively developed)
- `3-n8n.json` — legacy n8n workflow export (no longer used)

---

## 17. Architecture Diagram

```
                                    ┌─────────────────────────────┐
                                    │      Telegram Bot API       │
                                    │   POST /webhook -> agent.py │
                                    └──────────┬──────────────────┘
                                               │
                                    ┌──────────▼──────────────────┐
                                    │    Next.js Web Chat UI      │
                                    │  POST /api/web/session/     │
                                    └──────────┬──────────────────┘
                                               │
                                    ┌──────────▼──────────────────┐
                                    │   ConversationEngine        │
                                    │   (conversation_engine.py)  │
                                    │   - Channel-agnostic        │
                                    │   - Session orchestration   │
                                    │   - Intent classification   │
                                    │   - Workflow routing        │
                                    └──────────┬──────────────────┘
                                               │
                    ┌──────────────────────────┼──────────────────────────┐
                    │                          │                          │
         ┌──────────▼──────────┐   ┌───────────▼──────────┐   ┌──────────▼──────────┐
         │  Workflow Engine    │   │  Response Generator  │   │  Channel Adapters   │
         │  (workflows.py)     │   │  (conversational_    │   │  (channel_adapters/ │
         │  - generate_leads   │   │   response_generator │   │   telegram.py)      │
         │  - draft_message    │   │   .py)               │   │  - Format responses │
         │  - send_outreach    │   │  - AI generation     │   └─────────────────────┘
         └──────────┬──────────┘   │  - Variation fallback│
                    │              └──────────────────────┘
                    │
    ┌───────────────┼───────────────────┬──────────────────┐
    │               │                   │                  │
┌───▼────────┐ ┌───▼────────┐ ┌────────▼────────┐ ┌──────▼─────┐
│ Lead       │ │ AI Layer   │ │ Email Layer    │ │ State      │
│ Pipeline   │ │ (ai.py,    │ │ (gmail.py,     │ │ Layer      │
│            │ │  icp_      │ │  google_auth.py)│ │ (supabase  │
│ - icp_     │ │  extractor │ │                │ │  .py,      │
│  extractor │ │  .py)      │ │ - OAuth flow   │ │  conversati│
│ - search_  │ │            │ │ - Send         │ │  on_store  │
│  expansion │ │ - Classify │ │ - Token refresh│ │  .py)      │
│  .py       │ │ - Generate │ └────────────────┘ │            │
│ - providers│ │ - Rewrite  │                    │ - Users    │
│  / (abstra │ └────────────┘                    │ - Leads    │
│  ction)    │                                    │ - Sessions │
│ - commerci │                                    │ - Messages │
│  al_qualif │                                    │ - Events   │
│  ier.py    │                                    │ - Prefs    │
│ - lead_pro │                                    └──────┬─────┘
│  vider.py  │                                           │
└────────────┘                                    ┌──────▼─────┐
                                                  │  Supabase  │
                                                  │ (Postgres) │
                                                  └────────────┘
```

---

## 18. Key Numbers

| Metric | Value |
|--------|-------|
| Total Python files | 20 |
| Total TypeScript files | 4 |
| Total JSON template files | 5 |
| Total documentation files | 14 + 6 root docs |
| API endpoints | 8 |
| Service modules | 16 |
| Workflow types | 3 (leads, draft, send) |
| Lead scoring dimensions | 5 |
| AI call points | 6 |
| ICP industries mapped | 20 |
| Synthetic template industries | 20 |
| Synthetic cities | ~140 |
| Response variation pools | 10 |
| Database tables | 7+ |
| Frontend components | 1 main component |
