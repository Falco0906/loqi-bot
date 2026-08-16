-- 021 Identity session/token persistence schema (PR10).
--
-- 004_identity_platform.sql materialized `identity_users`, but no migration
-- ever created the remaining documented identity persistence tables
-- (docs/ARCHITECTURE.md — 001_identity_platform.sql). The Supabase-backed
-- identity repositories consequently resolve them at runtime and authentication
-- failed with PGRST205 ("Could not find the table 'public.sessions'").
--
-- This migration additively creates the four missing tables exactly as the
-- persistence repositories expect them:
--   sessions                — SupabaseSessionRepository      (_table_name 'sessions')
--   refresh_tokens          — SupabaseRefreshTokenRepository (_table_name 'refresh_tokens')
--   verification_tokens     — SupabaseVerificationTokenRepository (_table_name 'verification_tokens')
--   password_reset_requests — SupabasePasswordResetRepository (_table_name 'password_reset_requests')
--
-- Column names, types, nullability and defaults mirror the identity dataclass
-- models in services/identity/models/__init__.py; the repositories read/write
-- these snake_case columns directly (services/persistence/base_repository.py
-- serializes/deserializes by dataclass field name).
--
-- Design decisions:
--   * PKs are uuid, matching identity_users.id (004). The model ids are
--     str(uuid4()); PostgREST casts them into uuid transparently.
--   * Referencing columns (user_id, organization_id, session_id, target,
--     family, token_hash) are text NOT NULL DEFAULT '', matching the loose
--     str-typed model fields and 004's "no hard FK" convention. No FK
--     constraints are added: hard FKs would fail base_repository.delete() on
--     referenced rows and would reject legacy/bridge ids during the transition.
--   * purpose CHECK mirrors the VerificationTokenPurpose enum values
--     (repo convention: 020_connected_accounts_auth_failed.sql).
--   * Every repository query has a supporting index (incl. partial indexes for
--     active-row lookups); token_hash unique indexes are partial so untouched
--     default '' rows never collide.
--
-- Idempotent and safe to re-run. Additive, no destructive operations, no
-- changes to workflow_sessions (a separate conversation-domain table).
-- Apply via the Supabase SQL Editor (or psql), consistent with the numbered
-- migration convention used for 004-020.

create table if not exists sessions (
  id uuid primary key,
  user_id text not null default '',
  organization_id text not null default '',
  provider_type text not null default '',
  device_info text not null default '',
  ip_address text not null default '',
  user_agent text not null default '',
  last_activity_at timestamptz not null default now(),
  expires_at timestamptz not null default now(),
  revoked_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists sessions_user_created_idx on sessions(user_id, created_at desc);
create index if not exists sessions_user_active_idx on sessions(user_id, expires_at)
  where revoked_at is null;
create index if not exists sessions_org_active_idx on sessions(organization_id)
  where revoked_at is null;

create table if not exists refresh_tokens (
  id uuid primary key,
  session_id text not null default '',
  token_hash text not null default '',
  family text not null default '',
  sequence integer not null default 1,
  expires_at timestamptz not null default now(),
  revoked_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists refresh_tokens_session_active_idx on refresh_tokens(session_id, expires_at)
  where revoked_at is null;
create index if not exists refresh_tokens_family_seq_idx on refresh_tokens(family, sequence desc);
create unique index if not exists refresh_tokens_token_hash_uidx on refresh_tokens(token_hash)
  where token_hash <> '';

create table if not exists verification_tokens (
  id uuid primary key,
  purpose text not null default 'verify_email',
  target text not null default '',
  token_hash text not null default '',
  expires_at timestamptz not null default now(),
  used_at timestamptz,
  created_at timestamptz not null default now(),
  constraint verification_tokens_purpose_check
    check (purpose in ('verify_email', 'accept_invite', 'change_email'))
);

create index if not exists verification_tokens_target_purpose_active_idx
  on verification_tokens(target, purpose, expires_at) where used_at is null;
create index if not exists verification_tokens_target_created_idx
  on verification_tokens(target, created_at desc);
create unique index if not exists verification_tokens_token_hash_uidx
  on verification_tokens(token_hash) where token_hash <> '';

create table if not exists password_reset_requests (
  id uuid primary key,
  user_id text not null default '',
  token_hash text not null default '',
  expires_at timestamptz not null default now(),
  used_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists password_reset_requests_user_active_idx
  on password_reset_requests(user_id, expires_at) where used_at is null;
create unique index if not exists password_reset_requests_token_hash_uidx
  on password_reset_requests(token_hash) where token_hash <> '';