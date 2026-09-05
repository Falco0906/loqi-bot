"""Characterization tests for migration-tolerant runtime registration."""

from __future__ import annotations

import asyncio

import pytest

import main
from services.execution import AdapterRegistry
from services.planner.planning_models import TaskType


class _StopAfterRuntimeRegistration(Exception):
    """Stops lifespan execution immediately after runtime registration."""


async def _enter_lifespan() -> None:
    async with main.lifespan(object()):
        pass


def test_lifespan_warns_for_migration_failure_but_registers_runtime_dependencies(monkeypatch, caplog):
    calls: list[str] = []
    monkeypatch.setattr(main.app_lifespan, "begin_startup", lambda app: 0.0)
    monkeypatch.setattr(main.app_lifespan, "validate_startup_configuration", lambda: None)
    monkeypatch.setattr(
        "services.migration.apply_migrations",
        lambda: (_ for _ in ()).throw(RuntimeError("migration unavailable")),
    )
    monkeypatch.setattr(main.app_lifespan, "register_outbound_providers", lambda: calls.append("outbound"))
    monkeypatch.setattr(main.app_lifespan, "register_execution_adapters", lambda registry: calls.append("execution"))
    monkeypatch.setattr(
        "services.execution.adapter_registry_resolver.init_planner_registry",
        lambda registry: calls.append("planner"),
    )
    monkeypatch.setattr(
        main.app_lifespan,
        "register_execution_observability",
        lambda: (_ for _ in ()).throw(_StopAfterRuntimeRegistration()),
    )

    with caplog.at_level("INFO", logger="loqi"):
        with pytest.raises(_StopAfterRuntimeRegistration):
            asyncio.run(_enter_lifespan())

    assert calls == ["outbound", "execution", "planner"]
    assert "Migration check failed: migration unavailable" in caplog.text
    assert "Job engine initialized" in caplog.text


def test_execution_adapter_registration_keeps_the_registered_task_types(monkeypatch):
    registry = AdapterRegistry()
    monkeypatch.setattr(main, "_execution_adapter_registry", registry)

    main.app_lifespan.register_execution_adapters(registry)

    for task_type in (
        TaskType.SEND_EMAIL,
        TaskType.CALENDAR_LIST_EVENTS,
        TaskType.ANALYZE_REPLY,
        TaskType.FIND_CONTACT,
        TaskType.STORE_MEMORY,
    ):
        assert registry.resolve(task_type) is not None


def test_outbound_provider_registration_keeps_gmail_provider(monkeypatch):
    registered: list[type] = []
    monkeypatch.setattr(
        "services.outbound.outbound_registry.register_outbound_provider",
        registered.append,
    )

    main.app_lifespan.register_outbound_providers()

    assert [provider.__name__ for provider in registered] == ["GmailOutboundProvider"]


def test_recover_persisted_workflows_logs_nonempty_recovery(monkeypatch, caplog):
    monkeypatch.setattr(
        "services.workflow_recovery.recover_all",
        lambda: {"total_recovered": 1, "resumed": 1},
    )

    with caplog.at_level("INFO", logger="loqi"):
        main.app_lifespan.recover_persisted_workflows()

    assert "Workflow recovery: {'total_recovered': 1, 'resumed': 1}" in caplog.text
