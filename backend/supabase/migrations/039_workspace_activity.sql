-- Durable, workspace-scoped activity used by Mission Control deltas.
-- Application services authorize selected workspace scope before calling the
-- repository; this migration intentionally does not introduce RLS policy.

create table if not exists workspace_activity_sequences (
  workspace_id uuid primary key references workspaces(id) on delete cascade,
  last_sequence bigint not null default 0,
  updated_at timestamptz not null default now(),
  constraint workspace_activity_sequences_nonnegative check (last_sequence >= 0)
);

create table if not exists workspace_activity_events (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  actor_user_id uuid references identity_users(id) on delete set null,
  event_type text not null,
  payload jsonb not null default '{}'::jsonb,
  source_key text not null,
  sequence bigint not null,
  occurred_at timestamptz not null,
  created_at timestamptz not null default now(),
  constraint workspace_activity_events_source_uidx unique (workspace_id, source_key),
  constraint workspace_activity_events_sequence_uidx unique (workspace_id, sequence),
  constraint workspace_activity_events_sequence_positive check (sequence > 0)
);

create index if not exists workspace_activity_events_workspace_sequence_idx
  on workspace_activity_events(workspace_id, sequence desc);

create index if not exists workspace_activity_events_workspace_occurred_idx
  on workspace_activity_events(workspace_id, occurred_at desc);

create table if not exists workspace_briefing_cursors (
  workspace_id uuid not null references workspaces(id) on delete cascade,
  user_id uuid not null references identity_users(id) on delete cascade,
  last_viewed_sequence bigint not null default 0,
  last_viewed_at timestamptz,
  updated_at timestamptz not null default now(),
  primary key (workspace_id, user_id),
  constraint workspace_briefing_cursors_nonnegative check (last_viewed_sequence >= 0)
);

-- The advisory lock serializes duplicate source-key attempts before sequence
-- allocation. Different source keys can still allocate independently through
-- the per-workspace counter row.
create or replace function append_workspace_activity_event(
  p_workspace_id uuid,
  p_actor_user_id uuid,
  p_event_type text,
  p_payload jsonb,
  p_source_key text,
  p_occurred_at timestamptz default now()
)
returns table(event_id uuid, event_sequence bigint, occurred_at timestamptz, was_created boolean)
language plpgsql
as $$
declare
  v_existing workspace_activity_events%rowtype;
  v_sequence bigint;
  v_inserted workspace_activity_events%rowtype;
begin
  perform pg_advisory_xact_lock(hashtextextended(p_workspace_id::text || ':' || p_source_key, 0));

  select * into v_existing
  from workspace_activity_events
  where workspace_id = p_workspace_id and source_key = p_source_key;

  if found then
    return query select v_existing.id, v_existing.sequence, v_existing.occurred_at, false;
    return;
  end if;

  insert into workspace_activity_sequences (workspace_id, last_sequence)
  values (p_workspace_id, 0)
  on conflict (workspace_id) do nothing;

  update workspace_activity_sequences
  set last_sequence = last_sequence + 1,
      updated_at = now()
  where workspace_id = p_workspace_id
  returning last_sequence into v_sequence;

  insert into workspace_activity_events (
    workspace_id, actor_user_id, event_type, payload, source_key, sequence, occurred_at
  ) values (
    p_workspace_id, p_actor_user_id, p_event_type, p_payload, p_source_key, v_sequence,
    coalesce(p_occurred_at, now())
  ) returning * into v_inserted;

  return query select v_inserted.id, v_inserted.sequence, v_inserted.occurred_at, true;
end;
$$;

-- A cursor may only acknowledge events included in the delivered response.
-- It never reads the current workspace sequence itself.
create or replace function acknowledge_workspace_briefing(
  p_workspace_id uuid,
  p_user_id uuid,
  p_delivered_through_sequence bigint
)
returns table(last_viewed_sequence bigint, last_viewed_at timestamptz)
language plpgsql
as $$
begin
  if p_delivered_through_sequence < 0 then
    raise exception 'delivered_through_sequence must be nonnegative';
  end if;

  return query
  insert into workspace_briefing_cursors (
    workspace_id, user_id, last_viewed_sequence, last_viewed_at, updated_at
  ) values (
    p_workspace_id, p_user_id, p_delivered_through_sequence, now(), now()
  )
  on conflict (workspace_id, user_id) do update
  set last_viewed_sequence = greatest(
        workspace_briefing_cursors.last_viewed_sequence,
        excluded.last_viewed_sequence
      ),
      last_viewed_at = case
        when excluded.last_viewed_sequence > workspace_briefing_cursors.last_viewed_sequence
          then excluded.last_viewed_at
        else workspace_briefing_cursors.last_viewed_at
      end,
      updated_at = now()
  returning workspace_briefing_cursors.last_viewed_sequence,
            workspace_briefing_cursors.last_viewed_at;
end;
$$;
