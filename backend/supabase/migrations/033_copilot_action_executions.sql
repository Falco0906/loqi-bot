-- Durable, tenant-scoped idempotency and audit records for Copilot mutations.
-- Domain rows remain canonical; this table records whether Copilot may safely
-- replay a prior result instead of repeating a side effect.

create table if not exists copilot_action_executions (
  id uuid primary key,
  user_id text not null,
  workspace_id text not null,
  idempotency_key text not null,
  request_fingerprint text not null,
  tool_name text not null,
  status text not null check (status in ('running', 'accepted', 'completed', 'failed', 'verification_failed', 'declined', 'cancelled')),
  result jsonb not null default '{}'::jsonb,
  error_code text,
  audit jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  completed_at timestamptz,
  unique (user_id, workspace_id, idempotency_key)
);

create index if not exists copilot_action_executions_workspace_created_idx
  on copilot_action_executions (workspace_id, created_at desc);
create index if not exists copilot_action_executions_user_created_idx
  on copilot_action_executions (user_id, created_at desc);
