"""HTTP adapter for workspace-scoped CSV exports."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import Response

from services.export.service import build_workspace_leads_csv
from services.identity import dependencies as identity_dependencies
from services.workspace import access as workspace_access


router = APIRouter(tags=["Export"])


@router.get("/api/web/session/{session_token}/export-csv")
async def export_csv(session_token: str, request: Request = None):
    """Return the authenticated selected workspace's lead export."""
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    selected_workspace = await workspace_access.resolve_selected_workspace_context(request, owner_id)
    export = await asyncio.to_thread(
        build_workspace_leads_csv,
        owner_id,
        selected_workspace.workspace_id,
        session_token,
    )
    return Response(
        content=export.content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={export.filename}"},
    )
