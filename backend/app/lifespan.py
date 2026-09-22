"""Low-risk application startup operations used by the composition root."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any


log = logging.getLogger("loqi")


def begin_startup(app: Any) -> float:
    """Mark startup and register workflows that must exist before requests."""
    from services.platform.lifecycle import set_starting
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
    from services.platform.config_validation import assert_valid_startup_config, validate_config
    from services.platform.lifecycle import set_failed

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


def initialize_runtime_services(adapter_registry: Any) -> None:
    """Check migrations and register the application's runtime integrations."""
    from services.execution.adapter_registry_resolver import init_planner_registry
    from services.platform.migration import apply_migrations

    try:
        apply_migrations()
    except Exception as error:
        log.warning("Migration check failed: %s", error)
    log.info("Job engine initialized")
    register_outbound_providers()
    register_execution_adapters(adapter_registry)
    init_planner_registry(adapter_registry)


def register_outbound_providers() -> None:
    """Register production outbound provider implementations."""
    try:
        from services.outbound.gmail_outbound import GmailOutboundProvider
        from services.outbound.outbound_registry import register_outbound_provider

        register_outbound_provider(GmailOutboundProvider)
        log.info("GmailOutboundProvider registered")
    except Exception as error:
        log.warning("Failed to register GmailOutboundProvider: %s", error)


def register_execution_adapters(adapter_registry: Any) -> None:
    """Register the adapters available to the planner execution registry."""
    from services.adapters.analysis import ReplyAnalysisAdapter
    from services.adapters.crm import CrmAdapter
    from services.adapters.google.calendar import CalendarAdapter
    from services.adapters.google.gmail import GmailAdapter
    from services.adapters.memory import MemoryAdapter
    from services.execution import BridgeAdapter
    from services.execution.credential_factory import resolve_google_credentials
    from services.planner.planning_models import TaskType

    gmail_bridge = BridgeAdapter(
        sdk_adapter=GmailAdapter(),
        action_mapping={TaskType.SEND_EMAIL: "gmail_send_email"},
        credentials_factory=resolve_google_credentials,
    )
    adapter_registry.register(gmail_bridge, priority=100, version="1.0.0")
    log.info(
        "Execution adapter registered: %s (types=%s, factory=%s)",
        gmail_bridge.adapter_type,
        [task_type.value for task_type in gmail_bridge.supported_task_types],
        "resolve_google_credentials",
    )

    calendar_bridge = BridgeAdapter(
        sdk_adapter=CalendarAdapter(),
        action_mapping={
            TaskType.CALENDAR_LIST_EVENTS: "calendar_list_events",
            TaskType.CALENDAR_GET_EVENT: "calendar_get_event",
            TaskType.CALENDAR_CREATE_EVENT: "calendar_create_event",
            TaskType.CALENDAR_UPDATE_EVENT: "calendar_update_event",
            TaskType.CALENDAR_DELETE_EVENT: "calendar_delete_event",
        },
        credentials_factory=resolve_google_credentials,
    )
    adapter_registry.register(calendar_bridge, priority=100, version="1.0.0")
    log.info(
        "Execution adapter registered: %s (types=%s, factory=%s)",
        calendar_bridge.adapter_type,
        [task_type.value for task_type in calendar_bridge.supported_task_types],
        "resolve_google_credentials",
    )

    analysis_bridge = BridgeAdapter(
        sdk_adapter=ReplyAnalysisAdapter(),
        action_mapping={TaskType.ANALYZE_REPLY: "analyze_reply"},
    )
    adapter_registry.register(analysis_bridge, priority=100, version="1.0.0")
    log.info(
        "Execution adapter registered: %s (types=%s)",
        analysis_bridge.adapter_type,
        [task_type.value for task_type in analysis_bridge.supported_task_types],
    )

    crm_bridge = BridgeAdapter(
        sdk_adapter=CrmAdapter(),
        action_mapping={
            TaskType.FIND_CONTACT: "find_contact",
            TaskType.CREATE_CONTACT: "create_contact",
            TaskType.UPDATE_CONTACT: "update_contact",
            TaskType.FIND_COMPANY: "find_company",
            TaskType.CREATE_COMPANY: "create_company",
            TaskType.CREATE_OPPORTUNITY: "create_opportunity",
            TaskType.UPDATE_OPPORTUNITY: "update_opportunity",
            TaskType.CREATE_ACTIVITY: "create_activity",
            TaskType.CREATE_NOTE: "create_note",
            TaskType.ASSIGN_OWNER: "assign_owner",
        },
    )
    adapter_registry.register(crm_bridge, priority=100, version="1.0.0")
    log.info(
        "Execution adapter registered: %s (types=%s)",
        crm_bridge.adapter_type,
        [task_type.value for task_type in crm_bridge.supported_task_types],
    )

    memory_bridge = BridgeAdapter(
        sdk_adapter=MemoryAdapter(),
        action_mapping={
            TaskType.STORE_MEMORY: "store_memory",
            TaskType.RETRIEVE_MEMORY: "retrieve_memory",
            TaskType.SEARCH_MEMORY: "search_memory",
            TaskType.UPDATE_MEMORY: "update_memory",
            TaskType.DELETE_MEMORY: "delete_memory",
            TaskType.SUMMARIZE_MEMORY: "summarize_memory",
        },
    )
    adapter_registry.register(memory_bridge, priority=100, version="1.0.0")
    log.info(
        "Execution adapter registered: %s (types=%s)",
        memory_bridge.adapter_type,
        [task_type.value for task_type in memory_bridge.supported_task_types],
    )


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


def start_memory_consolidation(background_tasks: list[Any]) -> None:
    """Schedule optional memory consolidation and retain its shutdown handle."""
    try:
        from services.memory.consolidation import consolidate_memories
        from services.memory.memory_store import get_memory_provider

        task = asyncio.create_task(consolidate_memories(get_memory_provider()))
        background_tasks.append(task)
        log.info("Memory consolidation startup task created")
    except Exception as error:
        log.warning("Memory consolidation startup failed: %s", error)


def rehydrate_conversation_store() -> None:
    """Reload durable Inbox state without mistaking transport loss for corruption."""
    try:
        from services.conversations.conversation_store import (
            ConversationStoreRehydrationState,
            conversation_store,
        )

        state = conversation_store.reload()
        if state is ConversationStoreRehydrationState.TEMPORARILY_UNAVAILABLE:
            log.warning(
                "Conversation store rehydration deferred: durable persistence temporarily unavailable"
            )
            return
        log.info(
            "Conversation store rehydrated state=%s conversations=%d",
            state.value,
            sum(conversation_store.count_by_status().values()),
        )
    except Exception as error:
        environment = (
            os.getenv("ENVIRONMENT") or os.getenv("APP_ENV") or "development"
        ).strip().lower()
        if environment == "production":
            raise RuntimeError("Durable Inbox persistence is required in production") from error
        log.warning("Conversation store rehydration failed: %s", error)


def rehydrate_communication_store() -> None:
    """Restore communication cursors and thread mappings before workers start."""
    try:
        from services.communication.communication_store import store as communication_store

        communication_store.load_state()
    except Exception as error:  # noqa: BLE001 -- startup remains available without this cache
        log.warning("Communication store rehydration failed: %s", error)


def recover_persisted_workflows() -> None:
    """Restore legacy workflow runtime state before background workers start."""
    from services.workflows.recovery import recover_all

    try:
        recovered = recover_all()
        if recovered["total_recovered"] > 0:
            log.info("Workflow recovery: %s", recovered)
    except Exception as error:
        log.warning("Workflow recovery failed: %s", error)


def start_generation_recovery(background_tasks: list[asyncio.Task[Any]]) -> None:
    """Schedule durable draft-batch and strategy recovery without blocking startup."""
    async def recover_draft_batches() -> None:
        from services.drafts.service import reconcile_stale_draft_batch_jobs

        try:
            recovered = await reconcile_stale_draft_batch_jobs()
            if recovered:
                log.info("Resumed %d interrupted draft generation(s) after restart", recovered)
        except Exception as error:
            log.warning("Draft generation recovery sweep failed: %s", error)

    async def recover_strategy_jobs() -> None:
        from services.campaigns.service import reconcile_stale_strategy_jobs

        try:
            recovered = await reconcile_stale_strategy_jobs()
            if recovered:
                log.info("Reconciled %d interrupted strategy generation(s) after restart", recovered)
        except Exception as error:
            log.warning("Strategy generation recovery sweep failed: %s", error)

    background_tasks.append(asyncio.create_task(recover_draft_batches()))
    background_tasks.append(asyncio.create_task(recover_strategy_jobs()))


def start_launch_backfill(background_tasks: list[asyncio.Task[Any]]) -> None:
    """Schedule idempotent launch-table backfill and retain its task for shutdown."""
    try:
        from services.persistence.launch import backfill_all

        backfill_task = asyncio.create_task(asyncio.to_thread(backfill_all))

        def log_backfill_completion(task: asyncio.Task[Any]) -> None:
            try:
                result = task.result()
                log.info("backfill startup task completed sessions_marked=%s", result)
            except asyncio.CancelledError:
                log.warning("backfill startup task cancelled")
            except BaseException as error:
                log.error("backfill startup task raised error_type=%s", type(error).__name__)

        backfill_task.add_done_callback(log_backfill_completion)
        background_tasks.append(backfill_task)
    except Exception as error:
        log.warning("Canonical backfill startup task failed: %s", error)


def _abandoned_registration_cleanup_interval() -> int:
    """Return the bounded interval between automatic abandoned-registration cleanup cycles."""
    raw = os.getenv("ABANDONED_REGISTRATION_CLEANUP_INTERVAL_SECONDS", "900")
    try:
        return max(60, int(raw))
    except (TypeError, ValueError):
        return 900


def start_abandoned_registration_cleanup(background_tasks: list[asyncio.Task[Any]]) -> None:
    """Schedule fail-closed automatic cleanup of expired abandoned registrations."""
    try:
        from services.identity.registration_cleanup import (
            abandoned_cleanup_runtime_enabled,
            resolve_automatic_cleanup_client,
            run_abandoned_cleanup,
        )

        enabled, reason = abandoned_cleanup_runtime_enabled()
        if not enabled:
            log.info("Abandoned-registration cleanup loop disabled: %s", reason)
            return

        client = resolve_automatic_cleanup_client()
        if client is None:
            log.info("Abandoned-registration cleanup loop disabled: cleanup client unavailable")
            return

        async def cleanup_loop() -> None:
            interval = _abandoned_registration_cleanup_interval()
            log.info("Abandoned-registration cleanup loop started (interval=%ss)", interval)
            await asyncio.sleep(interval)
            while True:
                try:
                    report = await asyncio.to_thread(
                        run_abandoned_cleanup,
                        dry_run=False,
                        client=client,
                    )
                    log.info(
                        "abandoned-registration cleanup cycle "
                        "scanned=%d cleaned_emails=%d cleaned_rows=%d skipped=%d failures=%d",
                        report.get("scanned", 0),
                        report.get("cleaned_emails", 0),
                        report.get("cleaned_rows", 0),
                        report.get("skipped", 0),
                        report.get("failures", 0),
                    )
                except Exception as error:  # noqa: BLE001 -- next periodic cycle retries
                    log.warning("abandoned-registration cleanup cycle failed: %s", error)
                await asyncio.sleep(interval)

        background_tasks.append(asyncio.create_task(cleanup_loop()))
    except Exception as error:
        log.warning("Abandoned-registration cleanup startup failed: %s", error)


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


async def cancel_and_wait(tasks: list[asyncio.Task[Any]], *, timeout: float) -> None:
    """Cancel retained background tasks without allowing shutdown to block forever."""
    pending: list[asyncio.Task[Any]] = []
    for task in tasks:
        if task is None or task.done():
            continue
        task.cancel()
        pending.append(task)
    if not pending:
        return
    try:
        _, still_pending = await asyncio.wait(pending, timeout=timeout)
    except Exception as error:
        log.warning("shutdown await failed: %s", error)
        return
    for task in still_pending:
        log.warning("shutdown_timeout task=%s still pending after %.1fs", task.get_name(), timeout)


async def shutdown_runtime(
    background_tasks: list[asyncio.Task[Any]],
    inbox_sync_engine: Any | None,
    simulator_task: asyncio.Task[Any] | None,
) -> None:
    """Stop runtime integrations and retained background tasks in startup-safe order."""
    from services.platform.lifecycle import set_shutting_down

    set_shutting_down()
    log.info("application_shutdown_started")
    try:
        from services.platform import redis_client

        await redis_client.close()
    except Exception as error:
        log.warning("redis shutdown failed: %s", error)

    shutdown_timeout = float(os.getenv("SHUTDOWN_TIMEOUT_SECONDS", "5"))
    cancel_tasks = list(background_tasks)
    try:
        if inbox_sync_engine is not None:
            await inbox_sync_engine.stop()
    except Exception as error:
        log.warning("Inbox sync engine shutdown failed: %s", error)

    try:
        if simulator_task is not None and not simulator_task.done():
            simulator_task.cancel()
            cancel_tasks.append(simulator_task)
    except Exception as error:
        log.warning("Reply simulator shutdown failed: %s", error)

    await cancel_and_wait(cancel_tasks, timeout=shutdown_timeout)
    log.info("application_shutdown_completed")
