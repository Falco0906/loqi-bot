-- Repair migration 040's PL/pgSQL name ambiguity.  RETURN TABLE columns are
-- implicit variables, so every read/write reference to workspace_preferences
-- must use the relation alias rather than an unqualified output-column name.
-- The RPC signature and result contract intentionally remain unchanged.
create or replace function upsert_workspace_preference_if_higher(
  p_workspace_id uuid,
  p_actor_user_id uuid,
  p_preference_key text,
  p_preference_value text,
  p_confidence numeric,
  p_source text,
  p_evidence_count integer,
  p_first_observed_at timestamptz,
  p_last_observed_at timestamptz
)
returns table(
  id uuid,
  workspace_id uuid,
  preference_key text,
  preference_value text,
  confidence numeric,
  source text,
  evidence_count integer,
  first_observed_at timestamptz,
  last_observed_at timestamptz,
  version bigint,
  updated_by uuid,
  updated_at timestamptz,
  was_updated boolean
)
language plpgsql
as $$
declare
  v_current workspace_preferences%rowtype;
begin
  if p_workspace_id is null then
    raise exception 'workspace_id is required';
  end if;
  if coalesce(trim(p_preference_key), '') = '' then
    raise exception 'preference_key is required';
  end if;
  if coalesce(trim(p_preference_value), '') = '' then
    raise exception 'preference_value is required';
  end if;
  if p_confidence is null or p_confidence < 0 or p_confidence > 1 then
    raise exception 'confidence must be between 0 and 1';
  end if;
  if p_evidence_count is null or p_evidence_count < 0 then
    raise exception 'evidence_count must be nonnegative';
  end if;

  loop
    select wp.* into v_current
    from workspace_preferences as wp
    where wp.workspace_id = p_workspace_id
      and wp.preference_key = p_preference_key
    for update;

    if found then
      if v_current.confidence >= p_confidence then
        return query select
          v_current.id, v_current.workspace_id, v_current.preference_key,
          v_current.preference_value, v_current.confidence, v_current.source,
          v_current.evidence_count, v_current.first_observed_at,
          v_current.last_observed_at, v_current.version, v_current.updated_by,
          v_current.updated_at, false;
        return;
      end if;

      update workspace_preferences as wp
      set preference_value = p_preference_value,
          confidence = p_confidence,
          source = coalesce(p_source, ''),
          evidence_count = p_evidence_count,
          last_observed_at = coalesce(p_last_observed_at, now()),
          version = v_current.version + 1,
          updated_by = p_actor_user_id,
          updated_at = now()
      where wp.id = v_current.id
      returning wp.* into v_current;

      return query select
        v_current.id, v_current.workspace_id, v_current.preference_key,
        v_current.preference_value, v_current.confidence, v_current.source,
        v_current.evidence_count, v_current.first_observed_at,
        v_current.last_observed_at, v_current.version, v_current.updated_by,
        v_current.updated_at, true;
      return;
    end if;

    insert into workspace_preferences as wp (
      workspace_id, preference_key, preference_value, confidence, source,
      evidence_count, first_observed_at, last_observed_at, version,
      updated_by, updated_at
    ) values (
      p_workspace_id, p_preference_key, p_preference_value, p_confidence,
      coalesce(p_source, ''), p_evidence_count,
      coalesce(p_first_observed_at, now()), coalesce(p_last_observed_at, now()),
      1, p_actor_user_id, now()
    ) on conflict on constraint workspace_preferences_scope_key_uidx do nothing
    returning wp.* into v_current;

    if found then
      return query select
        v_current.id, v_current.workspace_id, v_current.preference_key,
        v_current.preference_value, v_current.confidence, v_current.source,
        v_current.evidence_count, v_current.first_observed_at,
        v_current.last_observed_at, v_current.version, v_current.updated_by,
        v_current.updated_at, true;
      return;
    end if;
  end loop;
end;
$$;
