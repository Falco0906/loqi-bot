-- 008 Launch Foundation — Campaigns, Campaign Leads, Strategies, Drafts.
-- Apply AFTER 007_domain.sql.
--
-- Campaigns never own strategy text directly: campaign -> strategies -> drafts.
-- Strategies can be regenerated (new version) without touching campaign metadata.
-- Drafts are first-class and reference campaign + workspace lead; generation
-- provenance (model, version, prompt hash) is stored for later comparison.
--
-- Review additions (production hardening):
--   campaign_leads.lead_id → workspace_leads(id) — campaigns reference the
--       workspace-scoped lead row (the campaign is workspace-scoped too), not
--       the global person.
--   drafts.lead_id → workspace_leads(id) ON DELETE SET NULL — a lead removed
--       from the workspace must not destroy generated drafts.
--   campaigns.updated_by / deleted_at / metadata / version — audit + undo +
--       optimistic concurrency in multi-user workspaces. deleted_at is distinct
--       from archived_at: archived is a business state, deleted is removal.
--   drafts.created_by/updated_by — who generated/edited (system or user).
--   CHECK constraints keep status vocabularies canonical (TEXT + CHECK, not
--       native enums, so new states are added by migration).

-- ─── campaigns ────────────────────────────────────────────────────────────

create table if not exists campaigns (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  organization_id text not null default '',
  name text not null default '',
  objective text not null default '',
  status text not null default 'planning',
  search_query text not null default '',
  settings jsonb not null default '{}',
  created_by text not null default '',
  updated_by text not null default '',
  metadata jsonb not null default '{}',
  version integer not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  archived_at timestamptz,
  deleted_at timestamptz,
  constraint campaigns_status_check
    check (status in ('planning', 'draft', 'running', 'paused', 'completed', 'archived', 'cancelled', 'failed'))
);

alter table campaigns add column if not exists updated_by text not null default '';
alter table campaigns add column if not exists metadata jsonb not null default '{}';
alter table campaigns add column if not exists version integer not null default 1;
alter table campaigns add column if not exists deleted_at timestamptz;

create index if not exists campaigns_workspace_idx on campaigns(workspace_id, created_at desc);
create index if not exists campaigns_workspace_status_idx
  on campaigns(workspace_id, status, created_at desc)
  where archived_at is null and deleted_at is null;
create index if not exists campaigns_deleted_idx on campaigns(deleted_at)
  where deleted_at is not null;

-- ─── campaign_leads ───────────────────────────────────────────────────────
-- Campaigns REFERENCE workspace leads. They do not own them. A lead can be in
-- many campaigns; the workspace lead itself lives in workspace_leads forever.

create table if not exists campaign_leads (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references campaigns(id) on delete cascade,
  lead_id uuid not null references workspace_leads(id) on delete cascade,
  status text not null default 'added',
  added_by text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz,
  constraint campaign_leads_status_check
    check (status in ('added', 'active', 'removed', 'paused'))
);

alter table campaign_leads add column if not exists deleted_at timestamptz;

-- Repoint any legacy FK that referenced the global leads table.
do $$
begin
  if exists (
    select 1 from pg_constraint where conname = 'campaign_leads_lead_id_fkey'
  ) then
    alter table campaign_leads drop constraint campaign_leads_lead_id_fkey;
  end if;
end $$;
alter table campaign_leads
  add constraint campaign_leads_lead_id_fkey
  foreign key (lead_id) references workspace_leads(id) on delete cascade;

create unique index if not exists campaign_leads_campaign_lead_uidx
  on campaign_leads(campaign_id, lead_id) where deleted_at is null;
create index if not exists campaign_leads_lead_idx on campaign_leads(lead_id);
create index if not exists campaign_leads_status_idx on campaign_leads(campaign_id, status);
create index if not exists campaign_leads_deleted_idx on campaign_leads(deleted_at)
  where deleted_at is not null;

-- ─── strategies ───────────────────────────────────────────────────────────
-- Versioned, immutable-after-write. New versions supersede (is_current=false).

create table if not exists strategies (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references campaigns(id) on delete cascade,
  version integer not null default 1,
  is_current boolean not null default true,
  objective text not null default '',
  audience text not null default '',
  channel text not null default '',
  messaging_angle text not null default '',
  sequence jsonb not null default '[]',
  tone text not null default '',
  persona text not null default '',
  offer jsonb not null default '{}',
  objections jsonb not null default '[]',
  raw jsonb not null default '{}',
  generated_at timestamptz not null default now(),
  generated_by text not null default '',
  model_used text not null default '',
  created_at timestamptz not null default now(),
  constraint strategies_version_check check (version >= 1)
);

create unique index if not exists strategies_campaign_version_uidx
  on strategies(campaign_id, version);
create index if not exists strategies_current_idx on strategies(campaign_id)
  where is_current = true;

-- ─── drafts ───────────────────────────────────────────────────────────────

create table if not exists drafts (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  campaign_id uuid references campaigns(id) on delete cascade,
  lead_id uuid references workspace_leads(id) on delete set null,
  provider text not null default '',
  subject text not null default '',
  body text not null default '',
  preview text not null default '',
  status text not null default 'pending',
  tone text not null default '',
  length text not null default '',
  generation_model text not null default '',
  generation_version text not null default '',
  prompt_hash text not null default '',
  generation_metadata jsonb not null default '{}',
  lead_snapshot jsonb not null default '{}',
  metadata jsonb not null default '{}',
  created_by text not null default '',
  updated_by text not null default '',
  version integer not null default 1,
  approved_at timestamptz,
  sent_at timestamptz,
  reply_state text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz,
  constraint drafts_status_check
    check (status in ('draft', 'pending', 'generating', 'approved', 'rejected', 'sent', 'delivered', 'failed'))
);

alter table drafts add column if not exists metadata jsonb not null default '{}';
alter table drafts add column if not exists created_by text not null default '';
alter table drafts add column if not exists updated_by text not null default '';
alter table drafts add column if not exists version integer not null default 1;
alter table drafts add column if not exists deleted_at timestamptz;

-- Repoint any legacy FK that referenced the global leads table.
do $$
begin
  if exists (
    select 1 from pg_constraint where conname = 'drafts_lead_id_fkey'
  ) then
    alter table drafts drop constraint drafts_lead_id_fkey;
  end if;
end $$;
alter table drafts
  add constraint drafts_lead_id_fkey
  foreign key (lead_id) references workspace_leads(id) on delete set null;

create index if not exists drafts_workspace_idx on drafts(workspace_id, created_at desc);
create index if not exists drafts_workspace_status_idx
  on drafts(workspace_id, status, created_at desc) where deleted_at is null;
create index if not exists drafts_campaign_idx on drafts(campaign_id);
create index if not exists drafts_lead_idx on drafts(lead_id);
create index if not exists drafts_status_idx on drafts(status);
create index if not exists drafts_reply_idx on drafts(reply_state) where reply_state <> '';
create index if not exists drafts_deleted_idx on drafts(deleted_at) where deleted_at is not null;