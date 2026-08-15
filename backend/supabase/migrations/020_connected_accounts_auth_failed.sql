-- PR10.8.2 — connected_accounts reauth status + one-account-per-user integrity
--
-- 1. Allow the persisted status 'auth_failed' (reauth-required, PR10.8.1) by
--    recreating the status CHECK constraint with every existing valid status
--    preserved plus 'auth_failed' added explicitly. The constraint is NOT
--    removed or weakened into an unrestricted string.
--
-- 2. Deterministically reconcile existing duplicate active rows: exactly one
--    canonical row per (user_id, provider). For each duplicate group the
--    newest row WITH a real refresh token wins (then newest created_at);
--    obsolete duplicates are soft-deleted (deleted_at) — data is preserved,
--    never hard-deleted.
--
-- 3. Enforce one active connected account per (user_id, provider) with a
--    partial unique index. This is the strongest stable identity the app
--    currently stores for a connected Google account (the Gmail OAuth flow
--    resolves a single account per user).
--
-- Run this in the Supabase SQL Editor (or psql) once per environment.
-- The statement list is idempotent and safe to re-run.

alter table connected_accounts drop constraint if exists connected_accounts_status_check;

alter table connected_accounts
  add constraint connected_accounts_status_check
  check (status in ('active', 'pending', 'expired', 'revoked', 'error', 'auth_failed'));

with ranked as (
  select id,
         row_number() over (
           partition by user_id, provider
           order by (refresh_token <> '') desc, created_at desc, id desc
         ) as rn
  from connected_accounts
  where deleted_at is null
)
update connected_accounts c
set deleted_at = now(),
    updated_at = now()
from ranked r
where c.id = r.id and r.rn > 1;

create unique index if not exists connected_accounts_user_provider_active_uidx
  on connected_accounts(user_id, provider) where deleted_at is null;
