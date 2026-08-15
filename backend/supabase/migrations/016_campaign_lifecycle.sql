-- 016 Campaign lifecycle statuses.
--
-- Campaign status is the LIFECYCLE, not the workflow UI step. Workflow
-- progression (strategy -> leads -> drafts -> review -> sending) is derived
-- from persisted state (strategy row, lead count, draft review state) and
-- surfaced as `current_step` by the API; it is never encoded in status.
--
-- This migration replaces the status CHECK with the lifecycle vocabulary and
-- adds soft-deletion support (status='deleted' + deleted_at).

-- Map any legacy rows that used draft/running into the lifecycle vocabulary
-- before the constraint is replaced.
update campaigns set status = 'planning'
  where status in ('draft', 'running');

alter table campaigns drop constraint if exists campaigns_status_check;

alter table campaigns
  add constraint campaigns_status_check
  check (status in ('planning', 'active', 'paused', 'completed', 'archived', 'cancelled', 'failed', 'deleted'));

alter table campaigns add column if not exists deleted_at timestamptz;