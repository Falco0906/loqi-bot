-- Safe, idempotent execution failures that have no canonical outbound-history row.
-- Application services supply already-authorized workspace/campaign scope.

create table if not exists campaign_launch_failures (
  id uuid primary key default gen_random_uuid(),
  campaign_launch_id uuid not null references campaign_launches(id) on delete cascade,
  workspace_id uuid not null references workspaces(id) on delete cascade,
  campaign_id uuid not null references campaigns(id) on delete cascade,
  draft_id uuid not null references drafts(id) on delete cascade,
  occurred_at timestamptz not null default now(),
  constraint campaign_launch_failures_launch_draft_uidx unique (campaign_launch_id, draft_id)
);

create index if not exists campaign_launch_failures_workspace_campaign_occurred_idx
  on campaign_launch_failures(workspace_id, campaign_id, occurred_at asc);

create or replace function record_campaign_launch_failure(
  p_campaign_launch_id uuid,
  p_workspace_id uuid,
  p_campaign_id uuid,
  p_draft_id uuid,
  p_occurred_at timestamptz default now()
)
returns table(failure_id uuid, occurred_at timestamptz, was_created boolean)
language plpgsql
as $$
declare
  v_existing campaign_launch_failures%rowtype;
  v_inserted campaign_launch_failures%rowtype;
begin
  perform 1
  from campaign_launches as cl
  join drafts as d on d.id = p_draft_id
  where cl.id = p_campaign_launch_id
    and cl.workspace_id = p_workspace_id
    and cl.campaign_id = p_campaign_id
    and d.workspace_id = cl.workspace_id
    and d.campaign_id = cl.campaign_id;

  if not found then
    raise exception 'Campaign launch, draft, campaign, and workspace scope must match';
  end if;

  select clf.* into v_existing
  from campaign_launch_failures as clf
  where clf.campaign_launch_id = p_campaign_launch_id
    and clf.draft_id = p_draft_id;

  if found then
    return query select v_existing.id, v_existing.occurred_at, false;
    return;
  end if;

  insert into campaign_launch_failures (
    campaign_launch_id, workspace_id, campaign_id, draft_id, occurred_at
  )
  select cl.id, cl.workspace_id, cl.campaign_id, d.id, coalesce(p_occurred_at, now())
  from campaign_launches as cl
  join drafts as d on d.id = p_draft_id
  where cl.id = p_campaign_launch_id
    and cl.workspace_id = p_workspace_id
    and cl.campaign_id = p_campaign_id
    and d.workspace_id = cl.workspace_id
    and d.campaign_id = cl.campaign_id
  on conflict (campaign_launch_id, draft_id) do nothing
  returning * into v_inserted;

  if found then
    return query select v_inserted.id, v_inserted.occurred_at, true;
    return;
  end if;

  select clf.* into v_existing
  from campaign_launch_failures as clf
  where clf.campaign_launch_id = p_campaign_launch_id
    and clf.draft_id = p_draft_id;

  if found then
    return query select v_existing.id, v_existing.occurred_at, false;
    return;
  end if;

  raise exception 'Campaign launch failure was not confirmed';
end;
$$;
