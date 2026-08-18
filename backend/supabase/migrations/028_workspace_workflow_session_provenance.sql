-- 028 Stable workspace ownership — workflow-session provenance (SaaS-2.3).
--
-- SaaS-2.1 established that NEW workspaces mint their own durable uuid and are
-- resolved by owner_user_id, never by a workflow session id. It deliberately
-- deferred adding provenance because legacy production workspaces still have
-- ``workspaces.id == workflow_sessions.id`` and the column was not yet present.
--
-- This migration introduces the durable ``workflow_session_id`` PROVENANCE
-- column on ``workspaces``:
--
--   * UUID-compatible, NULLABLE — a workspace can exist independently of any
--     workflow session (SaaS-2.1 new workspaces have no session linkage).
--   * It is a REFERENCE/PROVENANCE only. It is NEVER the workspace identity.
--   * NULL keeps existing rows valid; no existing workspace id is rewritten.
--   * Additive and idempotent (``add column if not exists``) — safe to re-run
--     and compatible with the PostgREST schema-cache deployment model.
--
-- The FK is deliberately NOT enforced: the legacy relationship lived in loose
-- text and production session rows may be recreated/absent. Enforcing a hard
-- FK could invalidate existing rows. The application writes only a valid
-- workflow session id when one is known, and keeps the column NULL otherwise.
--
-- Rollback: ``alter table workspaces drop column workflow_session_id;``
-- (additive; dropping is safe once no application writes depend on it).

alter table workspaces add column if not exists workflow_session_id uuid;

-- Justify the index by query path: the operator migration detects an already-
-- migrated workspace by looking up ``workspaces.workflow_session_id`` == a
-- legacy workspace id, and workspace bootstrap resolves by owner. Both are
-- point lookups; an index supports the provenance lookup and the eventual
-- reconciliation scan.
create index if not exists workspaces_workflow_session_idx
  on workspaces(workflow_session_id)
  where workflow_session_id is not null;
