import os

MIGRATION_SQL = """
create table if not exists jobs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  type text not null,
  status text not null default 'queued',
  stage text,
  progress integer not null default 0,
  query text not null default '',
  error_message text,
  result_ready boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  completed_at timestamptz
);

create index if not exists jobs_user_id_idx on jobs(user_id, created_at desc);
create index if not exists jobs_status_idx on jobs(status);

create table if not exists search_results (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null references jobs(id) on delete cascade,
  rank integer not null default 0,
  lead_data jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists search_results_job_id_idx on search_results(job_id, rank);
"""

ONBOARDING_SQL = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'onboarding_data'
    ) THEN
        ALTER TABLE users ADD COLUMN onboarding_data TEXT;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'onboarding_completed_at'
    ) THEN
        ALTER TABLE users ADD COLUMN onboarding_completed_at TIMESTAMPTZ;
    END IF;
END $$;
"""

BACKFILL_MARKER_SQL = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'workflow_sessions' AND column_name = 'backfilled_at'
    ) THEN
        ALTER TABLE workflow_sessions ADD COLUMN backfilled_at TIMESTAMPTZ;
    END IF;
END $$;
"""

# Hot-path lookup indexes. These serve the request that resolves a web token to
# its workspace owner (get_web_session / list_workflow_sessions) and the
# conversation reads behind it. Every branch is guarded so it is safe on both
# the legacy an fresh ``users``/``workflow_sessions`` schemas.
# Discovery first-class entities (014). Runs additively on databases that
# already have the canonical domain schema (006_workspaces + 007_domain);
# the campaigns.discovery_id link is self-guarding. Mirrors
# supabase/migrations/014_discoveries.sql — keep the two in sync.
DISCOVERIES_SQL = """
create table if not exists discoveries (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  query text not null default '',
  status text not null default 'queued',
  summary jsonb not null default '{}',
  filters jsonb not null default '[]',
  provider_provenance jsonb not null default '{}',
  created_by text not null default '',
  updated_by text not null default '',
  version integer not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  completed_at timestamptz,
  deleted_at timestamptz,
  constraint discoveries_status_check
    check (status in ('queued', 'searching', 'completed', 'failed', 'cancelled'))
);

alter table discoveries add column if not exists summary jsonb not null default '{}';
alter table discoveries add column if not exists filters jsonb not null default '[]';
alter table discoveries add column if not exists provider_provenance jsonb not null default '{}';
alter table discoveries add column if not exists created_by text not null default '';
alter table discoveries add column if not exists updated_by text not null default '';
alter table discoveries add column if not exists version integer not null default 1;
alter table discoveries add column if not exists updated_at timestamptz;
alter table discoveries add column if not exists completed_at timestamptz;
alter table discoveries add column if not exists deleted_at timestamptz;

do $$
begin
  update discoveries set updated_at = created_at where updated_at is null;
  alter table discoveries alter column updated_at set default now();
  alter table discoveries alter column updated_at set not null;
end $$;

create index if not exists discoveries_workspace_idx on discoveries(workspace_id, created_at desc);
create index if not exists discoveries_status_idx on discoveries(status);
create index if not exists discoveries_deleted_idx on discoveries(deleted_at) where deleted_at is not null;

-- Ownership link, persisted on the JOB side (Discovery → many Jobs).
do $$
begin
  if to_regclass('public.jobs') is not null then
    alter table jobs add column if not exists discovery_id uuid
      references discoveries(id) on delete set null;
    create index if not exists jobs_discovery_idx
      on jobs(discovery_id) where discovery_id is not null;
  end if;
end $$;

create table if not exists discovery_companies (
  id uuid primary key default gen_random_uuid(),
  discovery_id uuid not null references discoveries(id) on delete cascade,
  workspace_company_id uuid not null references workspace_companies(id) on delete cascade,
  company_id uuid references companies(id) on delete cascade,
  rank integer not null default 0,
  match_score numeric not null default 0,
  source_provider text not null default '',
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now(),
  deleted_at timestamptz
);

alter table discovery_companies add column if not exists metadata jsonb not null default '{}';
alter table discovery_companies add column if not exists deleted_at timestamptz;

create index if not exists discovery_companies_discovery_idx
  on discovery_companies(discovery_id, rank);
create index if not exists discovery_companies_company_idx
  on discovery_companies(company_id) where company_id is not null;
create index if not exists discovery_companies_deleted_idx
  on discovery_companies(deleted_at) where deleted_at is not null;

create unique index if not exists discovery_companies_discovery_company_uidx
  on discovery_companies(discovery_id, company_id) where company_id is not null and deleted_at is null;

create table if not exists discovery_leads (
  id uuid primary key default gen_random_uuid(),
  discovery_id uuid not null references discoveries(id) on delete cascade,
  lead_id uuid not null references workspace_leads(id) on delete cascade,
  rank integer not null default 0,
  match_score numeric not null default 0,
  status text not null default 'found',
  source_provider text not null default '',
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now(),
  deleted_at timestamptz,
  constraint discovery_leads_status_check
    check (status in ('found', 'reviewed', 'approved', 'rejected', 'added'))
);

alter table discovery_leads add column if not exists match_score numeric not null default 0;
alter table discovery_leads add column if not exists status text not null default 'found';
alter table discovery_leads add column if not exists source_provider text not null default '';
alter table discovery_leads add column if not exists metadata jsonb not null default '{}';
alter table discovery_leads add column if not exists deleted_at timestamptz;

create index if not exists discovery_leads_discovery_idx on discovery_leads(discovery_id, rank);
create index if not exists discovery_leads_lead_idx on discovery_leads(lead_id);
create index if not exists discovery_leads_deleted_idx on discovery_leads(deleted_at) where deleted_at is not null;

create unique index if not exists discovery_leads_discovery_lead_uidx
  on discovery_leads(discovery_id, lead_id) where deleted_at is null;

do $$
begin
  if to_regclass('public.campaigns') is not null then
    alter table campaigns add column if not exists discovery_id uuid
      references discoveries(id) on delete set null;
    create index if not exists campaigns_discovery_idx
      on campaigns(discovery_id) where discovery_id is not null;
  end if;
end $$;
"""

# Additive future-proofing columns for discoveries (015). 014 is immutable
# once applied, so this runs additively on top of it. Only idempotent
# `alter table ... add column if not exists` statements plus a guarded
# backfill DO block; safe on any database. Mirrors
# supabase/migrations/015_discovery_metadata.sql — keep the two in sync.
DISCOVERY_METADATA_SQL = """
alter table discoveries add column if not exists title text;
alter table discoveries add column if not exists description text;
alter table discoveries add column if not exists favorite boolean not null default false;
alter table discoveries add column if not exists archived_at timestamptz;
alter table discoveries add column if not exists last_viewed_at timestamptz;
alter table discoveries add column if not exists last_refreshed_at timestamptz;
alter table discoveries add column if not exists metadata jsonb not null default '{}'::jsonb;

do $$
begin
  if to_regclass('public.discoveries') is not null then
    update discoveries set title = query where title is null;
    update discoveries set last_viewed_at = created_at where last_viewed_at is null;
    update discoveries set last_refreshed_at = created_at where last_refreshed_at is null;
  end if;
end $$;
"""

LOOKUP_INDEXES_SQL = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'telegram_id'
    ) THEN
        CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users (telegram_id);
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'workflow_sessions' AND column_name = 'channel'
    ) THEN
        CREATE INDEX IF NOT EXISTS idx_workflow_sessions_channel_key
            ON workflow_sessions (channel, session_key);
        CREATE INDEX IF NOT EXISTS idx_workflow_sessions_user_channel
            ON workflow_sessions (user_id, channel, session_key);
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'conversations' AND column_name = 'user_id'
    ) THEN
        CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations (user_id);
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'connected_accounts' AND column_name = 'user_id'
    ) THEN
        CREATE INDEX IF NOT EXISTS idx_connected_accounts_user_id ON connected_accounts (user_id);
    END IF;
END $$;
"""


# PR10.8.2: connected_accounts auth_failed status + one-account-per-user
# uniqueness. Mirrors supabase/migrations/020_connected_accounts_auth_failed.sql
# — keep the two in sync. Idempotent and safe to re-run.
CONNECTED_ACCOUNTS_AUTH_FAILED_SQL = """
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
"""


def _log(msg: str) -> None:
    print(f"[migration] {msg}")


def _check_table_exists() -> bool:
    """Check if jobs table exists via Supabase REST API."""
    from services.supabase import get_supabase_client
    client = get_supabase_client()
    if not client:
        return False
    try:
        client.table("jobs").select("id").limit(1).execute()
        return True
    except Exception:
        return False


def apply_migrations() -> bool:
    jobs_exist = _check_table_exists()
    database_url = os.getenv("DATABASE_URL")
    if jobs_exist and not database_url:
        _log("Jobs table already exists — skipping migration")
        return True

    if jobs_exist and database_url:
        try:
            import psycopg2
            conn = psycopg2.connect(database_url, connect_timeout=10)
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute(ONBOARDING_SQL)
            cur.execute(BACKFILL_MARKER_SQL)
            cur.execute(LOOKUP_INDEXES_SQL)
            cur.execute(DISCOVERIES_SQL)
            cur.execute(DISCOVERY_METADATA_SQL)
            cur.execute(CONNECTED_ACCOUNTS_AUTH_FAILED_SQL)
            cur.close()
            conn.close()
            _log("Additive onboarding migration checked successfully")
            return True
        except Exception as e:
            _log(f"Additive onboarding migration failed: {e}")
            return False

    _log("Jobs table not found — attempting migration")

    if database_url:
        try:
            import psycopg2
            conn = psycopg2.connect(database_url, connect_timeout=10)
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute(MIGRATION_SQL)
            cur.execute(ONBOARDING_SQL)
            cur.execute(BACKFILL_MARKER_SQL)
            cur.execute(LOOKUP_INDEXES_SQL)
            cur.execute(DISCOVERIES_SQL)
            cur.execute(DISCOVERY_METADATA_SQL)
            cur.execute(CONNECTED_ACCOUNTS_AUTH_FAILED_SQL)
            cur.close()
            conn.close()
            _log("Migration applied successfully via DATABASE_URL")
            return True
        except Exception as e:
            _log(f"Migration via DATABASE_URL failed: {e}")

    _log(
        "Cannot apply migration. Set DATABASE_URL in .env:\n"
        "  DATABASE_URL=postgresql://postgres:PASSWORD@db.llckvmpwmovhchfpjnsa.supabase.co:5432/postgres\n"
        "Get the password from Supabase Dashboard → Project Settings → Database.\n"
        "Alternatively, run the SQL manually in the Supabase Dashboard SQL Editor:\n"
        "  Open https://supabase.com/dashboard/project/llckvmpwmovhchfpjnsa/sql/new\n"
        "  Paste and run backend/supabase/migrations/003_job_engine.sql\n"
        "  Then run 006_workspaces.sql, 007_domain.sql, 014_discoveries.sql"
    )
    return False
