-- Atomic revision allocation for the live workspace-scoped campaign update
-- path. This does not replace generic CampaignRepository.save() callers.
create or replace function update_workspace_campaign_with_revision(
  p_campaign_id uuid,
  p_workspace_id uuid,
  p_name text,
  p_name_provided boolean,
  p_objective text,
  p_objective_provided boolean,
  p_status text,
  p_status_provided boolean,
  p_touch boolean default false
)
returns table(
  id uuid,
  workspace_id uuid,
  organization_id text,
  name text,
  objective text,
  status text,
  search_query text,
  discovery_id uuid,
  settings jsonb,
  created_by text,
  updated_by text,
  metadata jsonb,
  version integer,
  created_at timestamptz,
  updated_at timestamptz,
  archived_at timestamptz,
  deleted_at timestamptz,
  was_updated boolean
)
language plpgsql
as $$
declare
  v_current campaigns%rowtype;
  v_updated campaigns%rowtype;
  v_name text;
  v_objective text;
  v_status text;
  v_changed boolean;
begin
  if p_campaign_id is null or p_workspace_id is null then
    raise exception 'campaign_id and workspace_id are required';
  end if;

  select c.* into v_current
  from campaigns as c
  where c.id = p_campaign_id
    and c.workspace_id = p_workspace_id
  for update;

  if not found then
    raise exception 'campaign not found in workspace';
  end if;

  -- Keep the existing Python persistence behavior for blank fields: an
  -- explicitly supplied empty name/objective becomes NULL and the table's
  -- existing constraints decide whether that mutation is valid.
  v_name := case when p_name_provided then nullif(p_name, '') else v_current.name end;
  v_objective := case when p_objective_provided then nullif(p_objective, '') else v_current.objective end;
  v_status := case when p_status_provided then p_status else v_current.status end;
  v_changed := p_touch
    or v_current.name is distinct from v_name
    or v_current.objective is distinct from v_objective
    or v_current.status is distinct from v_status;

  if not v_changed then
    return query select
      v_current.id, v_current.workspace_id, v_current.organization_id,
      v_current.name, v_current.objective, v_current.status,
      v_current.search_query, v_current.discovery_id, v_current.settings,
      v_current.created_by, v_current.updated_by, v_current.metadata,
      v_current.version, v_current.created_at, v_current.updated_at,
      v_current.archived_at, v_current.deleted_at, false;
    return;
  end if;

  update campaigns
  set name = v_name,
      objective = v_objective,
      status = v_status,
      version = v_current.version + 1,
      updated_at = now()
  where id = v_current.id
  returning * into v_updated;

  return query select
    v_updated.id, v_updated.workspace_id, v_updated.organization_id,
    v_updated.name, v_updated.objective, v_updated.status,
    v_updated.search_query, v_updated.discovery_id, v_updated.settings,
    v_updated.created_by, v_updated.updated_by, v_updated.metadata,
    v_updated.version, v_updated.created_at, v_updated.updated_at,
    v_updated.archived_at, v_updated.deleted_at, true;
end;
$$;
