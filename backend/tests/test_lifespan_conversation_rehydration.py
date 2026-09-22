"""Characterization tests for the durable Inbox startup gate."""

from __future__ import annotations

import asyncio

import pytest

import main


class _StopAfterConversationReload(BaseException):
    """Stops lifespan after the conversation-store startup section."""


async def _enter_lifespan() -> None:
    async with main.lifespan(object()):
        pass


def _prepare_lifespan_before_conversation_reload(monkeypatch) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(main.app_lifespan, "begin_startup", lambda app: 0.0)
    monkeypatch.setattr(main.app_lifespan, "validate_startup_configuration", lambda: None)
    monkeypatch.setattr(main.app_lifespan, "initialize_runtime_services", lambda registry: None)
    monkeypatch.setattr(main.app_lifespan, "register_execution_observability", lambda: None)
    monkeypatch.setattr(main.app_lifespan, "start_memory_consolidation", lambda tasks: None)
    monkeypatch.setattr(
        main.app_lifespan,
        "rehydrate_communication_store",
        lambda: calls.append("communication") or (_ for _ in ()).throw(_StopAfterConversationReload()),
    )
    return calls


def test_lifespan_reloads_durable_conversations_before_communication_rehydration(monkeypatch, caplog):
    from services.conversations.conversation_store import conversation_store

    calls = _prepare_lifespan_before_conversation_reload(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("APP_ENV", raising=False)
    from services.conversations.conversation_store import ConversationStoreRehydrationState

    monkeypatch.setattr(
        conversation_store,
        "reload",
        lambda: calls.append("conversations") or ConversationStoreRehydrationState.LOADED,
    )
    monkeypatch.setattr(conversation_store, "count_by_status", lambda: {"active": 2})

    with caplog.at_level("INFO", logger="loqi"):
        with pytest.raises(_StopAfterConversationReload):
            asyncio.run(_enter_lifespan())

    assert calls == ["conversations", "communication"]
    assert "Conversation store rehydrated state=loaded conversations=2" in caplog.text
    monkeypatch.undo()


def test_lifespan_logs_and_continues_when_development_rehydration_fails(monkeypatch, caplog):
    from services.conversations.conversation_store import conversation_store

    calls = _prepare_lifespan_before_conversation_reload(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setattr(
        conversation_store,
        "reload",
        lambda: (_ for _ in ()).throw(RuntimeError("snapshot unavailable")),
    )

    with caplog.at_level("WARNING", logger="loqi"):
        with pytest.raises(_StopAfterConversationReload):
            asyncio.run(_enter_lifespan())

    assert calls == ["communication"]
    assert "Conversation store rehydration failed: snapshot unavailable" in caplog.text
    monkeypatch.undo()


def test_lifespan_fails_closed_when_production_rehydration_fails(monkeypatch):
    from services.conversations.conversation_store import conversation_store

    calls = _prepare_lifespan_before_conversation_reload(monkeypatch)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setattr(
        conversation_store,
        "reload",
        lambda: (_ for _ in ()).throw(RuntimeError("snapshot unavailable")),
    )

    with pytest.raises(RuntimeError, match="Durable Inbox persistence is required in production") as error:
        asyncio.run(_enter_lifespan())

    assert isinstance(error.value.__cause__, RuntimeError)
    assert str(error.value.__cause__) == "snapshot unavailable"
    assert calls == []
    monkeypatch.undo()


def test_lifespan_continues_in_production_when_conversation_read_is_temporarily_unavailable(monkeypatch, caplog):
    from services.conversations.conversation_store import (
        ConversationStoreRehydrationState,
        conversation_store,
    )

    calls = _prepare_lifespan_before_conversation_reload(monkeypatch)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setattr(
        conversation_store,
        "reload",
        lambda: ConversationStoreRehydrationState.TEMPORARILY_UNAVAILABLE,
    )

    with caplog.at_level("WARNING", logger="loqi"):
        with pytest.raises(_StopAfterConversationReload):
            asyncio.run(_enter_lifespan())

    assert calls == ["communication"]
    assert "Conversation store rehydration deferred" in caplog.text
    monkeypatch.undo()
