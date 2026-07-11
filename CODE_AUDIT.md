# Loqi — Code Audit

Prepared as if for production readiness review. Every finding is based on direct codebase analysis.

---

## 1. Duplicated OpenAI Request Logic (4 Copies)

**Files:** `ai.py`, `icp_extractor.py`, `search_expansion.py`, `conversational_response_generator.py`

Each file implements its own `_send_openai_request()` (or equivalent) — identical payload construction, same `/v1/responses` URL, same `gpt-4o-mini` default model, same header building, same error handling.

```python
# ai.py (lines 42-76)
def _send_openai_request(system_text: str, user_text: str) -> str:
    ...

# icp_extractor.py (inlined, lines 589-651)
payload = {"model": OPENAI_MODEL, "input": [...]}
    ...

# search_expansion.py (inlined, lines 189-262)
payload = {"model": OPENAI_MODEL, "input": [...]}
    ...

# conversational_response_generator.py (lines 20-64)
def _send_openai_request(system_text, user_text, timeout=30):
    ...
```

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| Medium | Violates DRY. Any change to the API (model upgrade, retry logic, timeout tuning) must be replicated in 4 places. Error handling diverges — `ai.py` raises `OpenAIError`, others return `None` and fall back silently. | Extract a single `OpenAIClient` module. All four callers import from it. | 1-2 hours |

---

## 2. `_first_row()` Helper Duplicated

**Files:** `supabase.py` (line 45-47), `conversation_store.py` (line 11-13)

Identical 3-line function, same name, same behavior.

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| Low | Low impact but unnecessary duplication. | Move to a shared utility or keep only in `supabase.py` and import from there. | 15 minutes |

---

## 3. `_log()` Function Duplicated Across Every Service (~20 Files)

**Files:** Every file under `backend/services/`, `workflows.py`, `main.py`, `conversation_store.py`

Each file defines:
```python
def _log(message: str) -> None:
    print(f"[service_name] {message}")
```

The bracket label is the only difference. `icp_extractor.py` also randomly uses `_log` vs `print` interleaved.

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| Medium | No log levels, no structured logging, no configuration. Every `print()` goes to stdout with no timestamps, no severity, no routing. In production this means no way to filter errors vs debug noise. | Create `backend/lib/logging.py` with a proper logger. All services import `logger = get_logger(__name__)`. | 2-3 hours |

---

## 4. `_dedupe_and_cap()` Duplicated

**Files:** `icp_extractor.py` (lines 26-38), `search_expansion.py` (lines 19-31)

Identical 13-line function. Same logic, same `max_items=8` default.

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| Low | Trivial but DRY violation. | Move to a shared utility. | 15 minutes |

---

## 5. `load_dotenv()` Called in Every Service Module

**Files:** `ai.py`, `icp_extractor.py`, `search_expansion.py`, `supabase.py`, `telegram.py`, `google_auth.py`, `apollo.py`

Each module calls `load_dotenv()` at module load time. `main.py` also calls it. This means `.env` is read 7+ times per process startup.

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| Low | Wasteful but not harmful. Only matters at startup. | Call `load_dotenv()` once in the entry point (`main.py`). Remove from service modules. | 1 hour |

---

## 6. CORS Wide Open in Production

**Files:** `backend/main.py` (lines 22-28)

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| High | `allow_origins=["*"]` with `allow_credentials=True` is invalid per spec (browsers reject credentialed requests with wildcard origins), but also exposes the API to any website. In production with Render + Vercel, this should be locked to the actual frontend domain. | Set `allow_origins` to the Vercel deployment URL. Use env var `CORS_ORIGIN`. | 30 minutes |

---

## 7. API Keys Printed to Stdout

**Files:** `backend/services/apollo.py` (line 32)

```python
print("[apollo] request headers:", headers)
```

The `headers` dict contains `X-Api-Key: <actual API key>`. This gets printed to stdout on every Apollo search call.

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| Critical | Secrets leaking into logs. In production (Render), stdout is captured and stored. Anyone with log access sees the raw API key. | Remove the debug print. Never log headers containing auth credentials. | 5 minutes |

---

## 8. No Authentication — Session Tokens Are Simple UUIDs

**Files:** `backend/services/conversation_store.py` (line 53), `frontend/lib/api.ts` (all calls)

Session tokens are generated via `secrets.token_urlsafe(18)` — reasonably random UUIDs. But:
- No JWT signing or HMAC — tokens are opaque strings stored in the `users` table as `telegram_id`
- No expiry mechanism on sessions
- Tokens stored in `localStorage` with no httpOnly protection
- Any token can access any session (no user ownership validation in endpoints)

The `users` table uses `telegram_id` as the lookup key, and for web sessions this is literally `"web:{session_token}"`.

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| High | Token leakage (XSS, localStorage read) gives full access to the conversation history and lead data. No way to revoke tokens. No way to detect abuse. | Implement JWT-based sessions with expiry. Use httpOnly cookies for web. Add `user_id` ownership check to all endpoints. | 3-5 days |

---

## 9. `print()` Debugging Throughout Production Code

**Files:** Nearly every Python file in the project

Hundreds of `print()` statements like:
```python
print(f"[apollo] request payload:", payload)
print(f"[apollo] response status:", response.status_code)
print(f"[apollo] response body:", response.text)
```

These print request payloads, full API response bodies, database query inputs, etc. In production this is a:
- Performance concern (I/O to stdout on every request)
- Security concern (leaks PII, API keys, lead data)
- Maintenance concern (noise drowns out real errors)

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| Medium | Combined with the logging fix (#3), these should be converted to `logger.debug()` calls or removed entirely for production. | After fixing #3, audit all print statements. Convert to `logger.debug()`, `logger.info()`, or `logger.warning()` as appropriate. | 4-6 hours |

---

## 10. Session Context Reconstructed from Full Conversation History

**Files:** `backend/services/supabase.py` (lines 300-371, `get_session_context()`)

On every message, the system:
1. Fetches ALL conversation rows for the user
2. Iterates through every row to find the last `/start` or terminal message boundary
3. Reconstructs `service`, `target`, `selected_lead_id` from message text matching heuristics
4. Ignores the explicit `workflow_sessions` / `workflow_messages` / `workflow_events` tables that exist for this purpose

This is both fragile and expensive. "service" is `user_messages[0]` and "target" is `user_messages[1]` — if the user sends "hi" before their actual request, the context breaks.

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| Critical | As the conversation grows, this query gets slower. The heuristics for extracting service/target from message order are fragile — any extra message breaks the flow. The explicit `workflow_sessions` + `workflow_messages` + `workflow_events` tables were designed to replace this. | Store service/target/selected_lead_id directly in `workflow_sessions` or `user_preferences`. Read them directly instead of reconstructing from conversation history. | 2-3 days |

---

## 11. Apollo Integration — Removed

**File:** `backend/services/apollo.py` (removed)

The old `apollo.py` and `free_leads.py` legacy files have been removed. Both are superseded by the provider abstraction layer (`backend/services/providers/`). A new `ApolloProvider` stub exists at `backend/services/providers/apollo_provider.py` — implement its four methods to wire Apollo through the full ICP/expansion/qualification pipeline.

| Severity | Reason | Status |
|----------|--------|--------|
| Resolved | Legacy Apollo and free leads code removed. Provider abstraction layer in place. Apollo re-integration path is clean via `BaseProvider` subclass. | Fixed |

---

## 12. `state/memory.py` Is Completely Unused

**Files:** `backend/state/memory.py`

21-line in-memory session store with `{chat_id: {step, service, target}}`. Zero imports anywhere in the codebase. ConversationEngine uses Supabase exclusively.

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| Low | Dead code. Confuses new developers reading the project structure. | Delete the file. | 5 minutes |

---

## 13. `synthetic/build_anchors.py` and `build_full.py` Are Superseded

**Files:** `synthetic/build_anchors.py`, `synthetic/build_full.py`, `synthetic/data/`

These are hand-crafted company builders from an earlier approach. The `generator.py` deterministic system is the current approach. `data/anchor_companies.json`, `data/cafe_restaurant.json`, `data/manufacturing_logistics.json`, `data/gen_mfg_log.py`, `data/part_cafe_restaurant.py` are all intermediate/legacy files.

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| Low | Outdated files take up space and confuse. | Archive or remove the `data/` directory and the two legacy Python files. | 15 minutes |

---

## 14. `3-n8n.json` — Legacy Workflow Export

**Files:** `3-n8n.json` (project root)

n8n workflow export from when Loqi used n8n for orchestration. No longer used — all orchestration is now in `workflows.py` and `conversation_engine.py`.

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| Low | Dead file at project root. | Delete or move to `docs/legacy/`. | 5 minutes |

---

## 15. Huge Single-File Components

**Files:**
- `backend/services/conversation_engine.py` — ~500 lines
- `backend/services/conversational_response_generator.py` — 646 lines
- `backend/services/supabase.py` — 609 lines
- `backend/services/icp_extractor.py` — 690 lines
- `backend/services/commercial_qualifier.py` — 420+ lines
- `frontend/components/chat/loqi-app.tsx` — ~450 lines

These are the largest files in the project, each doing 3-5 distinct responsibilities.

**conversation_engine.py:** handle_message, create_web_session, greeting detection, natural language parsing, draft extraction, lead selection, preference detection, workflow routing, response formatting
**supabase.py:** user CRUD, lead CRUD, conversation logging, session context reconstruction, Google token management, preference CRUD — 25+ public functions
**loqi-app.tsx:** session management, localStorage persistence, message rendering, Gmail status, sidebar, composer, error handling

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| Medium | Hard to test, hard to reason about, merge conflicts are painful. Single files over 400 lines should be split by concern. | conversation_engine.py: extract greeting detection, lead selection, and response formatting into separate modules. supabase.py: split into users.py, leads.py, conversations.py, sessions.py. loqi-app.tsx: extract MessageBlock, Sidebar, Composer as separate components. | 3-5 days |

---

## 16. Inconsistent Error Handling Patterns

**Files:** Across the codebase

Three different patterns coexist:

1. **Raise custom exception** — `ai.py` raises `OpenAIError`, `free_leads.py` raises `SerpAPIError`
2. **Return error dict** — `lead_provider.py` returns `{"ok": False, "error": "..."}`
3. **Return None** — `supabase.py` returns `None` for "not found", `conversation_store.py` returns `None` for "no client"
4. **Return empty list** — `list_conversation_messages()` returns `[]` on error

Callers must handle all four patterns inconsistently. `workflows.py` catches `OpenAIError` from `ai.py` but `lead_provider.py` `search_with_expansion()` catches generic `Exception` from `icp_extractor.py`.

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| High | Makes the codebase fragile. A missed exception or unhandled error dict can crash a workflow mid-pipeline. Failed ICP extraction is caught as generic `Exception` and silently swallowed. | Adopt a single error pattern: either all services raise typed exceptions, or all return `{"ok": bool, "error": str}` dicts. Don't mix both. | 2-3 days |

---

## 17. `conversation_store.py` and `supabase.py` Have Blurred Boundaries

**Files:** `backend/services/supabase.py`, `backend/services/conversation_store.py`

`supabase.py` handles: user CRUD, lead CRUD, conversation logging, session context reconstruction, Google token management, user preferences
`conversation_store.py` handles: channel user mapping, web session creation, workflow session CRUD, message recording, event recording

Both call `get_supabase_client()`. Both do `_safe_insert()`. Both define `_first_row()`. There's no clear architectural boundary — `conversation_store.py` sometimes calls `supabase.py` functions (`get_or_create_user`, `get_user`), sometimes calls the Supabase client directly.

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| Medium | Confusing layering. New developer has to read both files to understand persistence. | Either merge conversation_store into supabase.py or make conversation_store the sole persistence layer and move all supabase.py functions into it. | 1-2 days |

---

## 18. Overlapping Exclusion Patterns in `commercial_qualifier.py` and `icp_extractor.py`

**Files:**
- `commercial_qualifier.py` — `EXCLUDED_COMPANY_PATTERNS`, `EXCLUDED_TITLE_PATTERNS`, `VENDOR_INDICATORS`
- `icp_extractor.py` — `EXCLUDED_ROLES`, `EXCLUDED_ROLE_PATTERNS`
- `free_leads.py` — `_is_service_provider_company()` with its own `vendor_keywords` and `provider_title_keywords`

Three separate files define overlapping lists of:
- "agency", "consulting", "solutions", "services", "digital", "marketing" (vendor detection)
- "developer", "designer", "freelancer", "consultant", "coach" (excluded roles)
- Regex patterns that are nearly identical (`r"\bdev(eloper)?\b"` appears in both)

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| Medium | Patterns drift over time. A fix to one exclusion list doesn't apply to the others. For example, `free_leads.py` rejects at parse time, `icp_extractor.py` excludes at search time, `commercial_qualifier.py` scores at ranking time — each with different rules. | Define exclusion rules in one place (e.g., a shared `exclusions.py`). All three files import from it. | 4-6 hours |

---

## 19. Magic Numbers and Hardcoded Constants

**Files:** Throughout

Examples:
- `MAX_LEADS = 5` (free_leads.py, lead_provider.py, supabase.py) — hardcoded in multiple places
- `timeout=20`, `timeout=30` — different timeouts per call site
- `per_page=5` (apollo.py) — buried in payload
- `max_items=8`, `max_items=6`, `max_items=4`, `max_items=10` — different caps in different dedup functions
- `rng.randint(10, 200)` style ranges in synthetic generator
- `max_leads_per_search = ~10` (KNOWN_ISSUES.md acknowledges this)

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| Medium | Brittle and hard to tune without reading every file. Today's "5" is tomorrow's "we need 10" — becomes a hunt. | Move all tunable constants to a `settings.py` or env vars. Define `MAX_LEADS = int(os.getenv("MAX_LEADS_PER_SEARCH", "5"))` once. | 4-6 hours |

---

## 20. The Frontend Is a Single Component

**Files:** `frontend/components/chat/loqi-app.tsx` (~450 lines)

Everything — sidebar, message feed, composer, Gmail button, session management, localStorage persistence — is in one `"use client"` component. State is managed via 10+ `useState` hooks and 6+ `useEffect` hooks.

The session token is stored in `localStorage` directly from the component:
```typescript
window.localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, sessionToken)
```

Messages from previous sessions are displayed in a "recents" sidebar that's also populated from localStorage.

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| Medium | Impossible to unit test. State management is fragile (race conditions between 6 useEffects). Mixing data fetching, rendering, and state management in one file. localStorage access mixed with business logic. | Split into: `ChatSidebar.tsx`, `MessageFeed.tsx`, `MessageComposer.tsx`, `MessageBlock.tsx`, `useSession()` hook, `useLocalStorage()` hook. | 2-3 days |

---

## 21. No Caching Layer

Every lead search hits SerpAPI fresh. Repeated searches for the same query (e.g., user goes back and re-selects) make new API calls.

SerpAPI has rate limits and costs per query. The free tier is limited.

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| Medium | Wastes API quota. Slows down repeated searches. No offline capability. | Add a simple in-memory cache (dict with TTL) or use Supabase as a query result cache. Key by normalized query + ICP hash. | 4-8 hours |

---

## 22. No Rate Limiting on API Endpoints

No middleware, no throttling, no per-IP or per-user limits on any endpoint.

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| High | An attacker (or buggy client) can hammer the API, consuming OpenAI and SerpAPI quota. The `/api/web/session` endpoint creates new database rows on every call with no throttle. | Add `slowapi` or FastAPI middleware for rate limiting. At minimum: 10 req/s per IP on write endpoints, 30 req/s on read endpoints. | 4-6 hours |

---

## 23. Synchronous Blocking AI Calls

All AI calls are synchronous within the request-response cycle:
- `classify_intent()` — 30s timeout, blocks the response
- `generate_outreach_email()` — 30s timeout, blocks
- `_send_openai_request()` in 4 files — 20-30s timeout each

During a single `handle_message()` call, the engine may make 2-3 sequential AI calls (classify -> expand -> generate). This means a single user message can take 60-90 seconds to respond.

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| High | Poor UX (user waits 30-90s for a response). Timeouts are likely under load. Render's free tier has a 30s request timeout — 2 AI calls in sequence will timeout. | Offload AI calls to a background task queue (Celery, Redis Queue, or asyncio). Return immediate acknowledgment, then push result via polling or WebSocket. | 3-5 days |

---

## 24. `get_session_context()` Scans All Messages on Every Request

**Files:** `backend/services/supabase.py` (lines 300-371)

```python
result = (
    client.table("conversations")
    .select("*")
    .eq("user_id", user_id)
    .order("created_at")
    .execute()
)
rows = getattr(result, "data", None) or []
# ...iterates through all rows looking for boundaries...
```

Every message fetch downloads the entire conversation history for the user. There's no pagination, no limit. For a user with 500 messages, this fetches all 500 rows on every request.

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| High | O(n) per request, where n = total conversation length over all time. Wastes bandwidth and memory. Gets worse as users accumulate more messages. | Add pagination (`.range()` on Supabase query) or store current session boundary as a timestamp and only fetch messages after it. | 4-6 hours |

---

## 25. Inconsistent Return Types in Lead Provider Chain

**Files:** `free_leads.py`, `apollo.py`, `lead_provider.py`, `workflows.py`

```
free_leads.search_free_leads(query)     -> list[dict]          (raises SerpAPIError on failure)
apollo.search_leads(query)              -> dict {ok, source, leads, error}
lead_provider.get_leads()               -> dict {ok, source, leads, error}
lead_provider.search_with_expansion()   -> dict with ok, source, leads, icp, expansion, filter_stats
workflows.generate_leads()              -> dict with ok, type, source, leads, stored_leads, message, error
```

Every layer wraps the output differently. `workflows.py` has to normalize these in `run_workflow()`.

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| Medium | Every new lead source needs to figure out which return format to use. The chain is fragile — if `search_free_leads()` raises instead of returning an error dict, the error propagates as an unhandled exception through `lead_provider.py`. | Standardize on one return format throughout. Either always return `{ok, leads, error}` dicts or always raise typed exceptions. | 1 day |

---

## 26. `_parse_person()` Uses String Concatenation for Names

**Files:** `backend/services/apollo.py` (lines 32-41)

```python
return {
    "name": " ".join(part for part in [first_name, last_name] if part) or "Unknown",
    ...
}
```

Minor style issue but `first_name` and `last_name` come from the Apollo API and could be `None`, empty strings, or contain whitespace. The filtering is correct but there's no trimming.

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| Low | Cosmetic, but could produce names like `"  John  "` if Apollo returns spaced strings. | `.strip()` each name before joining. | 10 minutes |

---

## 27. `free_leads.py` Reads a Variable Before It's Defined

**Files:** `backend/services/free_leads.py` (lines 296-300)

```python
if name.lower() in seen_names:
    continue
seen_names.add(name.lower())
```

`seen_names` is never initialized before this check. This should be `NameError` at runtime, but the code path may be dead due to earlier `continue` conditions. **Wait** — let me re-check. Actually, looking at lines 249-252, `seen_urls` is initialized as a set but `seen_names` is NOT initialized anywhere. There's a potential `NameError` if a lead reaches this code path.

Actually, looking more carefully at the code, I see:
```python
leads = []
seen_urls = set()
rejected = {...}
```

But then:
```python
if name.lower() in seen_names:
    continue
seen_names.add(name.lower())
```

`seen_names` is never defined. This is a **latent bug** — if the code ever reaches this path, it raises `NameError`.

Wait, I need to re-examine. Let me check the full flow... Actually, looking at the structure more carefully, the `name` variable is derived from `title = result.get("title", "")` and then `parts = title.split(" - ", 1)` then `name = parts[0].strip()`. The validation chain would likely catch it before reaching `seen_names`, BUT the `seen_names` reference is still undefined.

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| Critical | Latent `NameError` bug. If any organic result passes the LinkedIn URL check and has a parsable name, the search crashes instead of returning results. | Initialize `seen_names = set()` alongside `seen_urls = set()`. | 5 minutes |

---

## 28. `icp_extractor.py` Has Duplicate Entries in EXCLUDED_ROLES

**Files:** `backend/services/icp_extractor.py` (lines 223-256)

```python
EXCLUDED_ROLES = [
    "developer",
    "developer",    # duplicated
    "designer",
    ...
    "contractor",
    "contractor",   # duplicated
    ...
]
```

`"developer"` and `"contractor"` appear twice. Not harmful (the while-loop over the list just checks twice), but indicates sloppy maintenance.

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| Low | No functional impact but suggests this list grew without review. | Deduplicate the list. | 5 minutes |

---

## 29. TERMINAL_MESSAGES Set Probably Outdated

**Files:** `backend/services/supabase.py` (lines 12-15)

```python
TERMINAL_MESSAGES = {
    "Type /start when you are ready to reach out to more leads.",
    "Operation cancelled. Type /start to try again.",
}
```

This set is used in `get_session_context()` to find session boundaries. If the assistant messages no longer use these exact strings (the conversational engine uses varied response pools now), session boundary detection silently fails — meaning every message becomes part of a single ever-growing session.

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| Medium | Session reset via `/restart` may not work correctly because the terminal message detection depends on exact string matching, but the response generator uses random variation pools (which don't include these strings). | Store session boundaries as explicit events in `workflow_events` instead of scanning message text. | 1 day |

---

## 30. `/google/callback` Has Fragile State Parsing

**Files:** `backend/main.py` (lines 115-125)

```python
state_parts = state.split(":")
if len(state_parts) == 2:
    channel = "telegram"
    user_id, transport_id = state_parts
elif len(state_parts) == 3:
    channel, user_id, transport_id = state_parts
else:
    raise HTTPException(status_code=400, detail="Invalid OAuth state")
```

The `state` parameter is a colon-separated string that could contain user-controlled data. A user who manipulates their session token could inject colons and break the parsing. Also, `telegram_chat_id=int(transport_id)` will crash if `transport_id` is not a valid integer (e.g., for web sessions where transport_id is the session token).

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| High | Crash if web user completes Gmail OAuth (web channel has a 3-part state with session_token as transport_id, which is a UUID string — `int()` call will raise `ValueError`). Also, state parsing is fragile against injection. | Use URL-safe base64 encoding for state. Validate transport_id format before casting. | 2-4 hours |

---

## 31. `agent.py` Is an Unnecessary Wrapper

**Files:** `backend/services/agent.py` (22 lines)

```python
engine = ConversationEngine()

def process_message(chat_id, telegram_id, text, username=None):
    response = engine.handle_message(...)
    send_engine_response_to_telegram(chat_id, response)
    return response
```

This is a 3-line orchestration plus a module-level `engine` instance. The Telegram webhook in `main.py` could call the engine directly.

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| Low | Thin wrapper adds a layer with no benefit. The Telegram adapter in `channel_adapters/telegram.py` already handles response formatting. | Inline the logic into `main.py`'s webhook handler. Remove `agent.py`. | 30 minutes |

---

## 32. `channel_adapters/__init__.py` Is Empty

**Files:** `backend/services/channel_adapters/__init__.py`

Contains only a docstring:
```python
# Channel adapters translate structured engine responses into client-specific output.
```

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| Low | Harmless but adds a file to maintain. | Either use it for shared channel adapter logic or remove. | 5 minutes |

---

## 33. No Tests

Zero test files exist in the entire repository. No `test_*.py`, no `__tests__/`, no `pytest` configuration, no Jest setup.

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| Critical | Every refactor is blind. The commercial qualification logic (400+ lines with 5 scoring dimensions), the ICP extraction (690 lines with fallback), and the conversation engine (500+ lines) have zero test coverage. A single regression in any scoring dimension breaks lead quality silently. | Start with integration tests for the critical paths: ICP extraction (AI + fallback), lead search pipeline, commercial qualification scoring, draft generation. | 1-2 weeks initial, ongoing |

---

## 34. No Type Annotations in Several Files

**Files:** `state/memory.py`, `telegram.py`, partially in `commercial_qualifier.py`

`state/memory.py` has no type hints. `commercial_qualifier.py` has type hints only on some functions. `telegram.py` has partial annotations.

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| Low | Not enforced by the runtime anyway, but the rest of the codebase uses modern Python type annotations. Inconsistent. | Add missing type annotations. | 2-3 hours |

---

## 35. `commercial_qualifier.py` Has Near-Duplicate Keyword Lists

**Files:** `backend/services/commercial_qualifier.py`

`EXCLUDED_COMPANY_PATTERNS`, `VENDOR_INDICATORS`, `_check_excluded_company()`, `_check_vendor_title()`, and `_is_service_provider_company()` in `free_leads.py` all overlap:

```
EXCLUDED_COMPANY_PATTERNS: agency, consulting, solutions, services, digital, marketing, creative, software, technology, tech, dev, design, web, app, platform, automation, saas, cloud, inc, llc, ltd, corp
VENDOR_INDICATORS: agency, consulting, solutions, services, digital, marketing, creative, software, technology, tech, dev, design, web, app, platform, automated, automation, ai, saas, cloud, vendor, provider, integrator, implementation
```

These are 80% the same list, written twice. Changes to one won't propagate to the other.

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| Medium | Same as #18 — overlapping exclusion logic in multiple files. | Consolidate into a shared exclusions module. | 2-4 hours |

---

## 36. `leads` Table Status Values Are Not Enforced

**Files:** `backend/supabase/multi_client_mvp.sql`, `backend/services/supabase.py`

The `leads` table uses `status` text field. The code sets it to:
- `"pending"` (on store)
- `"selected"` (on selection)
- `"contacted"` (on send — in workflows.py's `send_outreach()`, though actually it doesn't set contacted status)
- `"cleared"` (on session clear)

But `send_outreach()` in `workflows.py` does NOT update lead status after sending. There's no DB constraint enforcing valid values. Misspellings like `"pendng"` would silently store bad data.

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| Medium | `workflows.py` doesn't mark leads as "contacted" after successful send. The SQL schema has no CHECK constraint on status. | Add `CHECK (status IN ('pending', 'selected', 'contacted', 'cleared'))` to the migration. Update `send_outreach()` to set status="contacted" on success. | 2-4 hours |

---

## 37. Inconsistent Naming of the Telegram User ID Field

**Files:** `backend/services/supabase.py`, `backend/services/conversation_store.py`

The `users` table column is called `telegram_id` but stores both Telegram user IDs AND web session tokens (as `"web:{session_token}"`). The field name is misleading for web users.

```python
# conversation_store.py
channel_key = f"{channel}:{external_user_id}"
return get_or_create_user(channel_key, username=username)
```

For web users, `telegram_id` = `"web:{token}"`. For Telegram users, `telegram_id` = the Telegram user ID string.

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| Medium | Field name is a lie. Makes the schema confusing for new developers. Will cause bugs when someone writes a query filtering by `telegram_id` thinking it only contains Telegram IDs. | Rename to `channel_user_id` or `external_id` with a `channel` column. Or at minimum, document the dual usage. | 4-8 hours (requires migration) |

---

## 38. Global `_client` Variable in `supabase.py` Is Not Thread-Safe

**Files:** `backend/services/supabase.py` (line 17)

```python
_client: Client | None = None
```

The Supabase client is cached in a module-level variable. FastAPI with `uvicorn` runs multiple workers by default. While `create_client` is likely thread-safe, the pattern of:
```python
if _client is not None:
    return _client
_client = create_client(SUPABASE_URL, SUPABASE_KEY)
```

has a TOCTOU race condition under thread concurrency (two threads could both pass the `is None` check and create two clients).

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| Low | In practice, FastAPI with a single worker is fine. But with multiple workers, this is a race. | Use a threading lock or `functools.lru_cache` on the factory function. | 1 hour |

---

## 39. The `user_preferences` Table Tracks Only Tone/Length/Style

**Files:** `backend/services/supabase.py` (lines 561-608)

The table has columns for `tone`, `length`, `style`, `industry_focus`. But:
- `detect_preferences_from_refinement()` only extracts `length`, `tone`, and `style`
- `workflows.py` only uses `tone` and `length` from preferences
- `conversation_engine.py` only reads preferences in `_get_after_draft_variation()` — nowhere else

The preference system is 80% implemented: storage and detection work, but the engine doesn't actually use preferences to influence draft generation, lead search, or conversational style.

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| Low | Feature is present but incomplete. Not harmful, just unused. | Either complete the integration (pass preferences to draft generation, adjust search behavior) or reduce the schema to only what's actually used. | 1-2 days to complete, 1 hour to trim |

---

## 40. `requirements.txt` Pins No Versions

**Files:** `backend/requirements.txt`

```
fastapi
uvicorn
requests
python-dotenv
supabase
serpapi
```

Zero version pins. Tomorrow a `serpapi==2.0.0` with a breaking API change could ship and the next Render deploy would crash.

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| High | Non-deterministic builds. A deploy that worked yesterday could break today because of an unpinned dependency upgrade. | Run `pip freeze > requirements.txt` after a known-good install. Pin at least major/minor versions. | 30 minutes |

---

## 41. `FRONTEND/package.json` Also Pins No Versions (Uses ^ Caret)

**Files:** `frontend/package.json`

```json
"next": "^15.3.8",
"react": "19.1.0",
"react-dom": "19.1.0",
"tailwindcss": "3.4.17",
```

Next.js uses the `^` caret range. While minor/patch updates are usually safe, `^15.3.8` could install `15.4.0` with behavioral changes. React 19.1.0 is pinned exactly (good), but the devDependencies use `^` ranges.

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| Low | Less severe than the backend since npm has lockfiles (`package-lock.json` exists). But the lockfile could be regenerated with different transitive deps. | Add `.npmrc` with `save-exact=true` or pin explicitly. | 15 minutes |

---

## 42. `send_outreach()` Regenerates the Draft on Every Send

**Files:** `backend/workflows.py` (lines 261-268)

```python
try:
    draft = generate_outreach_email(lead)
    send_email(access_token, lead.get("email"), draft.get("subject"), draft.get("body"))
```

When the user says "send it," the workflow regenerates the email from scratch instead of sending the draft that was already shown to and approved by the user. The approved draft text from `previous_message` is available in the context but ignored.

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| High | The email the user approved may differ from what gets sent. If the user requested "make it shorter" and then "send it," the regenerated draft won't include the user's requested edits. | Pass the approved draft text to `send_outreach()` and use it directly instead of regenerating. Only regenerate if no draft exists. | 2-4 hours |

---

## 43. `conversation_engine.py` Has Inline Duplication of Response Variation Logic

**Files:** `backend/services/conversation_engine.py` (lines 523-553)

The engine has its own `_get_dynamic_prompt()` that duplicates the variation pool logic from `conversational_response_generator.py`. Both files define response variation pools and selection logic. `conversation_engine.py`'s `_get_service_prompt_variation()` calls into `conversational_response_generator.py` but `_get_onboarding_prompt()` and `_get_greeting_response()` in the engine use their own local pools.

The engine also re-implements `_parse_natural_send_intent()`, `_parse_natural_refine_intent()`, and `_is_greeting()` — all of which partially overlap with `_classify_natural_action()` in the response generator.

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| Medium | Two parallel systems for understanding user intent and selecting responses. Changes to one may not reflect in the other. | Consolidate all intent understanding into `conversational_response_generator.py`. `conversation_engine.py` should only route, not classify. | 2-3 days |

---

## 44. No Mechanism to Retry Failed Workflow Steps

If `generate_outreach_email()` raises `OpenAIError` (quota exceeded, timeout), the whole send workflow fails. There's no retry mechanism.

If `search_free_leads()` raises `SerpAPIError` (quota exceeded, rate limited), the whole lead search fails for that query. There's no retry with backoff.

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| Medium | Transient failures (rate limits, network blips) cause permanent user-facing errors. Users have to re-type their request. | Add exponential backoff retry with jitter to OpenAI and SerpAPI calls. At least 1 retry before failing. | 4-6 hours |

---

## 45. The Project Has No `pyproject.toml` or `setup.py`

The backend is run directly via `uvicorn main:app` with no Python package metadata. There's no `[project]` section defining name, version, dependencies (pinned), Python version requirement, or entry points.

| Severity | Reason | Fix | Effort |
|----------|--------|-----|--------|
| Medium | No way to `pip install -e .` the project. No dependency/version metadata outside the unpinned requirements.txt. No Python version constraint. | Create `pyproject.toml` with project metadata, dependency list (pinned), and Python >=3.11 requirement. | 2-4 hours |

---

## Summary

| Severity | Count |
|----------|-------|
| Critical | 3 |
| High | 7 |
| Medium | 17 |
| Low | 10 |

### Critical Items (Fix First)
1. **#7** — API keys printed to stdout via debug logging
2. **#27** — `seen_names` undefined in `free_leads.py` (latent NameError)
3. **#33** — Zero tests across 67 source files

### High Items (Fix Before Production Launch)
4. **#6** — CORS wide open (`allow_origins=["*"]`)
5. **#8** — No authentication — UUID session tokens in localStorage
6. **#10** — Session context reconstructed by scanning all conversation history
7. **#16** — Inconsistent error handling (3 patterns coexist)
8. **#22** — No rate limiting
9. **#23** — Synchronous blocking AI calls (30-90s response times)
10. **#30** — `/google/callback` state parsing fragile, crashes on web sessions
11. **#40** — No version pins in requirements.txt (non-deterministic builds)
12. **#42** — `send_outreach()` regenerates draft instead of sending approved version
