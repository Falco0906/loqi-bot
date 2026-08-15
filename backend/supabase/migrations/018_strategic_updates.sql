-- 018 Strategic Intelligence — durable evidence-backed observations.
--
-- Strategic Updates are derived interpretations over canonical workspace
-- activity. Raw campaigns, leads, drafts, conversations and messages remain
-- their own sources of truth. No signal warehouse is created here.

create table if not exists strategic_updates (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  pattern_key text not null,
  title text not null,
  summary text not null default '',
  update_type text not null default 'performance',
  status text not null default 'active',
  confidence text not null default 'low',
  observed_at timestamptz not null default now(),
  observation text not null default '',
  interpretation text not null default '',
  recommendation text not null default '',
  structured_analysis jsonb not null default '{}',
  evidence jsonb not null default '[]',
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  archived_at timestamptz,
  deleted_at timestamptz
);

create unique index if not exists strategic_updates_workspace_pattern_uidx
  on strategic_updates(workspace_id, pattern_key)
  where deleted_at is null;
create index if not exists strategic_updates_workspace_idx
  on strategic_updates(workspace_id, updated_at desc);
create index if not exists strategic_updates_type_idx
  on strategic_updates(workspace_id, update_type, updated_at desc);
create index if not exists strategic_updates_deleted_idx
  on strategic_updates(deleted_at)
  where deleted_at is not null;
