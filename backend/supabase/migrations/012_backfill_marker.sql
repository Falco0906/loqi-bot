-- 012 Backfill marker for startup one-shot migration.
-- Applies AFTER 006_workspaces.sql.
--
-- The startup backfill (services/persistence/launch/backfill.py) replays each
-- channel='workspace' workflow session's event log into the canonical launch
-- tables exactly once. The backfilled_at marker records that a session has
-- been processed, so subsequent startups only touch sessions created after
-- the last run instead of scanning every historical session.

alter table workflow_sessions add column if not exists backfilled_at timestamptz;

create index if not exists workflow_sessions_backfill_idx
  on workflow_sessions(channel, backfilled_at)
  where channel = 'workspace' and backfilled_at is null;
