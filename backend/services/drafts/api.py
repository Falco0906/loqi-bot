"""HTTP adapters for canonical Draft lifecycle operations."""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Request
from pydantic import BaseModel

from services import workspace_context as workspace_access
from services.drafts import service
from services.identity import dependencies as identity_dependencies


router = APIRouter(tags=["Drafts"])
log = logging.getLogger("loqi")


class RefineDraftRequest(BaseModel):
    edit_request: str
    previous_message: str
    lead: dict
    campaign_id: str | None = None
    campaign_name: str | None = None
    company: str | None = None
    contact: str | None = None
    role: str | None = None
    industry: str | None = None
    messaging_angle: str | None = None
    business_summary: str | None = None


class UpdateDraftRequest(BaseModel):
    text: str


class AnalyzeDraftRequest(BaseModel):
    draft_text: str
    lead: dict
    campaign_id: str | None = None
    campaign_name: str | None = None
    company: str | None = None
    contact: str | None = None
    role: str | None = None
    industry: str | None = None
    messaging_angle: str | None = None
    business_summary: str | None = None


class AskDraftQuestionRequest(BaseModel):
    question: str
    draft_text: str
    lead: dict
    campaign_id: str | None = None
    campaign_name: str | None = None
    company: str | None = None
    contact: str | None = None
    role: str | None = None
    industry: str | None = None
    messaging_angle: str | None = None
    business_summary: str | None = None


class CompareDraftVersionsRequest(BaseModel):
    old_text: str
    new_text: str
    change_summary: list[str] | None = None


async def _authorized_identity(request: Request) -> tuple[str, str]:
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    return owner_id, session_token


async def _authorized_workspace(request: Request) -> tuple[str, str, str]:
    owner_id, session_token = await _authorized_identity(request)
    workspace_id = await workspace_access.resolve_legacy_workspace_id(request, owner_id)
    return owner_id, session_token, workspace_id


@router.get("/api/web/session/{session_token}/drafts")
async def list_drafts(session_token: str, request: Request):
    del session_token
    started_at = time.perf_counter()
    owner_id, _, workspace_id = await _authorized_workspace(request)
    result = await service.list_drafts(owner_id, workspace_id)
    log.info("[perf] route=/drafts owner=%s ms=%.0f drafts=%d", owner_id[:8],
             (time.perf_counter() - started_at) * 1000, len(result["drafts"]))
    return result


@router.put("/api/web/session/{session_token}/drafts/{draft_id}")
async def update_draft(session_token: str, draft_id: str, payload: UpdateDraftRequest, request: Request):
    del session_token
    owner_id, bearer_token = await _authorized_identity(request)
    return await service.update_draft(bearer_token, owner_id, draft_id, payload.text)


@router.post("/api/web/session/{session_token}/drafts/{draft_id}/refine")
async def refine_draft(session_token: str, draft_id: str, payload: RefineDraftRequest, request: Request):
    del session_token
    owner_id, bearer_token = await _authorized_identity(request)
    return await service.refine_draft(bearer_token, owner_id, draft_id, payload.model_dump())


@router.post("/api/web/session/{session_token}/drafts/analyze")
async def analyze_draft_endpoint(session_token: str, payload: AnalyzeDraftRequest):
    del session_token
    return await service.analyze_draft(payload.model_dump())


@router.post("/api/web/session/{session_token}/drafts/ask")
async def ask_draft_question_endpoint(session_token: str, payload: AskDraftQuestionRequest):
    del session_token
    return await service.ask_draft_question(payload.model_dump())


@router.post("/api/web/session/{session_token}/drafts/{draft_id}/approve")
async def approve_draft(session_token: str, draft_id: str, request: Request):
    del session_token
    owner_id, bearer_token, workspace_id = await _authorized_workspace(request)
    return await service.approve_draft(bearer_token, owner_id, workspace_id, draft_id)


@router.post("/api/web/session/{session_token}/drafts/{draft_id}/undo")
async def undo_draft(session_token: str, draft_id: str, request: Request):
    del session_token
    owner_id, bearer_token = await _authorized_identity(request)
    return await service.undo_draft(bearer_token, owner_id, draft_id)


@router.get("/api/web/session/{session_token}/drafts/{draft_id}/history")
async def draft_rewrite_history(session_token: str, draft_id: str, request: Request = None):
    del session_token
    owner_id, bearer_token, workspace_id = await _authorized_workspace(request)
    return await service.draft_history(bearer_token, owner_id, workspace_id, draft_id)


@router.post("/api/web/session/{session_token}/drafts/compare")
async def compare_draft_versions(session_token: str, payload: CompareDraftVersionsRequest):
    del session_token
    return await service.compare_draft_versions(payload.model_dump())
