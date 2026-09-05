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


def initialize_runtime_services(adapter_registry: Any) -> None:
    """Check migrations and register the application's runtime integrations."""
    from services.execution.adapter_registry_resolver import init_planner_registry
    from services.migration import apply_migrations

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
