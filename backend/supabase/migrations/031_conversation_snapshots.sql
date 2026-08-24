-- 031 Durable Inbox conversation snapshots.
--
-- The Inbox conversation store keeps its established Conversation/Thread/
-- Message API while persisting each conversation atomically as a workspace-
-- attributable snapshot. This removes the production dependency on the
-- container filesystem without introducing a second conversation model.

create table if not exists conversation_snapshots (
  conversation_id uuid primary key,
  owner_id text not null default '',
  workspace_id text not null,
  snapshot jsonb not null,
  version bigint not null default 0,
  updated_at timestamptz not null default now()
);

create index if not exists conversation_snapshots_owner_idx
  on conversation_snapshots(owner_id);

create index if not exists conversation_snapshots_workspace_idx
  on conversation_snapshots(workspace_id, owner_id);

-- A compare-and-swap write makes a stale process fail explicitly instead of
-- overwriting newer Inbox state. The application must reload and retry from
-- the authoritative snapshot after a conflict; it must never silently win.
create or replace function persist_conversation_snapshot(
  p_conversation_id uuid,
  p_owner_id text,
  p_workspace_id text,
  p_snapshot jsonb,
  p_expected_version bigint
) returns bigint
language plpgsql
as $$
declare
  current_version bigint;
  next_version bigint;
begin
  select version into current_version
  from conversation_snapshots
  where conversation_id = p_conversation_id
  for update;

  if not found then
    if p_expected_version <> 0 then
      raise exception 'conversation snapshot version conflict';
    end if;
    insert into conversation_snapshots (conversation_id, owner_id, workspace_id, snapshot, version)
    values (p_conversation_id, p_owner_id, p_workspace_id, p_snapshot, 1)
    returning version into next_version;
    return next_version;
  end if;

  if current_version <> p_expected_version then
    raise exception 'conversation snapshot version conflict';
  end if;

  update conversation_snapshots
  set owner_id = p_owner_id,
      workspace_id = p_workspace_id,
      snapshot = p_snapshot,
      version = version + 1,
      updated_at = now()
  where conversation_id = p_conversation_id
  returning version into next_version;
  return next_version;
end;
$$;
