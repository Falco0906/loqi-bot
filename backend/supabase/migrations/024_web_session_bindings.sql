-- 024 Web-session → canonical identity binding (SaaS-1.6).
--
-- Consolidates the legacy web-session boundary with the canonical SaaS
-- identity/session authority. When the web-session bootstrap is invoked with a
-- valid canonical access token, the issued web-session token is durably bound
-- to the canonical user and its canonical session:
--
--   web_session_bindings - web token -> canonical user + canonical session
--
-- Resolution (main._resolve_session_context) uses this binding to make the
-- web-session bearer authoritative: the actor becomes the canonical user, and
-- the web-session is authorized only while the canonical session remains valid
-- (not revoked / not expired). Logout, password change, and password reset all
-- revoke the canonical session, which therefore invalidates the bound
-- web-session token — the web-session can no longer outlive the canonical
-- session it was created from.
--
-- Anonymous (pre-auth) web-sessions that were never bound keep their legacy
-- behavior; they do not represent an authenticated SaaS identity.
--
-- Additive and idempotent; safe to re-run; no destructive operations; does not
-- touch workflow_sessions or any table from migrations 003-023.

create table if not exists web_session_bindings (
  id uuid primary key,
  session_key text not null default '',
  canonical_user_id text not null default '',
  canonical_session_id text not null default '',
  created_at timestamptz not null default now()
);

create unique index if not exists web_session_bindings_session_key_uidx
  on web_session_bindings(session_key) where session_key <> '';
create index if not exists web_session_bindings_user_idx
  on web_session_bindings(canonical_user_id);