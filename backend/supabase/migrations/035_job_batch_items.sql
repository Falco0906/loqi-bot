-- Durable per-lead execution state for resumable draft-generation jobs.
create table if not exists job_batch_items (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null references jobs(id) on delete cascade,
  workspace_id text not null,
  campaign_id uuid references campaigns(id) on delete set null,
  position integer not null,
  lead_snapshot jsonb not null default '{}'::jsonb,
  idempotency_key text not null,
  status text not null default 'pending',
  attempt_count integer not null default 0,
  last_error text not null default '',
  draft_id uuid references drafts(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(job_id, idempotency_key),
  unique(job_id, position)
);
create index if not exists job_batch_items_resume_idx on job_batch_items(job_id, workspace_id, status, position);
