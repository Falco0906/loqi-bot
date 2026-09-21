-- Durable, bounded derived context for Copilot. This table deliberately holds
-- conversational references only; canonical workspace state remains in its
-- existing domain tables and repositories.

create table if not exists copilot_memories (
  user_id text not null,
  workspace_id text not null,
  conversation_key text not null,
  memory jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (user_id, workspace_id, conversation_key)
);

create index if not exists copilot_memories_workspace_user_idx
  on copilot_memories(workspace_id, user_id, updated_at desc);
