-- 027 Workspace tenant foundation (SaaS-2.1).
--
-- Establishes the workspace as the canonical durable product tenant root with
-- an identity INDEPENDENT of workflow_sessions.id.
--
-- Previously `workspaces.id` was set equal to the channel='workspace'
-- workflow_sessions.id (see 006_workspaces.sql), so a recreated workflow
-- session changed the workspace identity and orphaned every workspace-owned
-- row (campaigns, workspace_leads, drafts, knowledge, ...). From this
-- migration onward NEW workspaces are minted with their own durable uuid and
-- the workflow session is only a chat/session/log object.
--
-- This migration is ADDITIVE and BACKWARDS-COMPATIBLE and touches ONLY
-- existing columns:
--   * existing workspace ids are left untouched (no rewrite, no delete);
--   * an index supports the durable owner -> workspace resolution path.
--
-- Existing legacy workspaces keep their workflow-session-derived id; they are
-- re-discovered by owner_user_id (workspaces.owner_user_id was always the
-- durable owner key). A later migration phase (SaaS-2.8) will remap child
-- resources for those legacy rows under a stable id and may add a
-- `workflow_session_id` provenance column at that time (deliberately deferred
-- so the new code is schema-cache compatible with pre-migration deployments).
--
-- Idempotent; safe to re-run; no destructive operations.

-- Support the canonical resolution: authenticated user -> canonical workspace
-- by durable owner relationship. Non-unique intentionally: legacy accounts
-- may transiently hold more than one workspace until reconciliation (SaaS-2.8).
create index if not exists workspaces_owner_org_active_idx
  on workspaces(owner_user_id, organization_id)
  where deleted_at is null;
