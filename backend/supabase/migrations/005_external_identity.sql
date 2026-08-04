-- 005 Launch Foundation — Identity: one canonical user, external facades, connected accounts.
-- Apply AFTER 004_identity_platform.sql.
--
-- Review additions:
--   last_verified_at  — when the identity was last confirmed (provider re-auth /
--                       email verification); powers reconcile jobs.
--   deleted_at        — soft delete so disconnecting an identity is reversible
--                       and re-linking uses the same uniqueness key.
--   connected_accounts.last_synced_at — token refresh / provider sync cadence.
--   connected_accounts.version        — optimistic concurrency against token
--                       refresh and webhook races.

-- ─── external_identities ────────────────────────────────────────────────
-- Every authenticated user resolves to ONE identity_users row. Each provider
-- facade (google, github, telegram, email, magic_link) is an external identity
-- that links back to that single row. UNIQUE(provider, provider_subject) is the
-- dedup key that makes "no duplicate user rows" enforceable.

create table if not exists external_identities (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references identity_users(id) on delete cascade,
  provider text not null,
  provider_subject text not null,
  email text not null default '',
  username text not null default '',
  metadata jsonb not null default '{}',
  last_verified_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz
);

alter table external_identities add column if not exists last_verified_at timestamptz;
alter table external_identities add column if not exists deleted_at timestamptz;

create unique index if not exists external_identities_provider_subject_uidx
  on external_identities(provider, provider_subject) where deleted_at is null;
create index if not exists external_identities_user_id_idx on external_identities(user_id);
create index if not exists external_identities_email_idx on external_identities(email)
  where email <> '';
create index if not exists external_identities_deleted_idx on external_identities(deleted_at)
  where deleted_at is not null;

-- ─── connected_accounts ──────────────────────────────────────────────────
-- Every external account a user connects (Google, Microsoft, Slack, HubSpot,
-- Apollo, PDL, Hunter, Stripe, SMTP). OAuth tokens NEVER live anywhere else.

create table if not exists connected_accounts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references identity_users(id) on delete cascade,
  provider text not null,
  account_id text not null default '',
  display_name text not null default '',
  email text not null default '',
  access_token text not null default '',
  refresh_token text not null default '',
  token_type text not null default 'bearer',
  token_expires_at timestamptz,
  status text not null default 'active',
  scope jsonb not null default '[]',
  metadata jsonb not null default '{}',
  last_synced_at timestamptz,
  version integer not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz,
  constraint connected_accounts_status_check
    check (status in ('active', 'pending', 'expired', 'revoked', 'error'))
);

alter table connected_accounts add column if not exists last_synced_at timestamptz;
alter table connected_accounts add column if not exists version integer not null default 1;
alter table connected_accounts add column if not exists deleted_at timestamptz;

create unique index if not exists connected_accounts_user_provider_uidx
  on connected_accounts(user_id, provider, account_id) where deleted_at is null;
create index if not exists connected_accounts_provider_idx on connected_accounts(provider);
create index if not exists connected_accounts_email_idx on connected_accounts(email)
  where email <> '';
create index if not exists connected_accounts_deleted_idx on connected_accounts(deleted_at)
  where deleted_at is not null;
create index if not exists connected_accounts_sync_idx on connected_accounts(provider, last_synced_at)
  where last_synced_at is not null;