# Supabase Workflow Tables Migration Guide

## Tables to Create
The following tables need to be created in your Supabase database:
1. `workflow_sessions`
2. `workflow_messages` 
3. `workflow_events`

These tables are additive and do not replace existing tables like `conversations`, `users`, or `leads`.

## How to Apply

### Option 1: Supabase Dashboard (Recommended)
1. Go to your Supabase project dashboard
2. Navigate to **SQL Editor** in the left sidebar
3. Click **"New query"**
4. Copy and paste the entire contents of `/backend/supabase/multi_client_mvp.sql`
5. Click **RUN**

### Option 2: Supabase CLI
If you have the Supabase CLI installed:
```bash
supabase db push --schema-file backend/supabase/multi_client_mvp.sql
```

### Option 3: Direct SQL Execution
The SQL to execute is:

```sql
create table if not exists workflow_sessions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  channel text not null,
  session_key text not null,
  title text,
  status text not null default 'active',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists workflow_sessions_user_id_idx
  on workflow_sessions(user_id, updated_at desc);

create unique index if not exists workflow_sessions_unique_active_idx
  on workflow_sessions(user_id, channel, session_key, status);

create table if not exists workflow_messages (
  id uuid primary key default gen_random_uuid(),
  workflow_session_id uuid not null references workflow_sessions(id) on delete cascade,
  role text not null,
  message_type text not null,
  content text not null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists workflow_messages_session_id_idx
  on workflow_messages(workflow_session_id, created_at);

create table if not exists workflow_events (
  id uuid primary key default gen_random_uuid(),
  workflow_session_id uuid not null references workflow_sessions(id) on delete cascade,
  event_type text not null,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists workflow_events_session_id_idx
  on workflow_events(workflow_session_id, created_at);
```

## Behavior When Tables Are Missing

The backend is designed to **degrade gracefully** when workflow tables are absent:

1. **conversation_store.py** uses `_safe_insert` and `_safe_query` functions that:
   - Return `None`/do nothing if Supabase client is unavailable
   - Catch exceptions and print helpful logs instead of crashing
   - Fall back to session IDs like `"web:{session_token}"` when workflow tables fail

2. **Workflow functionality** will still work but:
   - Workflow session persistence won't be available across restarts
   - Workflow message and event history won't be stored
   - The system falls back to using the existing `conversations` table for state

## Verification

After applying the migration, verify tables exist by running:
```sql
SELECT table_name FROM information_schema.tables 
WHERE table_schema = 'public' 
AND table_name IN ('workflow_sessions', 'workflow_messages', 'workflow_events');
```

All three tables should be returned.