"""HTTP adapters for canonical outbound draft operations."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from services.workspace import access as workspace_access
from services.workspace.state import load_drafts_only
from services.identity import dependencies as identity_dependencies
from services.outbound import service
from services.outbound.outbound_events import get_events, latest_sequence


router = APIRouter(tags=["Outbound"])


class OutboundCreateDraftRequest(BaseModel):
    provider_id: str
    conversation_id: str = ""
    thread_id: str = ""
    workflow_id: str = ""
    subject: str
    body: str
    recipient_email: str
    recipient_name: str = ""
    sender_email: str
    sender_name: str = ""
    cc: list[dict] = []
    bcc: list[dict] = []
    reply_to_message_id: str = ""
    in_reply_to: str = ""
    references: str = ""


class OutboundUpdateDraftRequest(BaseModel):
    provider_id: str
    draft_id: str
    external_draft_id: str = ""
    subject: str = ""
    body: str = ""
    recipient_email: str = ""
    recipient_name: str = ""


class ApproveAllRequest(BaseModel):
    auto: bool = False


class SendDraftRequest(BaseModel):
    test_recipient: str = ""
    test_recipient_name: str = ""


class ScheduleDraftRequest(BaseModel):
    send_at: str


class OutboundSendRequest(BaseModel):
    provider_id: str
    draft_id: str = ""


class OutboundScheduleRequest(BaseModel):
    provider_id: str
    draft_id: str
    send_at: str


async def _authorized_owner(request: Request) -> tuple[str, str]:
    """Resolve the existing legacy bearer and authenticated owner."""
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    return session_token, owner_id


async def _authorized_owner_and_workspace(request: Request) -> tuple[str, str, str]:
    """Resolve the existing legacy bearer, authenticated owner, and workspace."""
    session_token, owner_id = await _authorized_owner(request)
    workspace_id = await workspace_access.resolve_legacy_workspace_id(request, owner_id)
    return session_token, owner_id, workspace_id


def _history_dict(history: object) -> dict:
    """Preserve the established outbound-history response shape."""
    if hasattr(history, "model_dump"):
        return history.model_dump()
    sent_at = getattr(history, "sent_at", None)
    return {
        "id": getattr(history, "id", ""),
        "provider_id": getattr(history, "provider_id", ""),
        "external_message_id": getattr(history, "external_message_id", ""),
        "conversation_id": getattr(history, "conversation_id", ""),
        "thread_id": getattr(history, "thread_id", ""),
        "workflow_id": "",
        "subject": getattr(history, "subject", ""),
        "recipient": {
            "email": getattr(history, "recipient_email", ""),
            "name": getattr(history, "recipient_name", ""),
        },
        "status": getattr(history, "status", "sent"),
        "sent_at": sent_at.isoformat() if sent_at else "",
        "draft_id": getattr(history, "draft_id", ""),
        "error": getattr(history, "error", ""),
    }


@router.post("/api/web/session/{session_token}/outbound/drafts")
async def outbound_create_draft(session_token: str, payload: OutboundCreateDraftRequest, request: Request):
    del session_token
    return await service.create_outbound_draft(request, payload.model_dump())


@router.patch("/api/web/session/{session_token}/outbound/drafts/{draft_id}")
async def outbound_update_draft(
    session_token: str, draft_id: str, payload: OutboundUpdateDraftRequest, request: Request,
):
    del session_token
    return await service.update_outbound_draft(request, draft_id, payload.model_dump())


@router.delete("/api/web/session/{session_token}/outbound/drafts/{draft_id}")
async def outbound_delete_draft(
    session_token: str, draft_id: str, provider_id: str = "", request: Request = None,
):
    del session_token
    return await service.delete_outbound_draft(request, draft_id, provider_id)


@router.post("/api/web/session/{session_token}/outbound/drafts/{draft_id}/approve")
async def outbound_approve_draft(
    session_token: str, draft_id: str, auto: bool = False, request: Request = None,
):
    del session_token
    return await service.approve_outbound_draft(request, draft_id, auto)


@router.post("/api/web/session/{session_token}/outbound/drafts/{draft_id}/reject")
async def outbound_reject_draft(session_token: str, draft_id: str, request: Request = None):
    del session_token
    return await service.reject_outbound_draft(request, draft_id)


@router.post("/api/web/session/{session_token}/outbound/approve-all")
async def outbound_approve_all(session_token: str, payload: ApproveAllRequest, request: Request = None):
    del session_token
    return await service.approve_all_outbound_drafts(request, payload.auto)


@router.post("/api/web/session/{session_token}/drafts/{draft_id}/send")
async def send_draft(session_token: str, draft_id: str, request: Request, payload: SendDraftRequest = None):
    del session_token
    payload = payload or SendDraftRequest()
    return await service.send_outbound_draft(
        request, draft_id, test_recipient=payload.test_recipient, test_recipient_name=payload.test_recipient_name,
    )


@router.post("/api/web/session/{session_token}/drafts/{draft_id}/schedule")
async def schedule_draft(session_token: str, draft_id: str, payload: ScheduleDraftRequest, request: Request):
    del session_token
    return await service.schedule_outbound_draft(request, draft_id, payload.send_at)


@router.post("/api/web/session/{session_token}/drafts/{draft_id}/cancel-schedule")
async def cancel_schedule_draft(session_token: str, draft_id: str, request: Request):
    del session_token
    return await service.cancel_outbound_draft_schedule(request, draft_id)


@router.post("/api/web/session/{session_token}/outbound/send")
async def outbound_send(session_token: str, payload: OutboundSendRequest, request: Request):
    del session_token
    if not payload.draft_id:
        raise HTTPException(status_code=400, detail="Draft id is required")
    return await service.send_outbound_draft(request, payload.draft_id)


@router.post("/api/web/session/{session_token}/outbound/schedule")
async def outbound_schedule(session_token: str, payload: OutboundScheduleRequest, request: Request):
    del session_token
    return await service.schedule_outbound_draft(request, payload.draft_id, payload.send_at)


@router.delete("/api/web/session/{session_token}/outbound/schedule/{schedule_id}")
async def outbound_cancel_schedule(
    session_token: str, schedule_id: str, provider_id: str = "", request: Request = None,
):
    del session_token
    return await service.cancel_outbound_draft_schedule(request, schedule_id, provider_id)


@router.get("/api/web/session/{session_token}/outbound/drafts")
async def outbound_list_drafts(session_token: str, request: Request, provider_id: str = ""):
    del session_token
    bearer_token, owner_id = await _authorized_owner(request)
    if provider_id and not service.provider_owned_by(provider_id, owner_id):
        raise HTTPException(status_code=404, detail="Provider not found")
    workspace_id = await workspace_access.resolve_legacy_workspace_id(request, owner_id)
    drafts = [
        service.hydrate_outbound_draft(draft, bearer_token, owner_id=owner_id)
        for draft in await asyncio.to_thread(
            load_drafts_only, owner_id, workspace_id=workspace_id,
        )
        if (draft.get("provider") or (draft.get("metadata") or {}).get("outbound_projection"))
        and (
            not provider_id
            or str(
                draft.get("provider")
                or (draft.get("metadata") or {}).get("outbound_projection", {}).get("provider_id")
                or ""
            ) == provider_id
        )
    ]
    return {"ok": True, "drafts": [draft.model_dump() for draft in drafts], "total": len(drafts)}


@router.get("/api/web/session/{session_token}/outbound/drafts/{draft_id}")
async def outbound_get_draft(session_token: str, draft_id: str, request: Request):
    del session_token
    bearer_token = identity_dependencies.web_session_token(request)
    _owner_id, _workspace_id, canonical, _draft = await service.require_canonical_outbound_draft(
        request, bearer_token, draft_id,
    )
    return {"ok": True, "draft": canonical}


@router.get("/api/web/session/{session_token}/outbound/history")
async def outbound_history(session_token: str, request: Request, provider_id: str = ""):
    del session_token
    _bearer_token, owner_id, workspace_id = await _authorized_owner_and_workspace(request)
    if provider_id and not service.provider_record_owned_by(provider_id, owner_id):
        raise HTTPException(status_code=404, detail="Provider not found")
    from services.persistence.launch.communication_persistence import list_outbound_history

    durable = await asyncio.to_thread(list_outbound_history, workspace_id, provider_id, 100)
    return {"ok": True, "history": [_history_dict(history) for history in durable]}


@router.get("/api/web/session/{session_token}/outbound/events")
async def outbound_events_endpoint(
    session_token: str, request: Request, provider_id: str = "", after: int = 0,
):
    del session_token
    _bearer_token, owner_id = await _authorized_owner(request)
    if provider_id and not service.provider_owned_by(provider_id, owner_id):
        raise HTTPException(status_code=404, detail="Provider not found")
    events = [
        event for event in get_events(provider_id=provider_id, after_sequence=after)
        if service.provider_owned_by(event.provider_id, owner_id)
    ]
    return {
        "ok": True,
        "events": [
            {
                "id": event.id,
                "event_type": event.event_type.value,
                "provider_id": event.provider_id,
                "message": event.message,
                "timestamp": event.timestamp,
                "sequence": event.sequence,
                "metadata": event.metadata,
            }
            for event in events
        ],
        "latest_sequence": latest_sequence(),
    }


@router.get("/api/web/session/{session_token}/outbound/drafts/{draft_id}/versions")
async def outbound_draft_versions(session_token: str, draft_id: str, request: Request):
    del session_token
    bearer_token = identity_dependencies.web_session_token(request)
    _owner_id, _workspace_id, canonical, _draft = await service.require_canonical_outbound_draft(
        request, bearer_token, draft_id,
    )
    versions = list((canonical.get("metadata") or {}).get("outbound_versions") or [])
    return {"ok": True, "versions": [{"draft_id": draft_id, **version} for version in versions]}
