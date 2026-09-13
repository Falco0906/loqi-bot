-- 037 Durable legacy conversation-intelligence memory.
--
-- The legacy communication projection is keyed by an arbitrary caller ID
-- today.  This table deliberately accepts only canonical Inbox conversation
-- IDs and keeps its own versioned record so intelligence writes do not race
-- with conversation snapshot/message/timeline writes.

create table if not exists conversation_intelligence_memories (
  conversation_id uuid primary key references conversation_snapshots(conversation_id) on delete cascade,
  owner_id text not null,
  workspace_id text not null,
  memory jsonb not null default '{}'::jsonb,
  processed_source_message_ids jsonb not null default '[]'::jsonb,
  version bigint not null default 0,
  updated_at timestamptz not null default now()
);

create index if not exists conversation_intelligence_memories_scope_idx
  on conversation_intelligence_memories(workspace_id, owner_id);

-- Compare-and-swap persistence. A repeated source-message ID is explicitly
-- idempotent: it returns the current version without changing memory. The
-- bounded source-ID list prevents unbounded row growth while retaining enough
-- replay protection for provider retry windows.
create or replace function persist_conversation_intelligence_memory(
  p_conversation_id uuid,
  p_owner_id text,
  p_workspace_id text,
  p_memory jsonb,
  p_source_message_id text,
  p_expected_version bigint
) returns bigint
language plpgsql
as $$
declare
  current_version bigint;
  current_owner_id text;
  current_workspace_id text;
  current_source_ids jsonb;
  next_version bigint;
  next_source_ids jsonb;
begin
  if coalesce(trim(p_source_message_id), '') = '' then
    raise exception 'conversation intelligence source message id is required';
  end if;

  select version, owner_id, workspace_id, processed_source_message_ids
    into current_version, current_owner_id, current_workspace_id, current_source_ids
  from conversation_intelligence_memories
  where conversation_id = p_conversation_id
  for update;

  if not found then
    if p_expected_version <> 0 then
      raise exception 'conversation intelligence memory version conflict';
    end if;
    insert into conversation_intelligence_memories (
      conversation_id, owner_id, workspace_id, memory,
      processed_source_message_ids, version
    ) values (
      p_conversation_id, p_owner_id, p_workspace_id, p_memory,
      jsonb_build_array(p_source_message_id), 1
    ) returning version into next_version;
    return next_version;
  end if;

  if current_owner_id <> p_owner_id or current_workspace_id <> p_workspace_id then
    raise exception 'conversation intelligence memory ownership mismatch';
  end if;

  if current_source_ids ? p_source_message_id then
    return current_version;
  end if;

  if current_version <> p_expected_version then
    raise exception 'conversation intelligence memory version conflict';
  end if;

  select coalesce(jsonb_agg(value), '[]'::jsonb)
    into next_source_ids
  from (
    select value
    from jsonb_array_elements(current_source_ids || jsonb_build_array(p_source_message_id))
    with ordinality as entries(value, position)
    order by position desc
    limit 200
  ) recent;

  update conversation_intelligence_memories
  set memory = p_memory,
      processed_source_message_ids = next_source_ids,
      version = version + 1,
      updated_at = now()
  where conversation_id = p_conversation_id
  returning version into next_version;
  return next_version;
end;
$$;
