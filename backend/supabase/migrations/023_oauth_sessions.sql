-- 023 OAuth session state persistence (SaaS-1.5).
--
-- OAuth state is currently process-local in-memory (services/oauth_state and
-- the identity api's OAuthSession repo). Under a multi-instance / restarting
-- Railway deployment a callback can land on a different instance than the one
-- that issued the state, which would fail the flow (or worse, be rejected as
-- a lost token). This migration makes OAuth state durable:
--
--   oauth_sessions - single-use, expiring, server-issued OAuth state
--
-- Columns mirror the identity OAuthSession model
-- (services/identity/models/oauth_session.py):
--   state          - cryptographically random server-issued token (unique)
--   user_id        - the initiating identity when known at issuance
--   context        - provider flow context (e.g. legacy channel/transport id)
--   code_verifier  - PKCE verifier for the identity provider flow
--   used_at        - single-use consumption marker
--   expires_at     - short-lived TTL enforced at consumption
--
-- Additive and idempotent; safe to re-run; no destructive operations; does
-- not touch workflow_sessions or any table from migrations 003-022.

create table if not exists oauth_sessions (
  id uuid primary key,
  state text not null default '',
  provider_type text not null default '',
  code_verifier text not null default '',
  nonce text not null default '',
  redirect_uri text not null default '',
  user_id text not null default '',
  context text not null default '',
  expires_at timestamptz not null default now(),
  used_at timestamptz,
  created_at timestamptz not null default now()
);

create unique index if not exists oauth_sessions_state_uidx
  on oauth_sessions(state) where state <> '';
create index if not exists oauth_sessions_user_id_idx on oauth_sessions(user_id);
create index if not exists oauth_sessions_expiry_idx on oauth_sessions(expires_at);