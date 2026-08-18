-- 029 Durable outbound communication + provider events (SaaS-2.6).
--
-- Persists the outbound send history and provider lifecycle/communication
-- events that previously lived only in process-global in-memory lists
-- (services/outbound/outbound_persistence.py, services/communication/
-- provider_events.py). These are user-visible product state that must survive
-- restart/redeploy and must be tenant-isolated.
--
-- Ownership: both tables are WORKSPACE-scoped. ``workspace_id`` is the
-- canonical durable workspace id (workspaces.id), server-derived from the
-- authenticated user's canonical workspace — never from the client. The
-- owning workspace is resolved from the connected provider's user via the
-- canonical workspace resolver.
--
-- Sensitive OAuth credentials are NOT stored here — they remain in the
-- existing secure connected_accounts credential path. Only references
-- (provider_id, external ids) and normalized, non-secret state are persisted.
--
-- Additive, idempotent, non-destructive, safe to apply before deploy.

-- Outbound send history / delivery state (workspace-owned).
create table if not exists outbound_messages (
  id uuid primary key,
  workspace_id text not null default '',
  provider_id text not null default '',
  draft_id text not null default '',
  conversation_id text not null default '',
  thread_id text not null default '',
  subject text not null default '',
  recipient_email text not null default '',
  recipient_name text not null default '',
  status text not null default 'sent',
  error text not null default '',
  external_message_id text not null default '',
  sent_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists outbound_messages_workspace_idx
  on outbound_messages(workspace_id);
create index if not exists outbound_messages_ws_sent_idx
  on outbound_messages(workspace_id, sent_at desc);

-- Provider lifecycle / communication events (workspace-owned).
create table if not exists provider_events (
  id uuid primary key,
  workspace_id text not null default '',
  provider_id text not null default '',
  event_type text not null default '',
  message text not null default '',
  metadata jsonb not null default '{}',
  event_timestamp timestamptz not null default now(),
  created_at timestamptz not null default now()
);
create index if not exists provider_events_workspace_idx
  on provider_events(workspace_id);
create index if not exists provider_events_ws_time_idx
  on provider_events(workspace_id, event_timestamp);
