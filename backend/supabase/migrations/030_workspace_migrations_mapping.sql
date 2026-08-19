-- 030 Workspace migration mapping (SaaS-2.8).
--
-- Durable, idempotent, resumable record of legacy-workspace migrations so that
-- re-running the operator migration CLI never duplicates work and rollback is
-- possible. Additive and idempotent; safe to apply before the CLI runs.
--
-- One row per legacy workspace migration. ``status`` is one of
-- pending / applied / failed. A unique index on legacy_workspace_id makes
-- reruns safe: an already-migrated legacy workspace is never migrated twice.

create table if not exists workspace_migrations (
  id uuid primary key,
  legacy_workspace_id text not null default '',
  new_workspace_id text not null default '',
  workflow_session_id text not null default '',
  organization_id text not null default '',
  owner_user_id text not null default '',
  status text not null default 'pending',
  error text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create unique index if not exists workspace_migrations_legacy_uidx
  on workspace_migrations(legacy_workspace_id);
create index if not exists workspace_migrations_status_idx
  on workspace_migrations(status);
