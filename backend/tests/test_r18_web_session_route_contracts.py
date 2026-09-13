"""R18-0 characterization for the current legacy web-session adapters.

These tests pin externally visible route behavior before the large web-session
and Copilot extraction.  They deliberately exercise the currently registered
``main`` routes rather than a future service interface.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import HTTPException

import main as main_module
import services.conversations.api as conversations_api
import services.conversations.service as conversations_service


def test_create_session_invalid_bearer_falls_back_to_anonymous_contract(monkeypatch, client):
    """A rejected optional bearer header still creates an anonymous session."""
    captured: dict[str, object] = {}

    async def rejected_auth(_request):
        raise HTTPException(status_code=401, detail="Invalid session")

    def create_web_session(*, display_name=None, user_id=None):
        captured["display_name"] = display_name
        captured["user_id"] = user_id
        return {
            "ok": True,
            "session_token": "anonymous-session",
            "user_id": "web:anonymous",
            "display_name": display_name,
            "gmail_connected": False,
            "initial_messages": [],
        }

    monkeypatch.setattr(
        "services.identity.dependencies.get_current_auth", rejected_auth,
    )
    monkeypatch.setattr(conversations_api.engine, "create_web_session", create_web_session)

    response = client.post(
        "/api/web/session",
        json={"display_name": "Guest"},
        headers={"Authorization": "Bearer invalid"},
    )

    assert response.status_code == 200
    assert captured == {"display_name": "Guest", "user_id": None}
    assert response.json() == {
        "ok": True,
        "session_token": "anonymous-session",
        "user_id": "web:anonymous",
        "display_name": "Guest",
        "gmail_connected": False,
        "initial_messages": [],
    }


def test_web_session_read_routes_use_bound_token_and_preserve_envelopes(monkeypatch, client):
    """Path tokens are transport-only; reads resolve the bound request token."""
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        main_module.identity_dependencies,
        "web_session_token",
        lambda _request: "bound-session",
    )
    monkeypatch.setattr(
        conversations_api.engine,
        "get_web_session_summary",
        lambda token: calls.append(("summary", token)) or {"ok": True, "session_token": token},
    )
    monkeypatch.setattr(
        conversations_api.engine,
        "list_messages",
        lambda **kwargs: calls.append(("messages", kwargs)) or [{"role": "assistant", "text": "Hi"}],
    )

    summary = client.get("/api/web/session/path-token")
    messages = client.get("/api/web/session/path-token/messages")

    assert summary.status_code == 200
    assert summary.json() == {"ok": True, "session_token": "bound-session"}
    assert messages.status_code == 200
    assert messages.json() == {
        "ok": True,
        "messages": [{"role": "assistant", "text": "Hi"}],
    }
    assert calls == [
        ("summary", "bound-session"),
        ("messages", {"channel": "web", "external_user_id": "bound-session"}),
    ]


def test_web_session_summary_missing_is_404_with_frozen_error(monkeypatch, client):
    monkeypatch.setattr(main_module.identity_dependencies, "web_session_token", lambda _request: "bound-session")
    monkeypatch.setattr(conversations_api.engine, "get_web_session_summary", lambda _token: None)

    response = client.get("/api/web/session/path-token")

    assert response.status_code == 404
    assert response.json() == {"detail": "Session not found"}


def test_legacy_message_branch_returns_engine_result_and_publishes_received_event(monkeypatch):
    """Non-Copilot web messages retain the legacy engine response and event."""
    published: list[tuple[object, ...]] = []
    monkeypatch.setattr(main_module.identity_dependencies, "web_session_token", lambda _request: "bound-session")
    monkeypatch.setattr(
        main_module.engine,
        "get_web_session_summary",
        lambda _token: {"display_name": "Ada", "user_id": "legacy-user"},
    )
    monkeypatch.setattr(
        main_module.engine,
        "handle_message",
        lambda **kwargs: {"ok": True, "messages": [{"role": "assistant", "text": "Legacy reply"}]},
    )
    monkeypatch.setattr(conversations_service, "publish", lambda *args, **kwargs: published.append(args))

    result = asyncio.run(
        conversations_api.post_web_session_message(
            "path-token",
            conversations_api.SendWebMessageRequest(text="hello"),
            SimpleNamespace(headers=SimpleNamespace(get=lambda _key, default="": default)),
        )
    )

    assert result == {"ok": True, "messages": [{"role": "assistant", "text": "Legacy reply"}]}
    assert published == [
        (
            "bound-session",
            main_module.WMEventType.MESSAGE_RECEIVED,
            {"from": "Ada", "text_preview": "hello", "channel": "web"},
        )
    ]


def test_legacy_message_bootstrap_creates_anonymous_session_without_outer_event(monkeypatch):
    """The historic bootstrap early-return deliberately does not publish MESSAGE_RECEIVED."""
    created: list[dict[str, object]] = []
    published: list[tuple[object, ...]] = []
    summaries = iter([None, {"display_name": "web-user", "user_id": "web:anonymous"}])

    monkeypatch.setattr(main_module.identity_dependencies, "web_session_token", lambda _request: "missing-token")
    monkeypatch.setattr(main_module.engine, "get_web_session_summary", lambda _token: next(summaries))
    monkeypatch.setattr(
        main_module.engine,
        "create_web_session",
        lambda **kwargs: created.append(kwargs) or {"session_token": "created-token"},
    )
    monkeypatch.setattr(
        main_module.engine,
        "handle_message",
        lambda **kwargs: {"ok": True, "messages": [{"role": "assistant", "text": "Welcome"}]},
    )
    monkeypatch.setattr(conversations_service, "publish", lambda *args, **kwargs: published.append(args))

    result = asyncio.run(
        conversations_api.post_web_session_message(
            "path-token",
            conversations_api.SendWebMessageRequest(text="hello"),
            SimpleNamespace(headers=SimpleNamespace(get=lambda _key, default="": default)),
        )
    )

    assert created == [{"display_name": "web-user", "user_id": None}]
    assert result == {"ok": True, "messages": [{"role": "assistant", "text": "Welcome"}]}
    assert published == []
