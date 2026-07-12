-- Job Engine: persistent async workflow execution

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
