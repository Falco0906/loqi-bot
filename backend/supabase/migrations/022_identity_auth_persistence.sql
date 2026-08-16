-- 022 Identity email/password/registration persistence + refresh-family
-- integrity (SaaS-1.2).
--
-- 021 materialized the session/token tables. This migration completes the
-- identity lifecycle's durable state so authentication survives restarts and
-- multi-instance operation:
--
--   email_identities       - verified email <-> user mapping (login + reset)
--   password_credentials   - Argon2id password hash per user
--   registration_sessions  - signup (pending -> verified -> completed)
--
-- Plus a DB-level refresh-token integrity guard:
--
--   refresh_tokens_family_active_uidx - at most one ACTIVE token per family.
--   Rotation revokes the presented token before minting its successor, so a
--   legitimate rotation never violates this; a concurrent rotation of the
--   same token (replay race) is rejected by the unique index and is handled
--   as theft (family + session revocation) by TokenService.
--
-- Column names/types/nullability mirror the identity dataclass models
-- (services/identity/models/__init__.py) and the repository serializers in
-- services/persistence/base_repository.py. `purpose`/`status` are text with
-- CHECK constraints matching their enums. Additive and idempotent; safe to
-- re-run; no destructive operations; does not touch workflow_sessions or any
-- table from migrations 003-021.

create table if not exists email_identities (
  id uuid primary key,
  user_id text not null default '',
  email text not null default '',
  is_verified boolean not null default false,
  is_primary boolean not null default false,
  verified_at timestamptz,
  created_at timestamptz not null default now()
);

create unique index if not exists email_identities_email_uidx
  on email_identities(email) where email <> '';
create index if not exists email_identities_user_id_idx on email_identities(user_id);
create index if not exists email_identities_primary_idx
  on email_identities(user_id, is_primary) where is_primary;

create table if not exists password_credentials (
  id uuid primary key,
  user_id text not null default '',
  password_hash text not null default '',
  created_at timestamptz not null default now(),
  last_changed_at timestamptz not null default now()
);

create unique index if not exists password_credentials_user_id_uidx
  on password_credentials(user_id) where user_id <> '';

create table if not exists registration_sessions (
  id uuid primary key,
  email text not null default '',
  status text not null default 'pending',
  verification_token_id text not null default '',
  email_identity_id text not null default '',
  user_id text not null default '',
  organization_id text not null default '',
  expires_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint registration_sessions_status_check
    check (status in ('pending', 'verified', 'completed', 'expired'))
);

create index if not exists registration_sessions_email_status_idx
  on registration_sessions(email, status);
create index if not exists registration_sessions_status_expiry_idx
  on registration_sessions(status, expires_at);

create unique index if not exists refresh_tokens_family_active_uidx
  on refresh_tokens(family) where revoked_at is null;