-- General durable-job contract. Search jobs retain their discovery_id link;
-- other job types use explicit workspace/campaign linkage and bounded JSON.
alter table jobs add column if not exists workspace_id text;
alter table jobs add column if not exists campaign_id uuid references campaigns(id) on delete set null;
alter table jobs add column if not exists payload jsonb not null default '{}'::jsonb;
alter table jobs add column if not exists result jsonb not null default '{}'::jsonb;

create index if not exists jobs_workspace_status_idx on jobs(workspace_id, status, created_at desc);
create index if not exists jobs_campaign_idx on jobs(campaign_id) where campaign_id is not null;
