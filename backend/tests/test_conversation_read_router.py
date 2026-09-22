"""Characterization guards for the extracted Conversation read router."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import main
import services.conversations.api as conversation_api


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/api/web/session/_/conversations",
        "headers": [(b"authorization", b"Bearer session-token")],
    })


async def _owner(_request: Request) -> tuple[str, str]:
    return "owner-1", "session-token"


def _conversation(conversation_id: str, owner_id: str = "owner-1"):
    return SimpleNamespace(
        conversation_id=conversation_id,
        owner_id=owner_id,
        provider_id="",
        to_dict=lambda: {"conversation_id": conversation_id, "owner_id": owner_id},
    )


def _configure_store(monkeypatch, conversations: list[object]) -> None:
    by_id = {conversation.conversation_id: conversation for conversation in conversations}
    monkeypatch.setattr(conversation_api.identity_dependencies, "resolve_web_session", _owner)
    monkeypatch.setattr(
        conversation_api.conversation_store,
        "list_conversations",
        lambda limit=50: list(conversations),
    )
    monkeypatch.setattr(
        conversation_api.conversation_store,
        "get_conversation",
        by_id.get,
    )
    monkeypatch.setattr(conversation_api.conversation_store, "get_timeline", lambda _id: [])
    monkeypatch.setattr(
        conversation_api.conversation_store,
        "get_messages_for_conversation",
        lambda _id: [],
    )


async def test_conversation_read_router_preserves_routes_and_top_level_shapes(monkeypatch):
    expected_paths = [
        "/api/web/session",
        "/api/web/session/{session_token}",
            "/api/web/session/{session_token}/messages",
            "/api/web/session/{session_token}/messages",
            "/api/web/session/{session_token}/select-lead",
            "/api/web/session/{session_token}/preview-lead",
            "/api/web/session/{session_token}/conversations",
        "/api/web/session/{session_token}/conversations/{conversation_id}",
        "/api/web/session/{session_token}/conversations/{conversation_id}/timeline",
        "/api/web/session/{session_token}/conversations/{conversation_id}/messages",
        "/api/web/session/{session_token}/conversations/{conversation_id}/reasoning",
        "/api/web/session/{session_token}/conversations/{conversation_id}/plan",
        "/api/web/session/{session_token}/conversations/{conversation_id}/generate-reply",
        "/api/web/session/{session_token}/conversations/{conversation_id}/reply",
        "/api/web/session/{session_token}/conversations/{conversation_id}/follow-up",
    ]
    assert [route.path for route in conversation_api.router.routes] == expected_paths
    assert any(
        getattr(route, "original_router", None) is conversation_api.router
        for route in main.app.routes
    )

    conversation = _conversation("conversation-1")
    _configure_store(monkeypatch, [conversation, _conversation("foreign", "owner-2")])

    listed = await conversation_api.list_conversations_route("_", _request())
    detail = await conversation_api.get_conversation_route("_", "conversation-1", _request())
    timeline = await conversation_api.get_conversation_timeline_route("_", "conversation-1", _request())
    messages = await conversation_api.get_conversation_messages_route("_", "conversation-1", _request())

    assert set(listed) == {"ok", "conversations"}
    assert listed["conversations"] == [{"conversation_id": "conversation-1", "owner_id": "owner-1"}]
    assert set(detail) == {"ok", "conversation"}
    assert set(timeline) == {"ok", "events"}
    assert set(messages) == {"ok", "messages"}


@pytest.mark.parametrize(
    "route",
    [
        conversation_api.get_conversation_route,
        conversation_api.get_conversation_timeline_route,
        conversation_api.get_conversation_messages_route,
    ],
)
async def test_conversation_read_router_preserves_not_found_contract(monkeypatch, route):
    _configure_store(monkeypatch, [])

    with pytest.raises(HTTPException) as error:
        await route("_", "missing", _request())

    assert error.value.status_code == 404
    assert error.value.detail == "Conversation not found"


async def test_unavailable_conversation_persistence_is_an_explicit_503():
    from services.conversations.conversation_store import ConversationPersistenceUnavailable

    response = await main.conversation_persistence_unavailable_handler(
        _request(),
        ConversationPersistenceUnavailable("durable state unavailable"),
    )

    assert response.status_code == 503
    assert response.body == b'{"detail":"Conversation data is temporarily unavailable"}'
