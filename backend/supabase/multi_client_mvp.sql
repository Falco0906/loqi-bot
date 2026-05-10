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
