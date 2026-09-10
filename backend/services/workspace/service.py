"""Workspace lifecycle use cases backed by canonical launch persistence."""
from __future__ import annotations

import asyncio
from uuid import uuid4

from services.persistence.launch import repositories
from services.persistence.launch.models import Workspace, WorkspaceMember
from services.workspace import access


class OrganizationNotFoundForWorkspace(Exception):
    """The caller is not an active member of the requested organization."""


class WorkspaceCreationForbidden(Exception):
    """The caller lacks the owner/admin role required to create a workspace."""


def default_workspace_slug(workspace_id: str, name: str = "Workspace") -> str:
    """Build the legacy default slug format for a newly created workspace."""
    base = (name or "Workspace").replace(" ", "-").lower()
    suffix = str(workspace_id or "")[:8]
    return f"{base}-{suffix}" if suffix else base


async def create_workspace(
    user_id: str,
    organization_id: str,
    name: str = "Workspace",
    slug: str = "",
) -> Workspace:
    """Create a workspace for an owner/admin active in its organization."""
    organization_id = (organization_id or "").strip()
    memberships = await asyncio.to_thread(access.active_memberships, None, user_id)
    membership = next(
        (item for item in memberships if item.get("organization_id") == organization_id),
        None,
    )
    if membership is None:
        raise OrganizationNotFoundForWorkspace()
    if (membership.get("role") or "member") not in ("owner", "admin"):
        raise WorkspaceCreationForbidden()

    workspace_id = str(uuid4())
    name = (name or "").strip() or "Workspace"
    slug = (slug or "").strip() or default_workspace_slug(workspace_id, name)
    workspace = Workspace(
        id=workspace_id,
        organization_id=organization_id,
        name=name,
        slug=slug,
        owner_user_id=user_id,
        created_by=user_id,
        updated_by=user_id,
        status="active",
    )
    await repositories.WorkspaceRepository().save(workspace)
    await repositories.WorkspaceMemberRepository().save(WorkspaceMember(
        workspace_id=workspace_id,
        user_id=user_id,
        role="owner",
        status="active",
    ))
    return workspace
