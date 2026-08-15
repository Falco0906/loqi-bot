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
-- older shape, `create table if not exists` is a no-op and the ALTER blocks
-- below re-add EVERY column the indexes/data-migration/application code rely
-- on — including base columns that normally live only in the CREATE block.
-- This makes the migration RESUMABLE: if a run aborts partway (e.g. a legacy
-- column was missing and an index creation errored), the statements that
-- already committed are all `if not exists` / idempotent, so re-running the
-- file from the top completes the upgrade with no reset required.
-- This includes the ORIGINAL legacy leads shape
-- (id/user_id/name/company/email/linkedin_url/status/created_at), which lacks
-- first_name/last_name/title/phone/updated_at: first_name & last_name are
-- backfilled from `name`, updated_at from created_at, and title/phone default
-- to ''. Any legacy NOT NULL column with no default that is NOT part of the new
-- schema (e.g. user_id, status, company) has its NOT NULL relaxed so
-- new-schema inserts (which omit those columns) can never fail. The same
-- column re-add + orphan relaxation applies to workspace_leads and
-- workspace_companies so legacy workspace tables are fully upgraded too. The
-- data migration section (DO blocks) then deterministically collapses
-- duplicates:
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

-- Every column the indexes, dedup blocks, or application code depend on is
-- re-added idempotently below — including base columns that only exist in the
-- CREATE block — so an ORIGINAL-schema legacy companies table (which may only
-- have id/user_id/name/domain/linkedin_url/status/created_at) is upgraded
-- fully before any index is created.
alter table companies add column if not exists canonical_id text not null default '';
alter table companies add column if not exists domain text not null default '';
alter table companies add column if not exists name text not null default '';
alter table companies add column if not exists website text not null default '';
alter table companies add column if not exists linkedin_url text not null default '';
alter table companies add column if not exists industry text not null default '';
alter table companies add column if not exists employee_count integer;
alter table companies add column if not exists revenue_band text not null default '';
alter table companies add column if not exists country text not null default '';
alter table companies add column if not exists city text not null default '';
alter table companies add column if not exists location text not null default '';
alter table companies add column if not exists description text not null default '';
alter table companies add column if not exists source_provider text not null default '';
alter table companies add column if not exists created_by text not null default '';
alter table companies add column if not exists updated_by text not null default '';
alter table companies add column if not exists metadata jsonb not null default '{}';
alter table companies add column if not exists last_synced_at timestamptz;
alter table companies add column if not exists version integer not null default 1;
alter table companies add column if not exists created_at timestamptz not null default now();
alter table companies add column if not exists updated_at timestamptz;
alter table companies add column if not exists deleted_at timestamptz;

-- Backfill: when updated_at was absent (legacy schema), it arrives NULL;
-- anchor it to created_at, add the now() default, and tighten to NOT NULL.
-- No-op on fresh installs (default already present; set default is idempotent).
do $$
begin
  update companies set updated_at = created_at where updated_at is null;
  alter table companies alter column updated_at set default now();
  alter table companies alter column updated_at set not null;
end $$;

-- Relax ANY legacy orphan column (user_id, status, ...) that is NOT NULL
-- without a default and is not part of the new schema: new-schema inserts omit
-- those columns, so a legacy NOT NULL would make every future write fail.
-- Idempotent and schema-agnostic — drop not null simply no-ops a second time.
do $$
declare
  r record;
begin
  for r in
    select c.column_name from information_schema.columns c
    where c.table_schema = 'public' and c.table_name = 'companies'
      and c.is_nullable = 'NO'
      and c.column_name not in (
        'id', 'canonical_id', 'domain', 'name', 'website', 'linkedin_url',
        'industry', 'employee_count', 'revenue_band', 'country', 'city',
        'location', 'description', 'source_provider', 'created_by',
        'updated_by', 'metadata', 'last_synced_at', 'version', 'created_at',
        'updated_at', 'deleted_at')
  loop
    execute format('alter table companies alter column %I drop not null', r.column_name);
  end loop;
end $$;

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

-- Relax ANY legacy orphan NOT NULL column (user_id, status, ...) not part of
-- the new schema, same rationale as the companies/leads normalizers.
do $$
declare
  r record;
begin
  for r in
    select c.column_name from information_schema.columns c
    where c.table_schema = 'public' and c.table_name = 'workspace_companies'
      and c.is_nullable = 'NO'
      and c.column_name not in (
        'id', 'workspace_id', 'company_id', 'source', 'created_by',
        'created_at', 'deleted_at')
  loop
    execute format('alter table workspace_companies alter column %I drop not null', r.column_name);
  end loop;
end $$;

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

-- Every column the indexes, dedup blocks, or application code depend on is
-- re-added idempotently below — including base columns that only exist in the
-- CREATE block — so an ORIGINAL-schema legacy leads table (which may only have
-- id/user_id/name/company/email/linkedin_url/status/created_at) is upgraded
-- fully before any index is created. first_name/last_name are backfilled from
-- the legacy single-column `name`; updated_at is backfilled from created_at.
alter table leads add column if not exists canonical_id text not null default '';
alter table leads add column if not exists email text not null default '';
alter table leads add column if not exists first_name text not null default '';
alter table leads add column if not exists last_name text not null default '';
alter table leads add column if not exists title text not null default '';
alter table leads add column if not exists phone text not null default '';
alter table leads add column if not exists linkedin_url text not null default '';
alter table leads add column if not exists source_provider text not null default '';
alter table leads add column if not exists created_by text not null default '';
alter table leads add column if not exists updated_by text not null default '';
alter table leads add column if not exists metadata jsonb not null default '{}';
alter table leads add column if not exists last_synced_at timestamptz;
alter table leads add column if not exists version integer not null default 1;
alter table leads add column if not exists created_at timestamptz not null default now();
alter table leads add column if not exists updated_at timestamptz;
alter table leads add column if not exists deleted_at timestamptz;

-- Backfill legacy leads:
--   * split single-column `name` into first_name/last_name (name exists only
--     on legacy databases — the new schema has no such column, so the block is
--     guarded and is a no-op on fresh installs);
--   * updated_at = created_at (updated_at was absent in the legacy schema);
--   * tighten updated_at to NOT NULL.
do $$
begin
  if exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'leads' and column_name = 'name'
  ) then
    update leads set first_name = split_part(name, ' ', 1)
      where coalesce(name, '') <> '' and coalesce(first_name, '') = '';
    update leads set last_name =
        case
          when length(trim(substr(name, length(split_part(name, ' ', 1)) + 1))) > 0
          then trim(substr(name, length(split_part(name, ' ', 1)) + 1))
          else '' end
      where coalesce(name, '') <> '' and coalesce(last_name, '') = '';
  end if;
  update leads set updated_at = created_at where updated_at is null;
  alter table leads alter column updated_at set default now();
  alter table leads alter column updated_at set not null;
end $$;

-- Relax ANY legacy orphan column (user_id, status, company, ...) that is NOT
-- NULL without a default and is not part of the new schema: new-schema inserts
-- omit those columns, so a legacy NOT NULL would make every future write fail.
-- Idempotent and schema-agnostic — drop not null simply no-ops a second time.
do $$
declare
  r record;
begin
  for r in
    select c.column_name from information_schema.columns c
    where c.table_schema = 'public' and c.table_name = 'leads'
      and c.is_nullable = 'NO'
      and c.column_name not in (
        'id', 'canonical_id', 'email', 'first_name', 'last_name', 'title',
        'phone', 'linkedin_url', 'source_provider', 'created_by',
        'updated_by', 'metadata', 'last_synced_at', 'version', 'created_at',
        'updated_at', 'deleted_at')
  loop
    execute format('alter table leads alter column %I drop not null', r.column_name);
  end loop;
end $$;

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

-- Re-add every remaining column the indexes, dedup blocks, and application
-- code depend on (the CREATE block above is a no-op on legacy tables, so
-- without this the workspace_leads indexes and dedup block 4 would fail).
alter table workspace_leads add column if not exists email text not null default '';
alter table workspace_leads add column if not exists first_name text not null default '';
alter table workspace_leads add column if not exists last_name text not null default '';
alter table workspace_leads add column if not exists title text not null default '';
alter table workspace_leads add column if not exists phone text not null default '';
alter table workspace_leads add column if not exists linkedin_url text not null default '';
alter table workspace_leads add column if not exists lead_status text not null default 'new';
alter table workspace_leads add column if not exists research_status text not null default 'not_researched';
alter table workspace_leads add column if not exists verification_status text not null default 'unverified';
alter table workspace_leads add column if not exists confidence numeric not null default 0;
alter table workspace_leads add column if not exists source text not null default '';
alter table workspace_leads add column if not exists updated_at timestamptz;

-- Backfill: anchor updated_at to created_at and tighten to NOT NULL.
do $$
begin
  update workspace_leads set updated_at = created_at where updated_at is null;
  alter table workspace_leads alter column updated_at set default now();
  alter table workspace_leads alter column updated_at set not null;
end $$;

-- Relax ANY legacy orphan NOT NULL column (status, company, ...) not part of
-- the new schema, same rationale as the companies/leads normalizers.
do $$
declare
  r record;
begin
  for r in
    select c.column_name from information_schema.columns c
    where c.table_schema = 'public' and c.table_name = 'workspace_leads'
      and c.is_nullable = 'NO'
      and c.column_name not in (
        'id', 'workspace_id', 'lead_id', 'company_id', 'email', 'first_name',
        'last_name', 'title', 'phone', 'linkedin_url', 'lead_status',
        'research_status', 'verification_status', 'confidence', 'source',
        'created_by', 'updated_by', 'metadata', 'last_synced_at', 'version',
        'created_at', 'updated_at', 'deleted_at')
  loop
    execute format('alter table workspace_leads alter column %I drop not null', r.column_name);
  end loop;
end $$;

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
