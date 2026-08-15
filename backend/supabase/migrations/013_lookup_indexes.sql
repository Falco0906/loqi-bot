-- 013 Hot-path lookup indexes for web-session → workspace-owner resolution.
--
-- Mission Control and Briefing resolve a web session token to its workspace
-- owner via the legacy `users` bridge (telegram_id) and the durable
-- workflow_sessions mapping, then read the workspace owner's conversations
-- and connected accounts. None of those columns were indexed, so every
-- request paid a sequential scan per lookup (~300-800ms × N lookups, and a
-- 17s cold-start scan on `users`).
--
-- All guarded / idempotent: safe on both the legacy users schema and fresh
-- installs. Apply via Supabase SQL Editor (or the startup migration in
-- services/migration.py when DATABASE_URL is set).

do $$
begin
    if exists (
        select 1 from information_schema.columns
        where table_name = 'users' and column_name = 'telegram_id'
    ) then
        create index if not exists idx_users_telegram_id on users (telegram_id);
    end if;
    if exists (
        select 1 from information_schema.columns
        where table_name = 'workflow_sessions' and column_name = 'channel'
    ) then
        create index if not exists idx_workflow_sessions_channel_key
            on workflow_sessions (channel, session_key);
        create index if not exists idx_workflow_sessions_user_channel
            on workflow_sessions (user_id, channel, session_key);
    end if;
    if exists (
        select 1 from information_schema.columns
        where table_name = 'conversations' and column_name = 'user_id'
    ) then
        create index if not exists idx_conversations_user_id on conversations (user_id);
    end if;
    if exists (
        select 1 from information_schema.columns
        where table_name = 'connected_accounts' and column_name = 'user_id'
    ) then
        create index if not exists idx_connected_accounts_user_id on connected_accounts (user_id);
    end if;
end $$;