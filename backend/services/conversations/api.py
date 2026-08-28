"""Read-only HTTP routes for authenticated conversation access."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from services.conversations.conversation_store import conversation_owned_by, conversation_store
from services.identity import dependencies as identity_dependencies


router = APIRouter(tags=["Conversations"])


async def _authenticated_owner(request: Request | None) -> str:
    """Resolve the existing web-session owner for a conversation read."""
    if request is None:
        return ""
    owner_id, _ = await identity_dependencies.resolve_web_session(request)
    return owner_id


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
