-- Durable identity for one accepted campaign-send invocation.
-- The application authorizes workspace/campaign scope before creating a row.

create table if not exists campaign_launches (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  campaign_id uuid not null references campaigns(id) on delete cascade,
  actor_user_id uuid references identity_users(id) on delete set null,
  started_at timestamptz not null default now()
);

create index if not exists campaign_launches_workspace_campaign_started_idx
  on campaign_launches(workspace_id, campaign_id, started_at desc);
