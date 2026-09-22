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
        "start_conversation_rehydration",
        lambda _tasks: calls.append("conversations"),
    )
    monkeypatch.setattr(
        main.app_lifespan,
        "rehydrate_communication_store",
        lambda: calls.append("communication") or (_ for _ in ()).throw(_StopAfterConversationReload()),
    )
    return calls


def test_lifespan_starts_conversation_rehydration_before_communication_services(monkeypatch):
    calls = _prepare_lifespan_before_conversation_reload(monkeypatch)
    with pytest.raises(_StopAfterConversationReload):
        asyncio.run(_enter_lifespan())

    assert calls == ["conversations", "communication"]
    monkeypatch.undo()


@pytest.mark.asyncio
async def test_background_rehydration_logs_failure_without_crashing_lifespan(monkeypatch, caplog):
    import app.lifespan as lifespan

    def fail() -> None:
        raise RuntimeError("corrupt snapshot")

    monkeypatch.setattr(lifespan, "rehydrate_conversation_store", fail)
    tasks: list[asyncio.Task] = []

    with caplog.at_level("ERROR", logger="loqi"):
        lifespan.start_conversation_rehydration(tasks)
        await tasks[0]

    assert "Conversation store background rehydration failed error_type=RuntimeError" in caplog.text
