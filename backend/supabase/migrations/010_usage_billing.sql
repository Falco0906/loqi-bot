-- 010 Launch Foundation — Plans, Plan Features, Subscriptions, Usage.
-- Apply AFTER 009_knowledge.sql.
--
-- Schema readiness for launch billing. No billing implementation; these tables
-- define the contract. Plan features are not hardcoded — they are rows.
--
-- Review additions (production hardening):
--   plans.deleted_at / sort_order — retire plans without deleting history;
--                                    deterministic catalog ordering.
--   subscriptions.version / last_synced_at — webhook/Stripe event races and
--                                    sync cadence.
--   partial unique active-subscription-per-org — enforces the billing invariant
--                                    "one active plan per organization".
--   subscriptions are financial records → intentionally NO deleted_at.
--   usage_records.external_id — provider-side usage reference for reconciliation.

-- ─── plans ────────────────────────────────────────────────────────────────

create table if not exists plans (
  id uuid primary key default gen_random_uuid(),
  code text not null,
  name text not null,
  description text not null default '',
  billing_interval text not null default 'monthly',
  currency text not null default 'usd',
  price integer not null default 0,
  is_active boolean not null default true,
  sort_order integer not null default 0,
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz,
  constraint plans_interval_check
    check (billing_interval in ('monthly', 'yearly'))
);

alter table plans add column if not exists sort_order integer not null default 0;
alter table plans add column if not exists deleted_at timestamptz;

create unique index if not exists plans_code_uidx on plans(code) where deleted_at is null;
create index if not exists plans_deleted_idx on plans(deleted_at) where deleted_at is not null;

-- ─── plan_features ────────────────────────────────────────────────────────
-- Immutable catalog rows per plan version.

create table if not exists plan_features (
  id uuid primary key default gen_random_uuid(),
  plan_id uuid not null references plans(id) on delete cascade,
  feature text not null,
  value text not null default '',
  unit text not null default '',
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now()
);

create unique index if not exists plan_features_plan_feature_uidx on plan_features(plan_id, feature);

-- ─── subscriptions ────────────────────────────────────────────────────────

create table if not exists subscriptions (
  id uuid primary key default gen_random_uuid(),
  organization_id text not null default '',
  workspace_id uuid references workspaces(id) on delete cascade,
  plan_id uuid references plans(id) on delete set null,
  status text not null default 'incomplete',
  trial_ends_at timestamptz,
  current_period_start timestamptz,
  current_period_end timestamptz,
  cancel_at_period_end boolean not null default false,
  canceled_at timestamptz,
  provider text not null default '',
  provider_subscription_id text not null default '',
  metadata jsonb not null default '{}',
  version integer not null default 1,
  last_synced_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint subscriptions_status_check
    check (status in ('incomplete', 'incomplete_expired', 'trialing', 'active', 'past_due', 'canceled', 'unpaid', 'paused'))
);

alter table subscriptions add column if not exists version integer not null default 1;
alter table subscriptions add column if not exists last_synced_at timestamptz;

create index if not exists subscriptions_org_idx on subscriptions(organization_id);
create index if not exists subscriptions_status_idx on subscriptions(status);
create unique index if not exists subscriptions_provider_uidx
  on subscriptions(provider, provider_subscription_id) where provider <> '';
create unique index if not exists subscriptions_active_org_uidx
  on subscriptions(organization_id) where status in ('active', 'trialing') and organization_id <> '';
create index if not exists subscriptions_sync_idx on subscriptions(provider, last_synced_at)
  where last_synced_at is not null;

-- ─── usage_records ────────────────────────────────────────────────────────
-- Event-style usage tracking: research credits, AI credits, draft generations,
-- emails sent, provider API usage, monthly quotas, plan limits.
-- Append-only billing evidence: no updated_at, no deleted_at, no version.

create table if not exists usage_records (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid references workspaces(id) on delete cascade,
  organization_id text not null default '',
  user_id uuid references identity_users(id) on delete set null,
  feature text not null,
  resource text not null default '',
  units numeric not null default 1,
  provider text not null default '',
  provider_cost numeric not null default 0,
  external_id text not null default '',
  metadata jsonb not null default '{}',
  occurred_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);

alter table usage_records add column if not exists external_id text not null default '';

create index if not exists usage_records_workspace_time_idx on usage_records(workspace_id, occurred_at desc);
create index if not exists usage_records_feature_time_idx on usage_records(feature, occurred_at desc);
create index if not exists usage_records_org_time_idx on usage_records(organization_id, occurred_at desc);
create index if not exists usage_records_ws_feature_time_idx
  on usage_records(workspace_id, feature, occurred_at desc);
create index if not exists usage_records_external_idx on usage_records(provider, external_id)
  where external_id <> '';