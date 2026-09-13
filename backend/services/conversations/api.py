"""Read-only HTTP routes for authenticated conversation access."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from services.conversation_engine import ConversationEngine
from services.copilot import service as copilot_service
from services.conversations.conversation_store import conversation_owned_by, conversation_store
from services.conversations import service as conversation_service
from services.conversations import compatibility
from services.identity import dependencies as identity_dependencies


router = APIRouter(tags=["Conversations"])
engine = ConversationEngine()


class CreateWebSessionRequest(BaseModel):
    display_name: str | None = None


class CopilotContextModel(BaseModel):
    current_page: str | None = None
    page_context: dict | None = None
    available_actions: list[str] | None = None
    message_history: list[dict] | None = None
    conversation_id: str | None = None
    request_id: str | None = None
    active_search: dict | None = None


class SendWebMessageRequest(BaseModel):
    text: str
    copilot: CopilotContextModel | None = None


class SendConversationReplyRequest(BaseModel):
    body: str
    thread_id: str = ""
    reply_to_message_id: str = ""
    from_email: str = ""
    to_email: str = ""
    test_recipient: str = ""
    test_recipient_name: str = ""


class SelectLeadRequest(BaseModel):
    index: int


class PreviewLeadRequest(BaseModel):
    index: int


async def _authenticated_owner(request: Request | None) -> str:
    """Resolve the existing web-session owner for a conversation read."""
    if request is None:
        return ""
    owner_id, _ = await identity_dependencies.resolve_web_session(request)
    return owner_id


@router.post("/api/web/session")
async def create_web_session_route(payload: CreateWebSessionRequest, request: Request):
    """Create a legacy web session through the canonical compatibility use case."""
    try:
        return await conversation_service.create_legacy_web_session(
            request=request,
            display_name=payload.display_name,
            engine=engine,
        )
    except ValueError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@router.get("/api/web/session/{session_token}")
async def get_web_session_route(session_token: str, request: Request = None):
    """Read a request-bound web session; the URL token is not authority."""
    del session_token
    return await conversation_service.read_legacy_web_session(request=request, engine=engine)


@router.get("/api/web/session/{session_token}/messages")
async def get_web_session_messages_route(session_token: str, request: Request = None):
    """Read messages for the request-bound legacy web session."""
    del session_token
    return await conversation_service.read_legacy_web_session_messages(request=request, engine=engine)


@router.post("/api/web/session/{session_token}/messages")
async def post_web_session_message(
    session_token: str,
    payload: SendWebMessageRequest,
    request: Request,
):
    """Dispatch one web message to the legacy or canonical Copilot boundary."""
    del session_token
    if payload.copilot is None:
        return await conversation_service.handle_legacy_web_message(
            request=request,
            text=payload.text,
            engine=engine,
        )

    resolved_token, summary, _created = await conversation_service.resolve_legacy_web_message_session(
        request=request,
        engine=engine,
    )
    prepared_turn = await copilot_service.prepare_copilot_turn(
        request=request,
        session_token=resolved_token,
        text=payload.text,
        current_page=payload.copilot.current_page,
        page_context=payload.copilot.page_context,
        message_history=payload.copilot.message_history,
        conversation_id=payload.copilot.conversation_id,
        active_search=payload.copilot.active_search,
    )
    return await copilot_service.execute_prepared_copilot_turn(
        prepared=prepared_turn,
        user_text=payload.text,
        copilot_context=payload.copilot.model_dump(),
        legacy_user_id=summary.get("user_id"),
        request_id=payload.copilot.request_id,
        request=request,
    )


@router.post("/api/web/session/{session_token}/select-lead")
async def select_lead_endpoint(
    session_token: str,
    payload: SelectLeadRequest,
    request: Request = None,
):
    """Adapt legacy lead-card selection to the canonical conversations use case."""
    del session_token
    resolved_token = identity_dependencies.web_session_token(request)
    user = compatibility.get_web_session(resolved_token)
    if user is None:
        raise HTTPException(status_code=404, detail="Session not found")
    workflow_session_id = compatibility.ensure_workflow_session(
        user_id=user["id"],
        channel="web",
        session_key=resolved_token,
    )
    result = conversation_service.select_legacy_workflow_lead_and_draft(
        user_id=user["id"],
        lead_index=payload.index,
        workflow_session_id=workflow_session_id,
        session_token=resolved_token,
    )
    if not result.get("ok"):
        raise HTTPException(
            status_code=400,
            detail=result.get("messages", [{}])[0].get("text", "Selection failed"),
        )
    return {"ok": True, "messages": result.get("messages", [])}


@router.post("/api/web/session/{session_token}/preview-lead")
async def preview_lead_endpoint(
    session_token: str,
    payload: PreviewLeadRequest,
    request: Request = None,
):
    """Adapt legacy lead-card preview to the canonical conversations use case."""
    del session_token
    resolved_token = identity_dependencies.web_session_token(request)
    user = compatibility.get_web_session(resolved_token)
    if user is None:
        raise HTTPException(status_code=404, detail="Session not found")
    result = conversation_service.preview_legacy_workflow_lead_intelligence(
        user_id=user["id"],
        lead_index=payload.index,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Preview failed"))
    return {"ok": True, "lead_intelligence": result.get("lead_intelligence")}


def _owned_conversation(conversation_id: str, owner_id: str):
    """Load one conversation only when it is attributable to this owner."""
    conversation = conversation_store.get_conversation(conversation_id)
    if conversation is None or not conversation_owned_by(conversation, owner_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@router.get("/api/web/session/{session_token}/conversations")
async def list_conversations_route(session_token: str, request: Request = None):
    """List only conversations provably owned by the authenticated user."""
    del session_token
    owner_id = await _authenticated_owner(request)
    conversations = conversation_store.list_conversations(limit=1000)
    return {
        "ok": True,
        "conversations": [
            conversation.to_dict()
            for conversation in conversations
            if conversation_owned_by(conversation, owner_id)
        ],
    }


@router.get("/api/web/session/{session_token}/conversations/{conversation_id}")
async def get_conversation_route(
    session_token: str,
    conversation_id: str,
    request: Request = None,
):
    """Return one owner-scoped conversation."""
    del session_token
    conversation = _owned_conversation(conversation_id, await _authenticated_owner(request))
    return {"ok": True, "conversation": conversation.to_dict()}


@router.get("/api/web/session/{session_token}/conversations/{conversation_id}/timeline")
async def get_conversation_timeline_route(
    session_token: str,
    conversation_id: str,
    request: Request = None,
):
    """Return the persisted timeline for one owner-scoped conversation."""
    del session_token
    _owned_conversation(conversation_id, await _authenticated_owner(request))
    return {
        "ok": True,
        "events": [event.to_dict() for event in conversation_store.get_timeline(conversation_id)],
    }


@router.get("/api/web/session/{session_token}/conversations/{conversation_id}/messages")
async def get_conversation_messages_route(
    session_token: str,
    conversation_id: str,
    request: Request = None,
):
    """Return persisted messages for one owner-scoped conversation."""
    del session_token
    _owned_conversation(conversation_id, await _authenticated_owner(request))
    return {
        "ok": True,
        "messages": [
            message.to_dict()
            for message in conversation_store.get_messages_for_conversation(conversation_id)
        ],
    }


async def _owned_conversation_or_404(conversation_id: str, request: Request | None):
    owner_id = await _authenticated_owner(request)
    conversation = conversation_service.owned_conversation(conversation_id, owner_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return owner_id


@router.get("/api/web/session/{session_token}/conversations/{conversation_id}/reasoning")
async def get_conversation_reasoning_route(session_token: str, conversation_id: str, request: Request = None):
    del session_token
    await _owned_conversation_or_404(conversation_id, request)
    return conversation_service.conversation_reasoning(conversation_id)


@router.post("/api/web/session/{session_token}/conversations/{conversation_id}/plan")
async def get_conversation_plan_route(session_token: str, conversation_id: str, request: Request = None):
    del session_token
    await _owned_conversation_or_404(conversation_id, request)
    return conversation_service.conversation_plan(conversation_id)


@router.post("/api/web/session/{session_token}/conversations/{conversation_id}/generate-reply")
async def generate_reply_route(session_token: str, conversation_id: str, body: dict = None, request: Request = None):
    del session_token
    owner_id = await _owned_conversation_or_404(conversation_id, request)
    return await conversation_service.generate_reply(conversation_id, owner_id, body or {})


@router.post("/api/web/session/{session_token}/conversations/{conversation_id}/reply")
async def send_conversation_reply_route(
    session_token: str,
    conversation_id: str,
    body: SendConversationReplyRequest | None = None,
    request: Request = None,
):
    del session_token
    if request is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    owner_id = await _authenticated_owner(request)
    return await conversation_service.send_reply(
        conversation_id, owner_id, body or SendConversationReplyRequest(body=""),
    )


@router.post("/api/web/session/{session_token}/conversations/{conversation_id}/follow-up")
async def send_conversation_followup_route(
    session_token: str,
    conversation_id: str,
    body: SendConversationReplyRequest | None = None,
    request: Request = None,
):
    del session_token
    if request is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    owner_id = await _authenticated_owner(request)
    return await conversation_service.send_follow_up(
        conversation_id, owner_id, body or SendConversationReplyRequest(body=""),
    )
