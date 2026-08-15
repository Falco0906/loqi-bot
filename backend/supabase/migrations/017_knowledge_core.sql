-- 017 Knowledge Core — user-owned Knowledge foundation (PR5).
--
-- User Knowledge is distinct from AI memory (the `knowledge` table in 009,
-- which stores one AI-generated summary per (owner_type, owner_id,
-- summary_type)). Knowledge here is USER-ENTERED canonical context about the
-- business: company facts, ICP, messaging rules, sales/offer material, and
-- retrievable source material. It is workspace-scoped and soft-deletable.
--
-- provenance model:
--   source_type: user_input | uploaded_document | imported_source | system_generated
--   source_id:   optional reference to a knowledge_sources row or external doc.
--   created_by:  owner user id for attribution.
--
-- No embeddings/vectors in this PR — retrieval is structured filtering.

-- ─── knowledge_items ──────────────────────────────────────────────────────

create table if not exists knowledge_items (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  category text not null,
  title text not null,
  summary text not null default '',
  content jsonb not null default '{}',
  tags jsonb not null default '[]',
  source_type text not null default 'user_input',
  source_id text not null default '',
  created_by text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz
);

create index if not exists knowledge_items_workspace_idx
  on knowledge_items(workspace_id, created_at desc);
create index if not exists knowledge_items_category_idx
  on knowledge_items(workspace_id, category, updated_at desc);
create index if not exists knowledge_items_deleted_idx
  on knowledge_items(deleted_at) where deleted_at is not null;

-- ─── knowledge_sources ────────────────────────────────────────────────────

create table if not exists knowledge_sources (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  title text not null,
  source_type text not null default 'user_input',
  content text not null default '',
  reference text not null default '',
  metadata jsonb not null default '{}',
  created_by text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz
);

-- Keep the migration safe if an earlier local iteration created the table with
-- UI-oriented values instead of the canonical provenance vocabulary.
update knowledge_sources set source_type = 'user_input' where source_type = 'note';
update knowledge_sources set source_type = 'uploaded_document' where source_type = 'document';
update knowledge_sources set source_type = 'imported_source' where source_type = 'imported';
alter table knowledge_sources alter column source_type set default 'user_input';

create index if not exists knowledge_sources_workspace_idx
  on knowledge_sources(workspace_id, created_at desc);
create index if not exists knowledge_sources_deleted_idx
  on knowledge_sources(deleted_at) where deleted_at is not null;
