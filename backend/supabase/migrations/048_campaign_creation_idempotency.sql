-- Campaign creation is one transaction; the existing campaign row owns the
-- immutable request fingerprint. No extra entity, queue, or storage authority.
-- Only the backend service role may invoke this authorization-sensitive RPC.
create or replace function create_workspace_campaign_once(
  p_campaign_id uuid,
  p_workspace_id uuid,
  p_actor_user_id text,
  p_request_hash text,
  p_campaign jsonb,
  p_lead_ids uuid[],
  p_strategy jsonb default null
) returns jsonb
language plpgsql
set search_path = public
as $$
declare
  v_campaign campaigns%rowtype;
  v_workspace workspaces%rowtype;
  v_metadata jsonb;
  v_lead_ids uuid[];
begin
  if p_campaign_id is null or p_workspace_id is null
     or nullif(p_actor_user_id, '') is null or nullif(p_request_hash, '') is null then
    raise exception 'Campaign creation identity is required' using errcode = '22023';
  end if;
  -- Serialized across requests/processes, scoped to this creation identity.
  perform pg_advisory_xact_lock(hashtextextended(p_campaign_id::text, 0));
  select w.* into v_workspace from workspaces w
    where w.id = p_workspace_id and w.deleted_at is null for share;
  if not found then
    raise exception 'Workspace unavailable' using errcode = '42501';
  end if;
  -- Match workspace.access: organization membership is the authority, not
  -- ownership or the legacy workspace_members projection. Lock membership
  -- through commit so concurrent revocation cannot invalidate this check.
  perform m.id from memberships m
    where m.organization_id = v_workspace.organization_id
      and m.user_id = p_actor_user_id and m.status = 'active' for share;
  if not found then
    raise exception 'Workspace access denied' using errcode = '42501';
  end if;
  select c.* into v_campaign from campaigns c where c.id = p_campaign_id for update;
  if found then
    -- Existing repository writes can encode JSONB as a JSON string. Read
    -- both canonical objects and that existing representation after updates.
    v_metadata := case when jsonb_typeof(v_campaign.metadata) = 'string'
      then (v_campaign.metadata #>> '{}')::jsonb else v_campaign.metadata end;
    if v_campaign.workspace_id is distinct from p_workspace_id
       or v_campaign.created_by is distinct from p_actor_user_id
       or v_metadata->>'creation_request_hash' is distinct from p_request_hash then
      raise exception 'Idempotency key belongs to a different request' using errcode = '23514';
    end if;
    if v_campaign.deleted_at is not null or v_campaign.status = 'deleted' then
      raise exception 'Campaign was deleted' using errcode = 'P0002';
    end if;
    return jsonb_build_object('campaign', to_jsonb(v_campaign), 'created', false);
  end if;
  -- Lock the selected canonical leads until attachment commit. FK identity
  -- alone does not prove that a lead belongs to this workspace.
  -- Count and attach precisely the locked set, not a second query snapshot.
  select coalesce(array_agg(selected.id), '{}'::uuid[]) into v_lead_ids
    from (select l.id from workspace_leads l
      where l.id = any(coalesce(p_lead_ids, '{}'))
        and l.workspace_id = p_workspace_id and l.deleted_at is null
      order by l.id for share) selected;
  if cardinality(v_lead_ids) <> cardinality(coalesce(p_lead_ids, '{}')) then
    raise exception 'Selected lead unavailable in workspace' using errcode = '42501';
  end if;
  if nullif(p_campaign->>'discovery_id', '') is not null then
    perform d.id from discoveries d where d.id = (p_campaign->>'discovery_id')::uuid
      and d.workspace_id = p_workspace_id and d.deleted_at is null for share;
    if not found then
      raise exception 'Discovery unavailable in workspace' using errcode = '42501';
    end if;
  end if;
  insert into campaigns (id, workspace_id, organization_id, name, objective, status,
    search_query, discovery_id, created_by, updated_by, metadata)
  values (p_campaign_id, p_workspace_id, v_workspace.organization_id,
    p_campaign->>'name', coalesce(p_campaign->>'objective', ''), coalesce(p_campaign->>'status', 'planning'),
    coalesce(p_campaign->>'search_query', ''), nullif(p_campaign->>'discovery_id', '')::uuid,
    p_actor_user_id, p_actor_user_id, jsonb_build_object('creation_request_hash', p_request_hash))
  returning * into v_campaign;
  insert into campaign_leads (campaign_id, lead_id, added_by)
    select p_campaign_id, selected.id, p_actor_user_id
      from unnest(v_lead_ids) selected(id);
  -- Preserve an explicitly supplied existing strategy, without generating one.
  if p_strategy is not null then
    insert into strategies (campaign_id, objective, audience, channel, messaging_angle,
      sequence, tone, persona, offer, objections, raw, generated_by, model_used)
    values (p_campaign_id, coalesce(p_strategy->>'objective', ''), coalesce(p_strategy->>'audience', ''),
      coalesce(p_strategy->>'channel', ''), coalesce(p_strategy->>'messaging_angle', ''),
      coalesce(p_strategy->'sequence', '[]'), coalesce(p_strategy->>'tone', ''),
      coalesce(p_strategy->>'persona', ''), coalesce(p_strategy->'offer', '{}'),
      coalesce(p_strategy->'objections', '[]'), p_strategy, 'loqi', coalesce(p_strategy->>'model_used', ''));
  end if;
  return jsonb_build_object('campaign', to_jsonb(v_campaign), 'created', true);
end;
$$;
revoke all on function create_workspace_campaign_once(uuid, uuid, text, text, jsonb, uuid[], jsonb) from public, anon, authenticated;
grant execute on function create_workspace_campaign_once(uuid, uuid, text, text, jsonb, uuid[], jsonb) to service_role;
