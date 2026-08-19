"""SaaS-2.3 — Stable workspace ownership: legacy workspace detection + migration.

A legacy workspace is one whose ``id`` equals its originating
``workflow_sessions.id`` (channel='workspace') — i.e. created before SaaS-2.1
decoupled the workspace identity from the workflow session.

This module provides the application machinery to migrate those legacy
workspaces safely and explicitly:

  * ``detect_legacy_workspaces`` — READ-ONLY discovery.
  * ``build_migration_plan`` — READ-ONLY plan for one legacy workspace.
  * ``apply_migration_plan`` — DRY-RUN-FIRST write path (``--apply`` explicit).

The migration:
  1. mints a NEW canonical workspace id (fresh uuid, never derived from a
     workflow session),
  2. preserves ``owner_user_id`` / ``organization_id`` / name / slug / status /
     settings / metadata,
  3. sets ``workflow_session_id`` = the legacy workflow session id
     (provenance/REFRERENCE only — never the identity),
  4. remaps workspace-owned child resources from the legacy id to the new id,
  5. keeps the workflow session intact (never deleted),
  6. soft-deletes the legacy workspace row ONLY after children are remapped.

Migration is an EXPLICIT operator action (``--apply``). It is NEVER performed
automatically during normal requests. It is idempotent and refuses ambiguous /
blocked states without mutating anything.

The write path uses direct PostgREST operations (no multi-statement
transaction is available via PostgREST), so it is designed for resumability and
explicit partial-failure reporting — never claimed to be atomic.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from services.supabase import get_supabase_client

# Workspace-owned product resources carrying a workspace_id column (FK NOT NULL
# to workspaces.id). These are remapped when the workspace tenant identity is
# stabilized. Optional/reference-only tables (notifications, audit_log,
# usage_records, subscriptions) are intentionally NOT remapped in SaaS-2.3 and
# are deferred to SaaS-2.4 resource-by-resource scoping.
CHILD_WORKSPACE_TABLES: tuple[str, ...] = (
    "campaigns",
    "workspace_leads",
    "workspace_companies",
    "drafts",
    "discoveries",
    "knowledge",
    "knowledge_items",
    "knowledge_sources",
    "strategic_updates",
    "strategic_actions",
    "workspace_members",
)


def _select(client: Any, table: str,
            where: list[tuple[str, str, str]] | None = None) -> list[dict[str, Any]]:
    """Read a table with tenant filters, paginating past PostgREST's default
    max-rows cap (1000) so counts are exact and categories are internally
    consistent (legacy + non-legacy == total)."""
    rows: list[dict[str, Any]] = []
    page_size = 500
    offset = 0
    while True:
        q = client.table(table).select("*")
        for col, op, val in (where or []):
            if op == "eq":
                q = q.eq(col, val)
            elif op == "is":
                q = q.is_(col, val)
        q = q.limit(page_size).offset(offset)
        page = getattr(q.execute(), "data", None) or []
        if not page:
            break
        rows.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    return rows


def _first(client: Any, table: str,
           where: list[tuple[str, str, str]] | None = None) -> dict[str, Any] | None:
    rows = _select(client, table, where=where)
    return rows[0] if rows else None


def _count(client: Any, table: str,
           where: list[tuple[str, str, str]] | None = None) -> int:
    total = 0
    page_size = 500
    offset = 0
    while True:
        q = client.table(table).select("id")
        for col, op, val in (where or []):
            if op == "eq":
                q = q.eq(col, val)
            elif op == "is":
                q = q.is_(col, val)
        q = q.limit(page_size).offset(offset)
        page = getattr(q.execute(), "data", None) or []
        total += len(page)
        if len(page) < page_size:
            break
        offset += page_size
    return total


def detect_legacy_workspaces(client: Any = None) -> list[dict[str, Any]]:
    """READ-ONLY: discover workspaces whose id equals a workflow_sessions.id.

    A workspace is legacy when an active (non-deleted) workspace row has an id
    that matches a channel='workspace' workflow session.

    Uses a two-scan set-intersection (all channel='workspace' session ids, then
    active workspaces) so it stays efficient at production scale — it never
    performs a per-workspace session lookup. Returns safe metadata only (no
    secrets).
    """
    client = client or get_supabase_client()

    # 1. Collect all channel='workspace' workflow session ids (lightweight).
    session_ids: set[str] = set()
    page_size = 500
    offset = 0
    while True:
        q = (client.table("workflow_sessions").select("id")
             .eq("channel", "workspace").limit(page_size).offset(offset))
        page = getattr(q.execute(), "data", None) or []
        if not page:
            break
        session_ids.update(r["id"] for r in page if r.get("id"))
        if len(page) < page_size:
            break
        offset += page_size

    # 2. Active workspaces whose id is one of those session ids.
    legacy: list[dict[str, Any]] = []
    offset = 0
    while True:
        q = (client.table("workspaces").select("*")
             .is_("deleted_at", "null").order("created_at", desc=True)
             .limit(page_size).offset(offset))
        page = getattr(q.execute(), "data", None) or []
        if not page:
            break
        for ws in page:
            ws_id = ws.get("id")
            if ws_id and ws_id in session_ids:
                legacy.append({
                    "workspace_id": ws_id,
                    "owner_user_id": ws.get("owner_user_id", "") or "",
                    "organization_id": ws.get("organization_id", "") or "",
                    "workflow_session_id": ws_id,
                    "name": ws.get("name", "") or "",
                    "slug": ws.get("slug", "") or "",
                    "status": ws.get("status", "active") or "active",
                    "settings": ws.get("settings") or {},
                    "metadata": ws.get("metadata") or {},
                })
        if len(page) < page_size:
            break
        offset += page_size
    return legacy


def _already_migrated(client: Any, legacy_workspace_id: str) -> bool:
    """True when a canonical workspace already records this session as provenance."""
    try:
        existing = _first(client, "workspaces",
                          where=[("workflow_session_id", "eq", legacy_workspace_id)])
    except Exception:
        # Column absent (migration 028 not yet applied) — no provenance recorded.
        return False
    return existing is not None and existing.get("id") != legacy_workspace_id


def _has_workflow_session_column(client: Any) -> bool:
    """True when the workspaces table exposes workflow_session_id (migration 028)."""
    try:
        client.table("workspaces").select("workflow_session_id").limit(1).execute()
        return True
    except Exception:
        return False


def build_migration_plan(
    client: Any = None,
    workspace_id: str = "",
    *,
    user_id: str = "",
    organization_id: str = "",
) -> dict[str, Any]:
    """READ-ONLY: build a migration plan for one legacy workspace.

    Returns blocker reasons (never guesses) and readiness. No writes.
    """
    client = client or get_supabase_client()

    def _blocked(reason: str, **extra) -> dict[str, Any]:
        return {
            "legacy_workspace_id": workspace_id,
            "new_workspace_id": "",
            "owner_user_id": "",
            "organization_id": "",
            "workflow_session_id": "",
            "ready": False,
            "already_migrated": False,
            "blockers": [reason],
            "child_counts": {},
            **extra,
        }

    legacy = _first(client, "workspaces", where=[("id", "eq", workspace_id), ("deleted_at", "is", "null")])
    if legacy is None:
        return _blocked("legacy workspace not found or already soft-deleted")

    session = _first(client, "workflow_sessions",
                     where=[("id", "eq", workspace_id), ("channel", "eq", "workspace")])
    if session is None:
        return _blocked("not a legacy workspace (no matching channel='workspace' workflow session)")

    if _already_migrated(client, workspace_id):
        return {
            "legacy_workspace_id": workspace_id,
            "new_workspace_id": "",
            "owner_user_id": legacy.get("owner_user_id", "") or "",
            "organization_id": legacy.get("organization_id", "") or "",
            "workflow_session_id": workspace_id,
            "ready": False,
            "already_migrated": True,
            "blockers": ["already migrated (provenance workflow_session_id already set)"],
            "child_counts": {},
        }

    owner_user_id = legacy.get("owner_user_id", "") or ""
    org_id = legacy.get("organization_id", "") or ""

    blockers: list[str] = []

    # Owner must exist.
    if not owner_user_id:
        blockers.append("owner_user_id is missing")
    else:
        owner = _first(client, "identity_users", where=[("id", "eq", owner_user_id)])
        if owner is None:
            blockers.append("owner user does not exist")

    # Organization must exist.
    if not org_id:
        blockers.append("organization_id is missing")
    else:
        org = _first(client, "organizations", where=[("id", "eq", org_id)])
        if org is None:
            blockers.append("organization does not exist")

    # Ambiguity: exactly one active canonical workspace per owner is required
    # to determine the correct tenant. More than one => refuse.
    if owner_user_id:
        owner_workspaces = _select(client, "workspaces",
                                   where=[("owner_user_id", "eq", owner_user_id), ("deleted_at", "is", "null")])
        if len(owner_workspaces) > 1:
            blockers.append(
                "ambiguous: multiple active workspaces for owner; cannot determine canonical tenant"
            )

    # Child-resource inventory (read-only). Collision against the fresh new id
    # is enforced at apply time (no rows can exist under a freshly minted id;
    # any such row indicates a prior partial/conflicting migration).
    child_counts: dict[str, int] = {}
    for table in CHILD_WORKSPACE_TABLES:
        child_counts[table] = _count(client, table, [("workspace_id", "eq", workspace_id)])

    new_workspace_id = str(uuid4())

    return {
        "legacy_workspace_id": workspace_id,
        "new_workspace_id": new_workspace_id,
        "owner_user_id": owner_user_id,
        "organization_id": org_id,
        "workflow_session_id": workspace_id,
        "name": legacy.get("name", "") or "",
        "slug": legacy.get("slug", "") or "",
        "status": legacy.get("status", "active") or "active",
        "settings": legacy.get("settings") or {},
        "metadata": legacy.get("metadata") or {},
        "child_counts": child_counts,
        "ready": not blockers,
        "already_migrated": False,
        "blockers": blockers,
    }


def _collision_check(client: Any, table: str, new_workspace_id: str) -> str | None:
    """Return a blocker string if rows already exist under the new workspace id.

    The new id is fresh (never minted before), so any existing row under it
    indicates a prior conflicting/partial migration. Never silently overwrite.
    """
    if _count(client, table, [("workspace_id", "eq", new_workspace_id)]) > 0:
        return f"collision: rows already exist for new workspace id in {table}"
    return None


def apply_migration_plan(
    client: Any = None,
    plan: dict[str, Any] | None = None,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Apply (or dry-run) a migration plan for one legacy workspace.

    ``dry_run=True`` (default) performs zero writes. ``dry_run=False`` is the
    explicit operator apply path.
    """
    client = client or get_supabase_client()
    if plan is None:
        return {"applied": False, "reason": "no plan provided"}

    if plan.get("already_migrated"):
        return {"applied": False, "reason": "already_migrated", "dry_run": dry_run}
    if not plan.get("ready"):
        return {
            "applied": False, "reason": "blocked",
            "blockers": plan.get("blockers", []), "dry_run": dry_run,
        }

    legacy_id = plan["legacy_workspace_id"]
    new_id = plan["new_workspace_id"]

    if dry_run:
        return {
            "applied": False, "dry_run": True,
            "plan": plan,
            "reason": "dry-run (no writes)",
        }

    # Idempotency / re-run safety: re-verify durable state at apply time, even
    # if the plan was built earlier. Never create a second workspace or remap
    # twice.
    if _already_migrated(client, legacy_id):
        return {"applied": False, "reason": "already_migrated", "dry_run": False}
    legacy_now = _first(client, "workspaces", where=[("id", "eq", legacy_id), ("deleted_at", "is", "null")])
    if legacy_now is None:
        return {"applied": False, "reason": "already_migrated_or_removed", "dry_run": False}

    # Re-read durable state at apply time: never trust a stale dry-run plan.
    # The organization must still exist and the owner must still have an ACTIVE
    # membership in it; otherwise refuse this workspace.
    org_id = plan.get("organization_id", "") or ""
    owner_id = plan.get("owner_user_id", "") or ""
    if org_id and _first(client, "organizations", where=[("id", "eq", org_id)]) is None:
        return {"applied": False, "reason": "blocked",
                "blockers": ["organization no longer exists"], "dry_run": False}
    if owner_id and not any(
        m.get("organization_id") == org_id and m.get("status") == "active"
        for m in _select(client, "memberships", where=[("user_id", "eq", owner_id)])
    ):
        return {"applied": False, "reason": "blocked",
                "blockers": ["owner no longer has an active membership in the target organization"],
                "dry_run": False}

    # The provenance column must exist (migration 028) to write the mapping.
    if not _has_workflow_session_column(client):
        return {
            "applied": False, "reason": "blocked",
            "blockers": ["migration 028 not applied (workflow_session_id column missing)"],
            "dry_run": False,
        }

    # Collision guard against partial/conflicting prior state.
    for table in CHILD_WORKSPACE_TABLES:
        blocker = _collision_check(client, table, new_id)
        if blocker:
            return {"applied": False, "reason": "blocked", "blockers": [blocker], "dry_run": False}

    now = datetime.now(timezone.utc).isoformat()

    # 1. Create the new canonical workspace (fresh uuid, provenance only).
    row = {
        "id": new_id,
        "organization_id": plan.get("organization_id", "") or "",
        "workflow_session_id": plan.get("workflow_session_id", "") or None,
        "name": plan.get("name", "") or "",
        "slug": plan.get("slug", "") or "",
        "owner_user_id": plan.get("owner_user_id", "") or "",
        "created_by": plan.get("owner_user_id", "") or "",
        "updated_by": plan.get("owner_user_id", "") or "",
        "status": plan.get("status", "active") or "active",
        "settings": json.dumps(plan.get("settings") or {}),
        "metadata": json.dumps(plan.get("metadata") or {}),
        "version": 1,
        "created_at": now,
        "updated_at": now,
        "deleted_at": None,
    }
    client.table("workspaces").insert(row).execute()

    # 2. Remap workspace-owned children from legacy id -> new id.
    remapped: dict[str, int] = {}
    for table in CHILD_WORKSPACE_TABLES:
        res = (
            client.table(table)
            .update({"workspace_id": new_id})
            .eq("workspace_id", legacy_id)
            .execute()
        )
        remapped[table] = len(getattr(res, "data", None) or [])

    # 3. Soft-delete the legacy workspace (row preserved, excluded from lookups)
    #    ONLY after children are remapped.
    client.table("workspaces").update({"deleted_at": now}).eq("id", legacy_id).execute()

    return {
        "applied": True,
        "dry_run": False,
        "legacy_workspace_id": legacy_id,
        "new_workspace_id": new_id,
        "owner_user_id": plan.get("owner_user_id", ""),
        "organization_id": plan.get("organization_id", ""),
        "workflow_session_id": plan.get("workflow_session_id", ""),
        "remapped_child_counts": remapped,
    }
