-- 014 Discovery Foundation — Discoveries as first-class entities.
-- Apply AFTER 003_job_engine.sql, 006_workspaces.sql, 007_domain.sql.
-- (008_campaigns.sql optional: the campaigns.discovery_id link is only added
--  when the campaigns table exists.)
--
-- A Discovery is the durable, per-run record of ONE research run. It owns
-- everything about that run:
--   * the query asked, the lifecycle status and completed_at;
--   * its Jobs — the relationship is persisted on the JOB side:
--     jobs.discovery_id (nullable FK, ON DELETE SET NULL). A Discovery may be
--     refreshed, rerun, or scheduled many times over its lifetime, so
--     Discovery → many Jobs, Job → one Discovery. Purged transient jobs never
--     orphan a Discovery, and a Discovery never owns a single job.
--   * provider_provenance.jsonb — which search providers surfaced leads per
--     run, with per-provider counts (extension point for provider billing /
--     re-enrichment decisions).
--   * summary / filters jsonb — the narrative brief + active filters
--     (extension point: swap the deterministic count brief for a real
--     AI-generated brief; schema is already shaped for it).
--
-- Link tables discovery_companies / discovery_leads never duplicate canonical
-- data. They reference the workspace_* links (whose global identity lives in
-- 007_domain), and add ONLY the per-run rank / match score / provenance.
-- Same pattern as campaign_leads: one company or lead can belong to many
-- Discoveries; each link row is scoped per (discovery_id, entity).
--
-- Idempotency contract: mirrors 007 — `create table if not exists` guarded by
-- `alter ... add column if not exists` blocks and `create index if not exists`,
-- so the file is RESUMABLE and safe to re-run on any database.
--
-- ─── discoveries ────────────────────────────────────────────────────────
-- One row per research run. Ownership root of the Discovery genre: campaigns
-- may later reference a discovery_id, never the reverse, and jobs reference a
-- discovery_id, never the reverse.

create table if not exists discoveries (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  query text not null default '',
  status text not null default 'queued',
  summary jsonb not null default '{}',
  filters jsonb not null default '[]',
  provider_provenance jsonb not null default '{}',
  created_by text not null default '',
  updated_by text not null default '',
  version integer not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  completed_at timestamptz,
  deleted_at timestamptz,
  constraint discoveries_status_check
    check (status in ('queued', 'searching', 'completed', 'failed', 'cancelled'))
);

alter table discoveries add column if not exists summary jsonb not null default '{}';
alter table discoveries add column if not exists filters jsonb not null default '[]';
alter table discoveries add column if not exists provider_provenance jsonb not null default '{}';
alter table discoveries add column if not exists created_by text not null default '';
alter table discoveries add column if not exists updated_by text not null default '';
alter table discoveries add column if not exists version integer not null default 1;
alter table discoveries add column if not exists updated_at timestamptz;
alter table discoveries add column if not exists completed_at timestamptz;
alter table discoveries add column if not exists deleted_at timestamptz;

do $$
begin
  update discoveries set updated_at = created_at where updated_at is null;
  alter table discoveries alter column updated_at set default now();
  alter table discoveries alter column updated_at set not null;
end $$;

create index if not exists discoveries_workspace_idx on discoveries(workspace_id, created_at desc);
create index if not exists discoveries_status_idx on discoveries(status);
create index if not exists discoveries_deleted_idx on discoveries(deleted_at) where deleted_at is not null;

-- ─── jobs.discovery_id ──────────────────────────────────────────────────
-- The ownership link, persisted on the JOB side: each job that contributed to
-- a Discovery carries jobs.discovery_id. ON DELETE SET NULL so purging a
-- Discovery never breaks job history. Guarded so the migration is a no-op on
-- databases without 003_job_engine.

do $$
begin
  if to_regclass('public.jobs') is not null then
    alter table jobs add column if not exists discovery_id uuid
      references discoveries(id) on delete set null;
    create index if not exists jobs_discovery_idx
      on jobs(discovery_id) where discovery_id is not null;
  end if;
end $$;

-- ─── discovery_companies ────────────────────────────────────────────────
-- Workspace-scoped companies surfaced by a Discovery, with the per-run rank
-- and match score. References workspace_companies (workspace provenance) and
-- companies (global identity for joins).

create table if not exists discovery_companies (
  id uuid primary key default gen_random_uuid(),
  discovery_id uuid not null references discoveries(id) on delete cascade,
  workspace_company_id uuid not null references workspace_companies(id) on delete cascade,
  company_id uuid references companies(id) on delete cascade,
  rank integer not null default 0,
  match_score numeric not null default 0,
  source_provider text not null default '',
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now(),
  deleted_at timestamptz
);

alter table discovery_companies add column if not exists metadata jsonb not null default '{}';
alter table discovery_companies add column if not exists deleted_at timestamptz;

create index if not exists discovery_companies_discovery_idx
  on discovery_companies(discovery_id, rank);
create index if not exists discovery_companies_company_idx
  on discovery_companies(company_id) where company_id is not null;
create index if not exists discovery_companies_deleted_idx
  on discovery_companies(deleted_at) where deleted_at is not null;

-- Same canonical entity surfaces only once per Discovery; dismissing then
-- re-adding a company reuses the soft-deleted row (partial unique key).
create unique index if not exists discovery_companies_discovery_company_uidx
  on discovery_companies(discovery_id, company_id) where company_id is not null and deleted_at is null;

-- ─── discovery_leads ────────────────────────────────────────────────────
-- Workspace leads surfaced by a Discovery, with per-run rank / match score /
-- per-workspace review status (found → reviewed → approved/rejected/added).

create table if not exists discovery_leads (
  id uuid primary key default gen_random_uuid(),
  discovery_id uuid not null references discoveries(id) on delete cascade,
  lead_id uuid not null references workspace_leads(id) on delete cascade,
  rank integer not null default 0,
  match_score numeric not null default 0,
  status text not null default 'found',
  source_provider text not null default '',
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now(),
  deleted_at timestamptz,
  constraint discovery_leads_status_check
    check (status in ('found', 'reviewed', 'approved', 'rejected', 'added'))
);

alter table discovery_leads add column if not exists match_score numeric not null default 0;
alter table discovery_leads add column if not exists status text not null default 'found';
alter table discovery_leads add column if not exists source_provider text not null default '';
alter table discovery_leads add column if not exists metadata jsonb not null default '{}';
alter table discovery_leads add column if not exists deleted_at timestamptz;

create index if not exists discovery_leads_discovery_idx on discovery_leads(discovery_id, rank);
create index if not exists discovery_leads_lead_idx on discovery_leads(lead_id);
create index if not exists discovery_leads_deleted_idx on discovery_leads(deleted_at) where deleted_at is not null;

create unique index if not exists discovery_leads_discovery_lead_uidx
  on discovery_leads(discovery_id, lead_id) where deleted_at is null;

-- ─── campaigns.discovery_id ─────────────────────────────────────────────
-- Campaigns may reference the Discovery they were sourced from. ON DELETE
-- SET NULL: deleting a Discovery never deletes its campaigns. Guarded so the
-- migration is a no-op on databases without 008_campaigns.

do $$
begin
  if to_regclass('public.campaigns') is not null then
    alter table campaigns add column if not exists discovery_id uuid
      references discoveries(id) on delete set null;
    create index if not exists campaigns_discovery_idx
      on campaigns(discovery_id) where discovery_id is not null;
  end if;
end $$;