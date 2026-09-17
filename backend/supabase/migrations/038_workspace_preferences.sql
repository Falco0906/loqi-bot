-- Durable current-state preferences. Session tokens and analytical payloads
-- are deliberately excluded: every row is scoped to a canonical workspace.
create table if not exists workspace_preferences (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  preference_key text not null,
  preference_value text not null,
  confidence numeric not null,
  source text not null default '',
  evidence_count integer not null default 0,
  first_observed_at timestamptz not null default now(),
  last_observed_at timestamptz not null default now(),
  version bigint not null default 1,
  updated_by uuid references identity_users(id) on delete set null,
  updated_at timestamptz not null default now(),
  constraint workspace_preferences_scope_key_uidx unique (workspace_id, preference_key),
  constraint workspace_preferences_confidence_check check (confidence >= 0 and confidence <= 1),
  constraint workspace_preferences_evidence_check check (evidence_count >= 0),
  constraint workspace_preferences_version_check check (version >= 1)
);

create index if not exists workspace_preferences_workspace_updated_idx
  on workspace_preferences(workspace_id, updated_at desc);
