"""Characterization tests for lifespan memory-consolidation task startup."""

from __future__ import annotations

import asyncio

import pytest

import main


class _StopAfterMemoryStartup(BaseException):
    """Stops lifespan after the memory-consolidation startup section."""


class _Task:
    def done(self) -> bool:
        return True


async def _enter_lifespan() -> None:
    async with main.lifespan(object()):
        pass


def _stop_after_conversation_rehydration(monkeypatch) -> None:
    from services.conversations.conversation_store import conversation_store

    monkeypatch.setattr(conversation_store, "reload", lambda: None)
    monkeypatch.setattr(conversation_store, "count_by_status", lambda: {})
    monkeypatch.setattr(
        main.app_lifespan,
        "rehydrate_communication_store",
        lambda: (_ for _ in ()).throw(_StopAfterMemoryStartup()),
    )


def _prepare_lifespan_before_memory_startup(monkeypatch) -> None:
    monkeypatch.setattr(main.app_lifespan, "begin_startup", lambda app: 0.0)
    monkeypatch.setattr(main.app_lifespan, "validate_startup_configuration", lambda: None)
    monkeypatch.setattr(main.app_lifespan, "initialize_runtime_services", lambda registry: None)
    monkeypatch.setattr(main.app_lifespan, "register_execution_observability", lambda: None)


def test_lifespan_creates_and_tracks_memory_consolidation_task(monkeypatch, caplog):
    provider = object()
    created: list[object] = []
    _prepare_lifespan_before_memory_startup(monkeypatch)
    _stop_after_conversation_rehydration(monkeypatch)
    monkeypatch.setattr("services.memory.memory_store.get_memory_provider", lambda: provider)

    async def consolidate(received_provider):
        assert received_provider is provider

    def capture_task(coroutine):
        coroutine.close()
        task = _Task()
        created.append(task)
        return task

    monkeypatch.setattr("services.memory.consolidation.consolidate_memories", consolidate)
    monkeypatch.setattr(main.app_lifespan.asyncio, "create_task", capture_task)

    with caplog.at_level("INFO", logger="loqi"):
        with pytest.raises(_StopAfterMemoryStartup):
            asyncio.run(_enter_lifespan())

    assert len(created) == 1
    assert "Memory consolidation startup task created" in caplog.text


def test_lifespan_logs_memory_consolidation_setup_failure_and_continues(monkeypatch, caplog):
    _prepare_lifespan_before_memory_startup(monkeypatch)
    _stop_after_conversation_rehydration(monkeypatch)
    monkeypatch.setattr(
        "services.memory.memory_store.get_memory_provider",
        lambda: (_ for _ in ()).throw(RuntimeError("memory unavailable")),
    )

    with caplog.at_level("WARNING", logger="loqi"):
        with pytest.raises(_StopAfterMemoryStartup):
            asyncio.run(_enter_lifespan())

    assert "Memory consolidation startup failed: memory unavailable" in caplog.text
