-- 007 Launch Foundation — Global Companies, Global Leads, Workspace Links.
-- Apply AFTER 006_workspaces.sql.
--
-- Companies and leads are GLOBAL canonical entities:
--   companies are deduplicated once per normalized domain;
--   leads are deduplicated once per normalized email.
-- Workspace association lives in workspace_companies / workspace_leads, so the
-- same company is never duplicated across workspaces and enrichment performed
-- once is reusable everywhere. Search jobs are transient; search_results is a
-- staging area. Provider JSON payloads are archived immutably in
-- provider_payloads (011_provider_payloads.sql).
--
-- Review additions (production hardening):
--   source_provider    — which provider (pdl/apollo/hunter/ui) first surfaced
--                        the record; enables provenance + re-enrich decisions.
--   last_synced_at     — enrichment/verification cadence for periodic jobs.
--   created_by/updated_by — audit trail for multi-user workspaces.
--   deleted_at         — GDPR-recoverable soft delete (partial unique keys so
--                        the same email/domain can be re-created after delete).
--   version            — optimistic concurrency for human edits.
--   metadata jsonb     — provider extras / per-workspace overrides.
--   CHECK constraints on status fields — TEXT + CHECK instead of native enums
--                        so new states are added by migration, not ALTER TYPE.
--
-- Idempotency contract: on databases where these tables already exist from an
-- older shape (workspace-owned companies/leads, missing canonical_id, duplicate
-- emails/domains across workspaces), `create table if not exists` is a no-op and
-- the ALTER blocks below re-add every column the indexes rely on. The data
-- migration section (DO blocks) then deterministically collapses duplicates:
--   * group by normalized key (lower(email) / lower(domain)),
--   * keep the OLDEST row per group (created_at asc, id asc as tiebreak),
--   * repoint every referencing row (workspace_leads, workspace_companies,
--     lead_sources, lead_signals, campaign_leads, drafts) to the kept row,
--   * merge/delete only the redundant duplicates,
--   * only then are the UNIQUE indexes created (end of file), so they can
--     never fail on pre-existing data.

-- ─── companies (global) ──────────────────────────────────────────────────
-- One row per canonical company. canonical_id is a stable provider-neutral
-- key (e.g. "domain:acme.com"); domain is normalized lowercase.

create table if not exists companies (
  id uuid primary key default gen_random_uuid(),
  canonical_id text not null,
  domain text not null default '',
  name text not null default '',
  website text not null default '',
  linkedin_url text not null default '',
  industry text not null default '',
  employee_count integer,
  revenue_band text not null default '',
  country text not null default '',
  city text not null default '',
  location text not null default '',
  description text not null default '',
  source_provider text not null default '',
  created_by text not null default '',
  updated_by text not null default '',
  metadata jsonb not null default '{}',
  last_synced_at timestamptz,
  version integer not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz
);

alter table companies add column if not exists canonical_id text not null default '';
alter table companies add column if not exists source_provider text not null default '';
alter table companies add column if not exists created_by text not null default '';
alter table companies add column if not exists updated_by text not null default '';
alter table companies add column if not exists metadata jsonb not null default '{}';
alter table companies add column if not exists last_synced_at timestamptz;
alter table companies add column if not exists version integer not null default 1;
alter table companies add column if not exists deleted_at timestamptz;

create index if not exists companies_industry_idx on companies(industry);
create index if not exists companies_sync_idx on companies(source_provider, last_synced_at)
  where last_synced_at is not null;
create index if not exists companies_deleted_idx on companies(deleted_at)
  where deleted_at is not null;

-- ─── workspace_companies ─────────────────────────────────────────────────
-- Association + discovery provenance between a workspace and a global company.

create table if not exists workspace_companies (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  company_id uuid not null references companies(id) on delete cascade,
  source text not null default '',
  created_by text not null default '',
  created_at timestamptz not null default now(),
  deleted_at timestamptz
);

alter table workspace_companies add column if not exists created_by text not null default '';
alter table workspace_companies add column if not exists deleted_at timestamptz;

create index if not exists workspace_companies_company_idx on workspace_companies(company_id);
create index if not exists workspace_companies_workspace_idx on workspace_companies(workspace_id, created_at desc);
create index if not exists workspace_companies_deleted_idx on workspace_companies(deleted_at)
  where deleted_at is not null;

-- ─── leads (global) ──────────────────────────────────────────────────────
-- One row per canonical person. canonical_id is stable (e.g. "email:a@b.co");
-- email is normalized lowercase.

create table if not exists leads (
  id uuid primary key default gen_random_uuid(),
  canonical_id text not null,
  email text not null default '',
  first_name text not null default '',
  last_name text not null default '',
  title text not null default '',
  phone text not null default '',
  linkedin_url text not null default '',
  source_provider text not null default '',
  created_by text not null default '',
  updated_by text not null default '',
  metadata jsonb not null default '{}',
  last_synced_at timestamptz,
  version integer not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz
);

alter table leads add column if not exists canonical_id text not null default '';
alter table leads add column if not exists source_provider text not null default '';
alter table leads add column if not exists created_by text not null default '';
alter table leads add column if not exists updated_by text not null default '';
alter table leads add column if not exists metadata jsonb not null default '{}';
alter table leads add column if not exists last_synced_at timestamptz;
alter table leads add column if not exists version integer not null default 1;
alter table leads add column if not exists deleted_at timestamptz;

create index if not exists leads_name_idx on leads(lower(first_name), lower(last_name));
create index if not exists leads_sync_idx on leads(source_provider, last_synced_at)
  where last_synced_at is not null;
create index if not exists leads_deleted_idx on leads(deleted_at) where deleted_at is not null;

-- ─── workspace_leads ─────────────────────────────────────────────────────
-- Workspace-scoped context for a global lead: which global company it is
-- linked to here, plus acquisition/decision state (status, source, confidence)
-- that is inherently per-workspace.

create table if not exists workspace_leads (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  lead_id uuid not null references leads(id) on delete cascade,
  company_id uuid references companies(id) on delete set null,
  email text not null default '',
  first_name text not null default '',
  last_name text not null default '',
  title text not null default '',
  phone text not null default '',
  linkedin_url text not null default '',
  lead_status text not null default 'new',
  research_status text not null default 'not_researched',
  verification_status text not null default 'unverified',
  confidence numeric not null default 0,
  source text not null default '',
  created_by text not null default '',
  updated_by text not null default '',
  metadata jsonb not null default '{}',
  last_synced_at timestamptz,
  version integer not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz,
  constraint workspace_leads_lead_status_check
    check (lead_status in ('new', 'added', 'approved', 'rejected')),
  constraint workspace_leads_research_status_check
    check (research_status in ('not_researched', 'researching', 'researched', 'failed')),
  constraint workspace_leads_verification_status_check
    check (verification_status in ('unverified', 'verified', 'invalid', 'bounced'))
);

alter table workspace_leads add column if not exists created_by text not null default '';
alter table workspace_leads add column if not exists updated_by text not null default '';
alter table workspace_leads add column if not exists metadata jsonb not null default '{}';
alter table workspace_leads add column if not exists last_synced_at timestamptz;
alter table workspace_leads add column if not exists version integer not null default 1;
alter table workspace_leads add column if not exists deleted_at timestamptz;

create index if not exists workspace_leads_workspace_idx on workspace_leads(workspace_id, created_at desc);
create index if not exists workspace_leads_email_idx on workspace_leads(workspace_id, lower(email))
  where email <> '';
create index if not exists workspace_leads_company_idx on workspace_leads(company_id)
  where company_id is not null;
create index if not exists workspace_leads_status_idx on workspace_leads(lead_status);
create index if not exists workspace_leads_research_idx on workspace_leads(research_status);
create index if not exists workspace_leads_deleted_idx on workspace_leads(deleted_at)
  where deleted_at is not null;

-- ─── lead_sources ─────────────────────────────────────────────────────────
-- One workspace lead may originate from many providers (PDL, Apollo, Hunter,
-- Clay, ...). Acquisition provenance is retained forever and never deleted.
-- The raw provider JSON is archived in provider_payloads and referenced via
-- payload_id; raw_payload remains for backward compatibility but is deprecated.

create table if not exists lead_sources (
  id uuid primary key default gen_random_uuid(),
  lead_id uuid not null references workspace_leads(id) on delete cascade,
  provider text not null,
  provider_lead_id text not null default '',
  job_id uuid,
  rank integer not null default 0,
  retrieved_at timestamptz not null default now(),
  cost numeric not null default 0,
  raw_payload jsonb not null default '{}',
  provider_metadata jsonb not null default '{}',
  payload_id uuid,
  created_at timestamptz not null default now()
);

create index if not exists lead_sources_lead_idx on lead_sources(lead_id);
create index if not exists lead_sources_job_idx on lead_sources(job_id);
create index if not exists lead_sources_payload_idx on lead_sources(payload_id)
  where payload_id is not null;

-- ─── lead_signals ─────────────────────────────────────────────────────────
-- Reusable AI intelligence: hiring, funding, tech stack, expansion, leadership
-- change, intent. Scoped to the workspace lead; the personalization engine
-- reads this table. Immutable after detection (new detections append rows).

create table if not exists lead_signals (
  id uuid primary key default gen_random_uuid(),
  lead_id uuid not null references workspace_leads(id) on delete cascade,
  company_id uuid references companies(id) on delete cascade,
  signal_type text not null,
  label text not null default '',
  strength numeric not null default 0,
  source text not null default '',
  detected_at timestamptz not null default now(),
  data jsonb not null default '{}',
  created_at timestamptz not null default now()
);

create index if not exists lead_signals_lead_type_idx on lead_signals(lead_id, signal_type);
create index if not exists lead_signals_company_type_idx on lead_signals(company_id, signal_type)
  where company_id is not null;
create index if not exists lead_signals_type_detected_idx on lead_signals(signal_type, detected_at desc);

-- ─── Data migration: deterministic deduplication ─────────────────────────
-- Legacy databases may hold one row per (workspace, email/domain) — the old
-- workspace-owned shape. Every block below is a NO-OP when no duplicates
-- exist (fresh database or already-migrated), so re-running is safe.
--
-- Rules: keep the OLDEST row per normalized key; repoint every reference to
-- the kept row; merge children of collapsed workspace_leads/workspace_companies
-- rows into the surviving row; delete only the redundant duplicates. References
-- into 008 tables are repointed when those tables exist (to_regclass guard),
-- preserving campaigns/drafts on existing databases.

-- 1) workspace_companies: collapse duplicates per (workspace_id, company_id).
do $$
declare
  g record;
  k uuid;
  wc record;
  t uuid;
begin
  for g in
    select workspace_id, company_id from workspace_companies
    where deleted_at is null
    group by workspace_id, company_id
    having count(*) > 1
  loop
    select id into k from workspace_companies
      where workspace_id = g.workspace_id and company_id = g.company_id
        and deleted_at is null
      order by created_at asc, id asc
      limit 1;
    for wc in
      select * from workspace_companies
        where workspace_id = g.workspace_id and company_id = g.company_id
          and deleted_at is null and id <> k
        order by id asc
    loop
      delete from workspace_companies where id = wc.id;
    end loop;
  end loop;
end $$;

-- 2) companies: collapse duplicates per lower(domain).
do $$
declare
  g record;
  k uuid;
  dup uuid;
  wc record;
begin
  for g in
    select lower(domain) as key from companies
    where domain <> '' and deleted_at is null
    group by lower(domain)
    having count(*) > 1
    order by lower(domain)
  loop
    select id into k from companies
      where lower(domain) = g.key
      order by created_at asc, id asc
      limit 1;
    for dup in
      select id from companies
        where lower(domain) = g.key and id <> k
        order by id asc
    loop
      update workspace_leads set company_id = k where company_id = dup;
      update lead_signals set company_id = k where company_id = dup;
      for wc in
        select * from workspace_companies
          where company_id = dup
          order by created_at asc, id asc
      loop
        if exists (
          select 1 from workspace_companies x
          where x.workspace_id = wc.workspace_id and x.company_id = k
            and x.deleted_at is null
        ) then
          delete from workspace_companies where id = wc.id;
        else
          update workspace_companies set company_id = k where id = wc.id;
        end if;
      end loop;
      delete from companies where id = dup;
    end loop;
  end loop;
end $$;

-- 3) workspace_leads: collapse duplicates per (workspace_id, lead_id), merging
--    children (lead_sources, lead_signals, campaign_leads, drafts) into the
--    surviving row so no relationship is lost.
do $$
declare
  g record;
  k uuid;
  wl record;
begin
  for g in
    select workspace_id, lead_id from workspace_leads
    where deleted_at is null
    group by workspace_id, lead_id
    having count(*) > 1
  loop
    select id into k from workspace_leads
      where workspace_id = g.workspace_id and lead_id = g.lead_id
        and deleted_at is null
      order by created_at asc, id asc
      limit 1;
    for wl in
      select * from workspace_leads
        where workspace_id = g.workspace_id and lead_id = g.lead_id
          and deleted_at is null and id <> k
        order by id asc
    loop
      update lead_sources s set lead_id = k
        where s.lead_id = wl.id
          and not exists (
            select 1 from lead_sources x
            where x.lead_id = k and x.provider = s.provider
              and x.provider_lead_id = s.provider_lead_id
              and x.provider_lead_id <> '' and x.id <> s.id
          );
      delete from lead_sources where lead_id = wl.id;
      update lead_signals set lead_id = k where lead_id = wl.id;
      if to_regclass('public.campaign_leads') is not null then
        update campaign_leads c set lead_id = k
          where c.lead_id = wl.id
            and not exists (
              select 1 from campaign_leads x
              where x.campaign_id = c.campaign_id and x.lead_id = k
                and x.deleted_at is null and x.id <> c.id
            );
        delete from campaign_leads where lead_id = wl.id;
      end if;
      if to_regclass('public.drafts') is not null then
        update drafts set lead_id = k where lead_id = wl.id;
      end if;
      delete from workspace_leads where id = wl.id;
    end loop;
  end loop;
end $$;

-- 4) leads: collapse duplicates per lower(email). This is the row that must
--    never be lost: every workspace_leads row for the duplicate is repointed
--    (or merged) to the OLDEST lead of the group before the duplicate is
--    deleted, so workspace state, sources, signals, campaign links and drafts
--    all survive.
do $$
declare
  g record;
  k uuid;
  dup uuid;
  w record;
  t uuid;
begin
  for g in
    select lower(email) as key from leads
    where email <> '' and deleted_at is null
    group by lower(email)
    having count(*) > 1
    order by lower(email)
  loop
    select id into k from leads
      where lower(email) = g.key
      order by created_at asc, id asc
      limit 1;
    for dup in
      select id from leads
        where lower(email) = g.key and id <> k
        order by id asc
    loop
      for w in
        select * from workspace_leads
          where lead_id = dup
          order by created_at asc, id asc
      loop
        select wl.id into t from workspace_leads wl
          where wl.workspace_id = w.workspace_id and wl.lead_id = k
            and wl.deleted_at is null
          limit 1;
        if t is null then
          update workspace_leads set lead_id = k, updated_at = now()
            where id = w.id;
        else
          update lead_sources s set lead_id = t
            where s.lead_id = w.id
              and not exists (
                select 1 from lead_sources x
                where x.lead_id = t and x.provider = s.provider
                  and x.provider_lead_id = s.provider_lead_id
                  and x.provider_lead_id <> '' and x.id <> s.id
              );
          delete from lead_sources where lead_id = w.id;
          update lead_signals set lead_id = t where lead_id = w.id;
          if to_regclass('public.campaign_leads') is not null then
            update campaign_leads c set lead_id = t
              where c.lead_id = w.id
                and not exists (
                  select 1 from campaign_leads x
                  where x.campaign_id = c.campaign_id and x.lead_id = t
                    and x.deleted_at is null and x.id <> c.id
                );
            delete from campaign_leads where lead_id = w.id;
          end if;
          if to_regclass('public.drafts') is not null then
            update drafts set lead_id = t where lead_id = w.id;
          end if;
          delete from workspace_leads where id = w.id;
        end if;
      end loop;
      delete from leads where id = dup;
    end loop;
  end loop;
end $$;

-- 5) lead_sources: collapse duplicates per (provider, provider_lead_id).
do $$
declare
  g record;
  k uuid;
  ls record;
begin
  for g in
    select provider, provider_lead_id from lead_sources
    where provider_lead_id <> ''
    group by provider, provider_lead_id
    having count(*) > 1
  loop
    select id into k from lead_sources
      where provider = g.provider and provider_lead_id = g.provider_lead_id
      order by created_at asc, id asc
      limit 1;
    for ls in
      select * from lead_sources
        where provider = g.provider and provider_lead_id = g.provider_lead_id
          and id <> k
        order by id asc
    loop
      delete from lead_sources where id = ls.id;
    end loop;
  end loop;
end $$;

-- ─── UNIQUE indexes (created only AFTER deduplication) ──────────────────
-- canonical_id uniques exclude '' so legacy rows backfilled with the default
-- never violate them; new rows always carry a real canonical_id
-- (see workspace_state._normalize_lead).

create unique index if not exists workspace_companies_ws_company_uidx
  on workspace_companies(workspace_id, company_id) where deleted_at is null;
create unique index if not exists companies_canonical_id_uidx on companies(canonical_id)
  where canonical_id <> '' and deleted_at is null;
create unique index if not exists companies_domain_uidx on companies(lower(domain))
  where domain <> '' and deleted_at is null;
create unique index if not exists workspace_leads_ws_lead_uidx
  on workspace_leads(workspace_id, lead_id) where deleted_at is null;
create unique index if not exists leads_canonical_id_uidx on leads(canonical_id)
  where canonical_id <> '' and deleted_at is null;
create unique index if not exists leads_email_uidx on leads(lower(email))
  where email <> '' and deleted_at is null;
create unique index if not exists lead_sources_provider_id_uidx
  on lead_sources(provider, provider_lead_id) where provider_lead_id <> '';
