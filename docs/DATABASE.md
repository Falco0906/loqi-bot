# Loqi Database Schema

Documenting the Supabase schema, tables, and how they're used.

---

## Overview

Loqi uses Supabase (PostgreSQL) for all persistence. The schema is defined in `backend/supabase/multi_client_mvp.sql`.

---

## Tables

### users

**Purpose:** Store user accounts

**Schema:**
```sql
id          UUID PRIMARY KEY DEFAULT gen_random_uuid()
telegram_id TEXT UNIQUE
username    TEXT
created_at  TIMESTAMPTZ DEFAULT now()
```

**Usage:** Created on first session. `telegram_id` prefixed with "web:" for web users.

---

### leads

**Purpose:** Store discovered leads

**Schema:**
```sql
id           UUID PRIMARY KEY DEFAULT gen_random_uuid()
user_id      UUID REFERENCES users(id)
name         TEXT
company      TEXT
email        TEXT
linkedin_url TEXT
status       TEXT DEFAULT 'pending'  -- pending, selected, contacted, replied, converted
created_at   TIMESTAMPTZ DEFAULT now()
```

**Usage:** Created when user runs lead search. Stores LinkedIn profile data.

---

### conversations

**Purpose:** Chat history

**Schema:**
```sql
id         UUID PRIMARY KEY DEFAULT gen_random_uuid()
user_id    UUID REFERENCES users(id)
role       TEXT  -- 'user' or 'assistant'
message    TEXT
created_at TIMESTAMPTZ DEFAULT now()
```

**Usage:** Full conversation log for context and debugging.

---

### workflow_sessions

**Purpose:** Explicit workflow state tracking

**Schema:**
```sql
id            UUID PRIMARY KEY DEFAULT gen_random_uuid()
user_id       UUID REFERENCES users(id)
workflow_type TEXT  -- 'generate_leads', 'draft_message', etc.
state         JSONB  -- current workflow state
created_at    TIMESTAMPTZ DEFAULT now()
updated_at    TIMESTAMPTZ DEFAULT now()
```

**Usage:** Enables durable workflow state instead of reconstructing from chat.

---

### workflow_messages

**Purpose:** Workflow-level message logging

**Schema:**
```sql
id                   UUID PRIMARY KEY DEFAULT gen_random_uuid()
workflow_session_id  UUID REFERENCES workflow_sessions(id)
role                 TEXT
message              TEXT
created_at           TIMESTAMPTZ DEFAULT now()
```

**Usage:** Detailed workflow event logging.

---

### workflow_events

**Purpose:** Event tracking (ICP stored here)

**Schema:**
```sql
id                   UUID PRIMARY KEY DEFAULT gen_random_uuid()
workflow_session_id  UUID REFERENCES workflow_sessions(id)
event_type           TEXT  -- 'icp.extracted', 'lead_search.ran', etc.
payload              JSONB  -- event data
created_at           TIMESTAMPTZ DEFAULT now()
```

**Usage:** Store structured data like ICP objects, search results, etc.

**Example payload:**
```json
{"structured_icp": {"offer": "CRM", "industries": ["startups"], "target_roles": ["Founder"]}}
```

---

### google_tokens

**Purpose:** Store Gmail OAuth tokens

**Schema:**
```sql
id           UUID PRIMARY KEY DEFAULT gen_random_uuid()
user_id      UUID REFERENCES users(id)
access_token TEXT
refresh_token TEXT
expires_at   TIMESTAMPTZ
created_at   TIMESTAMPTZ DEFAULT now()
updated_at   TIMESTAMPTZ DEFAULT now()
```

**Usage:** Gmail API authentication. Tokens refreshed via `google_auth.py`.

---

## Relationships

```
users
├── leads (one-to-many)
├── conversations (one-to-many)
├── workflow_sessions (one-to-many)
└── google_tokens (one-to-many)

workflow_sessions
├── workflow_messages (one-to-many)
└── workflow_events (one-to-many)
```

---

## How Orchestration Uses Tables

### Session Creation
1. `POST /api/web/session` → creates user in `users` table
2. Returns session token (simple UUID, not stored)

### Lead Search Flow
1. Service/target stored in conversation context
2. On trigger: create `workflow_session`
3. Run lead search
4. Store leads in `leads` table
5. Store ICP in `workflow_events` table

### Message Flow
1. Every message logged to `conversations`
2. Workflow messages logged to `workflow_messages`
3. Key events logged to `workflow_events`

### Gmail Integration
1. OAuth flow stores tokens in `google_tokens`
2. Tokens refreshed as needed
3. Email sends tracked via messages

---

## Schema Gaps / Known Issues

### 1. No User Authentication Table
Currently users identified by UUID but no password/auth. Future: Supabase Auth.

### 2. No Lead Quality Scoring
Leads don't have relevance scores. Future: ranking based on ICP match.

### 3. No Enrichment Data
Leads only have basic fields. Future: company data, emails, social.

### 4. No Campaign Tracking
No way to group emails into campaigns. Future: campaign table.

### 5. No Reply Tracking
No storage of reply status on leads. Future: status updates, reply classification.

### 6. No Analytics Tables
No dedicated analytics tables. Future: metrics tables.

---

## Migration Notes

### Running Migrations

```sql
-- In Supabase SQL Editor
-- Run contents of backend/supabase/multi_client_mvp.sql
```

### Adding New Tables

1. Add SQL to `backend/supabase/multi_client_mvp.sql`
2. Run in Supabase
3. Update `backend/services/supabase.py` to use new table

### Schema Changes

Always:
1. Update SQL file
2. Run in Supabase
3. Update Python code to match

---

## Future Schema Additions

```sql
-- Personalization memory
CREATE TABLE user_preferences (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id),
  tone TEXT,
  accepted_phrases TEXT[],
  rejected_phrases TEXT[],
  industries TEXT[],
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Email tracking
CREATE TABLE email_tracking (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id),
  lead_id UUID REFERENCES leads(id),
  message_id TEXT,
  status TEXT,  -- pending, sent, delivered, bounced, failed
  sent_at TIMESTAMPTZ,
  delivered_at TIMESTAMPTZ,
  opened_at TIMESTAMPTZ,
  replied_at TIMESTAMPTZ
);

-- Analytics
CREATE TABLE analytics_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id),
  event_type TEXT,
  properties JSONB,
  created_at TIMESTAMPTZ DEFAULT now()
);
```