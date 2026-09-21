"""Read-only HTTP routes for durable Discovery entities."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from services.identity import dependencies as identity_dependencies
from services.workspace import access as workspace_access
from services.discovery.service import (
    DiscoveryLeadDecisionError,
    DiscoveryJobLifecycleError,
    create_search_run,
    decide_discovery_lead,
    get_discovery,
    get_job_for_user,
    get_job_results_for_user,
    list_discoveries,
    list_recent_jobs_for_user,
)


router = APIRouter(tags=["Discovery"])
log = logging.getLogger("loqi")


async def _authorized_workspace(request: Request) -> tuple[str, str, str]:
    """Resolve the authenticated caller and its selected workspace."""
    user_id, session_token = await identity_dependencies.resolve_web_session(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Valid session required")
    workspace_id = await workspace_access.resolve_legacy_workspace_id(request, user_id)
    return user_id, session_token, workspace_id


class StartSearchRequest(BaseModel):
    query: str


class CreateDiscoveryRequest(BaseModel):
    query: str


class LeadDecisionRequest(BaseModel):
    lead: dict
    approved: bool


@router.post("/api/jobs/search")
async def start_search(payload: StartSearchRequest, request: Request):
    """Schedule a durable search linked to a canonical Discovery."""
    user_id, session_token, workspace_id = await _authorized_workspace(request)
    try:
        return await create_search_run(
            user_id,
            payload.query,
            session_token,
            workspace_id=workspace_id,
        )
    except DiscoveryJobLifecycleError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


@router.post("/api/discoveries")
async def create_discovery_endpoint(payload: CreateDiscoveryRequest, request: Request):
    """Create one first-class Discovery and queue its durable research job."""
    user_id, session_token, workspace_id = await _authorized_workspace(request)
    log.info("[kickoff] POST /api/discoveries: user=%s query=%r", user_id, payload.query)
    try:
        result = await create_search_run(
            user_id,
            payload.query,
            session_token,
            workspace_id=workspace_id,
        )
    except DiscoveryJobLifecycleError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    log.info(
        "[kickoff] POST /api/discoveries: ok discovery_id=%s job_id=%s",
        result.get("discovery_id", ""),
        result.get("job_id", ""),
    )
    return {"ok": True, **result}


@router.get("/api/discoveries")
async def list_discoveries_endpoint(request: Request):
    """Return recent durable discoveries for the selected workspace."""
    _, _, workspace_id = await _authorized_workspace(request)
    discoveries = await asyncio.to_thread(list_discoveries, workspace_id)
    return {"ok": True, "discoveries": discoveries}


@router.get("/api/discoveries/{discovery_id}")
async def get_discovery_endpoint(discovery_id: str, request: Request):
    """Return one workspace-authorized discovery and its surfaced results."""
    user_id, _, workspace_id = await _authorized_workspace(request)
    log.info("[kickoff] GET /api/discoveries/%s: user=%s", discovery_id, user_id)
    discovery = await asyncio.to_thread(get_discovery, discovery_id, workspace_id)
    if not discovery:
        raise HTTPException(status_code=404, detail="Discovery not found")
    return {"ok": True, "discovery": discovery}


@router.post("/api/web/session/{session_token}/leads/decision")
async def decide_discovery_lead_endpoint(
    session_token: str,
    payload: LeadDecisionRequest,
    request: Request,
):
    """Persist an approval/rejection for a durable Discovery workspace lead."""
    del session_token
    owner_id, bearer_token, workspace_id = await _authorized_workspace(request)
    try:
        return await decide_discovery_lead(
            owner_id,
            workspace_id,
            bearer_token,
            payload.lead,
            payload.approved,
        )
    except DiscoveryLeadDecisionError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


async def _authenticated_user(request: Request) -> str:
    user_id, _ = await identity_dependencies.resolve_web_session(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Valid session required")
    return user_id


@router.get("/api/jobs/{job_id}")
async def get_job(job_id: str, request: Request):
    user_id = await _authenticated_user(request)
    job = await get_job_for_user(job_id, user_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/api/jobs/{job_id}/results")
async def get_job_results(job_id: str, request: Request):
    user_id = await _authenticated_user(request)
    result = await get_job_results_for_user(job_id, user_id)
    if not result:
        raise HTTPException(status_code=404, detail="Job not found")
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Job not ready"))
    return result


@router.get("/api/jobs")
async def list_jobs(request: Request):
    # The user is derived only from the bound credential, never from a
    # client-supplied user_id query parameter.
    user_id, _ = await identity_dependencies.resolve_web_session(request)
    if not user_id:
        return {"jobs": []}
    return {"jobs": await list_recent_jobs_for_user(user_id)}
