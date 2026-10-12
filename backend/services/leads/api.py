"""HTTP boundary for the workspace-scoped Beta lead database."""
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from services.identity import dependencies as identity_dependencies
from services.workspace import access
from services.leads.service import (
    LeadImportError,
    LeadDatabaseUnavailable,
    analyze_workspace_leads,
    import_csv_rows,
    list_workspace_leads,
    parse_csv_preview,
)

router = APIRouter(tags=["Leads"])

class CsvPreviewRequest(BaseModel):
    csv: str = Field(max_length=5_000_000)
    mapping: dict[str, str] = Field(default_factory=dict)

class CsvImportRequest(BaseModel):
    rows: list[dict]
class LeadAnalysisRequest(BaseModel):
    lead_ids: list[str] = Field(min_length=1, max_length=50)

class LeadGenerationRequest(LeadAnalysisRequest):
    request_key: str = Field(min_length=1, max_length=128)

async def _scope(request: Request) -> tuple[str, str]:
    token = identity_dependencies.web_session_token(request)
    owner = await identity_dependencies.authenticated_user_id(request, token)
    selected = await access.resolve_selected_workspace_context(request, owner)
    return owner, selected.workspace_id

@router.get("/api/web/session/{session_token}/leads")
async def list_leads(session_token: str, request: Request, q: str = "", page: int = 1,
                     location: str = "", industry: str = "", company: str = "", title: str = "", keywords: str = "",
                     discovery_id: str = ""):
    del session_token
    _, workspace_id = await _scope(request)
    if page < 1:
        raise HTTPException(status_code=400, detail="page must be positive")
    try:
        return {"ok": True, **await list_workspace_leads(workspace_id, q, page, filters={
            "location": location, "industry": industry, "company": company, "title": title, "keywords": keywords,
        }, discovery_id=discovery_id)}
    except LeadDatabaseUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

@router.post("/api/web/session/{session_token}/leads/csv-preview")
async def csv_preview(session_token: str, payload: CsvPreviewRequest, request: Request):
    del session_token
    await _scope(request)
    try:
        preview = parse_csv_preview(payload.csv, payload.mapping or None)
    except LeadImportError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"ok": True, **preview}

@router.post("/api/web/session/{session_token}/leads/csv-import")
async def csv_import(session_token: str, payload: CsvImportRequest, request: Request):
    del session_token
    owner, workspace_id = await _scope(request)
    try:
        return {"ok": True, **await import_csv_rows(workspace_id, owner, payload.rows)}
    except LeadDatabaseUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

@router.post("/api/web/session/{session_token}/leads/analyze")
async def analyze_leads(session_token: str, payload: LeadAnalysisRequest, request: Request):
    del session_token
    owner_id, workspace_id = await _scope(request)
    try:
        return {"ok": True, **await analyze_workspace_leads(workspace_id, owner_id, payload.lead_ids)}
    except LeadImportError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/api/web/session/{session_token}/leads/generate-strategy")
async def generate_lead_strategy_drafts(session_token: str, payload: LeadGenerationRequest, request: Request):
    """Explicit Phase 4C action; scope is derived from the authenticated session."""
    del session_token
    owner_id, workspace_id = await _scope(request)
    from services.leads.generation import start_lead_generation
    try:
        return await start_lead_generation(workspace_id, owner_id, payload.lead_ids, payload.request_key)
    except LeadImportError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/api/web/session/{session_token}/leads/generation")
async def recover_lead_generation(session_token: str, request: Request, request_key: str):
    del session_token
    owner_id, workspace_id = await _scope(request)
    from services.leads.generation import generation_id, generation_status
    return await generation_status(workspace_id, owner_id, generation_id(workspace_id, owner_id, request_key))


@router.get("/api/web/session/{session_token}/leads/generation/{job_id}")
async def lead_generation_status(session_token: str, job_id: str, request: Request):
    del session_token
    owner_id, workspace_id = await _scope(request)
    from services.leads.generation import generation_status
    return await generation_status(workspace_id, owner_id, job_id)
