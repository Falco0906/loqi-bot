"""Low-risk application startup operations used by the composition root."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any


log = logging.getLogger("loqi")


def begin_startup(app: Any) -> float:
    """Mark startup and register workflows that must exist before requests."""
    from services.lifecycle import set_starting
    from services.operations import log_config_warnings, set_startup_time, startup_diagnostics
    from services.outbound import service as outbound_service
    from workflow_dispatcher import register_workflows

    set_starting()
    startup_started = time.time()
    log.info("application_starting")
    set_startup_time()
    log_config_warnings()
    startup_diagnostics(app)
    register_workflows()
    outbound_service.register_scheduled_send_workflow()
    return startup_started


def validate_startup_configuration() -> None:
    """Fail startup when required runtime configuration is invalid."""
    from services.config_validation import assert_valid_startup_config, validate_config
    from services.lifecycle import set_failed

    try:
        _errors, warnings = validate_config()
        for warning in warnings:
            log.warning("config: %s", warning)
        assert_valid_startup_config()
        log.info("Configuration validated successfully")
    except RuntimeError as error:
        log.error("Configuration validation failed — refusing to start: %s", error)
        set_failed()
        raise


def register_execution_observability() -> None:
    """Subscribe the production execution pipeline observers."""
    from services.execution.execution_pipeline import get_pipeline
    from services.execution.logging_subscriber import LoggingSubscriber
    from services.execution.metrics_collector import MetricsCollector
    from services.memory.subscriber import MemorySubscriber

    pipeline = get_pipeline()
    pipeline.event_bus.subscribe(LoggingSubscriber())
    pipeline.event_bus.subscribe(MetricsCollector())
    log.info("Execution engine logging + metrics subscribers registered")
    pipeline.event_bus.subscribe(MemorySubscriber())
    log.info("Memory subscriber registered")


def rehydrate_communication_store() -> None:
    """Restore communication cursors and thread mappings before workers start."""
    try:
        from services.communication.communication_store import store as communication_store

        communication_store.load_state()
    except Exception as error:  # noqa: BLE001 -- startup remains available without this cache
        log.warning("Communication store rehydration failed: %s", error)


async def start_communication_background_services() -> tuple[Any | None, asyncio.Task[Any] | None]:
    """Start Inbox sync and the optional development reply simulator."""
    inbox_sync_engine = None
    try:
        from services.communication.inbox_sync_engine import inbox_sync_engine as configured_inbox_sync_engine

        inbox_sync_engine = configured_inbox_sync_engine
        await inbox_sync_engine.start()
    except Exception as error:  # noqa: BLE001 -- Inbox sync reports its own recovery state
        log.warning("Inbox sync engine startup failed: %s", error)

    simulator_task = None
    try:
        from services.communication import reply_simulator

        if reply_simulator.is_enabled():
            simulator_task = reply_simulator.start_scheduler()
            log.info(
                "[sim] Reply simulator enabled (SIMULATE_REPLIES=true), pending=%d",
                reply_simulator.pending_count(),
            )
    except Exception as error:  # noqa: BLE001 -- simulator is development-only
        log.warning("Reply simulator startup failed: %s", error)
    return inbox_sync_engine, simulator_task


async def recover_search_and_start_due_jobs(background_tasks: list[asyncio.Task[Any]]) -> None:
    """Reconcile durable Discovery jobs and start delayed-job polling."""
    try:
        from services.discovery.service import reconcile_stale_search_jobs

        recovered_jobs = await reconcile_stale_search_jobs()
        if recovered_jobs:
            log.info("Reconciled %d interrupted search job(s) after restart", recovered_jobs)
    except Exception as error:  # noqa: BLE001 -- durable job status remains inspectable
        log.warning("Search job recovery sweep failed: %s", error)

    try:
        from services.job_engine import job_manager

        claimed_due_jobs = await job_manager.start_due_jobs()
        if claimed_due_jobs:
            log.info("Claimed %d due delayed job(s) after restart", claimed_due_jobs)
        background_tasks.append(asyncio.create_task(job_manager.poll_due_jobs()))
    except Exception as error:  # noqa: BLE001 -- polling can retry on the next process start
        log.warning("Delayed job recovery sweep failed: %s", error)
