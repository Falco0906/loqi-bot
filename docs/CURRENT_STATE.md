# Loqi Current State

This document captures what works RIGHT NOW in the Loqi codebase. It's the most important reference for understanding the current implementation.

---

## What Works RIGHT NOW

### ✅ Backend - Fully Operational

**Running on:** `http://localhost:10000` (local) or Render (production)

**API Endpoints:**

```
POST /api/web/session                  - Create new session
GET  /api/web/session/{token}          - Get session info
GET  /api/web/session/{token}/messages - Get message history
POST /api/web/session/{token}/messages - Send message
POST /webhook                           - Telegram webhook
GET  /google/callback                   - Gmail OAuth callback
```

**Session Flow:**
1. `POST /api/web/session` returns `{session_token, user_id, display_name}`
2. Send messages with `{"text": "your message"}`
3. Bot responds with prompts or leads

**Lead Search Flow:**
1. User enters service (what you sell) → stored as `service`
2. User enters target (who you want to reach) → stored as `target`
3. System triggers `generate_leads` workflow
4. ICP extracted → semantic expansion → SerpAPI search → deduplication → leads returned

### ✅ ICP Extraction - Dual Mode

**Location:** `backend/services/icp_extractor.py`

**AI Mode (when OPENAI_API_KEY works):**
- Uses OpenAI GPT-4o-mini via `/v1/responses` endpoint
- Returns structured ICP with industries, roles, keywords, search_hints
- Mode: `"ai"`

**Fallback Mode (when AI unavailable):**
- Industry-first role mapping (restaurants → Restaurant Owner, Operations Manager)
- Offer extraction (CRM for startups → CRM)
- Industry-aware keywords (restaurant automation, hospitality)
- Mode: `"fallback"`

**Output structure:**
```json
{
  "offer": "CRM",
  "industries": ["startups"],
  "target_roles": ["Founder", "COO", "Head of Operations"],
  "company_types": [],
  "pain_points": [],
  "keywords": ["CRM startups", "CRM for startups"],
  "search_hints": ["Founder startups"],
  "mode": "fallback"
}
```

### ✅ Semantic Search Expansion

**Location:** `backend/services/search_expansion.py`

- Takes ICP object (or raw service/target strings)
- Expands into LinkedIn search queries
- Format: `site:linkedin.com/in "search terms"`
- Falls back to deterministic when OpenAI unavailable

### ✅ Lead Provider (SerpAPI)

**Location:** `backend/services/lead_provider.py`, `backend/services/free_leads.py`

- Uses SerpAPI package with Client API
- Searches LinkedIn profiles
- Deduplicates by LinkedIn URL
- Returns leads with name, title, company, LinkedIn URL

**SerpAPI key in .env:**
```
SERPAPI_KEY=bb8c10c3ff5a32ce538c86c4f53334531c1003c974395380407eec4907f9ca63
```

### ✅ Supabase Persistence

**Location:** `backend/services/supabase.py`

**Tables used:**
- `users` - User accounts (telegram_id, username)
- `leads` - Stored leads (user_id, name, company, linkedin_url, status)
- `conversations` - Chat history
- `workflow_sessions` - Session state
- `workflow_messages` - Workflow message logs
- `workflow_events` - Event tracking (includes ICP storage)

**ICP stored to** `workflow_events` with:
```json
{"structured_icp": {...}}
```

### ✅ Web Chat UI

**Running on:** `http://localhost:3000` (local) or Vercel (production)

**Features:**
- Chat interface
- Lead list display with selection
- Draft preview
- Gmail connect button
- Session token persistence

---

## What Works PARTIALLY

### ⚠️ Gmail Integration

**Location:** `backend/services/gmail.py`, `backend/services/google_auth.py`

**Working:**
- OAuth2 flow (token exchange, refresh)
- Email sending via Gmail API

**Not Working Well:**
- Inbox sync (partial implementation)
- Reply detection (not implemented)
- Send status tracking

### ⚠️ Lead Ranking

**Status:** NOT IMPLEMENTED

Current: leads returned in SerpAPI order
Future: AI-powered relevance scoring based on ICP match

### ⚠️ Lead Enrichment

**Status:** NOT IMPLEMENTED

Current: only basic LinkedIn data from SerpAPI
Future: company data, email finding, social profiles

---

## What is NOT Implemented

### ❌ Reply Engine
- No reply detection
- No reply classification
- No auto-followup triggers

### ❌ Personalization Memory
- No storage of user preferences
- No tone learning
- No industry memory

### ❌ Analytics
- No metrics tracking
- No reply rate calculation
- No workflow analytics

### ❌ Stripe/Auth
- No proper authentication
- No subscription management
- Session tokens are simple UUIDs

### ❌ Apollo Integration
- Apollo service exists but not wired up
- Lead provider abstraction allows switching

---

## Current Limitations

1. **Lead Quality Variability** - SerpAPI returns mixed quality
2. **No Ranking** - Results not sorted by ICP relevance
3. **Limited Enrichment** - Only basic profile data
4. **OpenAI Quota** - Falls back to deterministic frequently
5. **No Reply Detection** - Can't detect responses
6. **Weak Gmail Sync** - Inbox not fully synced
7. **Single Provider** - Only SerpAPI for leads

---

## Environment Requirements

### Required Backend Variables:
```
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=xxx
OPENAI_API_KEY=sk-xxx (optional, fallback works without it)
SERPAPI_KEY=xxx
GMAIL_CLIENT_ID=xxx
GMAIL_CLIENT_SECRET=xxx
SESSION_SECRET=xxx
LEAD_PROVIDER=free (or "apollo")
```

### Required Frontend Variables:
```
NEXT_PUBLIC_API_URL=http://localhost:10000 (or production URL)
```

---

## Database Schema Summary

**users** - `id, telegram_id, username, created_at`
**leads** - `id, user_id, name, company, email, linkedin_url, status, created_at`
**conversations** - `id, user_id, role, message, created_at`
**workflow_sessions** - `id, user_id, workflow_type, state, created_at`
**workflow_messages** - `id, workflow_session_id, role, message, created_at`
**workflow_events** - `id, workflow_session_id, event_type, payload, created_at`

---

## Current File Structure

```
backend/
├── main.py                 # FastAPI entry, routes, webhooks
├── workflows.py           # Workflow orchestration (generate_leads, draft_message, send_email)
├── requirements.txt
├── .env
├── services/
│   ├── conversation_engine.py  # Shared multi-client orchestration
│   ├── icp_extractor.py        # ICP extraction (AI + fallback)
│   ├── search_expansion.py     # Semantic query expansion
│   ├── lead_provider.py        # Lead search orchestration
│   ├── free_leads.py           # SerpAPI implementation
│   ├── apollo.py               # Apollo integration (not wired)
│   ├── ai.py                   # OpenAI generation
│   ├── gmail.py                # Email sending
│   ├── google_auth.py          # OAuth handling
│   ├── supabase.py             # Database operations
│   └── conversation_store.py   # Event recording

frontend/
├── app/
│   ├── page.tsx            # Main chat UI
│   ├── layout.tsx          # Layout with providers
│   └── globals.css
├── components/
│   └── chat/               # Chat components
├── package.json
└── .env.local
```

---

## Deployment State

**Backend:** Render (auto-deploy from main branch)
**Frontend:** Vercel (auto-deploy from main branch)
**Database:** Supabase (managed)

---

## Testing Commands

```bash
# Start backend
cd backend && source venv/bin/activate && uvicorn main:app --reload --port 10000

# Start frontend
cd frontend && npm run dev

# Test ICP extraction
source venv/bin/activate
python3 -c "from services.icp_extractor import extract_structured_icp; print(extract_structured_icp('CRM for startups'))"

# Test lead search through API
curl -X POST http://127.0.0.1:10000/api/web/session -H "Content-Type: application/json" -d '{"message": "test"}'
```

---

## Key Behavior Summary

1. **Session Creation** → Returns token, stores user in Supabase
2. **Service Input** → Stored in session context
3. **Target Input** → Triggers lead search workflow
4. **Lead Search** → ICP → Expansion → SerpAPI → Dedupe → Return
5. **Lead Selection** → Number input selects lead for outreach
6. **Draft Generation** → OpenAI generates personalized email
7. **Email Send** → Gmail API sends draft