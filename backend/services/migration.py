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
    if _check_table_exists():
        _log("Jobs table already exists — skipping migration")
        return True

    _log("Jobs table not found — attempting migration")

    database_url = os.getenv("DATABASE_URL")
    if database_url:
        try:
            import psycopg2
            conn = psycopg2.connect(database_url, connect_timeout=10)
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute(MIGRATION_SQL)
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
        "  Paste and run backend/supabase/migrations/003_job_engine.sql"
    )
    return False
