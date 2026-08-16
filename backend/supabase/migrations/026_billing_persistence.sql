-- 026 Billing persistence closure (SaaS-1.7).
--
-- The billing Supabase repositories (SupabasePlanRepository, ...BillingEvent
-- Repository) target billing_* tables that no migration created. This closes
-- that gap so the authenticated, organization-bound billing routes (SaaS-1.4)
-- are backed by durable tables.
--
-- Column names/types/nullability mirror the billing dataclass models
-- (services/billing/models.py) and the serializers in
-- services/persistence/repositories/billing_repositories.py (metadata/data
-- are stored as jsonb and serialized via json.dumps). Enum-valued text
-- columns carry CHECK constraints matching their enums.
--
-- Additive and idempotent; safe to re-run; no destructive operations; no
-- speculative foreign keys (billing ids reference organization/customer ids
-- as loose text, consistent with the existing schema).

create table if not exists billing_plans (
  id uuid primary key,
  code text not null default '',
  name text not null default '',
  description text not null default '',
  billing_interval text not null default 'monthly',
  currency text not null default 'usd',
  price integer not null default 0,
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now(),
  constraint billing_plans_interval_check
    check (billing_interval in ('monthly', 'yearly'))
);

create unique index if not exists billing_plans_code_uidx
  on billing_plans(code) where code <> '';

create table if not exists billing_customers (
  id uuid primary key,
  organization_id text not null default '',
  provider text not null default '',
  provider_customer_id text not null default '',
  email text not null default '',
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now()
);

create index if not exists billing_customers_org_idx on billing_customers(organization_id);
create unique index if not exists billing_customers_provider_customer_uidx
  on billing_customers(provider_customer_id) where provider_customer_id <> '';

create table if not exists billing_subscriptions (
  id uuid primary key,
  organization_id text not null default '',
  customer_id text not null default '',
  provider_subscription_id text not null default '',
  status text not null default 'incomplete',
  plan_id text not null default '',
  trial_ends_at timestamptz,
  current_period_start timestamptz,
  current_period_end timestamptz,
  cancel_at_period_end boolean not null default false,
  canceled_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint billing_subscriptions_status_check
    check (status in ('incomplete', 'incomplete_expired', 'trialing', 'active',
                      'past_due', 'canceled', 'unpaid', 'paused'))
);

create index if not exists billing_subscriptions_org_idx
  on billing_subscriptions(organization_id);
create unique index if not exists billing_subscriptions_provider_uidx
  on billing_subscriptions(provider_subscription_id) where provider_subscription_id <> '';
create index if not exists billing_subscriptions_active_idx
  on billing_subscriptions(organization_id) where status = 'active';

create table if not exists billing_checkout_sessions (
  id uuid primary key,
  organization_id text not null default '',
  customer_id text not null default '',
  provider_checkout_id text not null default '',
  plan_id text not null default '',
  status text not null default 'open',
  url text not null default '',
  mode text not null default 'subscription',
  success_url text not null default '',
  cancel_url text not null default '',
  trial_days integer not null default 0,
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now(),
  completed_at timestamptz,
  constraint billing_checkouts_status_check
    check (status in ('open', 'complete', 'expired'))
);

create index if not exists billing_checkouts_org_idx
  on billing_checkout_sessions(organization_id);
create unique index if not exists billing_checkouts_provider_uidx
  on billing_checkout_sessions(provider_checkout_id) where provider_checkout_id <> '';

create table if not exists billing_invoices (
  id uuid primary key,
  organization_id text not null default '',
  customer_id text not null default '',
  subscription_id text not null default '',
  provider_invoice_id text not null default '',
  status text not null default 'draft',
  amount_due integer not null default 0,
  amount_paid integer not null default 0,
  currency text not null default 'usd',
  period_start timestamptz,
  period_end timestamptz,
  paid_at timestamptz,
  hosted_url text not null default '',
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now(),
  constraint billing_invoices_status_check
    check (status in ('draft', 'open', 'paid', 'uncollectible', 'void'))
);

create index if not exists billing_invoices_org_idx on billing_invoices(organization_id);
create unique index if not exists billing_invoices_provider_uidx
  on billing_invoices(provider_invoice_id) where provider_invoice_id <> '';

create table if not exists billing_events (
  id uuid primary key,
  event_type text not null default '',
  provider_event_id text not null default '',
  provider text not null default '',
  organization_id text not null default '',
  data jsonb not null default '{}',
  idempotency_key text not null default '',
  processed boolean not null default false,
  created_at timestamptz not null default now(),
  processed_at timestamptz
);

create unique index if not exists billing_events_provider_event_uidx
  on billing_events(provider_event_id) where provider_event_id <> '';
create unique index if not exists billing_events_idempotency_uidx
  on billing_events(idempotency_key) where idempotency_key <> '';