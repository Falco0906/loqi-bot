-- 015 Discovery Metadata — additive future-proofing columns for discoveries.
-- Apply AFTER 014_discoveries.sql. 014 is immutable once applied; any further
-- discovery-schema evolution must come as new additive migrations like this.
--
-- These columns support product features that are NOT built yet:
--   * title            — user-editable display name (defaults to the query)
--   * description      — optional user notes
--   * favorite         — pin important discoveries
--   * archived_at      — soft archive instead of delete
--   * last_viewed_at   — enables "Recently Viewed"
--   * last_refreshed_at— supports "Refresh Discovery" / scheduled rediscovery
--   * metadata         — reserved JSON for future UI / experimental attributes
--
-- Explicitly NOT added (belong to future migrations): tags, folders, sharing,
-- permissions, comments, collaborators.
--
-- Idempotency contract: only additive `alter table ... add column if not
-- exists` statements, plus backfills inside a guarded DO block. The file is
-- RESUMABLE and safe to re-run on any database, whether 014 applied the base
-- columns or not.

alter table discoveries add column if not exists title text;
alter table discoveries add column if not exists description text;
alter table discoveries add column if not exists favorite boolean not null default false;
alter table discoveries add column if not exists archived_at timestamptz;
alter table discoveries add column if not exists last_viewed_at timestamptz;
alter table discoveries add column if not exists last_refreshed_at timestamptz;
alter table discoveries add column if not exists metadata jsonb not null default '{}'::jsonb;

-- Backfill the creation defaults (title = query, view/refresh = created_at)
-- for rows that predate these columns. Guarded: no-op on databases where the
-- table or columns do not exist.
do $$
begin
  if to_regclass('public.discoveries') is not null then
    update discoveries set title = query where title is null;
    update discoveries set last_viewed_at = created_at where last_viewed_at is null;
    update discoveries set last_refreshed_at = created_at where last_refreshed_at is null;
  end if;
end $$;
