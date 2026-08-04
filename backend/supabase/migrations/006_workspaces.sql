-- 006 Launch Foundation — Organizations + Workspaces ownership root.
-- Apply AFTER 005_external_identity.sql.
--
-- Every user gets a Personal Organization and a Personal Workspace, so a solo
-- user never notices organizations. Later, Acme Inc can add Sales / Marketing /
-- Founders as additional workspaces under the same organization.
--
-- Review additions:
--   organizations.updated_by / version  — multi-admin audit + optimistic lock.
--   workspaces.created_by / updated_by  — who created/mutated; multi-user audit.
--   workspaces.metadata jsonb           — branding, region, feature flags.
--   workspaces.owner_user_id ON DELETE SET NULL — the owning user leaving must
--       not destroy the workspace and its campaigns/leads/knowledge.
--   workspace_members.updated_at / deleted_at / metadata — membership history,
--       removable-but-recoverable members, per-member overrides.
--   CHECK constraints on status/role/interval keep allowed states canonical and
--       catch data rot; TEXT (not native enum) so values can be extended with a
--       single migration instead of an ALTER TYPE lock.

-- ─── organizations ───────────────────────────────────────────────────────
-- Idempotent bootstrap of the organization platform table (002_organizations.sql
-- may or may not have been applied on an existing deployment).

create table if not exists organizations (
  id text primary key,
  name text not null,
  slug text not null,
  display_name text not null default '',
  description text not null default '',
  avatar_url text not null default '',
  created_by text not null default '',
  updated_by text not null default '',
  status text not null default 'active',
  metadata jsonb not null default '{}',
  settings jsonb not null default '{}',
  version integer not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz,
  constraint organizations_status_check
    check (status in ('active', 'suspended', 'archived'))
);

-- Idempotent for deployments where 002_organizations.sql already ran.
alter table organizations add column if not exists updated_by text not null default '';
alter table organizations add column if not exists version integer not null default 1;

create unique index if not exists idx_organizations_slug ON organizations (slug) WHERE deleted_at IS NULL;
create unique index if not exists idx_organizations_name ON organizations (name) WHERE deleted_at IS NULL;
create index if not exists idx_organizations_created_by ON organizations (created_by);
create index if not exists idx_organizations_deleted_at ON organizations (deleted_at)
  where deleted_at is not null;

-- ─── workspaces ───────────────────────────────────────────────────────────
-- The ownership root for campaigns, leads, companies, drafts, knowledge, jobs.
-- The web workspace's id equals its workflow_sessions.id (channel='workspace'),
-- which keeps every existing /api/web/session/{token} route working unchanged.

create table if not exists workspaces (
  id uuid primary key,
  organization_id text not null default '',
  name text not null,
  slug text not null default '',
  owner_user_id uuid references identity_users(id) on delete set null,
  created_by text not null default '',
  updated_by text not null default '',
  status text not null default 'active',
  settings jsonb not null default '{}',
  metadata jsonb not null default '{}',
  version integer not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz,
  constraint workspaces_status_check
    check (status in ('active', 'suspended', 'archived'))
);

alter table workspaces alter column owner_user_id drop not null;
alter table workspaces add column if not exists created_by text not null default '';
alter table workspaces add column if not exists updated_by text not null default '';
alter table workspaces add column if not exists metadata jsonb not null default '{}';
alter table workspaces add column if not exists version integer not null default 1;

-- Owner may leave without destroying the workspace (soft/hard delete of the
-- owner cascades elsewhere); demote to set-null-owner instead of cascade.
do $$
begin
  if exists (
    select 1 from pg_constraint
    where conname = 'workspaces_owner_user_id_fkey'
  ) then
    alter table workspaces drop constraint workspaces_owner_user_id_fkey;
  end if;
end $$;
alter table workspaces
  add constraint workspaces_owner_user_id_fkey
  foreign key (owner_user_id) references identity_users(id) on delete set null;

create unique index if not exists workspaces_org_slug_uidx
  on workspaces(organization_id, slug) where deleted_at is null;
create index if not exists workspaces_owner_idx on workspaces(owner_user_id);
create index if not exists workspaces_deleted_idx on workspaces(deleted_at)
  where deleted_at is not null;

-- ─── workspace_members ────────────────────────────────────────────────────
-- Single-user today (the owner), Teams/Enterprise tomorrow.

create table if not exists workspace_members (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  user_id uuid not null references identity_users(id) on delete cascade,
  role text not null default 'member',
  status text not null default 'active',
  joined_at timestamptz not null default now(),
  invited_by text not null default '',
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz,
  constraint workspace_members_role_check
    check (role in ('owner', 'admin', 'member', 'viewer')),
  constraint workspace_members_status_check
    check (status in ('active', 'invited', 'suspended'))
);

alter table workspace_members add column if not exists metadata jsonb not null default '{}';
alter table workspace_members add column if not exists updated_at timestamptz not null default now();
alter table workspace_members add column if not exists deleted_at timestamptz;

create unique index if not exists workspace_members_ws_user_uidx
  on workspace_members(workspace_id, user_id) where deleted_at is null;
create index if not exists workspace_members_user_idx on workspace_members(user_id);
create index if not exists workspace_members_deleted_idx on workspace_members(deleted_at)
  where deleted_at is not null;