"""HTTP routes for the workspace-scoped Knowledge domain."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from services.identity import dependencies as identity_dependencies
from services.knowledge.service import KnowledgeService, KnowledgeValidationError
from services import workspace_context as workspace_access


router = APIRouter(tags=["Knowledge"])


class KnowledgeItemCreateRequest(BaseModel):
    category: str
    title: str
    summary: str = ""
    content: dict = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    source_type: str = "user_input"
    source_id: str = ""


class KnowledgeItemUpdateRequest(BaseModel):
    title: str | None = None
    summary: str | None = None
    content: dict | None = None
    tags: list[str] | None = None
    source_type: str | None = None
    source_id: str | None = None


class KnowledgeSourceCreateRequest(BaseModel):
    title: str
    source_type: str = "user_input"
    content: str = ""
    reference: str = ""
    metadata: dict = Field(default_factory=dict)


class KnowledgeSourceUpdateRequest(BaseModel):
    title: str | None = None
    source_type: str | None = None
    content: str | None = None
    reference: str | None = None
    metadata: dict | None = None


def _service() -> KnowledgeService:
    """Build a request-scoped service over the current persistence connection."""
    return KnowledgeService()


async def _authorized_workspace(request: Request) -> tuple[str, str]:
    """Resolve the bearer identity and its legacy-compatible workspace scope."""
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    workspace_id = await workspace_access.resolve_legacy_workspace_id(request, owner_id)
    if not workspace_id:
        raise HTTPException(status_code=503, detail="Workspace could not be resolved")
    return owner_id, workspace_id


@router.get("/api/web/session/{session_token}/knowledge")
async def list_knowledge(
    session_token: str,
    request: Request,
    category: str = "",
    q: str = "",
    limit: int = 200,
):
    del session_token
    owner_id, workspace_id = await _authorized_workspace(request)
    try:
        items = await _service().list_items(
            workspace_id, category=category or None, q=q or None, limit=limit)
    except KnowledgeValidationError as error:
        raise HTTPException(status_code=400, detail=str(error))
    return {"ok": True, "items": items, "owner_id": owner_id}


@router.post("/api/web/session/{session_token}/knowledge")
async def create_knowledge_item(
    session_token: str, payload: KnowledgeItemCreateRequest, request: Request,
):
    del session_token
    owner_id, workspace_id = await _authorized_workspace(request)
    try:
        item = await _service().create_item(
            owner_id=owner_id,
            workspace_id=workspace_id,
            category=payload.category,
            title=payload.title,
            summary=payload.summary,
            content=payload.content,
            tags=payload.tags,
            source_type=payload.source_type,
            source_id=payload.source_id,
        )
    except KnowledgeValidationError as error:
        raise HTTPException(status_code=400, detail=str(error))
    return {"ok": True, "item": item}


@router.get("/api/web/session/{session_token}/knowledge/sources")
async def list_knowledge_sources(
    session_token: str,
    request: Request,
    q: str = "",
    limit: int = 200,
):
    del session_token
    owner_id, workspace_id = await _authorized_workspace(request)
    sources = await _service().list_sources(workspace_id, q=q or None, limit=limit)
    return {"ok": True, "sources": sources, "owner_id": owner_id}


@router.post("/api/web/session/{session_token}/knowledge/sources")
async def create_knowledge_source(
    session_token: str, payload: KnowledgeSourceCreateRequest, request: Request,
):
    del session_token
    owner_id, workspace_id = await _authorized_workspace(request)
    try:
        source = await _service().create_source(
            owner_id=owner_id,
            workspace_id=workspace_id,
            title=payload.title,
            source_type=payload.source_type,
            content=payload.content,
            reference=payload.reference,
            metadata=payload.metadata,
        )
    except KnowledgeValidationError as error:
        raise HTTPException(status_code=400, detail=str(error))
    return {"ok": True, "source": source}


@router.put("/api/web/session/{session_token}/knowledge/sources/{source_id}")
async def update_knowledge_source(
    session_token: str, source_id: str,
    payload: KnowledgeSourceUpdateRequest, request: Request,
):
    del session_token
    owner_id, workspace_id = await _authorized_workspace(request)
    try:
        source = await _service().update_source(
            owner_id=owner_id,
            workspace_id=workspace_id,
            source_id=source_id,
            title=payload.title,
            source_type=payload.source_type,
            content=payload.content,
            reference=payload.reference,
            metadata=payload.metadata,
        )
    except KnowledgeValidationError as error:
        raise HTTPException(status_code=400, detail=str(error))
    if source is None:
        raise HTTPException(status_code=404, detail="Knowledge source not found")
    return {"ok": True, "source": source}


@router.delete("/api/web/session/{session_token}/knowledge/sources/{source_id}")
async def archive_knowledge_source(
    session_token: str, source_id: str, request: Request,
):
    del session_token
    owner_id, workspace_id = await _authorized_workspace(request)
    source = await _service().archive_source(
        owner_id=owner_id, workspace_id=workspace_id, source_id=source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Knowledge source not found")
    return {"ok": True, "source": source}


@router.get("/api/web/session/{session_token}/knowledge/{item_id}")
async def get_knowledge_item(session_token: str, item_id: str, request: Request):
    del session_token
    _, workspace_id = await _authorized_workspace(request)
    item = await _service().get_item(workspace_id, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Knowledge item not found")
    return {"ok": True, "item": item}


@router.put("/api/web/session/{session_token}/knowledge/{item_id}")
async def update_knowledge_item(
    session_token: str, item_id: str,
    payload: KnowledgeItemUpdateRequest, request: Request,
):
    del session_token
    owner_id, workspace_id = await _authorized_workspace(request)
    try:
        item = await _service().update_item(
            owner_id=owner_id,
            workspace_id=workspace_id,
            item_id=item_id,
            title=payload.title,
            summary=payload.summary,
            content=payload.content,
            tags=payload.tags,
            source_type=payload.source_type,
            source_id=payload.source_id,
        )
    except KnowledgeValidationError as error:
        raise HTTPException(status_code=400, detail=str(error))
    if item is None:
        raise HTTPException(status_code=404, detail="Knowledge item not found")
    return {"ok": True, "item": item}


@router.delete("/api/web/session/{session_token}/knowledge/{item_id}")
async def archive_knowledge_item(session_token: str, item_id: str, request: Request):
    del session_token
    owner_id, workspace_id = await _authorized_workspace(request)
    item = await _service().archive_item(
        owner_id=owner_id, workspace_id=workspace_id, item_id=item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Knowledge item not found")
    return {"ok": True, "item": item}
