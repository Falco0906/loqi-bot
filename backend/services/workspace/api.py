"""HTTP adapters for workspace lifecycle and selection."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from services.identity import dependencies as identity_dependencies
from services.workspace import access, service


router = APIRouter(tags=["Workspace"])


class CreateWorkspaceRequest(BaseModel):
    organization_id: str = ""
    name: str = "Workspace"
    slug: str = ""


async def _authenticated_owner(request: Request) -> tuple[str, str]:
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    return owner_id, session_token


@router.get("/api/web/session/{session_token}/workspaces")
async def list_workspaces(session_token: str, request: Request):
    """List workspaces in every organization the caller actively belongs to."""
    del session_token
    owner_id, _ = await _authenticated_owner(request)
    workspaces = await asyncio.to_thread(access.workspaces_for_user, None, owner_id)
    return {"ok": True, "workspaces": workspaces}


@router.post("/api/web/session/{session_token}/workspaces/select")
async def select_workspace(session_token: str, request: Request):
    """Validate and return the explicitly selected workspace context."""
    del session_token
    owner_id, _ = await _authenticated_owner(request)
    context = await access.resolve_selected_workspace_context(request, owner_id)
    return {
        "ok": True,
        "workspace": {
            "id": context.workspace_id,
            "organization_id": context.organization_id,
            "name": context.workspace_name,
            "membership_role": context.membership_role,
            "membership_status": context.membership_status,
        },
    }


@router.post("/api/web/session/{session_token}/workspaces")
async def create_workspace(
    session_token: str,
    payload: CreateWorkspaceRequest,
    request: Request,
):
    """Create a workspace in an organization where the caller is owner/admin."""
    del session_token
    owner_id, _ = await _authenticated_owner(request)
    try:
        workspace = await service.create_workspace(
            owner_id,
            payload.organization_id,
            payload.name,
            payload.slug,
        )
    except service.OrganizationNotFoundForWorkspace as error:
        raise HTTPException(status_code=404, detail="Organization not found") from error
    except service.WorkspaceCreationForbidden as error:
        raise HTTPException(status_code=403, detail="Insufficient role to create a workspace") from error
    return {
        "ok": True,
        "workspace": {
            "id": workspace.id,
            "organization_id": workspace.organization_id,
            "name": workspace.name,
            "slug": workspace.slug,
            "owner_user_id": workspace.owner_user_id,
            "status": workspace.status,
        },
    }
