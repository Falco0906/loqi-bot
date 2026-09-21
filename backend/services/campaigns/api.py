"""Read-only HTTP routes for workspace-scoped campaigns."""
from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from services.workspace import access as workspace_access
from services.campaigns import service
from services.drafts import service as draft_service
from services.campaigns.service import load_campaigns
from services.identity import dependencies as identity_dependencies
from services.workspace.memory import record_campaign_open
from services.workspace.snapshot import enrich_campaigns
from services.workspace.state import load_drafts_only
from services.campaigns.timeline import CampaignTimelineService


router = APIRouter(tags=["Campaigns"])
log = logging.getLogger("loqi")


async def _authorized_workspace(request: Request) -> tuple[str, str, str]:
    """Resolve the authenticated caller, bearer token, and selected workspace."""
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    workspace_id = await workspace_access.resolve_legacy_workspace_id(request, owner_id)
    return owner_id, session_token, workspace_id


class SaveCampaignRequest(BaseModel):
    name: str
    objective: str = ""
    search_query: str = ""
    discovery_id: str = ""
    lead_count: int = 0
    leads: list[dict] | None = None
    strategy: dict | None = None
    status: str = "planning"


class UpdateCampaignRequest(BaseModel):
    name: str | None = None
    objective: str | None = None
    strategy: dict | None = None
    status: str | None = None


class AttachDiscoveryRequest(BaseModel):
    discovery_id: str


class AddCampaignLeadRequest(BaseModel):
    lead: dict
    discovery_id: str = ""


class RegenerateStrategyRequest(BaseModel):
    force: bool = False


class AnalyzeCampaignsRequest(BaseModel):
    leads: list[dict]
    campaign_id: str | None = None


@router.post("/api/web/session/{session_token}/analyze-campaigns")
async def analyze_campaigns_endpoint(session_token: str, payload: AnalyzeCampaignsRequest):
    """Preserve the legacy campaign-analysis response without adding state."""
    del session_token
    from services.campaigns.analysis import analyze_campaigns

    return analyze_campaigns(payload.leads)


@router.post("/api/web/session/{session_token}/campaigns")
async def save_campaign(session_token: str, payload: SaveCampaignRequest, request: Request):
    del session_token
    owner_id, bearer_token, workspace_id = await _authorized_workspace(request)
    return await service.create_campaign(
        bearer_token, owner_id, workspace_id, payload.model_dump(),
    )


@router.put("/api/web/session/{session_token}/campaigns/{campaign_id}")
async def update_campaign(
    session_token: str, campaign_id: str, payload: UpdateCampaignRequest, request: Request,
):
    del session_token
    owner_id, bearer_token, workspace_id = await _authorized_workspace(request)
    return await service.update_campaign(
        bearer_token, owner_id, workspace_id, campaign_id, payload.model_dump(),
    )


@router.post("/api/web/session/{session_token}/campaigns/{campaign_id}/leads")
async def add_campaign_lead(
    session_token: str, campaign_id: str, payload: AddCampaignLeadRequest, request: Request,
):
    del session_token
    owner_id, bearer_token, workspace_id = await _authorized_workspace(request)
    return await service.add_campaign_lead(
        bearer_token, owner_id, workspace_id, campaign_id, payload.lead, payload.discovery_id,
    )


@router.delete("/api/web/session/{session_token}/campaigns/{campaign_id}")
async def delete_campaign(session_token: str, campaign_id: str, request: Request):
    del session_token
    owner_id, bearer_token, workspace_id = await _authorized_workspace(request)
    return await service.delete_campaign(bearer_token, owner_id, workspace_id, campaign_id)


@router.post("/api/web/session/{session_token}/campaigns/{campaign_id}/duplicate")
async def duplicate_campaign(session_token: str, campaign_id: str, request: Request):
    del session_token
    owner_id, bearer_token, workspace_id = await _authorized_workspace(request)
    return await service.duplicate_campaign(bearer_token, owner_id, workspace_id, campaign_id)


@router.post("/api/web/session/{session_token}/campaigns/{campaign_id}/attach-discovery")
async def attach_discovery_to_campaign(
    session_token: str, campaign_id: str, payload: AttachDiscoveryRequest, request: Request,
):
    del session_token
    owner_id, bearer_token, workspace_id = await _authorized_workspace(request)
    return await service.attach_discovery(
        bearer_token, owner_id, workspace_id, campaign_id, payload.discovery_id,
    )


@router.get("/api/web/session/{session_token}/campaigns")
async def list_campaigns(session_token: str, request: Request):
    """Return enriched campaign list data without loading full campaign graphs."""
    del session_token
    started_at = time.perf_counter()
    owner_id, bearer_token, workspace_id = await _authorized_workspace(request)
    campaigns, drafts = await asyncio.gather(
        asyncio.to_thread(
            load_campaigns,
            owner_id,
            workspace_id=workspace_id,
            include_details=False,
        ),
        asyncio.to_thread(load_drafts_only, owner_id, workspace_id=workspace_id),
    )
    log.info(
        "[perf] route=/campaigns owner=%s ms=%.0f campaigns=%d",
        owner_id[:8],
        (time.perf_counter() - started_at) * 1000,
        len(campaigns),
    )
    del bearer_token
    return {"ok": True, "campaigns": enrich_campaigns(campaigns, drafts)}


@router.get("/api/web/session/{session_token}/campaigns/summary")
async def campaign_summary(session_token: str, request: Request):
    """Return the compact campaign summary used by workspace views."""
    del session_token
    owner_id, _, workspace_id = await _authorized_workspace(request)
    campaigns = load_campaigns(owner_id, workspace_id=workspace_id)
    drafts = load_drafts_only(owner_id, workspace_id=workspace_id)
    enriched = enrich_campaigns(campaigns, drafts)
    items = [{
        "id": campaign.get("id", ""),
        "name": campaign.get("name", ""),
        "status": campaign.get("status", "planning"),
        "lead_count": campaign.get("lead_count", 0),
        "pending_drafts": campaign.get("pending_drafts", 0),
        "updated_at": campaign.get("updated_at", ""),
    } for campaign in enriched]
    return {"ok": True, "campaigns": items}


@router.get("/api/web/session/{session_token}/campaigns/{campaign_id}")
async def get_campaign(session_token: str, campaign_id: str, request: Request):
    """Return one enriched campaign scoped to the selected workspace."""
    del session_token
    owner_id, bearer_token, workspace_id = await _authorized_workspace(request)
    campaigns = load_campaigns(owner_id, workspace_id=workspace_id)
    drafts = load_drafts_only(owner_id, workspace_id=workspace_id)
    target = next(
        (campaign for campaign in enrich_campaigns(campaigns, drafts)
         if campaign.get("id") == campaign_id),
        None,
    )
    if not target:
        raise HTTPException(status_code=404, detail="Campaign not found")
    record_campaign_open(bearer_token, campaign_id, target.get("name", ""))
    return {"ok": True, "campaign": target}


@router.get("/api/web/session/{session_token}/campaigns/{campaign_id}/launch-progress")
async def campaign_launch_progress(session_token: str, campaign_id: str, request: Request):
    """Return canonical launch counters for one selected-workspace campaign."""
    del session_token
    owner_id, _, workspace_id = await _authorized_workspace(request)
    campaigns = load_campaigns(owner_id, workspace_id=workspace_id)
    target = next((campaign for campaign in campaigns if campaign.get("id") == campaign_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Campaign not found")
    launch_sent = target.get("launch_sent", 0)
    launch_total = target.get("launch_total", 0)
    return {
        "ok": True,
        "launch_sent": launch_sent,
        "launch_total": launch_total,
        "launch_complete": launch_sent >= launch_total if launch_total > 0 else False,
    }


@router.get("/api/web/session/{session_token}/campaigns/{campaign_id}/timeline")
async def campaign_timeline(session_token: str, campaign_id: str, request: Request):
    """Return the safe durable/canonical campaign timeline projection."""
    del session_token
    owner_id, bearer_token, workspace_id = await _authorized_workspace(request)
    return await CampaignTimelineService().read(
        owner_id=owner_id,
        workspace_id=workspace_id,
        session_token=bearer_token,
        campaign_id=campaign_id,
    )


@router.post("/api/web/session/{session_token}/campaigns/{campaign_id}/generate-strategy", status_code=202)
async def generate_campaign_strategy(
    session_token: str,
    campaign_id: str,
    payload: RegenerateStrategyRequest | None,
    request: Request,
):
    del session_token
    owner_id, bearer_token, workspace_id = await _authorized_workspace(request)
    return await service.start_strategy_generation(
        bearer_token,
        owner_id,
        workspace_id,
        campaign_id,
        force=bool(payload and payload.force),
    )


@router.get("/api/web/session/{session_token}/campaigns/{campaign_id}/strategy-jobs/{job_id}")
async def strategy_job_status(session_token: str, campaign_id: str, job_id: str, request: Request):
    del session_token
    owner_id, _, workspace_id = await _authorized_workspace(request)
    job = await service.strategy_job_status(owner_id, workspace_id, campaign_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Strategy job not found")
    return job


@router.get("/api/web/session/{session_token}/campaigns/{campaign_id}/drafts")
async def list_campaign_drafts(session_token: str, campaign_id: str, request: Request):
    del session_token
    owner_id, _, workspace_id = await _authorized_workspace(request)
    return await draft_service.list_campaign_drafts(owner_id, workspace_id, campaign_id)


@router.post("/api/web/session/{session_token}/campaigns/{campaign_id}/generate-drafts", status_code=202)
async def generate_campaign_drafts(session_token: str, campaign_id: str, request: Request):
    del session_token
    owner_id, bearer_token, workspace_id = await _authorized_workspace(request)
    return await draft_service.start_campaign_draft_generation(
        bearer_token,
        owner_id,
        workspace_id,
        campaign_id,
    )


@router.get("/api/web/session/{session_token}/campaigns/{campaign_id}/generation-status")
async def campaign_generation_status(session_token: str, campaign_id: str, request: Request):
    del session_token
    owner_id, _, workspace_id = await _authorized_workspace(request)
    return await draft_service.campaign_draft_generation_status(owner_id, workspace_id, campaign_id)
