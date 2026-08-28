"""Read-only HTTP routes for durable Discovery entities."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request

from services.identity import dependencies as identity_dependencies
from services import workspace_context as workspace_access
from services.discovery.service import get_discovery, list_discoveries


router = APIRouter(tags=["Discovery"])
log = logging.getLogger("loqi")


async def _authorized_workspace(request: Request) -> tuple[str, str]:
    """Resolve the authenticated caller and its selected workspace."""
    user_id, _ = await identity_dependencies.resolve_web_session(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Valid session required")
    workspace_id = await workspace_access.resolve_legacy_workspace_id(request, user_id)
    return user_id, workspace_id


@router.get("/api/discoveries")
async def list_discoveries_endpoint(request: Request):
    """Return recent durable discoveries for the selected workspace."""
    _, workspace_id = await _authorized_workspace(request)
    discoveries = await asyncio.to_thread(list_discoveries, workspace_id)
    return {"ok": True, "discoveries": discoveries}


@router.get("/api/discoveries/{discovery_id}")
async def get_discovery_endpoint(discovery_id: str, request: Request):
    """Return one workspace-authorized discovery and its surfaced results."""
    user_id, workspace_id = await _authorized_workspace(request)
    log.info("[kickoff] GET /api/discoveries/%s: user=%s", discovery_id, user_id)
    discovery = await asyncio.to_thread(get_discovery, discovery_id, workspace_id)
    if not discovery:
        raise HTTPException(status_code=404, detail="Discovery not found")
    return {"ok": True, "discovery": discovery}
