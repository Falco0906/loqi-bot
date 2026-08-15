-- 019 Strategic Actions — explicit human approval layer for PR6.1.

create table if not exists strategic_actions (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  strategic_update_id uuid not null references strategic_updates(id) on delete cascade,
  action_type text not null,
  status text not null default 'proposed',
  proposal jsonb not null default '{}',
  created_by text not null default '',
  created_at timestamptz not null default now(),
  approved_at timestamptz,
  executed_at timestamptz,
  dismissed_at timestamptz,
  error text not null default '',
  result jsonb not null default '{}',
  metadata jsonb not null default '{}',
  updated_at timestamptz not null default now(),
  deleted_at timestamptz
);

create unique index if not exists strategic_actions_active_uidx
  on strategic_actions(workspace_id, strategic_update_id, action_type)
  where deleted_at is null and status <> 'dismissed';
create index if not exists strategic_actions_workspace_idx
  on strategic_actions(workspace_id, created_at desc);
create index if not exists strategic_actions_update_idx
  on strategic_actions(strategic_update_id, created_at desc);
