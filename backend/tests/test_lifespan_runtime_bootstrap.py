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
        "services.platform.migration.apply_migrations",
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
        "services.workflows.recovery.recover_all",
        lambda: {"total_recovered": 1, "resumed": 1},
    )

    with caplog.at_level("INFO", logger="loqi"):
        main.app_lifespan.recover_persisted_workflows()

    assert "Workflow recovery: {'total_recovered': 1, 'resumed': 1}" in caplog.text


@pytest.mark.asyncio
async def test_generation_recovery_schedules_durable_jobs_without_blocking_startup(monkeypatch, caplog):
    async def recover_draft_batches():
        return 2

    async def recover_strategy_jobs():
        return 1

    monkeypatch.setattr(
        "services.drafts.service.reconcile_stale_draft_batch_jobs",
        recover_draft_batches,
    )
    monkeypatch.setattr(
        "services.campaigns.service.reconcile_stale_strategy_jobs",
        recover_strategy_jobs,
    )
    background_tasks = []

    with caplog.at_level("INFO", logger="loqi"):
        main.app_lifespan.start_generation_recovery(background_tasks)
        assert len(background_tasks) == 2
        await asyncio.gather(*background_tasks)

    assert "Resumed 2 interrupted draft generation(s) after restart" in caplog.text
    assert "Reconciled 1 interrupted strategy generation(s) after restart" in caplog.text


@pytest.mark.asyncio
async def test_launch_backfill_runs_in_background_and_logs_completion(monkeypatch, caplog):
    monkeypatch.setattr("services.persistence.launch.backfill_all", lambda: 3)
    background_tasks = []

    with caplog.at_level("INFO", logger="loqi"):
        main.app_lifespan.start_launch_backfill(background_tasks)
        assert len(background_tasks) == 1
        await background_tasks[0]

    assert "backfill startup task completed sessions_marked=3" in caplog.text


@pytest.mark.asyncio
async def test_launch_backfill_logs_background_failure(monkeypatch, caplog):
    def fail_backfill():
        raise RuntimeError("backfill unavailable")

    monkeypatch.setattr("services.persistence.launch.backfill_all", fail_backfill)
    background_tasks = []

    with caplog.at_level("ERROR", logger="loqi"):
        main.app_lifespan.start_launch_backfill(background_tasks)
        with pytest.raises(RuntimeError, match="backfill unavailable"):
            await background_tasks[0]

    assert "backfill startup task raised error_type=RuntimeError" in caplog.text


def test_abandoned_registration_cleanup_remains_fail_closed_when_disabled(monkeypatch, caplog):
    monkeypatch.setattr(
        "services.identity.registration_cleanup.abandoned_cleanup_runtime_enabled",
        lambda: (False, "not an explicitly production environment"),
    )
    monkeypatch.setattr(
        "services.identity.registration_cleanup.resolve_automatic_cleanup_client",
        lambda: (_ for _ in ()).throw(AssertionError("client resolution must not run")),
    )
    background_tasks = []

    with caplog.at_level("INFO", logger="loqi"):
        main.app_lifespan.start_abandoned_registration_cleanup(background_tasks)

    assert background_tasks == []
    assert "Abandoned-registration cleanup loop disabled: not an explicitly production environment" in caplog.text


@pytest.mark.asyncio
async def test_abandoned_registration_cleanup_waits_before_first_mutation(monkeypatch, caplog):
    client = object()
    reports = []
    sleep_calls = []

    async def controlled_sleep(interval):
        sleep_calls.append(interval)
        if len(sleep_calls) == 1:
            return
        raise asyncio.CancelledError

    def run_cleanup(*, dry_run, client):
        reports.append((dry_run, client))
        return {
            "scanned": 3,
            "cleaned_emails": 1,
            "cleaned_rows": 2,
            "skipped": 0,
            "failures": 0,
        }

    monkeypatch.setattr(
        "services.identity.registration_cleanup.abandoned_cleanup_runtime_enabled",
        lambda: (True, "enabled"),
    )
    monkeypatch.setattr(
        "services.identity.registration_cleanup.resolve_automatic_cleanup_client",
        lambda: client,
    )
    monkeypatch.setattr("services.identity.registration_cleanup.run_abandoned_cleanup", run_cleanup)
    monkeypatch.setattr(main.app_lifespan, "_abandoned_registration_cleanup_interval", lambda: 60)
    monkeypatch.setattr(main.app_lifespan.asyncio, "sleep", controlled_sleep)
    background_tasks = []

    with caplog.at_level("INFO", logger="loqi"):
        main.app_lifespan.start_abandoned_registration_cleanup(background_tasks)
        assert len(background_tasks) == 1
        with pytest.raises(asyncio.CancelledError):
            await background_tasks[0]

    assert sleep_calls == [60, 60]
    assert reports == [(False, client)]
    assert "Abandoned-registration cleanup loop started (interval=60s)" in caplog.text
    assert "scanned=3 cleaned_emails=1 cleaned_rows=2 skipped=0 failures=0" in caplog.text


@pytest.mark.asyncio
async def test_shutdown_runtime_stops_integrations_before_cancelling_tasks(monkeypatch):
    events: list[str] = []

    class InboxSyncEngine:
        async def stop(self):
            events.append("inbox")

    async def close_redis():
        events.append("redis")

    async def wait_forever():
        await asyncio.Event().wait()

    monkeypatch.setattr("services.platform.lifecycle.set_shutting_down", lambda: events.append("state"))
    monkeypatch.setattr("services.platform.redis_client.close", close_redis)
    monkeypatch.setenv("SHUTDOWN_TIMEOUT_SECONDS", "0.1")
    background_task = asyncio.create_task(wait_forever())
    simulator_task = asyncio.create_task(wait_forever())
    await asyncio.sleep(0)

    await main.app_lifespan.shutdown_runtime(
        [background_task],
        InboxSyncEngine(),
        simulator_task,
    )

    assert events == ["state", "redis", "inbox"]
    assert background_task.cancelled()
    assert simulator_task.cancelled()
