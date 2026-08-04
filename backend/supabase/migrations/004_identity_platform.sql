-- Identity Platform: canonical durable home for the identity User aggregate.
--
-- The legacy `users` table doubles as the OAuth bridge (telegram_id, google_*)
-- and is referenced by jobs/workflow_sessions. It is intentionally NOT the
-- identity aggregate store and is left untouched here. This table holds the
-- full Identity Platform User model (display_name, locale, onboarding state,
-- soft-delete markers) and is written through UserService.save_user().
--
-- Review additions (production hardening):
--   email               — primary contact email for billing/support/analytics
--                         without joining email_identities on every query.
--   metadata jsonb      — signup_source, region, marketing flags, feature
--                         gating without schema migrations.
--   last_login_at       — security + product analytics (churn, dormant users).
--   version             — optimistic concurrency for profile edits.

create table if not exists identity_users (
  id uuid primary key,
  display_name text not null default '',
  avatar_url text not null default '',
  email text not null default '',
  locale text not null default 'en',
  onboarding_data jsonb,
  onboarding_completed_at timestamptz,
  metadata jsonb not null default '{}',
  last_login_at timestamptz,
  version integer not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz
);

-- Idempotent for environments where a variant of this table already exists.
alter table identity_users add column if not exists email text not null default '';
alter table identity_users add column if not exists metadata jsonb not null default '{}';
alter table identity_users add column if not exists last_login_at timestamptz;
alter table identity_users add column if not exists version integer not null default 1;

create unique index if not exists identity_users_email_uidx
  on identity_users(lower(email)) where email <> '' and deleted_at is null;
create index if not exists identity_users_created_at_idx on identity_users(created_at desc);
create index if not exists identity_users_completed_idx on identity_users(onboarding_completed_at)
  where onboarding_completed_at is not null;
create index if not exists identity_users_deleted_idx on identity_users(deleted_at)
  where deleted_at is not null;
