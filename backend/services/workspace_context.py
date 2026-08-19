"""SaaS-2.7 — Canonical multi-workspace context resolution.

A user may belong to multiple organizations/workspaces through ACTIVE
organization memberships. This module resolves, from authenticated context,
the set of workspaces a user may access and validates an explicitly selected
workspace — never trusting a client-supplied workspace/organization id as
authorization.

Authority model:
    identity_user -> ACTIVE membership -> organization -> workspace

A requested workspace is only authorized when:
  * the user has an ACTIVE membership in the workspace's organization, AND
  * the workspace belongs to that organization.

If no workspace is explicitly selected, a single accessible workspace may be
used as the implicit default (backwards compatibility). With multiple
accessible workspaces and no selection, resolution is ambiguous and refuses
rather than silently picking an arbitrary tenant.
"""

from __future__ import annotations

from dataclasses import dataclass

from services.supabase import get_supabase_client


class WorkspaceAccessDenied(Exception):
    """The requested workspace is not accessible to the user (safe 404)."""


class NoWorkspaceAvailable(Exception):
    """The user has no accessible workspace."""


class AmbiguousWorkspaceError(Exception):
    """The user has multiple accessible workspaces and none was selected."""


@dataclass
class WorkspaceContext:
    user_id: str
    organization_id: str
    workspace_id: str
    workspace_name: str
    membership_role: str = "member"
    membership_status: str = "active"


def _select(client, table: str, where: list[tuple[str, str, str]],
            limit: int = 0) -> list[dict]:
    q = client.table(table).select("*")
    for col, op, val in where:
        if op == "eq":
            q = q.eq(col, val)
        elif op == "in":
            q = q.in_(col, val)
        elif op == "is":
            q = q.is_(col, val)
    if limit:
        q = q.limit(limit)
    res = q.execute()
    return getattr(res, "data", None) or []


def active_memberships(client, user_id: str) -> list[dict]:
    """All ACTIVE organization memberships for a user."""
    return _select(client, "memberships", [
        ("user_id", "eq", user_id),
        ("status", "eq", "active"),
    ])


def workspaces_for_user(client=None, user_id: str = "") -> list[dict]:
    """Workspaces in every organization the user actively belongs to.

    READ-ONLY and membership-authorized: a workspace is only accessible when its
    organization is one the user is an ACTIVE member of. Returns safe metadata
    only.
    """
    client = client or get_supabase_client()
    if not user_id or client is None:
        return []
    memberships = active_memberships(client, user_id)
    org_ids = sorted({m.get("organization_id", "") for m in memberships if m.get("organization_id")})
    if not org_ids:
        return []
    workspaces = _select(client, "workspaces", [
        ("organization_id", "in", org_ids),
        ("deleted_at", "is", "null"),
    ])
    return [
        {
            "id": w.get("id", ""),
            "organization_id": w.get("organization_id", ""),
            "owner_user_id": w.get("owner_user_id", "") or "",
            "name": w.get("name", "") or "",
            "slug": w.get("slug", "") or "",
            "status": w.get("status", "active") or "active",
            "created_at": w.get("created_at"),
            "updated_at": w.get("updated_at"),
        }
        for w in workspaces
    ]


def resolve_workspace_context(
    client=None,
    user_id: str = "",
    requested_workspace_id: str = "",
) -> WorkspaceContext:
    """Resolve and validate a workspace context for an authenticated user.

    ``requested_workspace_id`` (e.g. from an X-Workspace-Id header) is
    validated against the user's ACTIVE memberships; it is never trusted as
    authorization by itself. When empty and the user has exactly one accessible
    workspace, that workspace is the implicit default; multiple without
    selection raises ``AmbiguousWorkspaceError``.
    """
    client = client or get_supabase_client()
    workspaces = workspaces_for_user(client, user_id)

    if requested_workspace_id:
        match = next((w for w in workspaces if w["id"] == requested_workspace_id), None)
        if match is None:
            raise WorkspaceAccessDenied(requested_workspace_id)
        selected = match
    else:
        if not workspaces:
            raise NoWorkspaceAvailable()
        if len(workspaces) > 1:
            raise AmbiguousWorkspaceError()
        selected = workspaces[0]

    # Membership for the selected workspace's organization (ACTIVE guaranteed
    # by workspaces_for_user, but re-read for role).
    role = "member"
    memberships = active_memberships(client, user_id)
    for m in memberships:
        if m.get("organization_id") == selected["organization_id"]:
            role = m.get("role", "member") or "member"
            break

    return WorkspaceContext(
        user_id=user_id,
        organization_id=selected["organization_id"],
        workspace_id=selected["id"],
        workspace_name=selected["name"],
        membership_role=role,
        membership_status="active",
    )
