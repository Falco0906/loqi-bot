-- 009 Launch Foundation — Knowledge (AI memory), Notifications, Audit Log.
-- Apply AFTER 008_campaigns.sql.
--
-- "Knowledge is data; memory is a behavior." Every AI-generated artifact gets
-- stored here: company summaries, lead summaries, campaign summaries, meeting
-- summaries, research summaries, reply summaries. Future agents never regenerate.
--
-- Review additions (production hardening):
--   knowledge.created_by — which agent/system produced the artifact
--                          ("loqi:reasoner", "user:u1") for attribution.
--   knowledge.deleted_at — memory revocation is reversible; the partial unique
--                          allows regeneration after revocation.
--   knowledge.version    — optimistic concurrency if knowledge is edited.
--   notifications.read_at / deleted_at — read state + dismiss is reversible.

-- ─── knowledge ────────────────────────────────────────────────────────────

create table if not exists knowledge (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  owner_type text not null,
  owner_id text not null,
  summary_type text not null,
  title text not null default '',
  content jsonb not null default '{}',
  source_event text not null default '',
  created_by text not null default '',
  version integer not null default 1,
  generated_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz
);

alter table knowledge add column if not exists created_by text not null default '';
alter table knowledge add column if not exists version integer not null default 1;
alter table knowledge add column if not exists deleted_at timestamptz;

create unique index if not exists knowledge_owner_summary_uidx
  on knowledge(owner_type, owner_id, summary_type) where deleted_at is null;
create index if not exists knowledge_workspace_idx on knowledge(workspace_id, created_at desc);
create index if not exists knowledge_owner_idx on knowledge(owner_type, owner_id);
create index if not exists knowledge_deleted_idx on knowledge(deleted_at)
  where deleted_at is not null;

-- ─── notifications ────────────────────────────────────────────────────────

create table if not exists notifications (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references identity_users(id) on delete cascade,
  workspace_id uuid references workspaces(id) on delete cascade,
  type text not null default 'info',
  title text not null default '',
  body text not null default '',
  read boolean not null default false,
  read_at timestamptz,
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now(),
  deleted_at timestamptz
);

alter table notifications add column if not exists read_at timestamptz;
alter table notifications add column if not exists deleted_at timestamptz;

create index if not exists notifications_user_read_idx
  on notifications(user_id, read, created_at desc);
create index if not exists notifications_user_unread_idx
  on notifications(user_id) where read_at is null and deleted_at is null;
create index if not exists notifications_deleted_idx on notifications(deleted_at)
  where deleted_at is not null;

-- ─── audit_log ────────────────────────────────────────────────────────────
-- Pure event record for audit / replay / debugging. NOT business storage.
-- Immutable by design: no updated_at, no deleted_at, no soft delete. FK
-- references are SET NULL so the log survives entity deletion.

create table if not exists audit_log (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid references workspaces(id) on delete set null,
  user_id uuid references identity_users(id) on delete set null,
  actor_type text not null default 'user',
  action text not null,
  entity_type text not null default '',
  entity_id text not null default '',
  before jsonb,
  after jsonb,
  request_id text not null default '',
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now()
);

create index if not exists audit_log_workspace_idx on audit_log(workspace_id, created_at desc);
create index if not exists audit_log_entity_idx on audit_log(entity_type, entity_id);
create index if not exists audit_log_action_idx on audit_log(action, created_at desc);