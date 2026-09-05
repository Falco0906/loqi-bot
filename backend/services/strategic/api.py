"""HTTP adapters for canonical Strategic Intelligence operations."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from services.identity import dependencies as identity_dependencies
from services.strategic.actions import StrategicActionError, StrategicActionService
from services.strategic.service import StrategicIntelligenceService


router = APIRouter(tags=["Strategic"])


async def _authorized_owner(request: Request) -> str:
    """Resolve the authenticated owner for a Strategic request."""
    session_token = identity_dependencies.web_session_token(request)
    return await identity_dependencies.authenticated_user_id(request, session_token)


def _action_http_error(error: StrategicActionError) -> HTTPException:
    """Translate established Strategic action errors to HTTP responses."""
    status = 404 if "not found" in str(error).lower() else 400
    return HTTPException(status_code=status, detail=str(error))


async def _action_call(method: str, owner_id: str, action_id: str, *args):
    """Call an action operation while preserving the existing error contract."""
    try:
        return await getattr(StrategicActionService(), method)(owner_id, action_id, *args)
    except StrategicActionError as error:
        raise _action_http_error(error)


@router.get("/api/web/session/{session_token}/strategic-updates")
async def list_strategic_updates(
    session_token: str,
    request: Request,
    update_type: str = "",
    confidence: str = "",
    q: str = "",
    include_archived: bool = False,
):
    del session_token
    owner_id = await _authorized_owner(request)
    updates = await StrategicIntelligenceService().list_updates(
        owner_id,
        update_type=update_type or None,
        confidence=confidence or None,
        query=q or None,
        include_archived=include_archived,
    )
    last_analyzed = max(
        (str(update.get("updated_at") or "") for update in updates),
        default=None,
    )
    return {"ok": True, "updates": updates, "last_analyzed": last_analyzed}


@router.post("/api/web/session/{session_token}/strategic-updates/refresh")
async def refresh_strategic_updates(session_token: str, request: Request):
    del session_token
    owner_id = await _authorized_owner(request)
    return await StrategicIntelligenceService().refresh(owner_id)


@router.get("/api/web/session/{session_token}/strategic-updates/{update_id}/actions")
async def list_strategic_actions(session_token: str, update_id: str, request: Request):
    del session_token
    owner_id = await _authorized_owner(request)
    actions = await StrategicActionService().list_actions(owner_id, update_id)
    return {"ok": True, "actions": actions}


@router.post("/api/web/session/{session_token}/strategic-updates/{update_id}/actions")
async def propose_strategic_action(
    session_token: str, update_id: str, request: Request, payload: dict = None,
):
    del session_token
    owner_id = await _authorized_owner(request)
    action_type = str((payload or {}).get("action_type") or "").strip()
    try:
        action = await StrategicActionService().propose(owner_id, update_id, action_type)
    except StrategicActionError as error:
        raise _action_http_error(error)
    return {"ok": True, "action": action}


@router.get("/api/web/session/{session_token}/strategic-updates/{update_id}")
async def get_strategic_update(session_token: str, update_id: str, request: Request):
    del session_token
    owner_id = await _authorized_owner(request)
    update = await StrategicIntelligenceService().get_update(owner_id, update_id)
    if update is None:
        raise HTTPException(status_code=404, detail="Strategic Update not found")
    return {"ok": True, "update": update}


@router.post("/api/web/session/{session_token}/strategic-actions/{action_id}/approve")
async def approve_strategic_action(session_token: str, action_id: str, request: Request):
    del session_token
    owner_id = await _authorized_owner(request)
    return {"ok": True, "action": await _action_call("approve", owner_id, action_id)}


@router.post("/api/web/session/{session_token}/strategic-actions/{action_id}/dismiss")
async def dismiss_strategic_action(session_token: str, action_id: str, request: Request):
    del session_token
    owner_id = await _authorized_owner(request)
    return {"ok": True, "action": await _action_call("dismiss", owner_id, action_id)}


@router.post("/api/web/session/{session_token}/strategic-actions/{action_id}/refine")
async def refine_strategic_action(
    session_token: str, action_id: str, request: Request, payload: dict = None,
):
    del session_token
    owner_id = await _authorized_owner(request)
    changes = (payload or {}).get("changes") if isinstance(payload, dict) else {}
    return {"ok": True, "action": await _action_call("refine", owner_id, action_id, changes or {})}


@router.post("/api/web/session/{session_token}/strategic-actions/{action_id}/execute")
async def execute_strategic_action(session_token: str, action_id: str, request: Request):
    del session_token
    owner_id = await _authorized_owner(request)
    return {"ok": True, "action": await _action_call("execute", owner_id, action_id)}


@router.delete("/api/web/session/{session_token}/strategic-updates/{update_id}")
async def archive_strategic_update(session_token: str, update_id: str, request: Request):
    del session_token
    owner_id = await _authorized_owner(request)
    update = await StrategicIntelligenceService().archive_update(owner_id, update_id)
    if update is None:
        raise HTTPException(status_code=404, detail="Strategic Update not found")
    return {"ok": True, "update": update}
