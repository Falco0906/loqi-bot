import asyncio
import csv
import hashlib
import hmac
import io
import json
import logging
import os
import threading
import time
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from typing import Any

from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field
from services.agent import process_message
from services.identity.api import router as auth_router
from services.onboarding.api import router as onboarding_router
from services.organizations.api import router as organizations_router, _build_org_deps, register_deps as register_org_deps
from services.billing.api import router as billing_router, _build_billing_deps, register_deps as register_billing_deps, create_billing_provider
from services.billing.config import BillingConfig
from services.billing.api import register_provider_and_config as _register_billing_provider_config
from services.capabilities.api import router as capabilities_router, register_deps as register_capability_deps, CapabilityDeps
from services.capabilities.config import CapabilityConfig
from services.capabilities.services import CapabilityService
from services.capabilities.repositories import (
    InMemoryCapabilityDefinitionRepository,
    InMemoryOrganizationCapabilityRepository,
    InMemoryCapabilityUsageRepository,
    InMemoryCapabilityLimitsRepository,
)
from services.identity.exceptions import (
    AuthenticationException,
    EmailAlreadyExistsException,
    IdentityException,
    RefreshTokenExpiredException,
    RefreshTokenRevokedException,
    RegistrationSessionExpiredException,
    RegistrationSessionNotFoundException,
    RegistrationSessionWrongStatusException,
    SessionNotFoundException,
    SessionRevokedException,
)
from services.identity.metrics import get_metrics
from services.identity.schemas import ErrorResponse
from starlette.responses import JSONResponse
from services.conversation_engine import ConversationEngine, _message
from services.google_auth import exchange_code_for_tokens
from services.supabase import save_google_tokens
from services.telegram import send_message
from services.campaign_planner import analyze_campaigns
from workflows import run_workflow
from services.job_engine import job_manager
from workflow_dispatcher import register_workflows
from services.workspace_memory import record as record_memory, record_campaign_open, record_draft_review, record_search
from services.workspace_timeline import (
    add_event as add_timeline_event,
    record_search_started,
    record_search_completed,
    record_campaign_created,
    record_drafts_generated,
    record_draft_approved,
    record_campaign_launched,
)
from services.workspace_snapshot import build_snapshot
from services.recommendation_engine import generate_recommendations
from services.learning.behavior_tracker import get_tracker as _get_behavior_tracker
from services.learning.feedback_interpreter import FeedbackInterpreter as _FeedbackInterpreter
from services.executive_brief import generate_brief
from services.draft_intelligence import analyze_draft as analyze_draft_intelligence
from services.strategic_intelligence_api import router as strategic_intelligence_router
from services.rewrite_engine import execute_rewrite
from services.rewrite_history import push as push_rewrite_history, undo as undo_rewrite_history, get_history as get_rewrite_history, get_current_version as get_draft_version
from services.draft_comparison import compare_versions
from services.workflow_planner import plan_workflow
from services.workflow_models import PlanningInput
from services.workflow_executor import execute as execute_workflow, approve as approve_workflow, pause as pause_workflow, resume as resume_workflow, cancel as cancel_workflow
from services.workflow_runtime import get_runtime, get_active_runtimes, get_all_runtimes, get_history as get_workflow_history
from services.workflow_progress import calculate_progress
from services.workflow_events import get_events as get_workflow_events, get_latest_sequence
from services.workflow_models import WorkflowPlan
from services.workflow_recovery import recover_all
from services.conversation_models import ConversationMessage
from services.communication.provider_registry import (
    register_provider, get_provider, list_providers,
    instantiate_provider, register_instance, remove_instance,
    disconnect_provider as registry_disconnect, health_check,
    list_registered_types,
)
from services.outbound.outbound_registry import (
    get_provider as get_outbound_provider,
    list_providers as outbound_list_providers,
    register_instance as outbound_register_instance,
    remove_instance as outbound_remove_instance,
)
from services.communication.provider_models import (
    ProviderType, ProviderStatus, CommunicationProvider,
)
from services.communication.communication_store import store as communication_store
from services.communication.provider_events import get_events as get_provider_events, latest_sequence
from services.communication.gmail_provider import GmailProvider
from services.communication.gmail_sync import sync_all, sync_thread
from services.communication.reply_simulator import maybe_schedule as simulate_reply
from services.reply_intelligence import analyze_message
from services.conversation_memory import memory_store, create_or_update_memory
from services.followup_reasoner import recommend_followup
from services.reply_summary import generate_summary
from services.conversation_timeline import get_events as get_conversation_events
from services.conversation_models import FollowupAction, BuyingSignal, SignalStrength, ConversationStage
from services.buying_signal import detect_signals
from services.planner.planning_pipeline import get_pipeline as get_planning_pipeline, PlanningPipeline
from services.planner.plan_validator import ValidationResult
from services.planner.exceptions import PlanningValidationError
from services.adapters.credential_registry import CredentialRegistry
from services.adapters.credentials import CredentialDescriptor, CredentialInstance
from services.execution import AdapterRegistry as ExecutionAdapterRegistry
from services.execution import BridgeAdapter
from services.planner.planning_models import TaskType
from services.operations import (
    RequestLoggingMiddleware,
    log_config_warnings,
    operations_router,
    set_startup_time,
    startup_diagnostics,
    redact_session_path,
)
from services.world_model import EventType as WMEventType, get_store as get_wm_store, publish

_feedback_interpreter: _FeedbackInterpreter | None = None


def _get_feedback() -> _FeedbackInterpreter:
    global _feedback_interpreter
    if _feedback_interpreter is None:
        _feedback_interpreter = _FeedbackInterpreter(_get_behavior_tracker())
    return _feedback_interpreter


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
)
from services.logging_setup import configure_logging
configure_logging()
log = logging.getLogger("loqi")

request_id_var: ContextVar[str] = ContextVar("request_id")


def _abandoned_registration_cleanup_interval() -> int:
    """Seconds between abandoned-registration cleanup cycles (min 60s)."""
    raw = os.getenv("ABANDONED_REGISTRATION_CLEANUP_INTERVAL_SECONDS", "900")
    try:
        return max(60, int(raw))
    except (TypeError, ValueError):
        return 900


async def _cancel_and_wait(tasks: list["asyncio.Task"], timeout: float) -> None:
    """Cancel background tasks and await them with a bounded timeout.

    A task that ignores cancellation is logged but never blocks shutdown.
    """
    pending: list[asyncio.Task] = []
    for task in tasks:
        if task is None or task.done():
            continue
        task.cancel()
        pending.append(task)
    if not pending:
        return
    try:
        done, still_pending = await asyncio.wait(pending, timeout=timeout)
    except Exception as error:
        log.warning("shutdown await failed: %s", error)
        return
    for task in still_pending:
        log.warning("shutdown_timeout task=%s still pending after %.1fs", task.get_name(), timeout)

@asynccontextmanager
async def lifespan(app: FastAPI):
    from services.lifecycle import set_starting, set_failed, set_ready, set_shutting_down
    set_starting()
    startup_started = time.time()
    log.info("application_starting")
    set_startup_time()
    log_config_warnings()
    startup_diagnostics(app)
    register_workflows()

    # PR10.2: validate runtime configuration BEFORE any background worker,
    # provider restore, or sync engine starts. Fail fast with non-secret,
    # key-only errors when required/unsafe configuration is invalid.
    try:
        from services.config_validation import assert_valid_startup_config, validate_config
        errors, warnings = validate_config()
        for warning in warnings:
            log.warning("config: %s", warning)
        assert_valid_startup_config()
        log.info("Configuration validated successfully")
    except RuntimeError as e:
        log.error("Configuration validation failed — refusing to start: %s", e)
        set_failed()
        raise

    try:
        from services.migration import apply_migrations
        apply_migrations()
    except Exception as e:
        log.warning("Migration check failed: %s", e)
    log.info("Job engine initialized")
    _register_outbound_providers()
    _register_execution_adapters()

    # Wire the global adapter registry to the PlannerRouter
    from services.execution.adapter_registry_resolver import init_planner_registry
    init_planner_registry(_execution_adapter_registry)

    # Subscribe execution engine event bus for production observability
    from services.execution.execution_pipeline import get_pipeline
    from services.execution.logging_subscriber import LoggingSubscriber
    from services.execution.metrics_collector import MetricsCollector
    get_pipeline().event_bus.subscribe(LoggingSubscriber())
    get_pipeline().event_bus.subscribe(MetricsCollector())
    log.info("Execution engine logging + metrics subscribers registered")

    from services.memory.subscriber import MemorySubscriber
    get_pipeline().event_bus.subscribe(MemorySubscriber())
    log.info("Memory subscriber registered")

    background_tasks: list[asyncio.Task] = []
    try:
        from services.memory.consolidation import consolidate_memories
        from services.memory.memory_store import get_memory_provider
        result = asyncio.create_task(consolidate_memories(get_memory_provider()))
        background_tasks.append(result)
        log.info("Memory consolidation startup task created")
    except Exception as e:
        log.warning("Memory consolidation startup failed: %s", e)

    # Rehydrate the conversation store from its persisted snapshot before
    # any API, workflow recovery, or background task (simulator, sync)
    # touches conversations.
    try:
        from services.conversations.conversation_store import conversation_store
        conversation_store.reload()
        log.info("Conversation store rehydrated: %d conversations",
                 sum(conversation_store.count_by_status().values()))
    except Exception as e:
        log.warning("Conversation store rehydration failed: %s", e)

    # Rehydrate the communication store (sync cursor, seen-message set,
    # thread mappings) BEFORE any provider/sync worker starts, so a restart
    # resumes incremental sync from the last cursor instead of re-syncing
    # from scratch (PR10.8 restart durability).
    try:
        from services.communication.communication_store import store as communication_store
        communication_store.load_state()
    except Exception as e:
        log.warning("Communication store rehydration failed: %s", e)

    # Restore providers and recover interrupted workflow work BEFORE any
    # worker task that consumes provider state starts (PR10.8 ordering —
    # workers must not begin consuming state before rehydration completes).
    try:
        _restore_providers_for_startup()
    except Exception as e:
        log.warning("Provider startup restoration failed: %s", e)

    _start_outbound_scheduler()
    inbox_sync_engine = None
    try:
        from services.communication.inbox_sync_engine import inbox_sync_engine as _inbox_sync_engine
        inbox_sync_engine = _inbox_sync_engine
        await inbox_sync_engine.start()
    except Exception as e:
        log.warning("Inbox sync engine startup failed: %s", e)
    # Development reply simulator (SIMULATE_REPLIES=true): schedules synthetic
    # inbound replies after sends. No-op when disabled.
    simulator_task = None
    try:
        from services.communication import reply_simulator
        if reply_simulator.is_enabled():
            simulator_task = reply_simulator.start_scheduler()
            log.info("[sim] Reply simulator enabled (SIMULATE_REPLIES=true), pending=%d",
                     reply_simulator.pending_count())
    except Exception as e:
        log.warning("Reply simulator startup failed: %s", e)
    # Draft-generation recovery is scheduled as a background task so startup
    # is never blocked: the sweep runs off the event loop in a worker thread
    # while the server accepts requests. Reconciliation stays idempotent —
    # each stale campaign is re-checked against the DB right before resolving.
    async def _run_generation_recovery() -> None:
        try:
            recovered = await asyncio.to_thread(_reconcile_stale_generating_campaigns)
            if recovered:
                log.info("Reconciled %d interrupted draft generation(s) after restart", recovered)
        except Exception as e:
            log.warning("Draft generation recovery sweep failed: %s", e)

    background_tasks.append(asyncio.create_task(_run_generation_recovery()))

    try:
        recovered_jobs = await _reconcile_stale_search_jobs()
        if recovered_jobs:
            log.info("Reconciled %d interrupted search job(s) after restart", recovered_jobs)
    except Exception as e:
        log.warning("Search job recovery sweep failed: %s", e)

    # Backfill canonical launch tables from the event log (idempotent).
    try:
        from services.persistence.launch import backfill_all
        backfill_task = asyncio.create_task(asyncio.to_thread(backfill_all))
        startup_backfill_task = backfill_task

        def _on_backfill_done(task: "asyncio.Task") -> None:
            try:
                result = task.result()
                log.info("backfill startup task completed sessions_marked=%s", result)
            except asyncio.CancelledError:
                log.warning("backfill startup task cancelled")
            except BaseException as error:
                log.error("backfill startup task raised error_type=%s", type(error).__name__)

        backfill_task.add_done_callback(_on_backfill_done)
        background_tasks.append(backfill_task)
    except Exception as e:
        log.warning("Canonical backfill startup task failed: %s", e)

    # Abandoned-registration lifecycle cleanup (SaaS): periodically reclaim
    # emails blocked by expired abandoned signup attempts. Uses the same
    # conservative predicate as the operator CLI and lazy signup reclaim;
    # idempotent and race-safe, so duplicate execution across instances is
    # harmless. FAIL-CLOSED: the loop is only created when the runtime gate is
    # satisfied (explicitly production AND
    # ABANDONED_REGISTRATION_CLEANUP_ENABLED=true). A test or dev lifespan
    # that sets ENVIRONMENT=production or connects to a shared Supabase project
    # can never create/execute this task because the explicit enable flag is
    # absent in tests.
    try:
        from services.identity.registration_cleanup import (
            abandoned_cleanup_runtime_enabled,
            resolve_automatic_cleanup_client,
            run_abandoned_cleanup,
        )
        _cleanup_enabled, _cleanup_reason = abandoned_cleanup_runtime_enabled()
        if not _cleanup_enabled:
            log.info("Abandoned-registration cleanup loop disabled: %s", _cleanup_reason)
        else:
            # Explicit client injection: the loop only ever operates on the
            # client returned by the gate-checked accessor, never on an
            # implicit get_supabase_client().
            _cleanup_client = resolve_automatic_cleanup_client()
            if _cleanup_client is None:
                log.info("Abandoned-registration cleanup loop disabled: cleanup client unavailable")
            else:
                async def _abandoned_registration_cleanup_loop() -> None:
                    interval = _abandoned_registration_cleanup_interval()
                    log.info("Abandoned-registration cleanup loop started (interval=%ss)", interval)
                    # Initial delay: never run a destructive cycle at boot (the
                    # safety decision is the runtime gate above, not this delay).
                    await asyncio.sleep(interval)
                    while True:
                        try:
                            report = await asyncio.to_thread(
                                run_abandoned_cleanup, dry_run=False, client=_cleanup_client,
                            )
                            log.info(
                                "abandoned-registration cleanup cycle "
                                "scanned=%d cleaned_emails=%d cleaned_rows=%d skipped=%d failures=%d",
                                report.get("scanned", 0), report.get("cleaned_emails", 0),
                                report.get("cleaned_rows", 0), report.get("skipped", 0),
                                report.get("failures", 0),
                            )
                        except Exception as exc:  # noqa: BLE001
                            log.warning("abandoned-registration cleanup cycle failed: %s", exc)
                        await asyncio.sleep(interval)

                background_tasks.append(asyncio.create_task(_abandoned_registration_cleanup_loop()))
    except Exception as e:
        log.warning("Abandoned-registration cleanup startup failed: %s", e)

    set_ready()
    try:
        import pwd
        log.info(
            "runtime_user uid=%d gid=%d name=%s",
            os.geteuid(), os.getgid(), pwd.getpwuid(os.geteuid()).pw_name,
        )
    except Exception:
        pass
    log.info("application_ready duration_ms=%d", int((time.time() - startup_started) * 1000))

    yield

    set_shutting_down()
    log.info("application_shutdown_started")
    try:
        from services import redis_client
        await redis_client.close()
    except Exception as e:
        log.warning("redis shutdown failed: %s", e)
    shutdown_timeout = float(os.getenv("SHUTDOWN_TIMEOUT_SECONDS", "5"))

    cancel_tasks: list[asyncio.Task] = list(background_tasks)
    try:
        if inbox_sync_engine is not None:
            await inbox_sync_engine.stop()
    except Exception as e:
        log.warning("Inbox sync engine shutdown failed: %s", e)

    try:
        if simulator_task is not None and not simulator_task.done():
            simulator_task.cancel()
            cancel_tasks.append(simulator_task)
    except Exception as e:
        log.warning("Reply simulator shutdown failed: %s", e)

    global _scheduler_task
    if _scheduler_task is not None and not _scheduler_task.done():
        _scheduler_task.cancel()
        cancel_tasks.append(_scheduler_task)

    await _cancel_and_wait(cancel_tasks, timeout=shutdown_timeout)
    log.info("application_shutdown_completed")

_production_env = (os.getenv("ENVIRONMENT") or os.getenv("APP_ENV") or "development").strip().lower() == "production"

app = FastAPI(
    lifespan=lifespan,
    # PR10.8.3.3: do not expose the OpenAPI surface in production.
    docs_url=None if _production_env else "/docs",
    openapi_url=None if _production_env else "/openapi.json",
    redoc_url=None if _production_env else "/redoc",
)
app.add_middleware(RequestLoggingMiddleware)


@app.middleware("http")
async def require_web_session_auth(request: Request, call_next):
    """PR10.8.3.1: every /api/web/session/... route (except the session
    creation bootstrap) requires a valid Authorization: Bearer token
    (identity access token OR web-session token). Session credentials are
    never accepted from URL paths. Fail closed with 401."""
    path = request.url.path
    if path == "/api/web/session" or not path.startswith("/api/web/session/"):
        return await call_next(request)
    try:
        await _resolve_session_context(request)  # raises 401 when unauthenticated
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return await call_next(request)


app.include_router(operations_router)
app.include_router(auth_router)
app.include_router(onboarding_router)
app.include_router(organizations_router, prefix="/api/v1")
app.include_router(billing_router)
app.include_router(capabilities_router)
app.include_router(strategic_intelligence_router)

# ── Wire Organization Platform services ──
_org_deps = _build_org_deps()
register_org_deps(_org_deps)

# ── Wire Organization Service into Onboarding ──
from services.identity.api import get_auth_user_service
from services.onboarding.api import set_onboarding_service, set_onboarding_completion_handler
from services.onboarding.services import LifecycleService, OnboardingService as OnboardingServiceCls
from services.onboarding.repositories import InMemoryLifecycleRepository, InMemoryOnboardingSessionRepository
_onboarding_lifecycle_repo = InMemoryLifecycleRepository()
_onboarding_session_repo = InMemoryOnboardingSessionRepository()
_onboarding_lifecycle_svc = LifecycleService(_onboarding_lifecycle_repo)
_onboarding_svc = OnboardingServiceCls(
    lifecycle_service=_onboarding_lifecycle_svc,
    session_repo=_onboarding_session_repo,
    org_service=_org_deps.org_service,
    user_service=get_auth_user_service(),
)
set_onboarding_service(_onboarding_svc)

# ── Wire Billing Platform services ──
_billing_config = BillingConfig(
    provider_mode=os.getenv("BILLING_PROVIDER_MODE", "mock"),
    stripe_secret_key=os.getenv("STRIPE_SECRET_KEY", ""),
    stripe_publishable_key=os.getenv("STRIPE_PUBLISHABLE_KEY", ""),
    stripe_webhook_secret=os.getenv("STRIPE_WEBHOOK_SECRET", ""),
)
_billing_provider = create_billing_provider(_billing_config)
_billing_deps = _build_billing_deps(_billing_provider, _billing_config)
register_billing_deps(_billing_deps)
_register_billing_provider_config(_billing_provider, _billing_config)

# ── Wire Capability Platform services ──
_capability_config = CapabilityConfig()
_capability_definition_repo = InMemoryCapabilityDefinitionRepository()
_capability_org_repo = InMemoryOrganizationCapabilityRepository()
_capability_usage_repo = InMemoryCapabilityUsageRepository()
_capability_limits_repo = InMemoryCapabilityLimitsRepository()

_capability_service = CapabilityService(
    definition_repo=_capability_definition_repo,
    org_capability_repo=_capability_org_repo,
    usage_repo=_capability_usage_repo,
    limits_repo=_capability_limits_repo,
    config=_capability_config,
)

register_capability_deps(CapabilityDeps(
    capability_service=_capability_service,
))

# ── Identity exception handler ──
_IDENTITY_STATUS: dict[type, int] = {
    AuthenticationException: 401,
    EmailAlreadyExistsException: 409,
    RefreshTokenExpiredException: 401,
    RefreshTokenRevokedException: 401,
    RegistrationSessionNotFoundException: 404,
    RegistrationSessionExpiredException: 410,
    RegistrationSessionWrongStatusException: 400,
    SessionNotFoundException: 404,
    SessionRevokedException: 401,
    IdentityException: 400,
}


def _embed_delta_into_snapshot(snapshot: dict, delta: "WorkspaceDelta") -> None:
    """Embed delta metadata into snapshot for Executive Brief consumption.

    The Executive Brief's public interface (``generate_brief(snapshot, recommendations)``)
    stays unchanged — it reads delta fields from the snapshot dict.
    """
    import dataclasses
    snapshot["_delta"] = {
        "first_visit": delta.first_visit,
        "event_count": delta.event_count,
        "event_range": list(delta.event_range),
        "new_campaigns": len(delta.new_campaigns),
        "changed_campaigns": len(delta.changed_campaigns),
        "new_drafts": len(delta.new_drafts),
        "scheduled_drafts": len(delta.scheduled_drafts),
        "sent_outreach": len(delta.sent_outreach),
        "new_leads": len(delta.new_leads),
        "new_providers": len(delta.new_providers),
        "new_conversations": len(delta.new_conversations),
        "escalated_conversations": len(delta.escalated_conversations),
        "completed_jobs": len(delta.completed_jobs),
        "learned_preferences": len(delta.learned_preferences),
        "new_insights": len(delta.new_insights),
        "has_delta": not delta.is_empty(),
    }


def _identity_status(exc: IdentityException) -> int:
    for cls in type(exc).__mro__:
        if cls in _IDENTITY_STATUS:
            return _IDENTITY_STATUS[cls]
    return 400


_FAIL_LABELS: dict[str, str] = {
    "RefreshTokenRevokedException": "replay",
    "RefreshTokenExpiredException": "fail",
    "InvalidCredentialsException": "fail",
    "EmailAlreadyExistsException": "duplicate",
    "SessionRevokedException": "fail",
}


def _record_auth_metric(request: Request, exc: IdentityException) -> None:
    m = get_metrics()
    exc_name = type(exc).__name__
    label = _FAIL_LABELS.get(exc_name, "fail")
    path = request.url.path

    if "/signup/email" in path and "/status" not in path:
        if isinstance(exc, EmailAlreadyExistsException):
            m.signup_total["duplicate"] += 1
        else:
            m.signup_total[label] += 1
    elif "/signup/email/verify" in path:
        m.verify_total[label] += 1
    elif "/login" in path:
        m.login_total[label] += 1
    elif "/refresh" in path:
        m.refresh_total[label] += 1
    elif "/logout" in path:
        m.logout_total[label] += 1
    elif "/sessions" in path:
        m.session_revoked_total[label] += 1


_SAFE_IDENTITY_MESSAGES: dict[str, str] = {
    "EmailAlreadyExistsException": "An account with this email already exists",
    "UserNotFoundException": "User not found",
    "SessionNotFoundException": "Session not found",
    "OrganizationNotFoundException": "Organization not found",
    "EmailIdentityNotFoundException": "Email identity not found",
}


def _safe_identity_message(exc: IdentityException) -> str:
    """Client-safe message that never echoes or discloses internals.

    Identity exceptions may embed an email, user id, or session id in their
    message (used for server-side diagnostics). These are stripped from the
    client response to avoid resource enumeration and identifier leakage;
    the full detail is still logged server-side by the exception handler.
    """
    safe = _SAFE_IDENTITY_MESSAGES.get(type(exc).__name__)
    if safe is not None:
        return safe
    message = str(exc) or "Authentication failed"
    if "registered: " in message or "not found: " in message:
        return message.split(":")[0].strip()
    return message


@app.exception_handler(IdentityException)
async def identity_exception_handler(request: Request, exc: IdentityException):
    req_id = request_id_var.get("")
    log.warning(
        "%s %s identity error: %s %s",
        req_id, request.method, type(exc).__name__, exc,
    )

    _record_auth_metric(request, exc)

    return JSONResponse(
        status_code=_identity_status(exc),
        content=ErrorResponse(
            code=type(exc).__name__,
            message=_safe_identity_message(exc),
            request_id=req_id,
        ).model_dump(),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Production-safe catch-all for unexpected exceptions.

    Logs the exception type, request/correlation ID, and stack trace
    server-side; returns a generic safe message to the client. Exception text
    is never returned to clients, and no secret values are logged here.
    """
    req_id = request_id_var.get("") or str(getattr(request.state, "request_id", "") or "")
    log.error(
        "unhandled_exception request_id=%s method=%s path=%s type=%s",
        req_id, request.method, redact_session_path(request.url.path), type(exc).__name__,
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error"},
        headers={"X-Request-ID": req_id},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Sanitize server-error (5xx) responses end to end.

    FastAPI's default HTTPException handler returns ``exc.detail`` verbatim.
    Several routes raise ``HTTPException(status_code=5xx, detail=str(e))`` which
    would leak raw exception text (internal paths, provider/SQL fragments) to
    production clients. For 5xx we log the real detail server-side (with the
    request/correlation id) and return a generic message; 4xx details are
    preserved because they describe the client's request, not internals.
    """
    status = exc.status_code
    detail = exc.detail
    headers = exc.headers or {}
    if status >= 500:
        req_id = request_id_var.get("") or str(getattr(request.state, "request_id", "") or "")
        log.error(
            "http_5xx request_id=%s method=%s path=%s status=%d detail=%s",
            req_id, request.method, redact_session_path(request.url.path), status, detail,
        )
        detail = "Internal Server Error"
    content = {"detail": detail} if not isinstance(detail, (dict, list)) else detail
    return JSONResponse(status_code=status, content=content, headers=headers)


engine = ConversationEngine()
_start_time = time.time()

_credential_registry = CredentialRegistry()
_execution_adapter_registry = ExecutionAdapterRegistry()

# ── In-memory batch / draft / campaign stores ──
batch_jobs: dict[str, dict[str, Any]] = {}
draft_store: dict[str, list[dict[str, Any]]] = {}
campaign_store: dict[str, list[dict[str, Any]]] = {}

# Retained references to running draft-batch tasks. The event loop only keeps
# weak references to tasks, so a fire-and-forget `asyncio.create_task` can be
# garbage-collected mid-await and silently kill draft generation. Retaining
# the task mirrors BackgroundRunner in services/job_engine/runner.py.
_draft_batch_tasks: dict[str, asyncio.Task] = {}

# Strategy generation runs as an in-process background job so the HTTP request
# returns 202 immediately; clients poll `strategy-jobs/{job_id}` (same
# contract as discovery searches and draft batches). Jobs are in-memory —
# a server restart abandons a mid-flight generation and the user re-runs it.
STRATEGY_JOBS: dict[str, dict[str, Any]] = {}
_strategy_job_tasks: dict[str, asyncio.Task] = {}


def _create_batch_job(batch_id: str, campaign_id: str | None, total: int) -> dict[str, Any]:
    job: dict[str, Any] = {
        "status": "processing",
        "total": total,
        "completed": 0,
        "current_index": -1,
        "current_name": None,
        "drafts": [],
        "error": None,
        "campaign_id": campaign_id,
        "batch_id": batch_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    batch_jobs[batch_id] = job
    return job


def _launch_batch_task(
    session_token: str,
    batch_id: str,
    leads: list[dict[str, Any]],
    owner_id: str,
) -> None:
    """Start a draft batch and retain the task so it survives GC mid-run."""
    task = asyncio.create_task(
        _process_batch_drafts(session_token, batch_id, leads, owner_id)
    )
    _draft_batch_tasks[batch_id] = task
    task.add_done_callback(lambda _done: _draft_batch_tasks.pop(batch_id, None))


def _reconcile_campaign_generation(owner_id: str, campaign: dict[str, Any]) -> dict[str, Any]:
    """Resolve a campaign whose draft batch was interrupted.

    Callers must verify no live batch task exists for this campaign. Marks the
    durable ``generation`` metadata completed when drafts were persisted,
    otherwise failed so generation can be retried. Uses only the durable
    workflow event stream; never touches authentication.
    """
    generation = campaign.get("generation")
    generation = generation if isinstance(generation, dict) else {}
    if generation.get("status") != "processing":
        return campaign

    batch_id = generation.get("batch_id")
    from services.workspace_state import persist_campaign_update
    drafts = _workspace_drafts(owner_id, "")
    batch_drafts = [
        d for d in drafts
        if d.get("campaign_id") == campaign.get("id")
        and (not batch_id or d.get("batch_id") == batch_id)
    ]

    now = datetime.now(timezone.utc).isoformat()
    if batch_drafts:
        resolved: dict[str, Any] = {
            **generation,
            "status": "completed",
            "total": generation.get("total", len(batch_drafts)),
            "completed": len(batch_drafts),
            "finished_at": now,
        }
    else:
        resolved = {
            **generation,
            "status": "failed",
            "error": "Draft generation was interrupted before any draft was persisted",
            "finished_at": now,
        }

    if persist_campaign_update(owner_id, campaign.get("id", ""), {"generation": resolved}):
        campaign["generation"] = resolved
        campaign["updated_at"] = now
    return campaign


def _reconcile_stale_generating_campaigns() -> int:
    """One-shot startup recovery for draft batches interrupted by a restart.

    After a restart no batch tasks exist, so any campaign still in 'generating'
    reflects an interrupted batch. Reconcile every one from the durable
    workflow event stream. Returns the number of campaigns reconciled.

    Discovery is targeted: only campaigns whose ``settings.generation.status``
    is 'processing' are loaded (no workspace-wide scan). Reconciliation
    semantics are unchanged — ``_reconcile_campaign_generation`` resolves
    completed/failed exactly as before. A status/batch re-check right before
    reconciling keeps duplicate or late executions idempotent: a campaign
    resolved by an earlier pass (or a batch started concurrently) is skipped.
    """
    from services.supabase import get_supabase_client

    client = get_supabase_client()
    if client is None:
        return 0
    try:
        rows = (
            client.table("campaigns")
            .select("id, workspace_id, settings")
            .filter("settings->generation->>status", "eq", "processing")
            .execute()
        )
    except Exception as error:
        log.warning("[recovery] stale campaign scan failed: %s", error)
        return 0
    campaign_rows = getattr(rows, "data", None) or []

    session_ids = {r.get("workspace_id") for r in campaign_rows if r.get("workspace_id")}
    if not session_ids:
        return 0
    try:
        sessions = (
            client.table("workflow_sessions")
            .select("id, user_id")
            .in_("id", list(session_ids))
            .execute()
        )
        session_owner = {
            s.get("id"): s.get("user_id")
            for s in getattr(sessions, "data", None) or []
            if s.get("id") and s.get("user_id")
        }
    except Exception as error:
        log.warning("[recovery] workspace session lookup failed: %s", error)
        return 0

    recovered = 0
    for row in campaign_rows:
        workspace_id = row.get("workspace_id")
        owner_id = session_owner.get(workspace_id)
        if not owner_id:
            log.warning("[recovery] no owner for workspace %s, skipping", workspace_id)
            continue
        try:
            settings = row.get("settings") or {}
            if isinstance(settings, str):
                try:
                    settings = json.loads(settings)
                except (TypeError, ValueError):
                    settings = {}
            generation = (settings.get("generation") or {}) if isinstance(settings, dict) else {}
            generation = generation if isinstance(generation, dict) else {}
            if generation.get("status") != "processing":
                continue
            if not _campaign_generation_still_processing(client, row.get("id"), generation):
                continue
            campaign = {"id": row.get("id"), "generation": generation}
            _reconcile_campaign_generation(owner_id, campaign)
            recovered += 1
        except Exception as error:
            log.warning("[recovery] reconcile failed for workspace %s: %s", workspace_id, error)
    return recovered


def _campaign_generation_still_processing(client, campaign_id: str, generation: dict) -> bool:
    """Re-read the campaign's generation right before reconciling.

    Guards against clobbering a batch that started concurrently with the
    recovery pass (the sweep now runs after the server accepts requests):
    only a campaign still 'processing' with the same batch_id is reconciled.
    Makes duplicate background executions idempotent.
    """
    batch_id = generation.get("batch_id") or ""
    try:
        rows = (
            client.table("campaigns")
            .select("settings")
            .eq("id", campaign_id)
            .limit(1)
            .execute()
        )
    except Exception as error:
        log.warning("[recovery] stale re-check failed for %s: %s", campaign_id, error)
        return False
    row = (getattr(rows, "data", None) or [None])[0]
    if not row:
        return False
    current = row.get("settings") or {}
    if isinstance(current, str):
        try:
            current = json.loads(current)
        except (TypeError, ValueError):
            current = {}
    current = (current.get("generation") or {}) if isinstance(current, dict) else {}
    current = current if isinstance(current, dict) else {}
    if current.get("status") != "processing":
        return False
    return (current.get("batch_id") or "") == batch_id


STALE_SEARCH_JOB_GRACE_SECONDS = 300


async def _reconcile_stale_search_jobs() -> int:
    """One-shot startup recovery for search jobs/discoveries interrupted by a restart.

    After a restart the in-process ``BackgroundRunner`` holds no tasks, so any
    non-terminal ``jobs`` row is orphaned. Two passes:

    1. Orphaned runs (``queued``/``running``, not touched within the grace
       window): if the workflow already persisted ``search_results`` the run is
       complete — mark the job completed and finalize its discovery; otherwise
       mark the job failed and, when the discovery is still ``searching``, the
       discovery failed too (retryable).
    2. Completed jobs whose discovery is still ``searching`` (the process died
       inside the ``on_complete`` hook, after the job was marked completed):
       re-run ``finalize_discovery`` (idempotent).

    Returns the number of job rows reconciled.
    """
    from services.discovery import (
        finalize_discovery,
        mark_discovery_status,
    )
    from services.job_engine.models import JobStatus
    from services.job_engine.storage import JobStorage
    from services.supabase import get_supabase_client

    client = get_supabase_client()
    if client is None:
        return 0

    def _chunked(values: list[str], size: int = 100) -> list[list[str]]:
        return [values[i : i + size] for i in range(0, len(values), size)]

    storage = JobStorage()
    grace_iso = (datetime.now(timezone.utc) - timedelta(seconds=STALE_SEARCH_JOB_GRACE_SECONDS)).isoformat()
    recovered = 0

    try:
        rows = (
            client.table("jobs")
            .select("id, discovery_id")
            .eq("type", "search")
            .in_("status", ["queued", "running"])
            .lt("updated_at", grace_iso)
            .execute()
        )
        orphaned = getattr(rows, "data", None) or []
    except Exception as error:
        log.warning("[recovery] stale search job scan failed: %s", error)
        orphaned = []

    orphan_ids = [str(r.get("id")) for r in orphaned if r.get("id")]
    jobs_with_results: set[str] = set()
    for chunk in _chunked(orphan_ids):
        try:
            result_rows = (
                client.table("search_results")
                .select("job_id")
                .in_("job_id", chunk)
                .execute()
            )
            jobs_with_results.update(
                str(r.get("job_id")) for r in (result_rows.data or []) if r.get("job_id")
            )
        except Exception as error:
            log.warning("[recovery] search results batch lookup failed: %s", error)

    orphan_disc_ids = [str(r.get("discovery_id")) for r in orphaned if r.get("discovery_id")]
    orphan_disc_status: dict[str, str] = {}
    for chunk in _chunked(orphan_disc_ids):
        try:
            disc_rows = (
                client.table("discoveries")
                .select("id, status")
                .in_("id", chunk)
                .execute()
            )
            orphan_disc_status.update(
                {str(d.get("id")): str(d.get("status")) for d in (disc_rows.data or [])}
            )
        except Exception as error:
            log.warning("[recovery] orphan discoveries batch lookup failed: %s", error)

    for row in orphaned:
        job_id = str(row.get("id") or "")
        if not job_id:
            continue
        try:
            has_results = job_id in jobs_with_results
            if has_results:
                storage.update_job(
                    job_id,
                    status=JobStatus.COMPLETED,
                    stage="Complete",
                    progress=100,
                    result_ready=True,
                    completed_at=datetime.now(timezone.utc),
                )
                job = storage.get_job(job_id)
                if job:
                    await finalize_discovery(job)
                log.info("[recovery] finalized orphaned search job %s", job_id)
            else:
                reason = "Search run interrupted by restart"
                storage.update_job(
                    job_id,
                    status=JobStatus.FAILED,
                    stage="Failed",
                    error_message=reason,
                    completed_at=datetime.now(timezone.utc),
                )
                if row.get("discovery_id"):
                    if orphan_disc_status.get(str(row["discovery_id"])) == "searching":
                        mark_discovery_status(
                            str(row["discovery_id"]), "failed", reason
                        )
                log.info("[recovery] failed orphaned search job %s", job_id)
            recovered += 1
        except Exception as error:
            log.warning("[recovery] stale search job %s reconcile failed: %s", job_id, error)

    try:
        rows = (
            client.table("jobs")
            .select("id, status, error_message, discovery_id")
            .eq("type", "search")
            .in_("status", ["completed", "failed"])
            .not_.is_("discovery_id", "null")
            .order("created_at", desc=True)
            .limit(200)
            .execute()
        )
        completed = getattr(rows, "data", None) or []
    except Exception as error:
        log.warning("[recovery] terminal search job scan failed: %s", error)
        completed = []

    discovery_ids = [str(r.get("discovery_id")) for r in completed if r.get("discovery_id")]
    discovery_by_id: dict[str, dict] = {}
    for chunk in _chunked(discovery_ids):
        try:
            disc_rows = (
                client.table("discoveries")
                .select("id, status")
                .in_("id", chunk)
                .execute()
            )
            for disc in disc_rows.data or []:
                discovery_by_id[str(disc.get("id"))] = disc
        except Exception as error:
            log.warning("[recovery] discoveries batch lookup failed: %s", error)

    for row in completed:
        job_id = str(row.get("id") or "")
        job_status = str(row.get("status") or "")
        try:
            discovery = discovery_by_id.get(str(row.get("discovery_id") or ""))
            if not discovery or (discovery or {}).get("status") != "searching":
                continue
            if job_status == JobStatus.COMPLETED.value:
                job = storage.get_job(job_id)
                if job and await finalize_discovery(job):
                    log.info("[recovery] finalized completed search job %s", job_id)
                    recovered += 1
            elif job_status == JobStatus.FAILED.value:
                mark_discovery_status(
                    str(discovery["id"]),
                    "failed",
                    row.get("error_message") or "Search run failed",
                )
                log.info("[recovery] failed terminal search job %s", job_id)
                recovered += 1
        except Exception as error:
            log.warning("[recovery] terminal search job %s reconcile failed: %s", job_id, error)
    return recovered


def _build_copilot_workspace_context(session_token: str, current_page: str | None = None, page_context: dict | None = None, conversation_id: str | None = None, user_id: str | None = None) -> dict:
    campaigns = campaign_store.get(session_token, [])
    drafts = draft_store.get(session_token, [])
    total_leads = sum(c.get("lead_count", 0) or 0 for c in campaigns)
    from services.workspace_snapshot import build_snapshot
    snapshot = build_snapshot(session_token, campaigns, drafts, total_leads, user_id=user_id)
    analysis = snapshot.get("analysis", {})

    active_workflows = get_active_runtimes(session_token)
    workflow_context = []
    for wf in active_workflows:
        progress = calculate_progress(wf)
        workflow_context.append({
            "workflow_id": wf.workflow_id,
            "goal": wf.plan.get("goal", ""),
            "status": wf.status.value,
            "progress": progress,
        })

    result = {
        "snapshot": {
            "campaigns": snapshot.get("campaigns", []),
            "campaign_count": snapshot.get("campaign_count", 0),
            "campaigns_ready": snapshot.get("campaigns_ready", 0),
            "campaigns_draft_review": snapshot.get("campaigns_draft_review", 0),
            "drafts": snapshot.get("drafts", {}),
            "total_leads": snapshot.get("total_leads", 0),
            "jobs": snapshot.get("jobs", {}),
            "memory": snapshot.get("memory", {}),
            "timeline": snapshot.get("timeline", []),
            "active_workflows": workflow_context,
        },
        "analysis": {
            "current_focus": analysis.get("current_focus"),
            "recommended_next_action": analysis.get("recommended_next_action"),
            "campaign_priorities": analysis.get("campaign_priorities", []),
            "workspace_health": analysis.get("workspace_health"),
            "cross_campaign_insights": analysis.get("cross_campaign_insights", []),
            "workflow_continuation": analysis.get("workflow_continuation"),
            "attention_items": analysis.get("attention_items", []),
        },
    }

    if current_page == "Draft Review" and page_context:
        selected_index = page_context.get("selected_index")
        if selected_index is not None and drafts:
            try:
                idx = int(selected_index)
                if 0 <= idx < len(drafts):
                    d = drafts[idx]
                    result["current_draft"] = {
                        "id": d.get("id"),
                        "subject": d.get("subject", ""),
                        "text_preview": d.get("text", "")[:300],
                        "lead_name": d.get("lead", {}).get("name", ""),
                        "lead_company": d.get("lead", {}).get("company", ""),
                        "lead_title": d.get("lead", {}).get("title", ""),
                        "campaign_name": d.get("campaign_name", ""),
                        "tone": d.get("tone"),
                        "length": d.get("length"),
                        "status": d.get("status"),
                    }
                    intel = d.get("draft_intelligence")
                    if intel:
                        result["current_draft"]["draft_intelligence"] = intel
                    hist = get_rewrite_history(session_token, d.get("id", ""))
                    if hist:
                        result["current_draft"]["rewrite_history"] = hist[:3]

                    draft_text = d.get("text", "")
                    try:
                        from services.draft_intelligence import analyze_draft as _analyze
                        new_intel = _analyze(draft_text, {
                            "campaign_name": d.get("campaign_name"),
                            "company": d.get("lead", {}).get("company"),
                            "contact": d.get("lead", {}).get("name"),
                            "role": d.get("lead", {}).get("title"),
                        })
                        result["current_draft"]["draft_intelligence"] = new_intel.to_dict()
                    except Exception:
                        pass
            except (ValueError, IndexError):
                pass

    # SaaS-2.5: only surface the authenticated owner's own providers. The
    # provider records are durable (rehydrated from connected_accounts), so a
    # cross-tenant read here would leak emails/ids/health across tenants.
    providers = [
        p for p in communication_store.list_providers()
        if not user_id or str(getattr(p, "user_id", "")) == str(user_id)
    ]
    if providers:
        provider_list = []
        for p in providers:
            instance = get_provider(p.id)
            health_val = instance.health().value if instance else p.status.value
            provider_list.append({
                "id": p.id,
                "provider_type": p.provider_type.value,
                "status": health_val,
                "email": p.metadata.get("email", ""),
                "last_sync": p.last_sync,
            })
        result["providers"] = provider_list
        result["provider_summary"] = {
            "total": len(providers),
            "healthy": sum(1 for p in provider_list if p["status"] == "healthy"),
            "offline": sum(1 for p in provider_list if p["status"] == "offline"),
            "last_sync": max((p["last_sync"] for p in provider_list if p["last_sync"]), default=""),
        }

    # SaaS-2.5: conversation memory/intelligence is only exposed for a
    # conversation the caller provably owns. A client-supplied conversation_id
    # must never read another tenant's memory/timeline.
    if conversation_id and user_id:
        from services.conversations.conversation_store import conversation_store
        convo = conversation_store.get_conversation(conversation_id)
        if convo is not None and _conversation_owned_by(convo, user_id):
            mem = memory_store.get(conversation_id)
            if mem:
                events = get_conversation_events(conversation_id)
                sigs = [BuyingSignal(signal=s, strength="medium", confidence=50, reason="") for s in mem.buying_signals] if mem.buying_signals else []
                obj_sigs = [s.model_dump() for s in sigs] if sigs else []
                result["conversation_intelligence"] = {
                    "conversation_id": conversation_id,
                    "current_stage": mem.current_stage.value,
                    "summary": mem.summary,
                    "open_questions": mem.open_questions,
                    "outstanding_objections": mem.outstanding_objections,
                    "pain_points": mem.pain_points,
                    "business_goals": mem.business_goals,
                    "competitor_mentioned": mem.competitor_mentioned,
                    "decision_makers": mem.decision_makers,
                    "buying_signals": mem.buying_signals,
                    "last_recommendation": mem.last_recommendation,
                    "last_followup": mem.last_followup,
                    "key_risks": mem.key_risks,
                    "key_opportunities": mem.key_opportunities,
                    "urgency": mem.urgency,
                    "decision_confidence": mem.decision_confidence,
                    "top_objection": mem.top_objection,
                    "timeline_events": [e.model_dump() for e in events],
                }

    return result


def _parse_draft_body(message: str) -> str | None:
    if "Draft ready:" not in message or "---" not in message:
        return None
    parts = message.split("---")
    return parts[1].strip() if len(parts) >= 3 else None


def _find_outbound_gmail_provider_id() -> str:
    """Find the first registered Gmail outbound provider instance ID.
    Returns empty string if none found.
    """
    providers = outbound_list_providers()
    for pid, inst in providers.items():
        if hasattr(inst, 'provider_type') and inst.provider_type == "gmail":
            return pid
    return ""


def _provider_owned_by(provider_id: str, owner_id: str) -> bool:
    """True only when the provider instance is registered and belongs to the
    durable workspace owner. Providers whose owning user cannot be resolved
    are never treated as owned."""
    if not owner_id:
        return False
    comm = get_provider(provider_id)
    if not comm:
        return False
    user_id = getattr(comm, "_user_id", "") or ""
    connected = getattr(comm, "_connected", False)
    return str(user_id) == str(owner_id) and bool(connected)


def _provider_record_owned_by(provider_id: str, owner_id: str) -> bool:
    """True when the communication-store record for ``provider_id`` belongs to
    ``owner_id``. Unlike ``_provider_owned_by`` this does NOT require the
    provider to be currently connected, so a reauth-required/disconnected
    provider is still correctly attributable to its owner (PR10.8.3)."""
    if not owner_id:
        return False
    provider = communication_store.get_provider(provider_id)
    if provider is None:
        return False
    return str(provider.user_id) == str(owner_id)


def _outbound_draft_owned_by(draft: "object", owner_id: str) -> bool:
    """True only when the outbound draft provably belongs to ``owner_id``.

    Fail-closed (PR10.8.3.2): a draft is attributed through its provider
    record. If the draft has no provider, or the provider is not in the
    runtime store, ownership cannot be established and access is denied.
    """
    if not owner_id or draft is None:
        return False
    pid = getattr(draft, "provider_id", "") or ""
    if not pid:
        return False
    provider = communication_store.get_provider(pid)
    if provider is None:
        return False
    return str(provider.user_id) == str(owner_id)


def _conversation_owned_by(conversation: "object", owner_id: str) -> bool:
    """True only when the conversation provably belongs to ``owner_id``.

    Fail-closed (PR10.8.3.1): ownership must be established from a trusted
    server-derived source (the conversation's persisted ``owner_id`` set by the
    trusted creation path, or its provider record). If ownership cannot be
    established — missing provider, unresolved provider, missing owner — access
    is DENIED. There is no "authenticated user = allowed" fallback.
    """
    if not owner_id:
        return False
    conv_owner = getattr(conversation, "owner_id", "") or ""
    if conv_owner:
        return str(conv_owner) == str(owner_id)
    provider_id = getattr(conversation, "provider_id", "") or ""
    if not provider_id:
        return False  # fail closed: no owner and no provider
    provider = communication_store.get_provider(provider_id)
    if provider is None:
        return False  # fail closed: provider cannot be resolved
    return str(provider.user_id) == str(owner_id)


def _resolve_owner_gmail_provider(owner_id: str) -> str:
    """Resolve the workspace owner's current connected Gmail provider.

    Scoped to the durable owner: candidates are Gmail outbound providers whose
    communication instance is registered for ``owner_id`` and currently
    connected. Deterministic tie-break by mailbox email.
    """
    candidates: list[tuple[str, str]] = []
    for pid, inst in outbound_list_providers().items():
        if not (hasattr(inst, 'provider_type') and inst.provider_type == "gmail"):
            continue
        comm = get_provider(pid)
        if not comm:
            continue
        user_id = getattr(comm, "_user_id", "") or ""
        connected = getattr(comm, "_connected", False)
        email = getattr(comm, "_mailbox_email", "") or ""
        if str(user_id) == str(owner_id) and bool(connected):
            candidates.append((email, pid))
    if not candidates:
        return ""
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _register_outbound_gmail_instance(comm_provider_id: str) -> None:
    """Create and register a GmailOutboundProvider instance from a connected communication provider.
    Copies tokens from the communication provider into the outbound provider.
    """
    from services.outbound.gmail_outbound import GmailOutboundProvider
    comm_instance = get_provider(comm_provider_id)
    if not comm_instance:
        log.warning("[outbound] No communication provider found for %s", comm_provider_id)
        return
    access_token = getattr(comm_instance, '_access_token', '')
    refresh_token = getattr(comm_instance, '_refresh_token', '')
    client_id = getattr(comm_instance, '_client_id', '')
    client_secret = getattr(comm_instance, '_client_secret', '')
    token_expiry = getattr(comm_instance, '_token_expiry', 0.0)
    if not access_token and not refresh_token:
        log.warning("[outbound] No tokens available for provider %s", comm_provider_id)
        return
    outbound = GmailOutboundProvider()
    outbound.configure(
        provider_id=comm_provider_id,
        access_token=access_token,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_expiry=token_expiry,
        user_id=getattr(comm_instance, '_user_id', ''),
    )
    outbound_register_instance(comm_provider_id, outbound)
    log.info("[outbound] Registered GmailOutboundProvider instance for %s", comm_provider_id)


def _restore_providers_on_startup() -> None:
    """On startup, load saved provider credentials from Supabase and restore instances.
    Refreshes tokens if expired.
    """
    log.info("[startup] Attempting provider restoration from Supabase")
    from services.supabase import load_all_provider_credentials, reconcile_connected_account_duplicates
    from services.outbound.gmail_outbound import GmailOutboundProvider
    from services.communication.gmail_provider import GmailProvider
    from services.google_auth import refresh_access_token
    from services.gmail_auth_failure import GmailReauthRequired
    try:
        reconcile_connected_account_duplicates()
    except Exception as e:
        log.warning("[startup] Connected-account duplicate reconciliation failed: %s", e)
    records = load_all_provider_credentials()
    if not records:
        log.info("[startup] No saved provider credentials found")
        return
    restored = 0
    reauth_restored = 0
    seen_user_providers: set[tuple[str, str]] = set()
    for row in records:
        try:
            user_id = row.get("id", "")
            provider_id = row.get("google_provider_id", "") or str(uuid.uuid4())
            refresh_token = row.get("google_refresh_token", "")
            access_token = row.get("google_access_token", "")
            email = row.get("email", "")
            account_id = row.get("account_id", "") or email
            client_id = row.get("google_client_id", "") or os.getenv("GOOGLE_CLIENT_ID", "")
            client_secret = row.get("google_client_secret", "") or os.getenv("GOOGLE_CLIENT_SECRET", "")
            token_expiry_str = row.get("token_expiry", "")
            account_status = row.get("status", "active")
            # Runtime dedup: exactly one provider instance per (user, provider).
            key = (user_id, "google")
            if key in seen_user_providers:
                log.warning(
                    "[startup] Skipping duplicate provider restore for user %s (already restored)",
                    user_id[:8],
                )
                continue
            seen_user_providers.add(key)
            token_expiry = 0.0
            if token_expiry_str:
                try:
                    token_expiry = datetime.fromisoformat(token_expiry_str.replace("Z", "+00:00")).timestamp()
                except Exception:
                    token_expiry = 0.0
            if not refresh_token:
                log.warning("[startup] No refresh_token for provider %s, skipping", provider_id[:12])
                continue
            if account_status == "auth_failed":
                # Already known to require re-authentication: restore the
                # instance in the reauth-required state WITHOUT attempting a
                # doomed token refresh (PR10.8.1).
                comm_provider = GmailProvider()
                comm_record = comm_provider.connect(
                    auth_token=access_token,
                    user_id=user_id,
                    email=email,
                    account_id=account_id,
                    refresh_token=refresh_token,
                    client_id=client_id,
                    client_secret=client_secret,
                )
                comm_provider.mark_reauth_required()
                register_instance(comm_record.id, comm_provider)
                log.warning(
                    "gmail_auth_reauth_required provider_id=%s user_id=%s action=reauth_required restored=yes",
                    comm_record.id[:12], user_id,
                )
                reauth_restored += 1
                continue
            import time
            if token_expiry <= time.time() + 60:
                log.info("[startup] Token expired for provider %s, refreshing", provider_id[:12])
                try:
                    token_result = refresh_access_token(refresh_token)
                    if token_result and token_result.get("access_token"):
                        access_token = token_result["access_token"]
                        token_expiry = time.time() + token_result.get("expires_in", 3600)
                        from services.supabase import update_google_access_token
                        update_google_access_token(
                            user_id,
                            access_token=access_token,
                            token_expiry=datetime.fromtimestamp(token_expiry, tz=timezone.utc).isoformat(),
                        )
                except GmailReauthRequired:
                    log.warning(
                        "gmail_auth_reauth_required provider_id=%s user_id=%s action=reauth_required restored=yes",
                        provider_id[:12], user_id,
                    )
                    comm_provider = GmailProvider()
                    comm_record = comm_provider.connect(
                        auth_token=access_token,
                        user_id=user_id,
                        email=email,
                        refresh_token=refresh_token,
                        client_id=client_id,
                        client_secret=client_secret,
                    )
                    comm_provider.mark_reauth_required()
                    register_instance(comm_record.id, comm_provider)
                    reauth_restored += 1
                    continue
                except Exception as e:
                    log.warning("[startup] Token refresh failed for provider %s: %s", provider_id[:12], e)
                    continue
            comm_provider = GmailProvider()
            from services.communication.provider_models import ProviderType
            comm_record = comm_provider.connect(
                auth_token=access_token,
                user_id=user_id,
                email=email,
                account_id=account_id,
                refresh_token=refresh_token,
                client_id=client_id,
                client_secret=client_secret,
            )
            register_instance(comm_record.id, comm_provider)
            outbound = GmailOutboundProvider()
            outbound.configure(
                provider_id=comm_record.id,
                access_token=access_token,
                refresh_token=refresh_token,
                client_id=client_id,
                client_secret=client_secret,
                token_expiry=token_expiry,
                user_id=user_id,
            )
            outbound_register_instance(comm_record.id, outbound)
            log.info("[startup] Restored provider %s (%s)", comm_record.id[:12], email)
            restored += 1
        except Exception as e:
            log.warning("[startup] Failed to restore provider: %s", e)
    log.info("[startup] Provider restoration complete: %d restored, %d reauth-required", restored, reauth_restored)


def _get_outbound_provider_for_draft(outbound_draft, owner_id: str = "") -> str:
    """Get a working outbound provider ID for a draft.

    When ``owner_id`` is provided the resolution is scoped to that workspace
    owner: the draft's stored provider is only used if it still resolves to a
    currently connected Gmail provider owned by the same user. Otherwise the
    owner's current connected Gmail provider is resolved. On successful
    fallback the draft's provider_id is updated in the outbound store so
    subsequent sends reuse the resolved provider. Returns empty string when no
    valid provider exists.
    """
    stored_ok = bool(
        outbound_draft and outbound_draft.provider_id
        and get_outbound_provider(outbound_draft.provider_id)
    )
    if stored_ok and (not owner_id or _provider_owned_by(outbound_draft.provider_id, owner_id)):
        return outbound_draft.provider_id
    if owner_id:
        found = _resolve_owner_gmail_provider(owner_id)
    else:
        found = _find_outbound_gmail_provider_id()
    if found and outbound_draft:
        if outbound_draft.provider_id != found:
            outbound_draft.provider_id = found
            from services.outbound.draft_store import draft_store as outbound_draft_store
            outbound_draft_store.update(outbound_draft)
    return found


def _resolve_provider_for_conversation(conversation: "object") -> str:
    """Resolve the connected Gmail provider used to send a conversation reply.

    Priority:
      1. Provider recorded on the conversation's thread (original send),
         if still registered in the outbound registry;
      2. The outbound provider recorded on the draft that created the thread
         (via conversation metadata draft_id);
      3. Any currently connected outbound Gmail provider.

    Returns empty string when no valid provider exists.
    """
    from services.outbound.draft_store import draft_store as outbound_draft_store
    from services.outbound.outbound_registry import get_provider

    if conversation is not None:
        from services.conversations.conversation_store import conversation_store
        from datetime import datetime, timezone

        threads = conversation_store.get_threads_for_conversation(conversation.conversation_id)
        if threads:
            threads.sort(key=lambda t: t.created_at or datetime.min.replace(tzinfo=timezone.utc))
            thread_provider_id = threads[-1].provider_id
            if thread_provider_id and get_provider(thread_provider_id):
                return thread_provider_id
        draft_id = getattr(conversation, "draft_id", "") or conversation.metadata.get("draft_id", "")
        if draft_id:
            outbound_draft = outbound_draft_store.get(draft_id)
            if outbound_draft:
                provider_id = _get_outbound_provider_for_draft(outbound_draft, owner_id="")
                if provider_id:
                    return provider_id
    return _find_outbound_gmail_provider_id()


def _sync_draft_to_outbound(
    legacy_draft: dict,
    session_token: str,
    owner_id: str = "",
) -> None:
    """Sync a legacy campaign draft into the outbound DraftStore.

    Uses workflow_id to store campaign_id for later lookup.
    Stores lead metadata in the DraftMessage metadata field.

    PR-2B: ``owner_id`` scopes provider stamping to the draft's owner. The
    previous behaviour stamped the FIRST Gmail provider in the global
    registry, so with two connected users (or after an identity divergence)
    a hydrated draft could carry another user's provider — which the send
    route's cross-user ownership check then rejected with a misleading 404
    "Draft not found". When the owner is known but has no connected Gmail
    provider we stamp an EMPTY provider id and let the send-time resolver
    (_get_outbound_provider_for_draft) bind the current one.
    """
    from services.outbound.draft_store import draft_store as outbound_draft_store
    from services.outbound.outbound_models import DraftMessage, DraftStatus, ApprovalState, Recipient
    now = datetime.now(timezone.utc).isoformat()
    lead = legacy_draft.get("lead", {})
    lead_email = lead.get("email", "")
    lead_name = lead.get("name") or f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip() or "Unknown"
    legacy_status = legacy_draft.get("status", "pending")
    status_map = {
        "pending": DraftStatus.PENDING_APPROVAL,
        "approved": DraftStatus.APPROVED,
        "rejected": DraftStatus.REJECTED,
        "draft": DraftStatus.DRAFT,
        "sent": DraftStatus.SENT,
    }
    if owner_id:
        real_provider_id = _resolve_owner_gmail_provider(owner_id)
    else:
        real_provider_id = _find_outbound_gmail_provider_id()
    sender_email = ""
    if real_provider_id:
        comm_instance = get_provider(real_provider_id)
        sender_email = getattr(comm_instance, "_mailbox_email", "") or ""
    outbound_draft = DraftMessage(
        id=legacy_draft.get("id", ""),
        provider_id=real_provider_id,
        workflow_id=legacy_draft.get("campaign_id", ""),
        subject=legacy_draft.get("subject", ""),
        body=legacy_draft.get("text", ""),
        recipient=Recipient(email=lead_email, name=lead_name),
        sender=Recipient(email=sender_email, name=""),
        status=status_map.get(legacy_status, DraftStatus.PENDING_APPROVAL),
        approval_state=ApprovalState.APPROVED if legacy_status == "approved" else ApprovalState.PENDING,
        created_at=legacy_draft.get("created_at", now),
        updated_at=now,
        metadata={
            "lead": lead,
            "tone": legacy_draft.get("tone"),
            "length": legacy_draft.get("length"),
            "lead_intelligence": legacy_draft.get("lead_intelligence"),
            "company_intelligence": legacy_draft.get("company_intelligence"),
            "session_token": session_token,
        },
    )
    existing = outbound_draft_store.get(outbound_draft.id)
    if existing:
        outbound_draft_store.update(outbound_draft)
    else:
        outbound_draft_store.create(outbound_draft)


def _outbound_to_legacy_draft(od: "DraftMessage") -> dict:
    """Convert an outbound DraftMessage back to legacy dict format for backward compat."""
    from services.outbound.outbound_models import DraftStatus
    lead = od.metadata.get("lead", {}) if od.metadata else {}
    status_map = {
        DraftStatus.DRAFT: "pending",
        DraftStatus.PENDING_APPROVAL: "pending",
        DraftStatus.APPROVED: "approved",
        DraftStatus.AUTO_APPROVED: "approved",
        DraftStatus.REJECTED: "rejected",
        DraftStatus.SENDING: "sending",
        DraftStatus.SENT: "sent",
        DraftStatus.SCHEDULED: "scheduled",
        DraftStatus.FAILED: "failed",
        DraftStatus.CANCELLED: "cancelled",
        DraftStatus.ARCHIVED: "archived",
    }
    return {
        "id": od.id,
        "campaign_id": od.workflow_id,
        "lead": lead,
        "subject": od.subject,
        "text": od.body,
        "status": status_map.get(od.status, "pending"),
        "tone": od.metadata.get("tone") if od.metadata else None,
        "length": od.metadata.get("length") if od.metadata else None,
        "lead_intelligence": od.metadata.get("lead_intelligence") if od.metadata else None,
        "company_intelligence": od.metadata.get("company_intelligence") if od.metadata else None,
        "created_at": od.created_at,
        "external_draft_id": od.external_draft_id,
        "gmail_message_id": od.gmail_message_id,
        "gmail_thread_id": od.gmail_thread_id,
    }


def _get_outbound_drafts_for_session(session_token: str) -> list[dict]:
    """Get all legacy-format drafts for a session from the outbound DraftStore.
    Merges with legacy draft_store for drafts not yet synced.
    """
    from services.outbound.draft_store import draft_store as outbound_draft_store
    outbound_all = outbound_draft_store.list_all()
    result = []
    seen_ids = set()
    for od in outbound_all.drafts:
        if od.metadata and od.metadata.get("session_token") == session_token:
            result.append(_outbound_to_legacy_draft(od))
            seen_ids.add(od.id)
    legacy_drafts = draft_store.get(session_token, [])
    for ld in legacy_drafts:
        if ld.get("id") not in seen_ids:
            result.append(ld)
    return result


_SYNONYM_STRATEGY_TABLE: list[tuple[list[str], str]] = [
    (["short", "concise", "punchy", "tighten", "trim", "cut", "fluff", "reduce"], "shorten"),
    (["longer", "expand", "more detail", "elaborate", "add more", "extend"], "lengthen"),
    (["professional", "polish", "formal", "corporate", "executive"], "professional"),
    (["casual", "conversational", "friendly", "human", "less formal", "natural", "like a founder"], "casual"),
    (["hiring", "growing", "team", "join us"], "hiring"),
    (["expansion", "expanding", "office", "new market"], "expansion"),
    (["cta", "call to action", "ending", "better ending", "ask"], "rewrite_cta"),
    (["funding", "raised", "series", "investment", "investor"], "mention_funding"),
    (["personalize", "personal", "customize", "tailor", "specific to"], "personalize"),
    (["aggressive", "urgent", "direct", "bold", "confident", "sound more confident"], "aggressive"),
    (["soften", "softer", "gentle", "gentler", "lower pressure", "less pushy"], "softer"),
    (["growth", "growing", "momentum", "traction"], "mention_growth"),
    (["launch", "product", "feature", "new"], "mention_product_launch"),
    (["punchy", "impactful", "stronger", "powerful", "persuasive"], "shorten"),
    (["robotic", "robot", "stiff", "less salesy", "salesy"], "casual"),
    (["curiosity", "intriguing", "hook"], "personalize"),
    (["credibility", "proof", "social proof", "testimonial", "case study"], "mention_growth"),
    (["opening", "first sentence", "intro", "stronger start", "hook"], "personalize"),
]


def _classify_rewrite_strategy(instruction: str) -> str:
    """Map a user's edit instruction to a rewrite strategy using synonym matching."""
    lower = instruction.lower()
    best_match = None
    best_count = 0
    for keywords, strategy in _SYNONYM_STRATEGY_TABLE:
        match_count = sum(1 for kw in keywords if kw in lower)
        if match_count > best_count:
            best_count = match_count
            best_match = strategy
    return best_match or "custom"


async def _evidence_trace(
    campaign_strategy: dict,
    company_intelligence: dict | None,
    lead_intelligence: dict | None,
    knowledge_context: dict | None = None,
) -> dict[str, Any]:
    """Retain internal provenance for every generated draft.

    Records which evidence fields were non-empty at generation time and which
    playbook sections were available to the model. Debug-only metadata —
    nothing here feeds the prompt.
    """
    evidence: list[str] = []
    ci = company_intelligence or {}
    for key, label in (
        ("company_summary", "company summary"),
        ("business_pain_summary", "business pain"),
        ("technology_summary", "technology"),
        ("growth_summary", "growth"),
        ("recent_events_summary", "recent events"),
        ("buying_signal_summary", "buying signals"),
        ("qualification_reason", "qualification reason"),
        ("recommended_pitch_angle", "pitch angle"),
    ):
        if str(ci.get(key) or "").strip() and str(ci.get(key)) != "N/A":
            evidence.append(label)
    li = lead_intelligence or {}
    for key, label in (
        ("buying_stage", "buying stage"),
        ("urgency", "urgency"),
        ("estimated_business_need", "business need"),
        ("objection_risk", "objection risk"),
        ("recommended_pitch", "pitch guidance"),
    ):
        if str(li.get(key) or "").strip() and str(li.get(key)) != "N/A":
            evidence.append(label)
    if isinstance(li.get("why_selected"), list) and li["why_selected"]:
        evidence.append("why-selected")

    strategy_used: list[str] = []
    for section in (
        "icp", "pain_points", "pain_prioritization", "personas", "proof_points",
        "differentiators", "positioning", "messaging_angles", "objection_handling",
        "cta", "outreach_strategy", "personalization",
    ):
        value = campaign_strategy.get(section)
        if value not in (None, "", [], {}):
            strategy_used.append(section)
    if strategy_used and (str(campaign_strategy.get("confidence") or "").strip()):
        strategy_used.append("confidence")

    knowledge = knowledge_context if isinstance(knowledge_context, dict) else {}

    return {
        "evidence_used": evidence,
        "strategy_used": strategy_used,
        "confidence": str(campaign_strategy.get("confidence") or ""),
        "knowledge_item_ids": list(knowledge.get("item_ids") or []),
        "knowledge_source_ids": list(knowledge.get("source_ids") or []),
        "knowledge_categories": list(knowledge.get("categories") or []),
        "knowledge_query": str(knowledge.get("query") or ""),
    }


async def _run_draft_with_retry(loop, workflow_input: dict, attempts: int = 3) -> dict:
    """Run a single draft workflow, retrying transient OpenAI failures.

    The sync workflow runs in an executor thread; a fresh attempt is made up
    to ``attempts`` times with a short backoff before re-raising.
    """
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            result = await loop.run_in_executor(None, run_workflow, workflow_input)
            return result
        except Exception as e:
            last_error = e
            if attempt < attempts - 1:
                await asyncio.sleep(1.5 * (attempt + 1))
    raise last_error


async def _process_batch_drafts(
    session_token: str,
    batch_id: str,
    leads: list[dict],
    owner_id: str,
) -> None:
    job = batch_jobs[batch_id]
    loop = asyncio.get_event_loop()

    campaign_strategy: dict = {}
    if job.get("campaign_id"):
        from services.workspace_state import load_campaign_state
        try:
            campaign = await asyncio.to_thread(
                load_campaign_state, owner_id, job.get("campaign_id"),
            )
            if campaign and isinstance(campaign.get("strategy"), dict):
                campaign_strategy = campaign["strategy"]
        except Exception as e:
            print(f"[batch] Could not load campaign strategy: {e}")

    draft_message_input = {
        "type": "draft_message",
        "campaign_strategy": campaign_strategy,
    }
    from services.knowledge.context_adapter import retrieve_knowledge_context
    strategy_query = " ".join(
        str(campaign_strategy.get(key) or "").strip()
        for key in ("icp", "messaging_angle", "value_proposition", "positioning")
        if str(campaign_strategy.get(key) or "").strip()
    )
    try:
        retrieved_knowledge = await retrieve_knowledge_context(
            owner_id,
            query=strategy_query,
            categories=["company", "icp", "messaging", "sales_offer"],
            limit=8,
        )
        draft_message_input["knowledge_context"] = retrieved_knowledge.to_dict()
        draft_message_input["_knowledge_context_trusted"] = True
    except Exception as error:
        log.warning("[batch] Knowledge retrieval skipped: %s", error)

    for i, lead in enumerate(leads):
        job["current_index"] = i
        name = (
            lead.get("name")
            or f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
            or "Unknown"
        )
        job["current_name"] = name

        try:
            workflow_result = await _run_draft_with_retry(
                loop, {**draft_message_input, "lead": lead}
            )

            draft_body = _parse_draft_body(workflow_result.get("message", ""))

            draft_entry: dict[str, Any] = {
                "id": str(uuid.uuid4()),
                "campaign_id": job.get("campaign_id"),
                "batch_id": job.get("batch_id"),
                "lead": lead,
                "subject": workflow_result.get("subject", ""),
                "text": draft_body or workflow_result.get("message", ""),
                "status": "pending",
                "tone": workflow_result.get("tone"),
                "length": workflow_result.get("length"),
                "lead_intelligence": workflow_result.get("lead_intelligence"),
                "company_intelligence": workflow_result.get("company_intelligence"),
                "evidence_trace": await _evidence_trace(
                    campaign_strategy,
                    workflow_result.get("company_intelligence"),
                    workflow_result.get("lead_intelligence"),
                    draft_message_input.get("knowledge_context"),
                ),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

            from services.workspace_state import persist_draft_awaited
            if not await persist_draft_awaited(owner_id, draft_entry):
                raise RuntimeError("Draft could not be persisted")

            job["drafts"].append(draft_entry)
            job["completed"] = i + 1

            publish(session_token, WMEventType.DRAFT_GENERATED, {
                "id": draft_entry["id"],
                "campaign_id": draft_entry["campaign_id"],
                "lead_id": lead.get("id", ""),
                "lead_name": name,
                "subject": draft_entry["subject"],
                "body_preview": draft_entry["text"][:200],
            }, actor="system")

            _sync_draft_to_outbound(draft_entry, session_token, owner_id=owner_id)

        except Exception as e:
            print(f"[batch] Draft failed for lead {i} ({name}): {e}")
            publish(session_token, WMEventType.DRAFT_FAILED, {
                "lead_index": i,
                "lead_name": name,
                "error": str(e),
                "campaign_id": job.get("campaign_id"),
            }, actor="system")
            job["completed"] = i + 1

    job["status"] = "completed"

    campaign_id = job.get("campaign_id")
    campaign_name = None
    if campaign_id:
        from services.workspace_state import persist_campaign_update
        finished_at = datetime.now(timezone.utc).isoformat()
        generation: dict[str, Any] = {
            "batch_id": job.get("batch_id"),
            "total": job.get("total", 0),
            "completed": job.get("completed", 0),
            "status": "completed" if job.get("drafts") else "failed",
            "error": job.get("error"),
            "started_at": job.get("started_at"),
            "finished_at": finished_at,
        }
        if not job.get("drafts"):
            persist_campaign_update(owner_id, campaign_id, {"generation": generation})
            job["status"] = "failed"
            job["error"] = "No drafts were generated"
            return
        if not persist_campaign_update(owner_id, campaign_id, {"generation": generation}):
            job["status"] = "failed"
            job["error"] = "Campaign generation metadata could not be persisted"
            return
        from services.workspace_state import load_workspace_state
        campaigns = await asyncio.to_thread(load_workspace_state, owner_id, include_details=False)
        campaign_name = next((c.get("name") for c in campaigns["campaigns"] if c.get("id") == campaign_id), "")
        publish(session_token, WMEventType.CAMPAIGN_UPDATED, {
            "campaign_id": campaign_id,
            "generation": generation,
        }, actor="system")
    if campaign_name:
        record_drafts_generated(session_token, campaign_name, job.get("completed", 0))

# ── Logging Middleware ──

# Rate-limit identity cache: session_token -> (expires_at, user_id).
#
# PR-P1.1: rate limiting only needs the owning user id, not the full web
# session summary (which costs ~9-10 sequential Supabase round trips and was
# executed synchronously on the event loop for EVERY request). We resolve the
# identity via the cheap `get_web_session` lookup (1-3 queries) off the event
# loop, and memoize it briefly. Only the non-sensitive user-id string is
# cached; no conversations/messages/tasks data is involved.
_RATE_LIMIT_IDENTITY_TTL_SECONDS = 30.0
_RATE_LIMIT_IDENTITY_CACHE_MAX = 5000
_rate_limit_identity_cache: dict[str, tuple[float, str]] = {}


async def _resolve_rate_limit_identity(session_token: str) -> str:
    """Return the user id owning this web-session token ("").

    Deliberately cheap: never loads conversations/messages/workflow state.
    Results are cached in-process for a short TTL so bursts of requests from
    one tab cost at most one small lookup per TTL window.
    """
    if not session_token:
        return ""
    now = time.monotonic()
    cached = _rate_limit_identity_cache.get(session_token)
    if cached is not None:
        expires_at, cached_user_id = cached
        if expires_at > now:
            return cached_user_id
        _rate_limit_identity_cache.pop(session_token, None)

    try:
        # Uses the module-level `engine` instance so tests (and future
        # decorators) can patch identity resolution in one place.
        user_id = await asyncio.to_thread(engine.get_web_session_user_id, session_token)
    except Exception as error:  # noqa: BLE001 — rate limiting must never fail a request
        log.warning("rate_limit_identity_lookup_failed error=%s", error)
        return ""
    if user_id:
        if len(_rate_limit_identity_cache) >= _RATE_LIMIT_IDENTITY_CACHE_MAX:
            # Opportunistic prune; the map is bounded so it cannot grow forever.
            expired = [k for k, (exp, _) in _rate_limit_identity_cache.items() if exp <= now]
            for key in expired:
                _rate_limit_identity_cache.pop(key, None)
            if len(_rate_limit_identity_cache) >= _RATE_LIMIT_IDENTITY_CACHE_MAX:
                _rate_limit_identity_cache.clear()
        _rate_limit_identity_cache[session_token] = (
            now + _RATE_LIMIT_IDENTITY_TTL_SECONDS,
            user_id,
        )
    return user_id


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """PR10.5 — production rate limiting.

    Runs inside ``log_requests`` (which sets the request/correlation ID) but
    before any route handler, so outbound sends are rejected with 429 before
    any side effect. Identity is derived server-side (web-session user id or
    normalized client IP); client-supplied identifiers are never read.

    PR-P1.1 — identity resolution no longer loads the full web-session
    summary. Only the owning user id is needed here; it is resolved with the
    minimal lookup off the event loop and short-cached.
    """
    from services.rate_limit import classify_rate_limit, rate_limiter

    category = classify_rate_limit(request.url.path)
    if category == "health":
        return await call_next(request)

    limit = rate_limiter.limits.get(category, 300)
    if limit <= 0:
        return await call_next(request)

    session_token = _session_token_from_request(request)
    identity = f"ip:{request.client.host if request.client else 'unknown'}"
    if session_token:
        user_id = await _resolve_rate_limit_identity(session_token)
        if user_id:
            identity = f"u:{user_id}"
        try:
            # Expose the resolved owner so downstream handlers can reuse it
            # instead of re-resolving (progressive de-duplication aid).
            request.state.rate_limit_user_id = user_id or None
        except Exception:
            pass

    allowed, retry_after = await rate_limiter.allow(f"{category}:{identity}", limit)
    if not allowed:
        req_id = request_id_var.get("")
        log.warning(
            "rate_limit_exceeded request_id=%s category=%s identity_scope=%s status=429",
            req_id, category, identity.split(":")[0],
        )
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded. Please try again shortly."},
            headers={
                "Retry-After": str(retry_after) if retry_after else "60",
                "X-Request-ID": req_id,
            },
        )
    return await call_next(request)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    req_id = str(uuid.uuid4())[:8]
    request_id_var.set(req_id)
    start = time.time()
    response = await call_next(request)
    duration = (time.time() - start) * 1000
    log.info(
        "%s %s %s %.0fms %s",
        req_id, request.method, redact_session_path(request.url.path), duration, response.status_code,
    )
    response.headers["X-Request-ID"] = req_id
    response.headers["X-API-Version"] = "1"
    return response


# ── CORS Configuration ──
_frontend_origins = {
    "http://localhost:3000",
    "http://127.0.0.1:3000",
}
if os.getenv("FRONTEND_URL"):
    _frontend_origins.add(os.environ["FRONTEND_URL"].rstrip("/"))
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(_frontend_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateWebSessionRequest(BaseModel):
    display_name: str | None = None


class CopilotContextModel(BaseModel):
    current_page: str | None = None
    page_context: dict | None = None
    available_actions: list[str] | None = None
    message_history: list[dict] | None = None


class SendWebMessageRequest(BaseModel):
    text: str
    copilot: CopilotContextModel | None = None


def _register_outbound_providers() -> None:
    try:
        from services.outbound.outbound_registry import register_outbound_provider
        from services.outbound.gmail_outbound import GmailOutboundProvider
        register_outbound_provider(GmailOutboundProvider)
        log.info("GmailOutboundProvider registered")
    except Exception as e:
        log.warning("Failed to register GmailOutboundProvider: %s", e)


def _register_execution_adapters() -> None:
    from services.execution.credential_factory import resolve_google_credentials

    from services.adapters.google.gmail import GmailAdapter
    gmail = GmailAdapter()
    gmail_bridge = BridgeAdapter(
        sdk_adapter=gmail,
        action_mapping={
            TaskType.SEND_EMAIL: "gmail_send_email",
        },
        credentials_factory=resolve_google_credentials,
    )
    _execution_adapter_registry.register(gmail_bridge, priority=100, version="1.0.0")
    log.info(
        "Execution adapter registered: %s (types=%s, factory=%s)",
        gmail_bridge.adapter_type,
        [t.value for t in gmail_bridge.supported_task_types],
        "resolve_google_credentials",
    )

    from services.adapters.google.calendar import CalendarAdapter
    calendar = CalendarAdapter()
    calendar_bridge = BridgeAdapter(
        sdk_adapter=calendar,
        action_mapping={
            TaskType.CALENDAR_LIST_EVENTS: "calendar_list_events",
            TaskType.CALENDAR_GET_EVENT: "calendar_get_event",
            TaskType.CALENDAR_CREATE_EVENT: "calendar_create_event",
            TaskType.CALENDAR_UPDATE_EVENT: "calendar_update_event",
            TaskType.CALENDAR_DELETE_EVENT: "calendar_delete_event",
        },
        credentials_factory=resolve_google_credentials,
    )
    _execution_adapter_registry.register(calendar_bridge, priority=100, version="1.0.0")
    log.info(
        "Execution adapter registered: %s (types=%s, factory=%s)",
        calendar_bridge.adapter_type,
        [t.value for t in calendar_bridge.supported_task_types],
        "resolve_google_credentials",
    )

    from services.adapters.analysis import ReplyAnalysisAdapter
    analysis = ReplyAnalysisAdapter()
    analysis_bridge = BridgeAdapter(
        sdk_adapter=analysis,
        action_mapping={
            TaskType.ANALYZE_REPLY: "analyze_reply",
        },
    )
    _execution_adapter_registry.register(analysis_bridge, priority=100, version="1.0.0")
    log.info(
        "Execution adapter registered: %s (types=%s)",
        analysis_bridge.adapter_type,
        [t.value for t in analysis_bridge.supported_task_types],
    )

    from services.adapters.crm import CrmAdapter
    crm = CrmAdapter()
    crm_bridge = BridgeAdapter(
        sdk_adapter=crm,
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
    _execution_adapter_registry.register(crm_bridge, priority=100, version="1.0.0")
    log.info(
        "Execution adapter registered: %s (types=%s)",
        crm_bridge.adapter_type,
        [t.value for t in crm_bridge.supported_task_types],
    )

    from services.adapters.memory import MemoryAdapter
    memory_adapter = MemoryAdapter()
    memory_bridge = BridgeAdapter(
        sdk_adapter=memory_adapter,
        action_mapping={
            TaskType.STORE_MEMORY: "store_memory",
            TaskType.RETRIEVE_MEMORY: "retrieve_memory",
            TaskType.SEARCH_MEMORY: "search_memory",
            TaskType.UPDATE_MEMORY: "update_memory",
            TaskType.DELETE_MEMORY: "delete_memory",
            TaskType.SUMMARIZE_MEMORY: "summarize_memory",
        },
    )
    _execution_adapter_registry.register(memory_bridge, priority=100, version="1.0.0")
    log.info(
        "Execution adapter registered: %s (types=%s)",
        memory_bridge.adapter_type,
        [t.value for t in memory_bridge.supported_task_types],
    )


def _register_credential_descriptors() -> None:
    from services.adapters.google.gmail.gmail_adapter import CREDENTIAL_DESCRIPTORS
    for desc in CREDENTIAL_DESCRIPTORS:
        descriptor = CredentialDescriptor(
            name=desc["name"],
            display_name=desc.get("display_name", desc["name"]),
            description=desc.get("description", ""),
            auth_type=desc["auth_type"],
        )
        if not _credential_registry.exists(descriptor.name):
            _credential_registry.register(descriptor)
            log.info("Credential descriptor registered: %s", descriptor.name)


def _register_credential_instance(access_token: str, refresh_token: str, email: str) -> None:
    instance = CredentialInstance(
        credential_id=f"google_oauth2::{email}",
        descriptor_name="google_oauth2",
        values={
            "access_token": access_token,
            "refresh_token": refresh_token,
            "email": email,
        },
    )
    log.info("Credential instance registered: %s", instance.credential_id)


_scheduler_task: asyncio.Task | None = None


def _restore_providers_for_startup() -> None:
    """Restore provider instances and recover interrupted work at startup.

    Runs BEFORE the outbound scheduler task is created so the scheduler can
    never tick against an empty provider registry (PR10.8 startup ordering).
    After restoration, runtime providers are reconciled to the invariant
    (exactly one active provider per user/provider type) so a process that
    accumulated duplicates self-heals on the next boot (PR10.8.2.2).
    """
    try:
        recovered = recover_all()
        if recovered["total_recovered"] > 0:
            log.info("Workflow recovery: %s", recovered)
    except Exception as e:
        log.warning("Workflow recovery failed: %s", e)
    try:
        register_provider(GmailProvider)
        log.info("Gmail provider registered")
    except Exception as e:
        log.warning("Gmail provider registration failed: %s", e)
    try:
        _register_credential_descriptors()
    except Exception as e:
        log.warning("Credential descriptor registration failed: %s", e)
    try:
        _restore_providers_on_startup()
    except Exception as e:
        log.warning("Provider startup restoration failed: %s", e)
    try:
        _reconcile_runtime_providers()
    except Exception as e:
        log.warning("Runtime provider reconciliation failed: %s", e)


def _reconcile_runtime_providers() -> None:
    """Enforce the one-active-provider-per-(user, provider_type) invariant.

    If more than one runtime provider record exists for the same
    (user, provider type) in the communication store, keep the newest active
    one and remove the others from the communication store, the provider
    registry, and the outbound registry. This is a runtime invariant fix, not
    an API-level dedup: after this, provider_list returns one logical account
    because only one exists.
    """
    from services.communication.provider_models import ProviderType
    from services.outbound.outbound_registry import remove_instance as outbound_remove

    by_key: dict[tuple[str, str], list[Any]] = {}
    for provider in communication_store.list_providers():
        by_key.setdefault(
            (provider.user_id, provider.provider_type.value if hasattr(provider.provider_type, "value") else str(provider.provider_type)),
            [],
        ).append(provider)

    removed = 0
    for key, group in by_key.items():
        if len(group) <= 1:
            continue
        # Newest active wins; a provider record that is auth_failed is NOT
        # preferred over a healthy one (healthier credential wins).
        canonical = max(
            group,
            key=lambda p: (
                p.status.value not in ("auth_failed", "expired_token", "scope_insufficient", "disconnected", "offline"),
                p.created_at or "",
            ),
        )
        for other in group:
            if other.id == canonical.id:
                continue
            try:
                communication_store.remove_provider(other.id)
            except Exception:
                pass
            try:
                remove_instance(other.id)
            except Exception:
                pass
            try:
                outbound_remove(other.id)
            except Exception:
                pass
            removed += 1
            log.info(
                "runtime_provider_reconciled provider_id=%s user_id=%s provider_type=%s reason=duplicate",
                other.id[:12], other.user_id[:8] if other.user_id else "", key[1],
            )
    if removed:
        log.info("runtime_provider_reconcile removed=%d duplicate provider record(s)", removed)


def _start_outbound_scheduler() -> None:
    global _scheduler_task
    try:
        from services.outbound.outbound_scheduler import outbound_scheduler
        _scheduler_task = asyncio.create_task(outbound_scheduler.run())
        log.info("Outbound scheduler started")
    except Exception as e:
        log.warning("Failed to start outbound scheduler: %s", e)


@app.get("/", response_class=PlainTextResponse)
def read_root():
    return "Loqi backend running"


# ── Gmail OAuth Endpoints ──


@app.get("/api/auth/gmail/url")
async def gmail_auth_url(request: Request, session_token: str = ""):
    from services.google_auth import get_google_auth_url
    from services.oauth_state import issue_state
    try:
        # SaaS-2.4: the OAuth state subject must be a provable identity. The
        # caller may provide a canonical bearer token OR their own web-session
        # token; a bare client-supplied user_id must NEVER become the subject
        # (otherwise an unauthenticated caller could mint state bound to a
        # victim's user id and plant their own Gmail credentials on the
        # victim's connected_accounts row).
        user_id = ""
        if request.headers.get("authorization", ""):
            from services.identity.api import get_authenticated_user_id
            user_id = await get_authenticated_user_id(request)
        if not user_id and session_token:
            # Only accept a web-session token that actually resolves to a user.
            # PR-2B: identity-only + cached; the full summary was overkill here.
            try:
                summary = await _cached_session_identity(session_token)
            except Exception:
                summary = None
            if summary and summary.get("user_id"):
                user_id = str(summary["user_id"])
        if not user_id:
            raise HTTPException(
                status_code=401,
                detail="Authentication required to connect a provider",
            )
        # Single-use server-side state token: the callback verifies it before
        # exchanging the authorization code (CSRF protection). Durable so a
        # callback landing on another instance/after restart still validates.
        state = await issue_state(user_id)
        url = get_google_auth_url(state=state)
        return {"ok": True, "url": url}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class GmailCallbackResponse(BaseModel):
    ok: bool
    provider_id: str = ""
    email: str = ""
    error: str = ""


# Serializes Gmail provider connect/replace sequences (OAuth callback, legacy
# /providers/connect, startup restore) so two concurrent connections for the
# same user can never register two runtime providers (PR10.8.2.1 invariant:
# exactly ONE active Gmail provider per user/provider type).
#
# PR-2A: per-user asyncio.Lock replaces the previous GLOBAL threading.Lock,
# which serialized unrelated users' OAuth completions behind each other while
# blocking the event loop. Same-user connects still serialize; different
# users are fully independent. The dict is bounded: when it exceeds the cap,
# entries for users with no in-flight connect are pruned.
_GMAIL_CONNECT_LOCKS_MAX = 4096
_gmail_connect_locks: dict[str, asyncio.Lock] = {}


def _gmail_connect_lock(user_id: str) -> asyncio.Lock:
    if not user_id:
        user_id = "_anonymous_"
    lock = _gmail_connect_locks.get(user_id)
    if lock is None:
        if len(_gmail_connect_locks) >= _GMAIL_CONNECT_LOCKS_MAX:
            for key in [k for k, l in _gmail_connect_locks.items() if not l.locked()]:
                _gmail_connect_locks.pop(key, None)
        lock = _gmail_connect_locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            _gmail_connect_locks[user_id] = lock
    return lock


def _remove_existing_gmail_provider(user_id: str) -> None:
    """Disconnect and remove any running Gmail provider instances for a user.

    Each successful OAuth reconnect issues a fresh provider instance; the old
    (e.g. reauth-required) instance must be replaced so the user never ends
    up with duplicate Gmail providers (PR10.8.1).
    """
    from services.communication.provider_models import ProviderType
    from services.outbound.outbound_registry import remove_instance as outbound_remove
    removed = 0
    for pid, instance in list(list_providers().items()):
        if getattr(instance, "provider_type", None) is not ProviderType.GMAIL:
            continue
        if getattr(instance, "_user_id", "") != user_id:
            continue
        try:
            instance.disconnect()
        except Exception:
            pass
        remove_instance(pid)
        try:
            outbound_remove(pid)
        except Exception:
            pass
        # Remove the provider record from the communication store too, so the
        # Settings API (which aggregates from the store) never sees the stale
        # entry after a reconnect (PR10.8.2 live fix).
        try:
            communication_store.remove_provider(pid)
        except Exception:
            pass
        removed += 1
    if removed:
        log.info("[oauth] Replaced %d existing Gmail provider(s) for user %s", removed, user_id[:8])


def _frontend_postmessage_origin() -> str:
    """Origin the OAuth callback may postMessage to (the Loqi frontend).

    PR10.8.x: the callback must NOT broadcast to '*' — it targets the
    configured frontend origin (FRONTEND_ORIGIN or FRONTEND_URL). Falls back
    to '*' only in development when no frontend origin is configured; the
    receiving frontend listener always validates event.origin strictly.
    """
    return os.getenv("FRONTEND_ORIGIN") or os.getenv("FRONTEND_URL") or ""


async def _resolve_oauth_state_user(state: str) -> str:
    """Resolve the OAuth callback state to the durable Loqi user id.

    Only server-issued, single-use state tokens are accepted (issued by
    ``services.oauth_state.issue_state``). Missing/invalid/expired/used state
    is rejected — there is no unverified fallback identity.
    """
    from services.oauth_state import consume_state
    user_id, _context = await consume_state(state)
    if not user_id or user_id == "gmail_user":
        return ""
    from services.supabase import get_user
    if get_user(user_id):
        return user_id
    return user_id


async def _perform_gmail_oauth_persistence(
    *,
    user_id: str,
    access_token: str,
    refresh_token: str,
    email: str,
    account_id: str,
) -> "CommunicationProvider":
    """PR-2A: complete one Gmail connection for a user.

    Sequence (all under a per-user lock):
      1. remove any previous runtime Gmail provider for this user
      2. connect runtime instance + register inbound/outbound
      3. persist durably to connected_accounts (authoritative)
      4. verify the durable record is actually readable
    If step 3 or 4 fails, runtime state from this attempt is rolled back and
    the exception propagates — the callback must never report success without
    a durable record. Never logs tokens/secrets.
    """
    from services.google_auth import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
    from services.supabase import (
        get_durable_providers_for_user,
        sync_connected_account,
    )

    lock = _gmail_connect_lock(user_id)
    async with lock:
        log.info(
            "[oauth] provider persistence started user=%s email=%s",
            user_id[:8], email or "(unknown)",
        )
        _remove_existing_gmail_provider(user_id)
        provider = GmailProvider()
        provider_record = provider.connect(
            auth_token=access_token,
            user_id=user_id,
            email=email,
            account_id=account_id,
            scope=",".join([
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/gmail.send",
            ]),
            refresh_token=refresh_token,
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
        )
        register_instance(provider_record.id, provider)
        _register_outbound_gmail_instance(provider_record.id)

        async def _rollback_runtime() -> None:
            """Remove runtime state created by THIS attempt after a durable
            failure, so a reported failure never leaves a half-connection."""
            try:
                provider.disconnect()
            except Exception:
                pass
            remove_instance(provider_record.id)
            try:
                from services.outbound.outbound_registry import remove_instance as outbound_remove
                outbound_remove(provider_record.id)
            except Exception:
                pass
            try:
                communication_store.remove_provider(provider_record.id)
            except Exception:
                pass

        token_expiry_iso = ""
        token_expiry_epoch = getattr(provider, "_token_expiry", 0.0)
        if token_expiry_epoch:
            token_expiry_iso = datetime.fromtimestamp(token_expiry_epoch, tz=timezone.utc).isoformat()

        saved = await asyncio.to_thread(
            sync_connected_account,
            user_id,
            provider="google",
            account_id=account_id,
            email=email,
            access_token=access_token,
            refresh_token=refresh_token,
            token_expiry=token_expiry_iso,
            communication_provider_id=provider_record.id,
        )
        if not saved:
            await _rollback_runtime()
            log.error("[oauth] provider persistence failed user=%s", user_id[:8])
            raise RuntimeError("Connected account could not be persisted")

        # Verify the durable record is genuinely visible through the same
        # read path /providers uses — closes the write/read gap completely.
        try:
            durable_rows = await asyncio.to_thread(get_durable_providers_for_user, user_id, "google")
        except Exception as error:
            await _rollback_runtime()
            log.error("[oauth] provider persistence verification failed user=%s error_type=%s",
                      user_id[:8], type(error).__name__)
            raise RuntimeError("Connected account persistence could not be verified") from error
        if not any(r.get("communication_provider_id") == provider_record.id for r in durable_rows):
            await _rollback_runtime()
            log.error("[oauth] persisted provider not visible in durable lookup user=%s", user_id[:8])
            raise RuntimeError("Connected account persistence could not be verified")

        _register_credential_instance(access_token, refresh_token, email)
        # PR-2B: the cached identity carries gmail_connected — drop stale
        # entries for this user so /gmail + resolvers reflect the new state.
        try:
            from services.session_cache import session_cache
            await session_cache.invalidate_user(user_id)
        except Exception:
            pass
        log.info(
            "[oauth] provider persistence succeeded user=%s provider=%s",
            user_id[:8], provider_record.id[:8],
        )
        return provider_record


@app.get("/api/auth/gmail/callback")
async def gmail_auth_callback(code: str = "", state: str = "", error: str = ""):
    import json
    from services.google_auth import exchange_code_for_tokens
    from fastapi.responses import HTMLResponse
    ok = False
    provider_id = ""
    email_val = ""
    error_msg = error or ""
    try:
        if error:
            raise Exception(f"Google OAuth error: {error}")
        if not code:
            raise Exception("No authorization code provided")
        _user_id = await _resolve_oauth_state_user(state)
        if not _user_id:
            raise Exception("Invalid or expired OAuth state")
        log.info("[oauth] state accepted user=%s", _user_id[:8])
        tokens = exchange_code_for_tokens(code)
        access_token = tokens.get("access_token", "")
        refresh_token = tokens.get("refresh_token", "")
        email_val = tokens.get("email", "")
        account_id = tokens.get("account_id", "") or email_val
        log.info("[oauth] token exchange succeeded user=%s", _user_id[:8])
        provider_record = await _perform_gmail_oauth_persistence(
            user_id=_user_id,
            access_token=access_token,
            refresh_token=refresh_token,
            email=email_val,
            account_id=account_id,
        )
        ok = True
        provider_id = provider_record.id
        log.info("[oauth] callback success user=%s provider=%s", _user_id[:8], provider_id[:8])
        try:
            from services.events_bus import event_bus
            await event_bus.publish_user_event(
                _user_id, "provider.connected",
                {"provider": "gmail", "email": email_val},
                status="connected",
            )
        except Exception:
            pass
    except Exception as e:
        error_msg = str(e)
        log.error("[oauth] callback failed error_type=%s", type(e).__name__)
    payload = json.dumps({"ok": ok, "provider_id": provider_id, "email": email_val, "error": error_msg})
    status_text = "✓ Gmail Connected" if ok else "✗ Gmail Connection Failed"
    pm_target = _frontend_postmessage_origin() or "*"
    html = f"""<!DOCTYPE html>
<html><body style="font-family:sans-serif;background:#0f172a;color:#e2e8f0;padding:40px;text-align:center">
<h2>{status_text}</h2>
<p style="color:#94a3b8">{email_val or error_msg}</p>
<p style="color:#6b7280;font-size:13px">You can close this window.</p>
<script>
if (window.opener) {{
    window.opener.postMessage({{ type: 'gmail-oauth', payload: {payload} }}, {json.dumps(pm_target)});
    setTimeout(function() {{ window.close(); }}, 500);
}}
</script>
</body></html>"""
    return HTMLResponse(content=html)


@app.get("/health")
def health():
    # Liveness only: no external calls (no Supabase/Gmail/OpenAI), no secrets.
    return {
        "status": "healthy",
        "version": "v2",
        "uptime": int(time.time() - _start_time),
        "database": "configured" if os.getenv("SUPABASE_URL") else "unconfigured",
        "providers": "ready",
    }


@app.post("/webhook")
async def telegram_webhook(request: Request):
    # PR10.8.3: validate the Telegram webhook secret when one is configured
    # (set via TELEGRAM_WEBHOOK_SECRET when registering the bot webhook with
    # Telegram's secret_token). Without it, anyone could POST fabricated
    # Telegram messages that the bot would act on.
    _webhook_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    if _webhook_secret:
        header_value = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not header_value or not hmac.compare_digest(header_value, _webhook_secret):
            raise HTTPException(status_code=403, detail="Invalid webhook secret")
    else:
        log.warning(
            "webhook_unauth TELEGRAM_WEBHOOK_SECRET is not configured — /webhook is unauthenticated"
        )
    try:
        data = await request.json()
        if "message" in data and "text" in data["message"]:
            chat_id = data["message"]["chat"]["id"]
            telegram_id = str(data["message"].get("from", {}).get("id", chat_id))
            username = data["message"].get("from", {}).get("username")
            text = data["message"]["text"]
            await asyncio.to_thread(
                process_message, chat_id, telegram_id, text, username=username,
            )
            publish(f"telegram:{telegram_id}", WMEventType.MESSAGE_RECEIVED, {
                "chat_id": chat_id,
                "telegram_id": telegram_id,
                "from": username or telegram_id,
                "text_preview": text[:200],
                "channel": "telegram",
            }, actor="user")

        return {"status": "ok"}
    except Exception as error:
        print(f"Error processing webhook: {error}")
        return {"status": "error", "message": str(error)}


@app.post("/api/web/session")
async def create_web_session(payload: CreateWebSessionRequest, request: Request):
    try:
        # An authenticated caller must never receive a second identity: the
        # web session binds to the authenticated user's existing row. The
        # session token stays the transport key; the workflow_sessions
        # mapping keeps it resolvable to that single user id.
        user_id = None
        canonical_session_id = ""
        if request.headers.get("authorization", ""):
            from services.identity.dependencies import get_current_auth
            try:
                # SaaS-1.6: an authenticated bootstrap binds the web-session
                # token to the canonical identity session so the web-session
                # cannot outlive (or diverge from) the canonical session.
                _auth = await get_current_auth(request)
                user_id = _auth.user_id
                canonical_session_id = _auth.session_id
            except HTTPException:
                # Failed authentication falls back to an anonymous web
                # session rather than failing the whole bootstrap request.
                user_id = None
                canonical_session_id = ""
        result = await asyncio.to_thread(
            engine.create_web_session,
            display_name=payload.display_name,
            user_id=user_id,
        )
        if user_id and canonical_session_id:
            from services.web_session_binding import bind_web_session
            await bind_web_session(
                result.get("session_token", ""),
                user_id,
                canonical_session_id,
            )
            from services.workspace_state import ensure_workspace
            await asyncio.to_thread(ensure_workspace, user_id)
        return result
    except ValueError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@app.get("/api/web/session/{session_token}")
async def get_web_session(session_token: str, request: Request = None):
    session_token = _session_token_from_request(request)
    data = await asyncio.to_thread(engine.get_web_session_summary, session_token)
    if data is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return data


@app.get("/api/web/session/{session_token}/messages")
async def get_web_session_messages(session_token: str, request: Request = None):
    session_token = _session_token_from_request(request)
    return {
        "ok": True,
        "messages": engine.list_messages(channel="web", external_user_id=session_token),
    }


@app.post("/api/web/session/{session_token}/messages")
async def post_web_session_message(
    session_token: str,
    payload: SendWebMessageRequest,
    request: Request,
):
    session_token = _session_token_from_request(request)
    import time; _t0 = time.time()
    print(f"[TRACE] 1 | ENTERED ENDPOINT | post_web_session_message | +0ms")
    summary = await asyncio.to_thread(engine.get_web_session_summary, session_token)

    if summary is None:
        user_id = None
        canonical_session_id = ""
        if request.headers.get("authorization", ""):
            from services.identity.dependencies import get_current_auth
            try:
                _auth = await get_current_auth(request)
                user_id = _auth.user_id
                canonical_session_id = _auth.session_id
            except HTTPException:
                user_id = None
                canonical_session_id = ""
        created = engine.create_web_session(
            display_name="web-user",
            user_id=user_id,
        )
        if created is None:
            raise HTTPException(status_code=500, detail="Unable to create session")
        # SaaS-1.6 / W1: bind the web session to the canonical session so that
        # revocation of the canonical session (logout/password change) also
        # invalidates this web session instead of leaving it live forever.
        if user_id and canonical_session_id:
            from services.web_session_binding import bind_web_session
            await bind_web_session(
                created["session_token"], user_id, canonical_session_id,
            )
        summary = await asyncio.to_thread(engine.get_web_session_summary, created["session_token"])
        if summary is None:
            raise HTTPException(status_code=500, detail="Session creation failed")
        return await asyncio.to_thread(
            engine.handle_message,
            channel="web",
            external_user_id=created["session_token"],
            text=payload.text,
            username=summary.get("display_name"),
        )

    if payload.copilot and payload.copilot.current_page:
        workspace_context = _build_copilot_workspace_context(
            session_token,
            current_page=payload.copilot.current_page,
            page_context=payload.copilot.page_context,
            user_id=summary.get("user_id"),
        )
        analysis = workspace_context.get("analysis", {})
        snapshot = workspace_context.get("snapshot", {})
        cf = analysis.get("current_focus", {})
        rna = analysis.get("recommended_next_action", {})
        priorities = analysis.get("campaign_priorities", [])
        health = analysis.get("workspace_health", {})
        print(
            f"[COPILOT_DEBUG] page={payload.copilot.current_page} "
            f"message=\"{payload.text[:60]}\" "
            f"campaign_count={snapshot.get('campaign_count', 0)} "
            f"pending_drafts={snapshot.get('drafts', {}).get('pending', 0)} "
            f"campaigns_ready={snapshot.get('campaigns_ready', 0)} "
            f"focus={cf.get('focus', 'none')} "
            f"recommended={rna.get('title', 'none')} "
            f"top_priority={priorities[0].get('name', 'none') if priorities else 'none'} "
            f"health={health.get('overall_health', 'unknown')} "
            f"timeline_events={len(snapshot.get('timeline', []))} "
            f"memory_action={snapshot.get('memory', {}).get('last_action', 'none')}"
        )
        from services.conversational_response_generator import generate_copilot_response
        # PR-P1.2: generate_copilot_response performs a synchronous OpenAI
        # HTTP call (20s timeout). Offload to a worker thread so a slow LLM
        # response cannot freeze the event loop for unrelated requests.
        response_text = await asyncio.to_thread(
            generate_copilot_response,
            user_message=payload.text,
            copilot_context={
                **(payload.copilot.model_dump()),
                "workspace_context": workspace_context,
            },
            context={
                "user_id": summary.get("user_id"),
                "service": "",
                "target": "",
            },
        )
        print(f"[COPILOT_TRACE] page={payload.copilot.current_page} message={payload.text[:60]} history_len={len(payload.copilot.message_history or [])}")
        msg = _message(role="assistant", message_type="text", text=response_text)
        return {"ok": True, "messages": [msg], "events": []}

    _result = await asyncio.to_thread(
        engine.handle_message,
        channel="web",
        external_user_id=session_token,
        text=payload.text,
        username=summary.get("display_name"),
    )
    publish(session_token, WMEventType.MESSAGE_RECEIVED, {
        "from": summary.get("display_name", "web-user"),
        "text_preview": payload.text[:200],
        "channel": "web",
    }, actor="user")
    print(f"[TRACE] 10 | RESPONSE RETURNED | post_web_session_message | +{int((time.time()-_t0)*1000)}ms")
    return _result


class BatchDraftRequest(BaseModel):
    leads: list[dict]
    campaign_id: str | None = None


class RefineDraftRequest(BaseModel):
    edit_request: str
    previous_message: str
    lead: dict
    campaign_id: str | None = None
    campaign_name: str | None = None
    company: str | None = None
    contact: str | None = None
    role: str | None = None
    industry: str | None = None
    messaging_angle: str | None = None
    business_summary: str | None = None


class UpdateDraftRequest(BaseModel):
    text: str


class KnowledgeItemCreateRequest(BaseModel):
    category: str
    title: str
    summary: str = ""
    content: dict = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    source_type: str = "user_input"
    source_id: str = ""


class KnowledgeItemUpdateRequest(BaseModel):
    title: str | None = None
    summary: str | None = None
    content: dict | None = None
    tags: list[str] | None = None
    source_type: str | None = None
    source_id: str | None = None


class KnowledgeSourceCreateRequest(BaseModel):
    title: str
    source_type: str = "user_input"
    content: str = ""
    reference: str = ""
    metadata: dict = Field(default_factory=dict)


class KnowledgeSourceUpdateRequest(BaseModel):
    title: str | None = None
    source_type: str | None = None
    content: str | None = None
    reference: str | None = None
    metadata: dict | None = None


class SaveCampaignRequest(BaseModel):
    name: str
    objective: str = ""
    search_query: str = ""
    discovery_id: str = ""
    lead_count: int = 0
    leads: list[dict] | None = None
    strategy: dict | None = None
    status: str = "planning"


class UpdateCampaignRequest(BaseModel):
    name: str | None = None
    objective: str | None = None
    strategy: dict | None = None
    status: str | None = None


# Campaign status is the LIFECYCLE only (planning → active/paused → completed).
# Workflow steps (strategy, leads, drafts, review, sending) are DERIVED from
# persisted state and exposed as current_step — never stored in status.
VALID_CAMPAIGN_STATUSES = {
    "planning", "active", "paused", "completed",
    "archived", "cancelled", "failed", "deleted",
}


class AttachDiscoveryRequest(BaseModel):
    discovery_id: str


class AddCampaignLeadRequest(BaseModel):
    lead: dict
    discovery_id: str = ""


class LeadDecisionRequest(BaseModel):
    lead: dict
    approved: bool


class GenerateDraftsRequest(BaseModel):
    campaign_id: str


class RegenerateStrategyRequest(BaseModel):
    force: bool = False


class SelectLeadRequest(BaseModel):
    index: int


@app.post("/api/web/session/{session_token}/batch-draft", status_code=202)
async def batch_draft(session_token: str, payload: BatchDraftRequest, request: Request):
    session_token = _session_token_from_request(request)
    if not payload.leads:
        raise HTTPException(status_code=400, detail="No leads provided")
    batch_id = str(uuid.uuid4())
    total = len(payload.leads)
    _create_batch_job(batch_id, payload.campaign_id, total)
    owner_id = await _workspace_owner(request, session_token)
    _launch_batch_task(session_token, batch_id, payload.leads, owner_id)
    return {"ok": True, "batch_id": batch_id, "total": total}


@app.get("/api/web/session/{session_token}/batch-status/{batch_id}")
async def batch_status(session_token: str, batch_id: str, request: Request = None):
    job = batch_jobs.get(batch_id)
    if not job:
        raise HTTPException(status_code=404, detail="Batch not found")
    owner_id = await _workspace_owner(request, session_token) if request is not None else ""
    campaign_id = job.get("campaign_id") or ""
    if campaign_id:
        campaigns = _workspace_campaigns(owner_id, session_token) if owner_id else []
        if not any(c.get("id") == campaign_id for c in campaigns):
            raise HTTPException(status_code=404, detail="Batch not found")
    return {"ok": True, **job}


@app.post("/api/web/session/{session_token}/analyze-campaigns")
async def analyze_campaigns_endpoint(session_token: str, payload: BatchDraftRequest):
    result = analyze_campaigns(payload.leads)
    return result

@app.get("/api/web/session/{session_token}/drafts")
async def list_drafts(session_token: str, request: Request):
    session_token = _session_token_from_request(request)
    import time as _t
    _t0 = _t.perf_counter()
    owner_id = await _workspace_owner(request, session_token)
    ws_id = await _resolved_workspace_id_or_default(request, owner_id)
    drafts = await asyncio.to_thread(_workspace_drafts, owner_id, session_token, workspace_id=ws_id)
    log.info("[perf] route=/drafts owner=%s ms=%.0f drafts=%d",
             owner_id[:8], (_t.perf_counter() - _t0) * 1000, len(drafts))
    return {"ok": True, "drafts": drafts}


@app.put("/api/web/session/{session_token}/drafts/{draft_id}")
async def update_draft(session_token: str, draft_id: str, payload: UpdateDraftRequest, request: Request):
    session_token = _session_token_from_request(request)
    owner_id = await _workspace_owner(request, session_token)
    drafts = _workspace_drafts(owner_id, session_token)
    for d in drafts:
        if d.get("id") == draft_id:
            from services.workspace_state import persist_draft_update
            if not persist_draft_update(owner_id, draft_id, {"text": payload.text, "status": "pending"}):
                raise HTTPException(status_code=503, detail="Draft could not be persisted")
            d["text"] = payload.text
            d["status"] = "pending"
            publish(session_token, WMEventType.DRAFT_UPDATED, {
                "draft_id": draft_id,
                "campaign_id": d.get("campaign_id", ""),
                "lead_name": d.get("lead", {}).get("name", ""),
            }, actor="user")
            return {"ok": True, "draft": d}
    raise HTTPException(status_code=404, detail="Draft not found")


@app.post("/api/web/session/{session_token}/drafts/{draft_id}/refine")
async def refine_draft(session_token: str, draft_id: str, payload: RefineDraftRequest, request: Request):
    session_token = _session_token_from_request(request)
    owner_id = await _workspace_owner(request, session_token)
    drafts = _workspace_drafts(owner_id, session_token)
    target = next((d for d in drafts if d.get("id") == draft_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Draft not found")

    context = {}
    for field in ("campaign_id", "campaign_name", "company", "contact", "role", "industry", "messaging_angle", "business_summary"):
        val = getattr(payload, field, None)
        if val:
            context[field] = val

    loop = asyncio.get_event_loop()
    try:
        if payload.edit_request and payload.previous_message:
            strategy = _classify_rewrite_strategy(payload.edit_request)
            rewrite_result = await loop.run_in_executor(
                None,
                execute_rewrite,
                payload.previous_message,
                strategy,
                context or None,
                payload.edit_request if strategy == "custom" else None,
            )
            previous_text = target["text"]
            target["text"] = rewrite_result.text
            target["status"] = "pending"
            from services.workspace_state import persist_draft_update
            if not persist_draft_update(owner_id, draft_id, {"text": target["text"], "status": "pending"}):
                raise RuntimeError("Draft rewrite could not be persisted")

            version = push_rewrite_history(
                session_token, draft_id,
                previous_text=previous_text,
                reason=payload.edit_request,
                strategy=strategy,
                change_summary=rewrite_result.change_summary,
            )

            comparison = await loop.run_in_executor(
                None,
                compare_versions,
                previous_text,
                rewrite_result.text,
                rewrite_result.change_summary,
            )

            try:
                intelligence = await loop.run_in_executor(
                    None,
                    analyze_draft_intelligence,
                    rewrite_result.text,
                    context or None,
                )
            except Exception:
                intelligence = None

            publish(session_token, WMEventType.DRAFT_UPDATED, {
                "draft_id": draft_id,
                "campaign_id": target.get("campaign_id", ""),
                "strategy": strategy,
                "change_summary": rewrite_result.change_summary or [],
            }, actor="user")

            return {
                "ok": True,
                "draft": target,
                "rewritten_text": rewrite_result.text,
                "change_summary": rewrite_result.change_summary,
                "draft_intelligence": intelligence.to_dict() if intelligence else None,
                "version": version,
                "confidence": rewrite_result.confidence,
                "comparison": comparison.to_dict(),
            }

        workflow_input = {
            "type": "draft_message",
            "lead": payload.lead,
            "edit_request": payload.edit_request,
            "previous_message": payload.previous_message,
        }
        if context:
            workflow_input["context"] = context

        workflow_result = await loop.run_in_executor(
            None,
            run_workflow,
            workflow_input,
        )
        new_body = _parse_draft_body(workflow_result.get("message", ""))
        rewritten_text = new_body or target["text"]
        if new_body:
            previous_text = target["text"]
            target["text"] = new_body
            target["status"] = "pending"
            from services.workspace_state import persist_draft_update
            if not persist_draft_update(owner_id, draft_id, {"text": target["text"], "status": "pending"}):
                raise RuntimeError("Draft rewrite could not be persisted")

            push_rewrite_history(
                session_token, draft_id,
                previous_text=previous_text,
                reason=payload.edit_request or "AI rewrite",
                strategy="custom",
                change_summary=["✓ Draft rewritten"],
            )

        publish(session_token, WMEventType.DRAFT_UPDATED, {
            "draft_id": draft_id,
            "campaign_id": target.get("campaign_id", ""),
            "method": "workflow_rewrite",
        }, actor="user")
        return {"ok": True, "draft": target, "rewritten_text": rewritten_text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class AnalyzeDraftRequest(BaseModel):
    draft_text: str
    lead: dict
    campaign_id: str | None = None
    campaign_name: str | None = None
    company: str | None = None
    contact: str | None = None
    role: str | None = None
    industry: str | None = None
    messaging_angle: str | None = None
    business_summary: str | None = None


@app.post("/api/web/session/{session_token}/drafts/analyze")
async def analyze_draft_endpoint(session_token: str, payload: AnalyzeDraftRequest):
    loop = asyncio.get_event_loop()
    try:
        context = {}
        for field in ("campaign_id", "campaign_name", "company", "contact", "role", "industry", "messaging_angle", "business_summary"):
            val = getattr(payload, field, None)
            if val:
                context[field] = val

        workflow_result = await loop.run_in_executor(
            None,
            run_workflow,
            {"type": "draft_analysis", "draft_text": payload.draft_text, "context": context},
        )

        intelligence = None
        try:
            intelligence = await loop.run_in_executor(
                None,
                analyze_draft_intelligence,
                payload.draft_text,
                context or None,
            )
        except Exception:
            pass

        return {
            "ok": workflow_result.get("ok", False),
            "analysis": workflow_result.get("analysis"),
            "draft_intelligence": intelligence.to_dict() if intelligence else None,
            "error": workflow_result.get("error"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class AskDraftQuestionRequest(BaseModel):
    question: str
    draft_text: str
    lead: dict
    campaign_id: str | None = None
    campaign_name: str | None = None
    company: str | None = None
    contact: str | None = None
    role: str | None = None
    industry: str | None = None
    messaging_angle: str | None = None
    business_summary: str | None = None


@app.post("/api/web/session/{session_token}/drafts/ask")
async def ask_draft_question_endpoint(session_token: str, payload: AskDraftQuestionRequest):
    loop = asyncio.get_event_loop()
    try:
        context = {}
        for field in ("campaign_id", "campaign_name", "company", "contact", "role", "industry", "messaging_angle", "business_summary"):
            val = getattr(payload, field, None)
            if val:
                context[field] = val
        workflow_result = await loop.run_in_executor(
            None,
            run_workflow,
            {"type": "draft_question", "question": payload.question, "draft_text": payload.draft_text, "context": context},
        )
        return {"ok": workflow_result.get("ok", False), "answer": workflow_result.get("answer"), "error": workflow_result.get("error")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _call_outbound_approval(draft_id: str, legacy_draft: dict) -> None:
    """Adapter: after legacy approval, also execute through outbound engine.
    Creates Gmail draft via outbound pipeline if provider is configured.
    Errors are logged but don't block the legacy flow.
    """
    try:
        from services.outbound.outbound_registry import create_draft as reg_create_draft
        from services.outbound.draft_store import draft_store as outbound_draft_store
        from services.outbound.outbound_models import DraftStatus
        outbound_draft = outbound_draft_store.get(draft_id)
        if not outbound_draft:
            log.warning("[outbound_adapter] Draft %s not found in outbound store", draft_id)
            return
        if outbound_draft.status in (DraftStatus.APPROVED, DraftStatus.AUTO_APPROVED, DraftStatus.SENT):
            return
        recipient_email = (outbound_draft.recipient.email if outbound_draft.recipient else "") or ""
        if not str(recipient_email).strip():
            log.info("[outbound_adapter] Draft %s has no recipient email — skipping Gmail draft creation", draft_id)
            return
        outbound_draft_store.approve(draft_id)
        real_provider_id = _get_outbound_provider_for_draft(outbound_draft)
        if not real_provider_id:
            log.warning("[outbound_adapter] No Gmail outbound provider registered — cannot create Gmail draft for %s", draft_id)
            return
        log.info("[outbound_adapter] Calling create_draft for %s via provider %s", draft_id, real_provider_id)
        provider_result = reg_create_draft(real_provider_id, outbound_draft)
        if provider_result and provider_result.external_draft_id:
            updated = outbound_draft_store.get(draft_id)
            if updated:
                updated.external_draft_id = provider_result.external_draft_id
                if provider_result.thread_id:
                    updated.thread_id = provider_result.thread_id
                updated.provider_id = real_provider_id
                outbound_draft_store.update(updated)
                log.info("[outbound_adapter] Gmail draft created — external_id=%s", provider_result.external_draft_id)
    except Exception as e:
        log.warning("[outbound_adapter] approve_draft failed for %s: %s", draft_id, e)


@app.post("/api/web/session/{session_token}/drafts/{draft_id}/approve")
async def approve_draft(session_token: str, draft_id: str, request: Request):
    session_token = _session_token_from_request(request)
    owner_id = await _workspace_owner(request, session_token)
    from services.workspace_state import load_workspace_state
    state = await asyncio.to_thread(load_workspace_state, owner_id, include_details=False)
    durable_drafts = state["drafts"]
    durable_target = next((d for d in durable_drafts if d.get("id") == draft_id), None)
    if durable_target:
        if durable_target.get("status") in ("sent", "sending"):
            raise HTTPException(status_code=409, detail="Draft already sent")
        new_status = "approved" if durable_target.get("status") != "approved" else "pending"
        from services.workspace_state import persist_draft_update_awaited
        if not await persist_draft_update_awaited(owner_id, draft_id, {"status": new_status}):
            raise HTTPException(status_code=503, detail="Draft approval could not be persisted")
        durable_target["status"] = new_status
        if new_status == "approved":
            _sync_draft_to_outbound(durable_target, session_token, owner_id=owner_id)
            _call_outbound_approval(draft_id, durable_target)
        campaign_id = durable_target.get("campaign_id")
        current_step = None
        pending_in_campaign = 0
        if campaign_id:
            from services.workspace_snapshot import enrich_campaigns
            enriched = next(
                (c for c in enrich_campaigns(state["campaigns"], durable_drafts)
                 if c.get("id") == campaign_id),
                None,
            )
            if enriched:
                current_step = enriched.get("current_step")
                pending_in_campaign = int(enriched.get("pending_drafts", 0) or 0)
        publish(session_token, WMEventType.DRAFT_APPROVED if new_status == "approved" else WMEventType.DRAFT_UPDATED, {
            "draft_id": draft_id, "campaign_id": campaign_id, "status": new_status,
        }, actor="user")
        return {"ok": True, "draft": durable_target, "current_step": current_step,
                "pending_drafts": pending_in_campaign}

    raise HTTPException(status_code=404, detail="Draft not found in the durable workspace")


@app.post("/api/web/session/{session_token}/drafts/{draft_id}/undo")
async def undo_draft(session_token: str, draft_id: str, request: Request):
    session_token = _session_token_from_request(request)
    owner_id = await _workspace_owner(request, session_token)
    drafts = _workspace_drafts(owner_id, session_token)
    target = next((d for d in drafts if d.get("id") == draft_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Draft not found")

    entry = undo_rewrite_history(session_token, draft_id)
    if entry is None:
        raise HTTPException(status_code=400, detail="No history to undo")

    target["text"] = entry.previous_text
    target["status"] = "pending"
    from services.workspace_state import persist_draft_update
    if not persist_draft_update(owner_id, draft_id, {"text": target["text"], "status": "pending"}):
        raise HTTPException(status_code=503, detail="Draft undo could not be persisted")
    return {
        "ok": True,
        "draft": target,
        "undo": entry.to_dict(),
    }


@app.get("/api/web/session/{session_token}/drafts/{draft_id}/history")
async def draft_rewrite_history(session_token: str, draft_id: str, request: Request = None):
    session_token = _session_token_from_request(request)
    owner_id = await _workspace_owner(request, session_token) if request is not None else ""
    draft = outbound_draft_store.get(draft_id) if hasattr(outbound_draft_store, "get") else None
    if not _outbound_draft_owned_by(draft, owner_id):
        raise HTTPException(status_code=404, detail="Draft not found")
    return {
        "ok": True,
        "history": get_rewrite_history(session_token, draft_id),
        "current_version": get_draft_version(session_token, draft_id),
    }


class CompareDraftVersionsRequest(BaseModel):
    old_text: str
    new_text: str
    change_summary: list[str] | None = None


@app.post("/api/web/session/{session_token}/drafts/compare")
async def compare_draft_versions(session_token: str, payload: CompareDraftVersionsRequest):
    try:
        comparison = compare_versions(
            payload.old_text,
            payload.new_text,
            payload.change_summary,
        )
        return {"ok": True, "comparison": comparison.to_dict()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Communication Intelligence Endpoints ──


class AnalyzeMessageRequest(BaseModel):
    text: str
    conversation_id: str = ""
    sender: str = "lead"
    subject: str = ""


@app.post("/api/web/session/{session_token}/communication/analyze")
async def communication_analyze(session_token: str, payload: AnalyzeMessageRequest):
    msg = ConversationMessage(
        text=payload.text,
        sender=payload.sender,
        subject=payload.subject,
    )
    existing = memory_store.get(payload.conversation_id) if payload.conversation_id else None
    intelligence, memory = analyze_message(
        message=msg,
        conversation_id=payload.conversation_id,
        existing_memory=existing,
    )
    return {
        "ok": True,
        "intelligence": intelligence.model_dump(),
        "memory": memory.model_dump(),
    }


@app.post("/api/web/session/{session_token}/communication/memory/update")
async def communication_memory_update(session_token: str, payload: AnalyzeMessageRequest, request: Request = None):
    session_token = _session_token_from_request(request)
    msg = ConversationMessage(text=payload.text, sender=payload.sender, subject=payload.subject)
    cid = payload.conversation_id or msg.id
    from services.intent_detector import detect_intents
    from services.conversation_classifier import classify_stage
    from services.followup_reasoner import recommend_followup
    intents = detect_intents(msg.text)
    signals = detect_signals(msg.text)
    stage, reasoning = classify_stage([], msg.text)
    recommendation = recommend_followup(intents, signals, stage)
    existing = memory_store.get(cid)
    memory = create_or_update_memory(
        conversation_id=cid,
        message=msg,
        intents=intents,
        buying_signals=signals,
        stage=stage,
        stage_reasoning=reasoning,
        followup_action=recommendation.action.value,
        existing_memory=existing,
    )
    publish(session_token, WMEventType.PREFERENCE_LEARNED, {
        "conversation_id": cid,
        "intents": [i.value for i in intents] if intents else [],
        "signals": [s.signal.value for s in signals] if signals else [],
        "stage": stage.value if stage else "",
        "followup_action": recommendation.action.value,
    }, actor="system")
    return {
        "ok": True,
        "memory": memory.model_dump(),
    }


class RecommendRequest(BaseModel):
    text: str
    conversation_id: str = ""


@app.post("/api/web/session/{session_token}/communication/recommend")
async def communication_recommend(session_token: str, payload: RecommendRequest):
    from services.intent_detector import detect_intents
    intents = detect_intents(payload.text)
    signals = detect_signals(payload.text)
    stage = ConversationStage.ENGAGED
    recommendation = recommend_followup(intents, signals, stage)
    return {
        "ok": True,
        "recommendation": recommendation.model_dump(),
    }


class SummaryRequest(BaseModel):
    text: str
    conversation_id: str = ""


@app.post("/api/web/session/{session_token}/communication/summary")
async def communication_summary(session_token: str, payload: SummaryRequest):
    from services.intent_detector import detect_intents
    intents = detect_intents(payload.text)
    signals = detect_signals(payload.text)
    stage = ConversationStage.ENGAGED
    from services.followup_reasoner import recommend_followup
    recommendation = recommend_followup(intents, signals, stage)
    summary = generate_summary(intents, signals, recommendation)
    return {
        "ok": True,
        "summary": summary,
    }


@app.get("/api/web/session/{session_token}/communication/{conversation_id}/timeline")
async def communication_timeline(session_token: str, conversation_id: str, request: Request):
    session_token = _session_token_from_request(request)
    owner_id = await _workspace_owner(request, session_token)
    from services.conversations.conversation_store import conversation_store
    convo = conversation_store.get_conversation(conversation_id)
    if convo is None or not _conversation_owned_by(convo, owner_id):
        # Safe not-found: foreign-but-existing and nonexistent conversations are
        # indistinguishable (no existence leak, no foreign memory/timeline).
        raise HTTPException(status_code=404, detail="Conversation not found")
    events = get_conversation_events(conversation_id)
    return {
        "ok": True,
        "events": [e.model_dump() for e in events],
        "total": len(events),
    }


# ── Workspace Context Endpoint (for dev tooling) ──


class DevWorkspaceContextRequest(BaseModel):
    conversation_id: str = ""


# ── Multi-Workspace Lifecycle (SaaS-2.7) ──

class CreateWorkspaceRequest(BaseModel):
    organization_id: str = ""
    name: str = "Workspace"
    slug: str = ""


@app.get("/api/web/session/{session_token}/workspaces")
async def list_workspaces(session_token: str, request: Request):
    """List workspaces in every organization the caller actively belongs to."""
    session_token = _session_token_from_request(request)
    owner_id = await _workspace_owner(request, session_token)
    from services.workspace_context import workspaces_for_user
    ws = await asyncio.to_thread(workspaces_for_user, None, owner_id)
    return {"ok": True, "workspaces": ws}


@app.post("/api/web/session/{session_token}/workspaces/select")
async def select_workspace(session_token: str, request: Request):
    """Validate + return the context for an explicitly selected workspace."""
    session_token = _session_token_from_request(request)
    owner_id = await _workspace_owner(request, session_token)
    ctx = await _resolve_selected_workspace_context(request, owner_id)
    return {
        "ok": True,
        "workspace": {
            "id": ctx.workspace_id,
            "organization_id": ctx.organization_id,
            "name": ctx.workspace_name,
            "membership_role": ctx.membership_role,
            "membership_status": ctx.membership_status,
        },
    }


@app.post("/api/web/session/{session_token}/workspaces")
async def create_workspace(session_token: str, payload: CreateWorkspaceRequest, request: Request):
    """Create an additional workspace in an organization the caller is an
    ACTIVE member of (owner/admin role required).

    The organization is validated against membership — never trusted as
    authority by itself. The workspace gets a fresh uuid (independent of any
    workflow/web session), owner_user_id = the authenticated user, and
    organization_id = the validated org. No duplicate organization is created
    and no existing workspace is modified.
    """
    session_token = _session_token_from_request(request)
    owner_id = await _workspace_owner(request, session_token)
    org_id = (payload.organization_id or "").strip()

    from services.workspace_context import active_memberships
    memberships = await asyncio.to_thread(active_memberships, None, owner_id)
    membership = next((m for m in memberships if m.get("organization_id") == org_id), None)
    if membership is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    if (membership.get("role") or "member") not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Insufficient role to create a workspace")

    from uuid import uuid4
    new_id = str(uuid4())
    slug = (payload.slug or "").strip() or _default_workspace_slug(new_id, payload.name)
    name = (payload.name or "").strip() or "Workspace"
    from services.persistence.launch.repositories import WorkspaceRepository, WorkspaceMemberRepository
    from services.persistence.launch.models import Workspace, WorkspaceMember
    repo = WorkspaceRepository()
    await repo.save(Workspace(
        id=new_id, organization_id=org_id, name=name, slug=slug,
        owner_user_id=owner_id, created_by=owner_id, updated_by=owner_id,
        status="active",
    ))
    # Owner workspace-member row for the new workspace.
    await WorkspaceMemberRepository().save(WorkspaceMember(
        workspace_id=new_id, user_id=owner_id, role="owner", status="active",
    ))
    return {"ok": True, "workspace": {
        "id": new_id, "organization_id": org_id, "name": name, "slug": slug,
        "owner_user_id": owner_id, "status": "active",
    }}


def _default_workspace_slug(workspace_id: str, name: str = "Workspace") -> str:
    base = (name or "Workspace").replace(" ", "-").lower()
    suffix = str(workspace_id or "")[:8]
    return f"{base}-{suffix}" if suffix else base


@app.get("/api/web/session/{session_token}/workspace-context")
async def dev_workspace_context(session_token: str, conversation_id: str = "", request: Request = None):
    session_token = _session_token_from_request(request)
    """Returns workspace context with provider info for the dev providers page."""
    owner_id = await _workspace_owner(request, session_token)
    ctx = _build_copilot_workspace_context(
        session_token,
        current_page="Mission Control",
        conversation_id=conversation_id or None,
        user_id=owner_id,
    )
    return ctx


# ── Provider Endpoints ──


class ProviderConnectRequest(BaseModel):
    provider_type: str  # "gmail", "outlook", etc.
    auth_token: str
    email: str = ""
    scope: str = ""


@app.post("/api/web/session/{session_token}/providers/connect")
async def provider_connect(session_token: str, payload: ProviderConnectRequest, request: Request = None):
    session_token = _session_token_from_request(request)
    # PR10.8.3: this legacy dev-only route accepts raw OAuth tokens and lets a
    # caller attach a Gmail provider without the OAuth flow. In production,
    # Gmail connection must go through /api/auth/gmail/url + callback.
    if (os.getenv("ENVIRONMENT") or os.getenv("APP_ENV") or "development").strip().lower() == "production":
        raise HTTPException(status_code=403, detail="Provider connect is disabled in production — use the Gmail OAuth flow")
    try:
        ptype = ProviderType(payload.provider_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown provider type: {payload.provider_type}")

    instance = instantiate_provider(ptype)
    if not instance:
        raise HTTPException(status_code=400, detail=f"Provider not registered: {payload.provider_type}")

    if ptype == ProviderType.GMAIL:
        # PR-2A: per-user lock (was global threading.Lock).
        async with _gmail_connect_lock(session_token):
            # Replace any existing Gmail provider for this user so the runtime
            # registry never holds duplicate providers for the same Google
            # account; the lock makes replace+connect+register atomic.
            _remove_existing_gmail_provider(session_token)
            provider = instance.connect(
                auth_token=payload.auth_token,
                user_id=session_token,
                email=payload.email,
                scope=payload.scope,
            )
            register_instance(provider.id, instance)
            _register_outbound_gmail_instance(provider.id)
    else:
        provider = instance.connect(
            auth_token=payload.auth_token,
            user_id=session_token,
            email=payload.email,
            scope=payload.scope,
        )
        register_instance(provider.id, instance)
    publish(session_token, WMEventType.PROVIDER_CONNECTED, {
        "provider_id": provider.id,
        "provider_type": payload.provider_type,
        "email": payload.email,
    }, actor="user")
    return {"ok": True, "provider": provider.model_dump()}


@app.post("/api/web/session/{session_token}/providers/{provider_id}/disconnect")
async def provider_disconnect(session_token: str, provider_id: str, request: Request):
    session_token = _session_token_from_request(request)
    owner_id = await _workspace_owner(request, session_token)
    if not _provider_record_owned_by(provider_id, owner_id):
        raise HTTPException(status_code=404, detail="Provider not found or already disconnected")
    success = registry_disconnect(provider_id)
    if not success:
        raise HTTPException(status_code=404, detail="Provider not found or already disconnected")
    # PR-2B: gmail_connected changed in the cached identity.
    try:
        from services.session_cache import session_cache
        await session_cache.invalidate_user(owner_id)
    except Exception:
        pass
    publish(session_token, WMEventType.PROVIDER_DISCONNECTED, {
        "provider_id": provider_id,
    }, actor="user")
    try:
        from services.events_bus import event_bus
        await event_bus.publish_user_event(owner_id, "provider.disconnected",
                                           {"provider": "gmail"}, status="disconnected")
    except Exception:
        pass
    return {"ok": True}


@app.get("/api/web/session/{session_token}/providers")
async def provider_list(session_token: str, request: Request):
    """PR-2A: durable-source-of-truth provider listing.

    The authoritative records come from ``connected_accounts`` (Supabase) for
    the resolved owner. Runtime registries (communication store + adapter
    registry) are used ONLY to enrich status/sync fields for providers that
    are currently live in this process — they can never make a provider
    appear or disappear across restarts/process boundaries.

    Response shape is unchanged: {ok, providers:[{id, provider_type, status,
    email, last_sync, sync_cursor, created_at}]}.
    """
    session_token = _session_token_from_request(request)
    owner_id = await _workspace_owner(request, session_token)

    # ── Durable records (authoritative) ──
    # Single indexed query; no Gmail calls, no messages, no session summary.
    from services.supabase import get_durable_providers_for_user
    try:
        durable_rows = await asyncio.to_thread(get_durable_providers_for_user, owner_id, "google")
    except Exception as error:
        log.error(
            "[providers] durable provider lookup failed user=%s error_type=%s",
            owner_id[:8], type(error).__name__,
        )
        # Distinguish "lookup failed" from "no providers" (PR-2A §10).
        raise HTTPException(status_code=503, detail="Unable to load connected accounts")

    log.info("[providers] durable provider lookup returned %d record(s) user=%s",
             len(durable_rows), owner_id[:8])

    result = []
    seen_runtime_ids: set[str] = set()
    persisted_auth_failed = False

    for row in durable_rows:
        comm_pid = row.get("communication_provider_id") or ""
        email = (row.get("email") or "").strip().lower()
        durable_status = row.get("status") or "active"
        if durable_status == "auth_failed":
            persisted_auth_failed = True

        runtime_instance = get_provider(comm_pid) if comm_pid else None
        comm_record = communication_store.get_provider(comm_pid) if comm_pid else None
        if comm_pid:
            seen_runtime_ids.add(comm_pid)
        if comm_record is not None:
            seen_runtime_ids.add(comm_record.id)

        # Persisted auth_failed wins over a still-valid runtime token
        # (revoked refresh token) — PR10.8.2.1 semantics preserved.
        if durable_status == "auth_failed":
            status_val = ProviderStatus.AUTH_FAILED.value
        elif runtime_instance is not None:
            try:
                status_val = runtime_instance.health().value
            except Exception as error:
                # PR-2A: a Gmail/network hiccup while probing one live
                # instance must never fail the whole provider list.
                log.warning(
                    "[providers] runtime health probe failed provider=%s error_type=%s",
                    comm_pid[:8], type(error).__name__,
                )
                if type(error).__name__ == "GmailReauthRequired":
                    status_val = ProviderStatus.AUTH_FAILED.value
                else:
                    status_val = durable_status if durable_status in {"active", "healthy"} else ProviderStatus.AUTH_FAILED.value
        else:
            # Not live in this process (e.g. after a restart): report the
            # durable status instead of pretending it is healthy.
            status_val = durable_status if durable_status in {"active", "healthy"} else ProviderStatus.AUTH_FAILED.value

        # Stable identity: prefer the persisted communication-provider id;
        # fall back to a deterministic id derived from the durable row.
        public_id = comm_pid or f"durable-{row.get('row_id', '')}"
        result.append({
            "id": public_id,
            "provider_type": ProviderType.GMAIL.value,
            "status": status_val,
            "email": row.get("email", ""),
            "last_sync": (comm_record.last_sync if comm_record else None) or row.get("last_synced_at"),
            "sync_cursor": comm_record.sync_cursor if comm_record else "",
            "created_at": row.get("created_at"),
        })

    # ── Runtime-only providers (secondary; e.g. legacy dev connects) ──
    # These have no durable row yet. They are still listed so existing
    # behaviour is preserved, but they can never mask missing durable state.
    # The per-user store only ever holds this owner's records.
    for p in communication_store.get_user_providers(owner_id):
        if p.id in seen_runtime_ids:
            continue
        instance = get_provider(p.id)
        result.append({
            "id": p.id,
            "provider_type": p.provider_type.value,
            "status": instance.health().value if instance else p.status.value,
            "email": p.metadata.get("email", ""),
            "last_sync": p.last_sync,
            "sync_cursor": p.sync_cursor,
            "created_at": p.created_at,
        })

    return {"ok": True, "providers": result}


@app.get("/api/web/session/{session_token}/providers/{provider_id}/health")
async def provider_health(session_token: str, provider_id: str, request: Request):
    session_token = _session_token_from_request(request)
    owner_id = await _workspace_owner(request, session_token)
    if not _provider_record_owned_by(provider_id, owner_id):
        raise HTTPException(status_code=404, detail="Provider not found")
    instance = get_provider(provider_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Provider not found")
    status = instance.health()
    provider = communication_store.get_provider(provider_id)
    # Persisted auth_failed wins over a still-valid runtime access token.
    if provider is not None and provider.provider_type == ProviderType.GMAIL:
        try:
            from services.supabase import is_connected_account_reauth_required
            if is_connected_account_reauth_required(provider.user_id, "google"):
                status = ProviderStatus.AUTH_FAILED
        except Exception:
            pass
    return {
        "ok": True,
        "provider_id": provider_id,
        "status": status.value,
        "last_sync": provider.last_sync if provider else "",
    }


@app.post("/api/web/session/{session_token}/providers/{provider_id}/sync")
async def provider_sync(session_token: str, provider_id: str, request: Request, cursor: str = ""):
    session_token = _session_token_from_request(request)
    owner_id = await _workspace_owner(request, session_token)
    if not _provider_record_owned_by(provider_id, owner_id):
        raise HTTPException(status_code=404, detail="Provider not found")
    from services.communication.provider_registry import sync_provider as registry_sync
    if cursor:
        result = registry_sync(provider_id, cursor=cursor)
    else:
        from services.communication.gmail_sync import sync_all
        instance = get_provider(provider_id)
        if not instance:
            raise HTTPException(status_code=404, detail="Provider not found")
        result = sync_all(instance)
    publish(session_token, WMEventType.SYNC_COMPLETED, {
        "provider_id": provider_id,
        "new_messages": result.new_messages if result else 0,
        "updated_threads": result.updated_threads if result else 0,
    }, actor="system")
    return {
        "ok": True,
        "result": result.model_dump() if result else None,
    }


@app.get("/api/web/session/{session_token}/providers/{provider_id}/status")
async def provider_status(session_token: str, provider_id: str, request: Request):
    session_token = _session_token_from_request(request)
    owner_id = await _workspace_owner(request, session_token)
    if not _provider_record_owned_by(provider_id, owner_id):
        raise HTTPException(status_code=404, detail="Provider not found")
    provider = communication_store.get_provider(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    instance = get_provider(provider_id)
    health_val = instance.health().value if instance else provider.status.value
    cursor = communication_store.get_cursor(provider_id)
    return {
        "ok": True,
        "provider_id": provider_id,
        "provider_type": provider.provider_type.value,
        "status": health_val,
        "connected": instance is not None,
        "last_sync": provider.last_sync,
        "sync_cursor": cursor.cursor if cursor else "",
        "watching": getattr(instance, "_watching", False) if instance else False,
    }


@app.get("/api/web/session/{session_token}/providers/{provider_id}/threads")
async def provider_threads(session_token: str, provider_id: str, request: Request = None):
    """List all tracked thread mappings for a provider."""
    owner_id = await _workspace_owner(request, session_token) if request is not None else ""
    if not _provider_record_owned_by(provider_id, owner_id):
        raise HTTPException(status_code=404, detail="Provider not found")
    store = communication_store
    all_threads = store.get_all_threads()
    provider_threads = [t for t in all_threads if t.provider_id == provider_id]
    return {
        "ok": True,
        "provider_id": provider_id,
        "threads": [t.model_dump() for t in provider_threads],
        "total": len(provider_threads),
    }


@app.get("/api/web/session/{session_token}/providers/{provider_id}/messages")
async def provider_messages(session_token: str, provider_id: str, request: Request = None):
    """Get message count, mailbox info, and recent activity for a provider."""
    owner_id = await _workspace_owner(request, session_token) if request is not None else ""
    if not _provider_record_owned_by(provider_id, owner_id):
        raise HTTPException(status_code=404, detail="Provider not found")
    count = communication_store.message_count()
    recent = communication_store.get_recent_messages(limit=10)
    return {
        "ok": True,
        "provider_id": provider_id,
        "total_messages_seen": count,
        "recent_messages": recent,
        "mailbox_email": "",
    }


@app.get("/api/web/session/{session_token}/providers/events")
async def provider_events_endpoint(session_token: str, request: Request, provider_id: str = "", after: int = 0):
    events = get_provider_events(provider_id=provider_id, after_sequence=after)
    # SaaS-2.6: also surface the caller's durable, tenant-scoped provider events.
    durable = []
    try:
        owner_id = await _workspace_owner(request, session_token)
        from services.workspace_state import ensure_workspace
        ws = await _resolved_workspace_id_or_default(request, owner_id)
        if ws:
            from services.persistence.launch.communication_persistence import list_provider_events
            durable = await asyncio.to_thread(list_provider_events, ws, provider_id, 100)
    except HTTPException:
        durable = []
    except Exception:  # noqa: BLE001
        durable = []
    seen = {e.id for e in events}
    durable_dicts = []
    for d in durable:
        if getattr(d, "id", "") in seen:
            continue
        durable_dicts.append({
            "id": getattr(d, "id", ""),
            "event_type": getattr(d, "event_type", ""),
            "provider_id": getattr(d, "provider_id", ""),
            "message": getattr(d, "message", ""),
            "timestamp": getattr(d, "event_timestamp", None).isoformat() if getattr(d, "event_timestamp", None) else "",
            "sequence": 0,
            "metadata": getattr(d, "metadata", {}) or {},
        })
    in_mem = [
        {
            "id": e.id,
            "event_type": e.event_type.value,
            "provider_id": e.provider_id,
            "message": e.message,
            "timestamp": e.timestamp,
            "sequence": e.sequence,
            "metadata": e.metadata,
        }
        for e in events
    ]
    return {
        "ok": True,
        "events": durable_dicts + in_mem,
        "latest_sequence": latest_sequence(),
    }


@app.get("/api/web/session/{session_token}/providers/registered")
async def provider_registered_types(session_token: str):
    return {
        "ok": True,
        "types": [t.value for t in list_registered_types()],
    }


# ── Outbound Endpoints ──


from services.outbound.outbound_models import (
    DraftMessage as OutboundDraftMessage,
    SendRequest as OutboundSendRequest,
    Recipient,
)
from services.outbound.draft_store import draft_store as outbound_draft_store
from services.outbound.outbound_persistence import outbound_persistence
from services.outbound.outbound_executor import executor as outbound_executor
from services.outbound.outbound_events import (
    get_events as get_outbound_events,
    latest_sequence as outbound_latest_sequence,
)


class OutboundCreateDraftRequest(BaseModel):
    provider_id: str
    conversation_id: str = ""
    thread_id: str = ""
    workflow_id: str = ""
    subject: str
    body: str
    recipient_email: str
    recipient_name: str = ""
    sender_email: str
    sender_name: str = ""
    cc: list[dict] = []
    bcc: list[dict] = []
    reply_to_message_id: str = ""
    in_reply_to: str = ""
    references: str = ""


class OutboundUpdateDraftRequest(BaseModel):
    provider_id: str
    draft_id: str
    external_draft_id: str = ""
    subject: str = ""
    body: str = ""
    recipient_email: str = ""
    recipient_name: str = ""


class OutboundSendRequest(BaseModel):
    provider_id: str
    draft_id: str = ""
    conversation_id: str = ""
    thread_id: str = ""
    workflow_id: str = ""
    subject: str = ""
    body: str = ""
    recipient_email: str = ""
    recipient_name: str = ""
    sender_email: str = ""
    sender_name: str = ""


class OutboundScheduleRequest(BaseModel):
    provider_id: str
    draft_id: str
    send_at: str


class OutboundDeleteDraftRequest(BaseModel):
    provider_id: str
    draft_id: str


@app.post("/api/web/session/{session_token}/outbound/drafts")
async def outbound_create_draft(session_token: str, payload: OutboundCreateDraftRequest, request: Request):
    session_token = _session_token_from_request(request)
    draft = OutboundDraftMessage(
        provider_id=payload.provider_id,
        conversation_id=payload.conversation_id,
        thread_id=payload.thread_id,
        workflow_id=payload.workflow_id,
        subject=payload.subject,
        body=payload.body,
        recipient=Recipient(email=payload.recipient_email, name=payload.recipient_name),
        sender=Recipient(email=payload.sender_email, name=payload.sender_name),
        cc=[Recipient(**c) for c in payload.cc],
        bcc=[Recipient(**b) for b in payload.bcc],
        reply_to_message_id=payload.reply_to_message_id,
        in_reply_to=payload.in_reply_to,
        references=payload.references,
    )
    from services.outbound.outbound_registry import create_draft as reg_create_draft
    outbound_draft_store.create(draft)
    result = reg_create_draft(payload.provider_id, draft)
    if result:
        outbound_draft_store.update(result)
    publish(session_token, WMEventType.DRAFT_GENERATED, {
        "id": draft.id,
        "campaign_id": draft.workflow_id,
        "subject": draft.subject,
        "body_preview": draft.body[:200],
        "recipient_email": draft.recipient.email,
        "provider_id": payload.provider_id,
    }, actor="user")
    try:
        owner_id = await _workspace_owner(request, session_token)
        if owner_id:
            from services.workspace_state import persist_draft
            persist_draft(owner_id, {
                "id": draft.id,
                "campaign_id": draft.workflow_id,
                "provider": payload.provider_id,
                "subject": draft.subject,
                "body": draft.body,
                "status": "draft",
                "lead": {
                    "email": draft.recipient.email,
                    "name": draft.recipient.name,
                },
            })
    except Exception:
        pass
    return {"ok": True, "draft": draft.model_dump()}


@app.patch("/api/web/session/{session_token}/outbound/drafts/{draft_id}")
async def outbound_update_draft(session_token: str, draft_id: str, payload: OutboundUpdateDraftRequest, request: Request):
    session_token = _session_token_from_request(request)
    existing = outbound_draft_store.get(draft_id)
    if not existing:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Draft not found")
    update_data = {}
    if payload.subject:
        update_data["subject"] = payload.subject
    if payload.body:
        update_data["body"] = payload.body
    if payload.recipient_email:
        update_data["recipient"] = Recipient(email=payload.recipient_email, name=payload.recipient_name)
    updated = existing.model_copy(update=update_data)
    outbound_draft_store.update(updated)
    if payload.external_draft_id:
        from services.outbound.outbound_registry import update_draft as reg_update_draft
        reg_result = reg_update_draft(payload.provider_id, updated)
        if reg_result:
            outbound_draft_store.update(reg_result)
    publish(session_token, WMEventType.DRAFT_UPDATED, {
        "draft_id": draft_id,
        "provider_id": payload.provider_id,
        "subject": payload.subject or existing.subject,
    }, actor="user")
    try:
        owner_id = await _workspace_owner(request, session_token)
        if owner_id:
            from services.workspace_state import persist_draft_update
            persist_draft_update(owner_id, draft_id, update_data)
    except Exception:
        pass
    return {"ok": True, "draft": updated.model_dump()}


@app.delete("/api/web/session/{session_token}/outbound/drafts/{draft_id}")
async def outbound_delete_draft(session_token: str, draft_id: str, provider_id: str = "", request: Request = None):
    session_token = _session_token_from_request(request)
    draft = outbound_draft_store.get(draft_id)
    if draft and draft.external_draft_id and provider_id:
        from services.outbound.outbound_registry import delete_draft as reg_delete_draft
        reg_delete_draft(provider_id, draft.external_draft_id)
    result = outbound_draft_store.delete(draft_id)
    if result:
        publish(session_token, WMEventType.DRAFT_REJECTED, {
            "draft_id": draft_id,
            "provider_id": provider_id,
        }, actor="user")
        _get_feedback().on_draft_rejected(session_token, draft_id)
    return {"ok": result}


class SendDraftRequest(BaseModel):
    """Optional test-only recipient override. Ignored unless
    LOQI_ENABLE_TEST_RECIPIENT_OVERRIDE=true."""
    test_recipient: str = ""
    test_recipient_name: str = ""


def _test_recipient_override_enabled() -> bool:
    return os.getenv("LOQI_ENABLE_TEST_RECIPIENT_OVERRIDE", "").strip().lower() in {"1", "true", "yes"}


@app.post("/api/web/session/{session_token}/drafts/{draft_id}/send")
async def send_draft(session_token: str, draft_id: str, request: Request, payload: SendDraftRequest = None):
    session_token = _session_token_from_request(request)
    from services.outbound.draft_store import draft_store as outbound_draft_store
    payload = payload or SendDraftRequest()
    test_recipient = payload.test_recipient or ""
    if test_recipient and not _test_recipient_override_enabled():
        raise HTTPException(status_code=403, detail="Test recipient override is disabled")

    # PR-2B: resolve ownership + workspace BEFORE hydration. The durable
    # lookup must use the same workspace scope as GET /drafts (the Review UI
    # source), and the hydration stamp must be scoped to THIS owner.
    owner_id = ""
    try:
        owner_id = await _workspace_owner(request, session_token)
    except HTTPException:
        owner_id = ""
    try:
        ws_id = await _resolved_workspace_id_or_default(request, owner_id) if owner_id else ""
    except Exception:
        # PR-2B: workspace scoping only narrows the durable fallback lookup;
        # a workspace-resolution failure (e.g. transient DB error) must never
        # fail the SEND itself. Empty scope = previous lookup semantics.
        ws_id = ""

    outbound_draft = outbound_draft_store.get(draft_id)
    hydrated_owner_id: str | None = None
    if not outbound_draft:
        legacy_drafts = draft_store.get(session_token, [])
        legacy = next((d for d in legacy_drafts if d.get("id") == draft_id), None)
        if not legacy:
            # Same source + scope as GET /drafts (PR-2B: was missing the
            # workspace id, which could hide drafts that /drafts shows).
            durable = next(
                (d for d in _workspace_drafts(owner_id, session_token, workspace_id=ws_id) if d.get("id") == draft_id),
                None,
            )
            if not durable:
                raise HTTPException(status_code=404, detail="Draft not found in any store")
            if durable.get("status") == "sent":
                return {"ok": False, "error": "Draft already sent"}
            _sync_draft_to_outbound(durable, session_token, owner_id=owner_id)
            hydrated_owner_id = owner_id
        else:
            _sync_draft_to_outbound(legacy, session_token, owner_id=owner_id)
        outbound_draft = outbound_draft_store.get(draft_id)
        if not outbound_draft:
            raise HTTPException(status_code=500, detail="Failed to sync draft to outbound store")
    from services.outbound.outbound_models import DraftStatus
    if outbound_draft.status in (DraftStatus.SENT, DraftStatus.SENDING):
        return {"ok": False, "error": "Draft already sent"}
    owner_id = hydrated_owner_id or owner_id
    # PR10.8.3: never send a draft whose provider provably belongs to another
    # user (cross-user draft access via a guessed draft id).
    if owner_id and outbound_draft.provider_id:
        _draft_prov = communication_store.get_provider(outbound_draft.provider_id)
        if _draft_prov is not None and str(_draft_prov.user_id) != str(owner_id):
            # Safe not-found: a foreign-but-existing draft must not be
            # distinguishable from a nonexistent one (no existence leak).
            raise HTTPException(status_code=404, detail="Draft not found")
    recipient_email = (outbound_draft.recipient.email if outbound_draft.recipient else "") or ""
    if not str(recipient_email).strip():
        return {"ok": False, "error": "This lead has no email address"}
    real_provider_id = _get_outbound_provider_for_draft(outbound_draft, owner_id)
    if not real_provider_id:
        return {"ok": False, "error": "No Gmail outbound provider registered"}

    # Test-only recipient override (LOQI_ENABLE_TEST_RECIPIENT_OVERRIDE=true):
    # changes ONLY the outbound recipient address/name. The lead, campaign,
    # draft, conversation, and provider thread identity are untouched so the
    # inbound reply still resolves to the existing Loqi conversation.
    send_recipient = {
        "email": outbound_draft.recipient.email,
        "name": outbound_draft.recipient.name,
    }
    if test_recipient:
        send_recipient = {"email": test_recipient, "name": payload.test_recipient_name or "Test Recipient"}
        log.info("[TEST RECIPIENT] original_recipient=%s effective_recipient=%s",
                 recipient_email, test_recipient)

    log.info("[send_draft] Sending draft %s via provider %s", draft_id, real_provider_id)
    result = outbound_executor.execute("send_reply", {
        "provider_id": real_provider_id,
        "draft_id": outbound_draft.id,
        "conversation_id": outbound_draft.conversation_id,
        "thread_id": outbound_draft.thread_id,
        "workflow_id": outbound_draft.workflow_id,
        "subject": outbound_draft.subject,
        "body": outbound_draft.body,
        "recipient": send_recipient,
        "sender": {"email": outbound_draft.sender.email, "name": outbound_draft.sender.name},
    })
    if result.get("ok"):
        outbound_draft_store.mark_sent(draft_id)
        legacy_drafts = draft_store.get(session_token, [])
        for d in legacy_drafts:
            if d.get("id") == draft_id:
                d["status"] = "sent"
                break
        if hydrated_owner_id:
            try:
                from services.workspace_state import persist_draft_update_awaited
                await persist_draft_update_awaited(hydrated_owner_id, draft_id, {"status": "sent"})
            except Exception as e:
                log.error(
                    "persistence_write_failed category=draft_status status=sent draft_id=%s error_type=%s",
                    draft_id[:12], type(e).__name__,
                )
        send_data = result.get("send_result", {})
        try:
            from services.conversations.integration import create_conversation_from_send
            conversation = create_conversation_from_send(
                provider_id=real_provider_id,
                provider_type="gmail",
                external_thread_id=send_data.get("thread_id", ""),
                external_message_id=send_data.get("external_message_id", ""),
                subject=outbound_draft.subject,
                from_email=outbound_draft.sender.email,
                from_name=outbound_draft.sender.name,
                to_email=outbound_draft.recipient.email,
                to_name=outbound_draft.recipient.name,
                body=outbound_draft.body,
                campaign_id=outbound_draft.workflow_id or "",
                workflow_id=outbound_draft.workflow_id or "",
                owner_id=owner_id,
            )
            simulate_reply({
                "conversation_id": conversation.conversation_id,
                "external_thread_id": send_data.get("thread_id", ""),
                "subject": outbound_draft.subject,
                "from_email": outbound_draft.sender.email,
                "from_name": outbound_draft.sender.name,
                "to_email": outbound_draft.recipient.email,
                "to_name": outbound_draft.recipient.name,
                "body": outbound_draft.body,
                "campaign_id": outbound_draft.workflow_id or "",
                "workflow_id": outbound_draft.workflow_id or "",
                "lead": outbound_draft.metadata.get("lead", {}) if outbound_draft.metadata else {},
                "objective": "",
            })
        except Exception as e:
            log.error(
                "persistence_write_failed category=conversation operation=create_from_send "
                "draft_id=%s provider_id=%s error_type=%s",
                draft_id[:12], real_provider_id[:12], type(e).__name__,
            )
        publish(session_token, WMEventType.DRAFT_SENT, {
            "draft_id": draft_id,
            "thread_id": send_data.get("thread_id", ""),
            "external_message_id": send_data.get("external_message_id", ""),
            "provider_id": real_provider_id,
            "subject": outbound_draft.subject,
            "recipient_email": outbound_draft.recipient.email,
            "campaign_id": outbound_draft.workflow_id or "",
        }, actor="system")
    else:
        publish(session_token, WMEventType.DRAFT_FAILED, {
            "draft_id": draft_id,
            "error": result.get("error", "Unknown error"),
        }, actor="system")
    return {"ok": result.get("ok", False), "send_result": result}


class ScheduleDraftRequest(BaseModel):
    send_at: str  # ISO 8601 datetime string


@app.post("/api/web/session/{session_token}/drafts/{draft_id}/schedule")
async def schedule_draft(session_token: str, draft_id: str, payload: ScheduleDraftRequest, request: Request):
    session_token = _session_token_from_request(request)
    from services.outbound.draft_store import draft_store as outbound_draft_store
    from services.outbound.outbound_scheduler import outbound_scheduler
    outbound_draft = outbound_draft_store.get(draft_id)
    owner_id = ""
    try:
        # PR-2B: resolve the owner before hydration so the provider stamp is
        # scoped to this user (same fix as the send route).
        owner_id = await _workspace_owner(request, session_token)
    except HTTPException:
        owner_id = ""
    if not outbound_draft:
        legacy_drafts = draft_store.get(session_token, [])
        legacy = next((d for d in legacy_drafts if d.get("id") == draft_id), None)
        if not legacy:
            raise HTTPException(status_code=404, detail="Draft not found in any store")
        _sync_draft_to_outbound(legacy, session_token, owner_id=owner_id)
        outbound_draft = outbound_draft_store.get(draft_id)
        if not outbound_draft:
            raise HTTPException(status_code=500, detail="Failed to sync draft to outbound store")
    recipient_email = (outbound_draft.recipient.email if outbound_draft.recipient else "") or ""
    if not str(recipient_email).strip():
        return {"ok": False, "error": "This lead has no email address"}
    real_provider_id = _get_outbound_provider_for_draft(outbound_draft, owner_id)
    if not real_provider_id:
        return {"ok": False, "error": "No Gmail outbound provider registered"}
    log.info("[schedule_draft] Scheduling draft %s at %s via provider %s", draft_id, payload.send_at, real_provider_id)
    result = outbound_scheduler.schedule(draft_id, real_provider_id, payload.send_at)
    if result.get("ok"):
        legacy_drafts = draft_store.get(session_token, [])
        for d in legacy_drafts:
            if d.get("id") == draft_id:
                d["status"] = "scheduled"
                break
        publish(session_token, WMEventType.DRAFT_SCHEDULED, {
            "draft_id": draft_id,
            "send_at": payload.send_at,
            "provider_id": real_provider_id,
            "campaign_id": outbound_draft.workflow_id if outbound_draft else "",
        }, actor="user")
    return result


@app.post("/api/web/session/{session_token}/drafts/{draft_id}/cancel-schedule")
async def cancel_schedule_draft(session_token: str, draft_id: str, request: Request = None):
    session_token = _session_token_from_request(request)
    from services.outbound.draft_store import draft_store as outbound_draft_store
    from services.outbound.outbound_scheduler import outbound_scheduler
    outbound_draft = outbound_draft_store.get(draft_id)
    if not outbound_draft:
        raise HTTPException(status_code=404, detail="Draft not found in outbound store")
    owner_id = await _workspace_owner(request, session_token) if request is not None else ""
    if not _outbound_draft_owned_by(outbound_draft, owner_id):
        raise HTTPException(status_code=404, detail="Draft not found in outbound store")
    result = outbound_scheduler.cancel_schedule(draft_id, outbound_draft.provider_id)
    if result.get("ok"):
        legacy_drafts = draft_store.get(session_token, [])
        for d in legacy_drafts:
            if d.get("id") == draft_id:
                d["status"] = "pending"
                break
        publish(session_token, WMEventType.DRAFT_UPDATED, {
            "draft_id": draft_id,
            "status": "pending",
            "previous_status": "scheduled",
        }, actor="user")
    return result


@app.post("/api/web/session/{session_token}/outbound/send")
async def outbound_send(session_token: str, payload: OutboundSendRequest):
    result = outbound_executor.execute("send_reply", {
        "provider_id": payload.provider_id,
        "draft_id": payload.draft_id,
        "conversation_id": payload.conversation_id,
        "thread_id": payload.thread_id,
        "workflow_id": payload.workflow_id,
        "subject": payload.subject,
        "body": payload.body,
        "recipient": {"email": payload.recipient_email, "name": payload.recipient_name} if payload.recipient_email else {},
        "sender": {"email": payload.sender_email, "name": payload.sender_name} if payload.sender_email else {},
    })
    return result


@app.post("/api/web/session/{session_token}/outbound/schedule")
async def outbound_schedule(session_token: str, payload: OutboundScheduleRequest):
    from services.outbound.outbound_scheduler import outbound_scheduler
    result = outbound_scheduler.schedule(payload.draft_id, payload.provider_id, payload.send_at)
    return result


@app.delete("/api/web/session/{session_token}/outbound/schedule/{schedule_id}")
async def outbound_cancel_schedule(session_token: str, schedule_id: str, provider_id: str = "", request: Request = None):
    from services.outbound.outbound_scheduler import outbound_scheduler
    from services.outbound.draft_store import draft_store as outbound_draft_store
    draft = outbound_draft_store.get(schedule_id)
    owner_id = await _workspace_owner(request, session_token) if request is not None else ""
    if not _outbound_draft_owned_by(draft, owner_id):
        raise HTTPException(status_code=404, detail="Schedule not found")
    result = outbound_scheduler.cancel_schedule(schedule_id, provider_id)
    return result


@app.get("/api/web/session/{session_token}/outbound/drafts")
async def outbound_list_drafts(session_token: str, provider_id: str = ""):
    if provider_id:
        result = outbound_draft_store.list_by_provider(provider_id)
    else:
        result = outbound_draft_store.list_all()
    return {"ok": True, "drafts": [d.model_dump() for d in result.drafts], "total": result.total}


@app.get("/api/web/session/{session_token}/outbound/drafts/{draft_id}")
async def outbound_get_draft(session_token: str, draft_id: str, request: Request = None):
    owner_id = await _workspace_owner(request, session_token) if request is not None else ""
    draft = outbound_draft_store.get(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    if not _outbound_draft_owned_by(draft, owner_id):
        raise HTTPException(status_code=404, detail="Draft not found")
    return {"ok": True, "draft": draft.model_dump()}


@app.post("/api/web/session/{session_token}/outbound/drafts/{draft_id}/approve")
async def outbound_approve_draft(session_token: str, draft_id: str, auto: bool = False, request: Request = None):
    session_token = _session_token_from_request(request)
    owner_id = await _workspace_owner(request, session_token) if request is not None else ""
    draft = outbound_draft_store.get(draft_id)
    if not _outbound_draft_owned_by(draft, owner_id):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Draft not found")
    result = outbound_draft_store.approve(draft_id, auto=auto)
    if not result:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Draft not found")
    try:
        from services.outbound.outbound_registry import create_draft as reg_create_draft
        provider_result = reg_create_draft(result.provider_id, result)
        if not provider_result:
            err = "No provider registered for " + result.provider_id
            outbound_draft_store.mark_failed(draft_id, err)
            raise HTTPException(status_code=502, detail=err)
        if not provider_result.external_draft_id:
            err = "Provider created draft but returned no external_draft_id"
            outbound_draft_store.mark_failed(draft_id, err)
            raise HTTPException(status_code=502, detail=err)
        updated = outbound_draft_store.get(draft_id)
        if updated:
            updated.external_draft_id = provider_result.external_draft_id
            if provider_result.thread_id:
                updated.thread_id = provider_result.thread_id
            outbound_draft_store.update(updated)
        publish(session_token, WMEventType.DRAFT_APPROVED, {
            "draft_id": draft_id,
            "provider_id": result.provider_id,
            "auto": auto,
            "campaign_id": result.workflow_id or "",
        }, actor="user")
        return {"ok": True, "draft": updated.model_dump() if updated else result.model_dump()}
    except HTTPException:
        raise
    except Exception as e:
        outbound_draft_store.mark_failed(draft_id, str(e))
        publish(session_token, WMEventType.DRAFT_FAILED, {
            "draft_id": draft_id,
            "error": str(e),
        }, actor="system")
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/web/session/{session_token}/outbound/drafts/{draft_id}/reject")
async def outbound_reject_draft(session_token: str, draft_id: str, request: Request = None):
    session_token = _session_token_from_request(request)
    owner_id = await _workspace_owner(request, session_token) if request is not None else ""
    draft = outbound_draft_store.get(draft_id)
    if not _outbound_draft_owned_by(draft, owner_id):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Draft not found")
    result = outbound_draft_store.reject(draft_id)
    if not result:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Draft not found")
    publish(session_token, WMEventType.DRAFT_REJECTED, {
        "draft_id": draft_id,
        "provider_id": result.provider_id,
        "campaign_id": result.workflow_id or "",
    }, actor="user")
    return {"ok": True, "draft": result.model_dump()}


class ApproveAllRequest(BaseModel):
    auto: bool = False


@app.post("/api/web/session/{session_token}/outbound/approve-all")
async def outbound_approve_all(session_token: str, payload: ApproveAllRequest, request: Request = None):
    session_token = _session_token_from_request(request)
    owner_id = await _workspace_owner(request, session_token) if request is not None else ""
    all_drafts = outbound_draft_store.list_all()
    # PR10.8.3.2: only the authenticated owner's drafts may be approved.
    pending = [
        d for d in all_drafts.drafts
        if d.status.value in ("draft", "pending_approval")
        and _outbound_draft_owned_by(d, owner_id)
    ]
    if not pending:
        return {"ok": True, "total": 0, "created": 0, "failed": 0, "results": []}
    from services.outbound.outbound_registry import create_draft as reg_create_draft
    results = []
    for draft in pending:
        try:
            outbound_draft_store.approve(draft.id, auto=payload.auto)
            provider_result = reg_create_draft(draft.provider_id, draft)
            if not provider_result or not provider_result.external_draft_id:
                outbound_draft_store.mark_failed(draft.id, "No provider or no external_draft_id returned")
                results.append({"draft_id": draft.id, "ok": False, "error": "No provider or no external_draft_id"})
            else:
                updated = outbound_draft_store.get(draft.id)
                if updated:
                    updated.external_draft_id = provider_result.external_draft_id
                    if provider_result.thread_id:
                        updated.thread_id = provider_result.thread_id
                    outbound_draft_store.update(updated)
                results.append({"draft_id": draft.id, "ok": True})
        except Exception as e:
            outbound_draft_store.mark_failed(draft.id, str(e))
            results.append({"draft_id": draft.id, "ok": False, "error": str(e)})
    created = sum(1 for r in results if r["ok"])
    failed = sum(1 for r in results if not r["ok"])
    publish(session_token, WMEventType.CAMPAIGN_STATUS_CHANGED, {
        "campaign_id": "approve_all",
        "status": "approved",
        "draft_count": created,
        "failed_count": failed,
    }, actor="user")
    return {"ok": True, "total": len(pending), "created": created, "failed": failed, "results": results}


@app.get("/api/web/session/{session_token}/outbound/history")
async def outbound_history(session_token: str, request: Request, provider_id: str = ""):
    session_token = _session_token_from_request(request)
    history = outbound_persistence.get_history(provider_id=provider_id)
    # SaaS-2.6: also surface the caller's durable, tenant-scoped send history.
    durable = []
    try:
        owner_id = await _workspace_owner(request, session_token)
        from services.workspace_state import ensure_workspace
        ws = await _resolved_workspace_id_or_default(request, owner_id)
        if ws:
            from services.persistence.launch.communication_persistence import list_outbound_history
            durable = await asyncio.to_thread(list_outbound_history, ws, provider_id, 100)
    except HTTPException:
        durable = []
    except Exception:  # noqa: BLE001
        durable = []
    merged = list(history)
    seen = {h.id for h in merged}
    for d in durable:
        if getattr(d, "id", "") not in seen:
            merged.append(d)
    merged.sort(key=lambda h: getattr(h, "sent_at", "") or "", reverse=True)

    def _hist_dict(h):
        if hasattr(h, "model_dump"):
            return h.model_dump()
        return {
            "id": getattr(h, "id", ""),
            "provider_id": getattr(h, "provider_id", ""),
            "external_message_id": getattr(h, "external_message_id", ""),
            "conversation_id": getattr(h, "conversation_id", ""),
            "thread_id": getattr(h, "thread_id", ""),
            "workflow_id": "",
            "subject": getattr(h, "subject", ""),
            "recipient": {"email": getattr(h, "recipient_email", ""), "name": getattr(h, "recipient_name", "")},
            "status": getattr(h, "status", "sent"),
            "sent_at": getattr(h, "sent_at", "").isoformat() if getattr(h, "sent_at", None) else "",
            "draft_id": getattr(h, "draft_id", ""),
            "error": getattr(h, "error", ""),
        }

    return {"ok": True, "history": [_hist_dict(h) for h in merged]}


@app.get("/api/web/session/{session_token}/outbound/events")
async def outbound_events_endpoint(session_token: str, provider_id: str = "", after: int = 0):
    events = get_outbound_events(provider_id=provider_id, after_sequence=after)
    return {
        "ok": True,
        "events": [
            {
                "id": e.id,
                "event_type": e.event_type.value,
                "provider_id": e.provider_id,
                "message": e.message,
                "timestamp": e.timestamp,
                "sequence": e.sequence,
                "metadata": e.metadata,
            }
            for e in events
        ],
        "latest_sequence": outbound_latest_sequence(),
    }


@app.get("/api/web/session/{session_token}/outbound/drafts/{draft_id}/versions")
async def outbound_draft_versions(session_token: str, draft_id: str):
    versions = outbound_draft_store.get_versions(draft_id)
    return {"ok": True, "versions": [v.model_dump() for v in versions]}


# ── Knowledge Endpoints ──
# User-owned Knowledge foundation (PR5). Ownership is always resolved from
# the authenticated session via _workspace_owner → _async_workspace; the
# client can never supply a workspace/user id.

def _knowledge_service():
    # Construct per request so repositories resolve the current connection
    # manager. This matters during reconnects and keeps tests from retaining a
    # client that was created before the authenticated request was handled.
    from services.knowledge.service import KnowledgeService
    return KnowledgeService()


async def _knowledge_workspace(request: Request, session_token: str) -> tuple[str, str]:
    """Resolve (owner_id, workspace_id) for the authenticated session.

    The workspace is the membership-validated selected workspace (or the
    single-workspace default). A genuine ambiguous multi-workspace request
    (409) is re-raised so the client must select; when the user has no
    accessible workspace via membership (e.g. legacy/fixture contexts), fall
    back to the owner-based single-workspace default for compatibility.
    """
    owner_id = await _workspace_owner(request, session_token)
    try:
        workspace_id = await _selected_workspace_id(request, owner_id)
    except HTTPException as exc:
        if exc.status_code == 409:
            raise
        from services.workspace_state import _async_workspace
        workspace_id = await _async_workspace(owner_id)
    if not workspace_id:
        raise HTTPException(status_code=503, detail="Workspace could not be resolved")
    return owner_id, workspace_id


@app.get("/api/web/session/{session_token}/knowledge")
async def list_knowledge(
    session_token: str,
    request: Request,
    category: str = "",
    q: str = "",
    limit: int = 200,
):
    session_token = _session_token_from_request(request)
    from services.knowledge.service import KnowledgeValidationError
    owner_id, workspace_id = await _knowledge_workspace(request, session_token)
    try:
        items = await _knowledge_service().list_items(
            workspace_id, category=category or None, q=q or None, limit=limit)
    except KnowledgeValidationError as error:
        raise HTTPException(status_code=400, detail=str(error))
    return {"ok": True, "items": items, "owner_id": owner_id}


@app.post("/api/web/session/{session_token}/knowledge")
async def create_knowledge_item(
    session_token: str, payload: KnowledgeItemCreateRequest, request: Request,
):
    session_token = _session_token_from_request(request)
    from services.knowledge.service import KnowledgeValidationError
    owner_id, workspace_id = await _knowledge_workspace(request, session_token)
    try:
        item = await _knowledge_service().create_item(
            owner_id=owner_id,
            workspace_id=workspace_id,
            category=payload.category,
            title=payload.title,
            summary=payload.summary,
            content=payload.content,
            tags=payload.tags,
            source_type=payload.source_type,
            source_id=payload.source_id,
        )
    except KnowledgeValidationError as error:
        raise HTTPException(status_code=400, detail=str(error))
    return {"ok": True, "item": item}


@app.get("/api/web/session/{session_token}/knowledge/sources")
async def list_knowledge_sources(
    session_token: str,
    request: Request,
    q: str = "",
    limit: int = 200,
):
    session_token = _session_token_from_request(request)
    owner_id, workspace_id = await _knowledge_workspace(request, session_token)
    sources = await _knowledge_service().list_sources(
        workspace_id, q=q or None, limit=limit)
    return {"ok": True, "sources": sources, "owner_id": owner_id}


@app.post("/api/web/session/{session_token}/knowledge/sources")
async def create_knowledge_source(
    session_token: str, payload: KnowledgeSourceCreateRequest, request: Request,
):
    session_token = _session_token_from_request(request)
    from services.knowledge.service import KnowledgeValidationError
    owner_id, workspace_id = await _knowledge_workspace(request, session_token)
    try:
        source = await _knowledge_service().create_source(
            owner_id=owner_id,
            workspace_id=workspace_id,
            title=payload.title,
            source_type=payload.source_type,
            content=payload.content,
            reference=payload.reference,
            metadata=payload.metadata,
        )
    except KnowledgeValidationError as error:
        raise HTTPException(status_code=400, detail=str(error))
    return {"ok": True, "source": source}


@app.put("/api/web/session/{session_token}/knowledge/sources/{source_id}")
async def update_knowledge_source(
    session_token: str, source_id: str,
    payload: KnowledgeSourceUpdateRequest, request: Request,
):
    session_token = _session_token_from_request(request)
    from services.knowledge.service import KnowledgeValidationError
    owner_id, workspace_id = await _knowledge_workspace(request, session_token)
    try:
        source = await _knowledge_service().update_source(
            owner_id=owner_id,
            workspace_id=workspace_id,
            source_id=source_id,
            title=payload.title,
            source_type=payload.source_type,
            content=payload.content,
            reference=payload.reference,
            metadata=payload.metadata,
        )
    except KnowledgeValidationError as error:
        raise HTTPException(status_code=400, detail=str(error))
    if source is None:
        raise HTTPException(status_code=404, detail="Knowledge source not found")
    return {"ok": True, "source": source}


@app.delete("/api/web/session/{session_token}/knowledge/sources/{source_id}")
async def archive_knowledge_source(
    session_token: str, source_id: str, request: Request,
):
    session_token = _session_token_from_request(request)
    owner_id, workspace_id = await _knowledge_workspace(request, session_token)
    source = await _knowledge_service().archive_source(
        owner_id=owner_id, workspace_id=workspace_id, source_id=source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Knowledge source not found")
    return {"ok": True, "source": source}


@app.get("/api/web/session/{session_token}/knowledge/{item_id}")
async def get_knowledge_item(session_token: str, item_id: str, request: Request):
    session_token = _session_token_from_request(request)
    owner_id, workspace_id = await _knowledge_workspace(request, session_token)
    item = await _knowledge_service().get_item(workspace_id, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Knowledge item not found")
    return {"ok": True, "item": item}


@app.put("/api/web/session/{session_token}/knowledge/{item_id}")
async def update_knowledge_item(
    session_token: str, item_id: str,
    payload: KnowledgeItemUpdateRequest, request: Request,
):
    session_token = _session_token_from_request(request)
    from services.knowledge.service import KnowledgeValidationError
    owner_id, workspace_id = await _knowledge_workspace(request, session_token)
    try:
        item = await _knowledge_service().update_item(
            owner_id=owner_id,
            workspace_id=workspace_id,
            item_id=item_id,
            title=payload.title,
            summary=payload.summary,
            content=payload.content,
            tags=payload.tags,
            source_type=payload.source_type,
            source_id=payload.source_id,
        )
    except KnowledgeValidationError as error:
        raise HTTPException(status_code=400, detail=str(error))
    if item is None:
        raise HTTPException(status_code=404, detail="Knowledge item not found")
    return {"ok": True, "item": item}


@app.delete("/api/web/session/{session_token}/knowledge/{item_id}")
async def archive_knowledge_item(session_token: str, item_id: str, request: Request):
    session_token = _session_token_from_request(request)
    owner_id, workspace_id = await _knowledge_workspace(request, session_token)
    item = await _knowledge_service().archive_item(
        owner_id=owner_id, workspace_id=workspace_id, item_id=item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Knowledge item not found")
    return {"ok": True, "item": item}


# ── Strategic Intelligence Endpoints ──
# Refreshing creates/refreshes read-only evidence-backed updates. It never
# mutates Knowledge, campaigns, drafts, conversations, or messages.

def _strategic_service():
    from services.strategic.service import StrategicIntelligenceService
    return StrategicIntelligenceService()


@app.get("/api/web/session/{session_token}/strategic-updates")
async def list_strategic_updates(
    session_token: str,
    request: Request,
    update_type: str = "",
    confidence: str = "",
    q: str = "",
    include_archived: bool = False,
):
    session_token = _session_token_from_request(request)
    owner_id = await _workspace_owner(request, session_token)
    updates = await _strategic_service().list_updates(
        owner_id,
        update_type=update_type or None,
        confidence=confidence or None,
        query=q or None,
        include_archived=include_archived,
    )
    last_analyzed = max(
        (str(update.get("updated_at") or "") for update in updates),
        default=None,
    )
    return {"ok": True, "updates": updates, "last_analyzed": last_analyzed}


@app.post("/api/web/session/{session_token}/strategic-updates/refresh")
async def refresh_strategic_updates(session_token: str, request: Request):
    session_token = _session_token_from_request(request)
    owner_id = await _workspace_owner(request, session_token)
    return await _strategic_service().refresh(owner_id)


@app.get("/api/web/session/{session_token}/strategic-updates/{update_id}/actions")
async def list_strategic_actions(session_token: str, update_id: str, request: Request):
    session_token = _session_token_from_request(request)
    owner_id = await _workspace_owner(request, session_token)
    actions = await _strategic_action_service().list_actions(owner_id, update_id)
    return {"ok": True, "actions": actions}


@app.post("/api/web/session/{session_token}/strategic-updates/{update_id}/actions")
async def propose_strategic_action(
    session_token: str, update_id: str, request: Request, payload: dict = None,
):
    session_token = _session_token_from_request(request)
    from services.strategic.actions import StrategicActionError
    owner_id = await _workspace_owner(request, session_token)
    action_type = str((payload or {}).get("action_type") or "").strip()
    try:
        action = await _strategic_action_service().propose(owner_id, update_id, action_type)
    except StrategicActionError as error:
        raise _strategic_action_http_error(error)
    return {"ok": True, "action": action}


@app.get("/api/web/session/{session_token}/strategic-updates/{update_id}")
async def get_strategic_update(session_token: str, update_id: str, request: Request):
    session_token = _session_token_from_request(request)
    owner_id = await _workspace_owner(request, session_token)
    update = await _strategic_service().get_update(owner_id, update_id)
    if update is None:
        raise HTTPException(status_code=404, detail="Strategic Update not found")
    return {"ok": True, "update": update}


def _strategic_action_service():
    from services.strategic.actions import StrategicActionService
    return StrategicActionService()


def _strategic_action_http_error(error: Exception) -> HTTPException:
    status = 404 if "not found" in str(error).lower() else 400
    return HTTPException(status_code=status, detail=str(error))


async def _action_route_call(method: str, owner_id: str, action_id: str, *args):
    from services.strategic.actions import StrategicActionError
    try:
        return await getattr(_strategic_action_service(), method)(owner_id, action_id, *args)
    except StrategicActionError as error:
        raise _strategic_action_http_error(error)


@app.post("/api/web/session/{session_token}/strategic-actions/{action_id}/approve")
async def approve_strategic_action(session_token: str, action_id: str, request: Request):
    session_token = _session_token_from_request(request)
    owner_id = await _workspace_owner(request, session_token)
    return {"ok": True, "action": await _action_route_call("approve", owner_id, action_id)}


@app.post("/api/web/session/{session_token}/strategic-actions/{action_id}/dismiss")
async def dismiss_strategic_action(session_token: str, action_id: str, request: Request):
    session_token = _session_token_from_request(request)
    owner_id = await _workspace_owner(request, session_token)
    return {"ok": True, "action": await _action_route_call("dismiss", owner_id, action_id)}


@app.post("/api/web/session/{session_token}/strategic-actions/{action_id}/refine")
async def refine_strategic_action(
    session_token: str, action_id: str, request: Request, payload: dict = None,
):
    session_token = _session_token_from_request(request)
    owner_id = await _workspace_owner(request, session_token)
    changes = (payload or {}).get("changes") if isinstance(payload, dict) else {}
    return {"ok": True, "action": await _action_route_call("refine", owner_id, action_id, changes or {})}


@app.post("/api/web/session/{session_token}/strategic-actions/{action_id}/execute")
async def execute_strategic_action(session_token: str, action_id: str, request: Request):
    session_token = _session_token_from_request(request)
    owner_id = await _workspace_owner(request, session_token)
    return {"ok": True, "action": await _action_route_call("execute", owner_id, action_id)}


@app.delete("/api/web/session/{session_token}/strategic-updates/{update_id}")
async def archive_strategic_update(session_token: str, update_id: str, request: Request):
    session_token = _session_token_from_request(request)
    owner_id = await _workspace_owner(request, session_token)
    update = await _strategic_service().archive_update(owner_id, update_id)
    if update is None:
        raise HTTPException(status_code=404, detail="Strategic Update not found")
    return {"ok": True, "update": update}


# ── Campaign Endpoints ──


async def _workspace_owner(request: Request, session_token: str) -> str:
    """Resolve the durable workspace owner, never the temporary web token."""
    owner_id, _ = await _workspace_owner_and_summary(request, session_token)
    return owner_id


def _session_token_from_request(request: Request) -> str:
    """Return the web-session token from the Authorization header only.

    PR10.8.3.1: session credentials are never accepted from URL paths, query
    parameters, or fragments. The frontend sends ``Authorization: Bearer`` and
    uses a fixed ``_`` placeholder in legacy URL paths.
    """
    if request is None:
        return ""
    headers = getattr(request, "headers", None)
    if headers is None:
        return ""
    try:
        authorization = headers.get("authorization", "")
    except Exception:
        return ""
    if not isinstance(authorization, str):
        authorization = str(authorization)
    if not authorization:
        return ""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return ""
    return token.strip()


async def _resolve_session_context(request: Request) -> tuple[str, str]:
    """Return ``(owner_id, web_session_token)`` from the Authorization header.

    Supports both the identity access token and the legacy web-session token.
    Never trusts client-supplied path params or user_ids. Raises 401 when the
    request is not authenticated (PR10.8.3.1 — fail closed, no URL fallback).

    SaaS-1.6 authority rule: when the web-session token is bound to a
    canonical identity session (web_session_bindings), the actor is the
    canonical user and the request is authorized ONLY while that canonical
    session remains valid (not revoked / not expired). A canonical-session
    revocation (logout, password change, password reset) therefore
    invalidates the bound web-session bearer.
    """
    token = _session_token_from_request(request)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        from services.identity.api import get_authenticated_user_id
        user_id = await get_authenticated_user_id(request)
        if user_id:
            return str(user_id), token
    except HTTPException:
        pass
    # PR-2B: this resolver previously fetched the FULL session summary
    # (~9-10 Supabase queries) and used only ``user_id``. The minimal cached
    # identity serves the same decision with 2-4 queries at most, and a 15s
    # TTL absorbs the per-request repetition.
    identity = await _cached_session_identity(token)
    if identity and identity.get("user_id"):
        binding = await _web_session_binding(token)
        if binding is not None:
            # The web-session is bound to a canonical session: require that
            # session to be valid before authorizing (sliding activity).
            from services.identity.api import _get_service
            try:
                await _get_service()._session_svc.touch_session(binding.canonical_session_id)
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(
                    status_code=401, detail="Invalid or expired session",
                ) from exc
            return binding.canonical_user_id, token
        return str(identity["user_id"]), token
    raise HTTPException(status_code=401, detail="Invalid or expired session")


_BINDING_TTL_SECONDS = 10


async def _web_session_binding(token: str):
    """Resolve the canonical web-session binding for a bearer token.

    PR-3A: cached in Redis (shared across workers) for 10s, including
    explicit negatives. Authority is NOT the cache: for bound sessions the
    resolver still calls ``touch_session`` on EVERY request, which fails
    closed (401) when the canonical session is revoked/expired — so
    revocation enforcement stays immediate regardless of cached contents.
    The cache only removes a repeated binding SELECT per request.
    """
    import json as _json
    from services import redis_client
    from services.session_cache import _token_hash

    key = redis_client.k_session_binding(_token_hash(token))
    local = getattr(_web_session_binding, "_local", None)
    if local is None:
        local = _web_session_binding._local = {}

    now = time.monotonic()
    entry = local.get(key)
    if entry is not None:
        expires_at, value = entry
        if expires_at > now:
            return value[1] if value[0] else None
        local.pop(key, None)

    client = await redis_client.get_client()
    if client is not None:
        try:
            raw = await asyncio.wait_for(client.get(key), redis_client.OPERATION_TIMEOUT)
            if raw is not None:
                data = _json.loads(raw)
                found = data.get("b") if isinstance(data, dict) else None
                local[key] = (now + _BINDING_TTL_SECONDS, (1, found))
                return found
        except Exception as error:  # noqa: BLE001 — degraded mode only
            log.debug("binding_cache_read_failed error_type=%s", type(error).__name__)
            client = None

    from services.web_session_binding import find_binding
    binding = await find_binding(token)

    if client is not None:
        try:
            payload = {"b": binding} if binding is not None else {}
            await asyncio.wait_for(
                client.set(key, _json.dumps(payload, separators=(",", ":")), ex=_BINDING_TTL_SECONDS),
                redis_client.OPERATION_TIMEOUT,
            )
        except Exception as error:  # noqa: BLE001
            log.debug("binding_cache_write_failed error_type=%s", type(error).__name__)
    local[key] = (
        now + _BINDING_TTL_SECONDS,
        (0 if binding is None else 1, binding),
    )
    return binding


async def _cached_session_identity(token: str) -> dict | None:
    """PR-2B: minimal per-token identity with a 15s TTL.

    Returns {user_id, display_name, gmail_connected} or None. Cache holds no
    credentials; invalidated on provider connect/disconnect and session
    revocation. Redis replaces the backing store pre-launch without caller
    changes (see services/session_cache.py).
    """
    from services.session_cache import session_cache, SessionIdentity

    # PR-3A: Redis-backed (shared across workers); local mirror only serves
    # while Redis is unavailable. None → caller falls back to Supabase.
    cached = await session_cache.get_identity(token)
    if cached is not None:
        return cached
    try:
        identity = await asyncio.to_thread(engine.get_web_session_identity, token)
    except Exception as error:
        log.warning("session_identity_lookup_failed error_type=%s", type(error).__name__)
        return None
    if identity and identity.get("user_id"):
        await session_cache.set_identity(token, SessionIdentity(
            user_id=str(identity["user_id"]),
            display_name=str(identity.get("display_name") or ""),
            gmail_connected=bool(identity.get("gmail_connected")),
        ))
    return identity


async def _workspace_owner_and_summary(request: Request, session_token: str = "") -> tuple[str, dict | None]:
    """Resolve the durable workspace owner and the web-session summary.

    PR10.8.3.1: authentication comes from the Authorization header only; the
    legacy ``{session_token}`` URL path parameter is ignored and never used as
    a credential.

    PR-2B: every current caller reads only ``summary["user_id"]`` — the full
    ~9-query summary fetch has been replaced with the cached minimal
    identity. The returned "summary" keeps its historical shape
    (``{"user_id": ...}``) so callers are untouched.
    """
    owner_id, token = await _resolve_session_context(request)
    identity = await _cached_session_identity(token)
    return owner_id, ({"user_id": identity["user_id"]} if identity else None)


def _workspace_campaigns(user_id: str, session_token: str = "", workspace_id: str = "",
                         include_details: bool = True) -> list[dict[str, Any]]:
    from services.workspace_state import load_workspace_state
    return load_workspace_state(user_id, workspace_id=workspace_id,
                                include_details=include_details)["campaigns"]


def _workspace_drafts(user_id: str, session_token: str = "", workspace_id: str = "") -> list[dict[str, Any]]:
    from services.workspace_state import load_drafts_only
    return load_drafts_only(user_id, workspace_id=workspace_id)


def _workspace_id_from_request(request: Request) -> str:
    """The explicitly selected workspace id (header), if any.

    This is a non-authoritative input: it is independently validated against
    the authenticated user's ACTIVE memberships before use.
    """
    if request is None:
        return ""
    try:
        value = request.headers.get("x-workspace-id") if hasattr(request, "headers") else ""
    except Exception:  # noqa: BLE001
        return ""
    if not isinstance(value, str):
        return ""
    return value.strip()


async def _resolve_selected_workspace_context(request: Request, owner_id: str):
    """Resolve + validate the selected workspace context for the caller.

    Raises a safe HTTP error when the requested workspace is inaccessible, the
    user has no accessible workspace, or multiple accessible workspaces exist
    without an explicit selection. Never trusts the client id as authority.
    """
    from services.workspace_context import (
        AmbiguousWorkspaceError,
        NoWorkspaceAvailable,
        WorkspaceAccessDenied,
        resolve_workspace_context,
    )
    requested = _workspace_id_from_request(request)
    try:
        ctx = await asyncio.to_thread(
            resolve_workspace_context, None, owner_id, requested,
        )
    except WorkspaceAccessDenied:
        raise HTTPException(status_code=404, detail="Workspace not found")
    except NoWorkspaceAvailable:
        raise HTTPException(status_code=404, detail="No accessible workspace")
    except AmbiguousWorkspaceError:
        raise HTTPException(
            status_code=409,
            detail="Multiple workspaces available; select one via the X-Workspace-Id header",
        )
    return ctx


async def _selected_workspace_id(request: Request, owner_id: str) -> str:
    """The validated selected workspace id for the caller (raises on error)."""
    ctx = await _resolve_selected_workspace_context(request, owner_id)
    return ctx.workspace_id


async def _resolved_workspace_id_or_default(request: Request, owner_id: str) -> str:
    """Selected workspace, falling back to the owner-based single-workspace
    default when membership resolution finds no accessible workspace (legacy /
    fixture accounts without a durable membership).

    A genuine ambiguous multi-workspace request (409) is re-raised so the
    client must select; never silently picks a workspace when multiple are
    accessible.
    """
    try:
        return await _selected_workspace_id(request, owner_id)
    except HTTPException as exc:
        if exc.status_code == 409:
            raise
        # Owner-based single-workspace default (legacy / fixture accounts
        # without a durable membership). Defensive: an invalid/non-uuid owner
        # id in a test/legacy context must not break the request.
        try:
            from services.workspace_state import _async_workspace
            return await _async_workspace(owner_id) or ""
        except Exception:  # noqa: BLE001
            return ""


@app.post("/api/web/session/{session_token}/campaigns")
async def save_campaign(session_token: str, payload: SaveCampaignRequest, request: Request):
    session_token = _session_token_from_request(request)
    owner_id = await _workspace_owner(request, session_token)
    ws_id = await _resolved_workspace_id_or_default(request, owner_id)
    now = datetime.now(timezone.utc).isoformat()
    leads = payload.leads or []
    campaign = {
        "id": str(uuid.uuid4()),
        "name": payload.name,
        "objective": payload.objective,
        "search_query": payload.search_query,
        "discovery_id": payload.discovery_id,
        "lead_count": payload.lead_count or len(leads),
        "leads": leads,
        "status": payload.status,
        "strategy": payload.strategy,
        "created_at": now,
        "updated_at": now,
    }
    from services.workspace_state import append_event, persist_campaign_lead_awaited, persist_campaign_row
    if not await persist_campaign_row(owner_id, campaign, workspace_id=ws_id):
        raise HTTPException(status_code=503, detail="Campaign could not be persisted")
    failed_leads = 0
    for lead in leads:
        if not await persist_campaign_lead_awaited(owner_id, campaign["id"], lead, workspace_id=ws_id):
            failed_leads += 1
    if failed_leads:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Campaign created but {failed_leads} of {len(leads)} "
                "lead(s) could not be persisted"
            ),
        )
    append_event(owner_id, "campaign.created", {"campaign": campaign})
    record_campaign_created(session_token, payload.name)
    publish(session_token, WMEventType.CAMPAIGN_CREATED, {
        "id": campaign["id"],
        "name": campaign["name"],
        "status": campaign["status"],
        "lead_count": campaign["lead_count"],
        "search_query": campaign["search_query"],
    }, actor="user")
    _get_feedback().on_campaign_created(session_token, campaign["id"])
    await _maybe_auto_strategy(
        session_token,
        owner_id,
        campaign["id"],
        str(payload.objective or "").strip(),
        campaign,
    )
    return {"ok": True, "campaign": campaign}


@app.get("/api/web/session/{session_token}/campaigns")
async def list_campaigns(session_token: str, request: Request):
    session_token = _session_token_from_request(request)
    import time as _t
    _t0 = _t.perf_counter()
    from services.workspace_snapshot import enrich_campaigns
    owner_id = await _workspace_owner(request, session_token)
    ws_id = await _resolved_workspace_id_or_default(request, owner_id)
    # PR-3B: (a) campaigns load COUNTS-ONLY — the list page never renders
    # nested leads/strategies, so the previous full graph fan-out
    # (ws_leads/leads/companies/strategies per id) was pure overfetch;
    # (b) campaigns + drafts are independent once ws_id is known → run
    # concurrently instead of serially.
    campaigns, drafts = await asyncio.gather(
        asyncio.to_thread(_workspace_campaigns, owner_id, session_token,
                          workspace_id=ws_id, include_details=False),
        asyncio.to_thread(_workspace_drafts, owner_id, session_token, workspace_id=ws_id),
    )
    log.info("[perf] route=/campaigns owner=%s ms=%.0f campaigns=%d",
             owner_id[:8], (_t.perf_counter() - _t0) * 1000, len(campaigns))
    return {"ok": True, "campaigns": enrich_campaigns(campaigns, drafts)}


@app.get("/api/web/session/{session_token}/campaigns/summary")
async def campaign_summary(session_token: str, request: Request):
    session_token = _session_token_from_request(request)
    from services.workspace_snapshot import enrich_campaigns
    owner_id = await _workspace_owner(request, session_token)
    ws_id = await _resolved_workspace_id_or_default(request, owner_id)
    campaigns = _workspace_campaigns(owner_id, session_token, workspace_id=ws_id)
    drafts = _workspace_drafts(owner_id, session_token, workspace_id=ws_id)
    enriched = enrich_campaigns(campaigns, drafts)
    items = [{
        "id": c.get("id", ""),
        "name": c.get("name", ""),
        "status": c.get("status", "planning"),
        "lead_count": c.get("lead_count", 0),
        "pending_drafts": c.get("pending_drafts", 0),
        "updated_at": c.get("updated_at", ""),
    } for c in enriched]
    return {"ok": True, "campaigns": items}


@app.get("/api/web/session/{session_token}/campaigns/{campaign_id}")
async def get_campaign(session_token: str, campaign_id: str, request: Request):
    session_token = _session_token_from_request(request)
    from services.workspace_snapshot import enrich_campaigns
    owner_id = await _workspace_owner(request, session_token)
    ws_id = await _resolved_workspace_id_or_default(request, owner_id)
    campaigns = _workspace_campaigns(owner_id, session_token, workspace_id=ws_id)
    drafts = _workspace_drafts(owner_id, session_token, workspace_id=ws_id)
    enriched = enrich_campaigns(campaigns, drafts)
    target = next((c for c in enriched if c.get("id") == campaign_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Campaign not found")
    record_campaign_open(session_token, campaign_id, target.get("name", ""))
    return {"ok": True, "campaign": target}


@app.get("/api/web/session/{session_token}/campaigns/{campaign_id}/launch-progress")
async def campaign_launch_progress(session_token: str, campaign_id: str, request: Request):
    session_token = _session_token_from_request(request)
    owner_id = await _workspace_owner(request, session_token)
    ws_id = await _resolved_workspace_id_or_default(request, owner_id)
    campaigns = _workspace_campaigns(owner_id, session_token, workspace_id=ws_id)
    target = next((c for c in campaigns if c.get("id") == campaign_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return {
        "ok": True,
        "launch_sent": target.get("launch_sent", 0),
        "launch_total": target.get("launch_total", 0),
        "launch_complete": target.get("launch_sent", 0) >= target.get("launch_total", 0) if target.get("launch_total", 0) > 0 else False,
    }


@app.get("/api/web/session/{session_token}/campaigns/{campaign_id}/timeline")
async def campaign_timeline(session_token: str, campaign_id: str, request: Request):
    session_token = _session_token_from_request(request)
    """Read-only campaign event timeline derived from World Model events.

    Aggregates events carrying this campaign_id (draft generated/updated/
    approved/sent/failed, campaign status changes) from the in-memory WM
    log, ordered by sequence. No new persistence — read-only projection.
    """
    owner_id = await _workspace_owner(request, session_token)
    campaigns = _workspace_campaigns(owner_id, session_token)
    target = next((c for c in campaigns if c.get("id") == campaign_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Campaign not found")
    store = get_wm_store()
    events: list[dict] = []
    after_sequence = 0
    while True:
        batch = store.get_events(session_token, after_sequence=after_sequence, limit=100)
        if not batch:
            break
        after_sequence = batch[-1].sequence
        for event in batch:
            if event.data.get("campaign_id") == campaign_id:
                events.append(event.to_dict())
        if len(batch) < 100:
            break
    return {"ok": True, "campaign_id": campaign_id, "events": events}


@app.put("/api/web/session/{session_token}/campaigns/{campaign_id}")
async def update_campaign(session_token: str, campaign_id: str, payload: UpdateCampaignRequest, request: Request):
    session_token = _session_token_from_request(request)
    owner_id = await _workspace_owner(request, session_token)
    ws_id = await _resolved_workspace_id_or_default(request, owner_id)
    campaigns = _workspace_campaigns(owner_id, session_token, workspace_id=ws_id)
    target = next((c for c in campaigns if c.get("id") == campaign_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Campaign not found")
    updates: dict[str, Any] = {}
    if payload.name is not None:
        target["name"] = payload.name
        updates["name"] = payload.name
    if payload.objective is not None:
        target["objective"] = payload.objective
        updates["objective"] = payload.objective
    if payload.strategy is not None:
        target["strategy"] = payload.strategy
        updates["strategy"] = payload.strategy
    if payload.status is not None:
        if payload.status not in VALID_CAMPAIGN_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid campaign status: {payload.status}")
        old_status = target.get("status", "")
        target["status"] = payload.status
        updates["status"] = payload.status
        publish(session_token, WMEventType.CAMPAIGN_STATUS_CHANGED, {
            "campaign_id": campaign_id,
            "status": payload.status,
            "previous_status": old_status,
        }, actor="user")
        if payload.status == "completed" and old_status != "completed":
            durable_drafts = _workspace_drafts(owner_id, session_token, workspace_id=ws_id)
            approved = [d for d in durable_drafts
                        if d.get("campaign_id") == campaign_id and d.get("status") == "approved"]
            if not approved:
                raise HTTPException(
                    status_code=400,
                    detail="No approved drafts — approve at least one draft before launching",
                )
            record_campaign_launched(session_token, target.get("name", ""))
            _get_feedback().on_campaign_launched(session_token, campaign_id)
            launch_result = await _dispatch_campaign_sends(session_token, target, owner_id)
            target["launch_result"] = {k: launch_result.get(k) for k in
                                       ("total", "sent", "failed", "error") if k in launch_result}
            if not launch_result.get("ok") and launch_result.get("error"):
                raise HTTPException(status_code=400, detail=launch_result["error"])
    elif payload.name is not None:
        publish(session_token, WMEventType.CAMPAIGN_UPDATED, {
            "campaign_id": campaign_id,
            "name": payload.name,
        }, actor="user")
    target["updated_at"] = datetime.now(timezone.utc).isoformat()
    from services.workspace_state import persist_campaign_update_awaited
    if updates and not await persist_campaign_update_awaited(owner_id, campaign_id, updates, workspace_id=ws_id):
        raise HTTPException(status_code=503, detail="Campaign update could not be persisted")
    return {"ok": True, "campaign": target}


async def _build_strategy_context(target: dict[str, Any]) -> dict[str, Any]:
    """Assemble the strategy-generation context from a campaign's persisted state.

    Pure extraction of the pre-3.1 synchronous endpoint body: leads profile,
    discovery plan + real market research when the campaign was built from a
    completed discovery. Grinds gracefully to the objective-only path for
    campaigns that predate discovery.
    """
    context: dict[str, Any] = {}
    lead_dicts = [l for l in (target.get("leads") or []) if isinstance(l, dict)]
    if lead_dicts:
        context["leads"] = [
            {
                "name": lead.get("name") or f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip(),
                "title": lead.get("title", ""),
                "company": lead.get("company", ""),
                "domain": lead.get("domain", ""),
            }
            for lead in lead_dicts
        ][:8]

        def _top_counts(items: list[str], limit: int) -> dict[str, int]:
            counts: dict[str, int] = {}
            for value in items:
                value = str(value or "").strip()
                if not value:
                    continue
                counts[value] = counts.get(value, 0) + 1
            return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit])

        companies: list[str] = []
        for lead in lead_dicts:
            company = str(lead.get("company") or "").strip()
            if company and company.lower() not in {c.lower() for c in companies}:
                companies.append(company)
        industries: list[str] = []
        locations: list[str] = []
        sizes: list[str] = []
        for lead in lead_dicts:
            industries.append(str(lead.get("industry") or ""))
            location = str(lead.get("city") or "").strip() or str(lead.get("country") or "").strip()
            if location:
                locations.append(location)
            employees = lead.get("employee_count")
            if isinstance(employees, (int, float)) and employees > 0:
                if employees < 50:
                    sizes.append("1-50 employees")
                elif employees < 200:
                    sizes.append("51-200 employees")
                elif employees < 1000:
                    sizes.append("201-1000 employees")
                else:
                    sizes.append("1,000+ employees")
        context["audience_profile"] = {
            "lead_count": len(lead_dicts),
            "companies": companies[:12],
            "industry_distribution": _top_counts(industries, 6),
            "location_distribution": _top_counts(locations, 6),
            "size_distribution": _top_counts(sizes, 4),
        }

    # Attach the Discovery Plan + real market research when the campaign was
    # built from a completed discovery. Grinds gracefully to the old
    # objective-only path for campaigns that predate discovery.
    discovery_id = str(target.get("discovery_id") or "").strip()
    if discovery_id:
        try:
            from services.discovery import get_discovery
            discovery = await asyncio.to_thread(get_discovery, discovery_id)
        except Exception as e:
            log.warning("[campaign_strategy] discovery lookup failed: %s", e)
            discovery = None
        if discovery:
            metadata = discovery.get("metadata") or {}
            plan = metadata.get("plan") if isinstance(metadata, dict) else None
            if isinstance(plan, dict) and plan.get("offering"):
                context["discovery_plan"] = plan

            discovered: list[dict] = []
            for dc in discovery.get("discovery_companies") or []:
                if not isinstance(dc, dict):
                    continue
                company = dc.get("company")
                if not isinstance(company, dict):
                    continue
                discovered.append({
                    "name": company.get("name") or "",
                    "industry": company.get("industry") or "",
                    "city": company.get("city") or "",
                    "country": company.get("country") or "",
                    "employees": company.get("employee_count") or 0,
                    "description": company.get("description") or "",
                })
            if discovered:
                res_industries = [c["industry"] for c in discovered if c["industry"]]
                res_locations = [
                    c["city"] or c["country"]
                    for c in discovered if c.get("city") or c.get("country")
                ]
                res_sizes: list[str] = []
                for c in discovered:
                    employees = c.get("employees")
                    if isinstance(employees, (int, float)) and employees > 0:
                        if employees < 50:
                            res_sizes.append("1-50 employees")
                        elif employees < 200:
                            res_sizes.append("51-200 employees")
                        elif employees < 1000:
                            res_sizes.append("201-1000 employees")
                        else:
                            res_sizes.append("1,000+ employees")
                context["market_research"] = {
                    "companies": discovered[:10],
                    "industry_distribution": _top_counts(res_industries, 6),
                    "location_distribution": _top_counts(res_locations, 6),
                    "size_distribution": _top_counts(res_sizes, 4),
                }
                log.info(
                    "[campaign_strategy] injected plan + research from discovery "
                    "%s (%d companies)", discovery_id, len(discovered)
                )
    return context


async def _run_strategy_job(
    session_token: str,
    job: dict[str, Any],
    target: dict[str, Any],
    objective: str,
) -> None:
    """Generate + persist a campaign strategy off the request path.

    The OpenAI call is CPU/IO-blocking (30s timeout inside
    ``_send_openai_request``), so it runs via ``asyncio.to_thread`` — never
    blocks the event loop the way the pre-3.1 synchronous endpoint did.
    """
    job_id = str(job.get("id") or "")
    job["status"] = "running"
    try:
        context = await _build_strategy_context(target)
        from services.knowledge.context_adapter import retrieve_knowledge_context
        knowledge_query = " ".join(
            str(value).strip()
            for value in (objective, target.get("search_query"), target.get("name"))
            if str(value or "").strip()
        )
        retrieved_knowledge = await retrieve_knowledge_context(
            job["owner_id"],
            query=knowledge_query,
            categories=["company", "icp", "messaging", "sales_offer"],
            limit=8,
        )
        context["knowledge_context"] = retrieved_knowledge.to_dict()
        from services.ai import OpenAIError, generate_campaign_strategy as _generate_strategy
        try:
            strategy = await asyncio.to_thread(_generate_strategy, objective, context)
        except OpenAIError as error:
            log.warning("[campaign_strategy] OpenAI generation failed, using fallback: %s", error)
            from services.ai import _fallback_playbook
            strategy = _fallback_playbook(objective, context)
        strategy["objective"] = objective
        strategy["generated_at"] = datetime.now(timezone.utc).isoformat()
        from services.workspace_state import persist_campaign_update_awaited
        ok = await persist_campaign_update_awaited(
            job["owner_id"], job["campaign_id"], {"strategy": strategy}
        )
        if not ok:
            raise RuntimeError("Strategy could not be persisted")
        job["strategy"] = strategy
        job["status"] = "completed"
        job["finished_at"] = datetime.now(timezone.utc).isoformat()
        publish(session_token, WMEventType.CAMPAIGN_UPDATED, {
            "campaign_id": job["campaign_id"],
            "objective": objective,
            "strategy": strategy,
        }, actor="loqi")
    except Exception as e:
        log.error("[campaign_strategy] job failed: %s", e)
        job["error"] = str(e)
        job["status"] = "failed"
        job["finished_at"] = datetime.now(timezone.utc).isoformat()


@app.post("/api/web/session/{session_token}/campaigns/{campaign_id}/generate-strategy", status_code=202)
async def generate_campaign_strategy(session_token: str, campaign_id: str, payload: RegenerateStrategyRequest | None, request: Request):
    session_token = _session_token_from_request(request)
    """Generate (or regenerate) and persist the strategy artifact for a campaign.

    Returns 202 immediately and runs generation as a background job; poll
    ``GET /api/web/session/{session_token}/campaigns/{campaign_id}/strategy-jobs/{job_id}``
    for status. A running job for the same campaign is reused (idempotent).

    Reuse rules (zero unused AI work):
    - A current strategy exists, the campaign objective is unchanged, and the
      user did not explicitly force a regenerate (``force=true``) → the
      existing strategy is returned as-is, no job is started.
    - Otherwise a generation job is enqueued (first generation, objective
      change, or explicit regenerate request).

    Lifecycle status is untouched — workflow progression is derived
    (current_step) from persisted state.
    """
    owner_id = await _workspace_owner(request, session_token)
    campaigns = _workspace_campaigns(owner_id, session_token)
    target = next((c for c in campaigns if c.get("id") == campaign_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Campaign not found")
    objective = str(target.get("objective") or "").strip()
    if not objective:
        raise HTTPException(status_code=400, detail="Campaign objective is required")
    if not (target.get("leads") or []):
        raise HTTPException(status_code=400, detail="Research prospects before generating a strategy")

    force = bool(payload and payload.force)
    current_strategy = target.get("strategy") if isinstance(target.get("strategy"), dict) else None
    if current_strategy and not force:
        stored_objective = str(
            current_strategy.get("objective")
            or current_strategy.get("campaign_objective")
            or ""
        ).strip()
        if stored_objective == objective:
            return {
                "ok": True,
                "job_id": None,
                "status": "completed",
                "reused": True,
                "strategy": current_strategy,
            }

    job_id, status = await _enqueue_strategy_job(session_token, owner_id, campaign_id, objective, target)
    return {"ok": True, "job_id": job_id, "status": status}


async def _enqueue_strategy_job(
    session_token: str,
    owner_id: str,
    campaign_id: str,
    objective: str,
    target: dict[str, Any],
) -> tuple[str, str]:
    """Enqueue a strategy generation job, reusing any in-flight job.

    Returns ``(job_id, status)``. Never starts a second job for the same
    campaign while one is queued/running (single in-memory generation at a
    time per campaign — the attached caller polls the same job).
    """
    for existing in STRATEGY_JOBS.values():
        if (
            existing.get("campaign_id") == campaign_id
            and existing.get("status") in ("queued", "running")
        ):
            return existing["id"], existing["status"]

    job_id = str(uuid.uuid4())
    job: dict[str, Any] = {
        "id": job_id,
        "campaign_id": campaign_id,
        "owner_id": owner_id,
        "status": "queued",
        "strategy": None,
        "error": None,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
    }
    STRATEGY_JOBS[job_id] = job
    task = asyncio.create_task(
        _run_strategy_job(session_token, job, target, objective)
    )
    _strategy_job_tasks[job_id] = task
    task.add_done_callback(lambda _done: _strategy_job_tasks.pop(job_id, None))
    return job_id, "queued"


async def _maybe_auto_strategy(
    session_token: str,
    owner_id: str,
    campaign_id: str,
    objective: str,
    target: dict[str, Any],
) -> str | None:
    """Carry discovery research into the campaign as its strategy — once.

    Auto-generates the strategy when a campaign was built from a discovery
    (``discovery_id`` set) and has prospects but no strategy yet. No-op when
    a strategy already exists or a job is in flight, so AI work is never
    duplicated and regeneration stays user-driven.

    Returns the enqueued job id, or None when nothing was started.
    """
    if not objective or not campaign_id:
        return None
    if not str(target.get("discovery_id") or "").strip():
        return None
    if isinstance(target.get("strategy"), dict) and target.get("strategy"):
        return None
    if not (target.get("leads") or []):
        return None
    job_id, _status = await _enqueue_strategy_job(session_token, owner_id, campaign_id, objective, target)
    log.info("[campaign_strategy] auto-generated from discovery for campaign %s (job %s)", campaign_id, job_id)
    return job_id


@app.get("/api/web/session/{session_token}/campaigns/{campaign_id}/strategy-jobs/{job_id}")
async def strategy_job_status(session_token: str, campaign_id: str, job_id: str, request: Request):
    session_token = _session_token_from_request(request)
    """Poll endpoint for a background strategy generation job."""
    await _workspace_owner(request, session_token)
    job = STRATEGY_JOBS.get(job_id)
    if not job or job.get("campaign_id") != campaign_id:
        raise HTTPException(status_code=404, detail="Strategy job not found")
    return {
        "job_id": job_id,
        "status": job.get("status"),
        "strategy": job.get("strategy"),
        "error": job.get("error"),
    }


@app.post("/api/web/session/{session_token}/campaigns/{campaign_id}/leads")
async def add_campaign_lead(session_token: str, campaign_id: str, payload: AddCampaignLeadRequest, request: Request):
    session_token = _session_token_from_request(request)
    owner_id = await _workspace_owner(request, session_token)
    campaigns = _workspace_campaigns(owner_id, session_token)
    target = next((c for c in campaigns if c.get("id") == campaign_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Campaign not found")
    lead = dict(payload.lead)
    candidate_email = str(lead.get("email") or "").strip().lower()
    lead_id = str(lead.get("id") or lead.get("linkedin_url") or candidate_email or uuid.uuid4())
    lead["id"] = lead_id
    leads = target.setdefault("leads", [])
    for existing in leads:
        if not isinstance(existing, dict):
            continue
        if existing.get("id") and str(existing["id"]) == lead_id:
            return {"ok": True, "campaign": target, "added": False}
        if candidate_email and str(existing.get("email") or "").strip().lower() == candidate_email:
            return {"ok": True, "campaign": target, "added": False}
    leads.append(lead)
    target["lead_count"] = len(leads)
    target["updated_at"] = datetime.now(timezone.utc).isoformat()
    from services.workspace_state import persist_campaign_lead_awaited, persist_campaign_update_awaited
    if not await persist_campaign_lead_awaited(owner_id, campaign_id, lead):
        raise HTTPException(status_code=503, detail="Lead could not be persisted to the campaign")
    if payload.discovery_id and str(target.get("discovery_id") or "") != payload.discovery_id:
        target["discovery_id"] = payload.discovery_id
        await persist_campaign_update_awaited(owner_id, campaign_id, {"discovery_id": payload.discovery_id})
    if payload.discovery_id:
        await _maybe_auto_strategy(
            session_token,
            owner_id,
            campaign_id,
            str(target.get("objective") or "").strip(),
            target,
        )
    publish(session_token, WMEventType.LEAD_DISCOVERED, {
        "id": lead_id,
        "name": lead.get("name", lead.get("full_name", "")),
        "company": lead.get("company", ""),
        "title": lead.get("title", lead.get("job_title", "")),
        "campaign_id": campaign_id,
    }, actor="user")
    publish(session_token, WMEventType.CAMPAIGN_UPDATED, {
        "campaign_id": campaign_id,
        "lead_count": target["lead_count"],
    }, actor="user")
    publish(session_token, WMEventType.LEAD_SELECTED, {
        "lead_id": lead_id,
        "campaign_id": campaign_id,
        "lead_name": lead.get("name", lead.get("full_name", "")),
    }, actor="user")
    return {"ok": True, "campaign": target, "added": True}


@app.post("/api/web/session/{session_token}/leads/decision")
async def decide_workspace_lead(session_token: str, payload: LeadDecisionRequest, request: Request):
    session_token = _session_token_from_request(request)
    """Persist Discovery approval/rejection in the authenticated workspace."""
    owner_id = await _workspace_owner(request, session_token)
    lead = dict(payload.lead)
    lead_id = str(lead.get("id") or lead.get("linkedin_url") or lead.get("email") or "")
    if not lead_id:
        raise HTTPException(status_code=400, detail="Lead identity is required")
    lead["id"] = lead_id
    from services.workspace_state import persist_lead_decision
    if not persist_lead_decision(owner_id, lead, payload.approved):
        raise HTTPException(status_code=503, detail="Lead decision could not be persisted")
    publish(session_token, WMEventType.LEAD_SELECTED if payload.approved else WMEventType.LEAD_DISCOVERED, {
        "lead_id": lead_id,
        "name": lead.get("name", lead.get("company", "")),
        "approved": payload.approved,
    }, actor="user")
    return {"ok": True, "lead": lead, "approved": payload.approved}


async def _dispatch_campaign_sends(session_token: str, campaign: dict, owner_id: str) -> dict:
    campaign_id = campaign.get("id", "")
    from services.outbound.draft_store import draft_store as outbound_draft_store

    # Durable workspace drafts are the source of truth: UI approvals persist
    # to workspace state, never the in-memory outbound store. Dispatch starts
    # from the durable approved set and syncs each approved draft to the
    # outbound store before sending.
    durable = _workspace_drafts(owner_id, session_token)
    approved_durable = [
        d for d in durable
        if d.get("campaign_id") == campaign_id and d.get("status") == "approved"
    ]
    if approved_durable:
        for d in approved_durable:
            _sync_draft_to_outbound(d, session_token, owner_id=owner_id)

    approved_ids = {d["id"] for d in approved_durable}
    all_outbound = outbound_draft_store.list_by_workflow(campaign_id)
    approved = [
        d for d in all_outbound.drafts
        if d.id in approved_ids and d.status.value in ("approved", "auto_approved")
    ]

    # Back-compat: drafts approved through the legacy in-memory session store.
    if not approved:
        legacy_drafts = _get_outbound_drafts_for_session(session_token)
        legacy_approved = [d for d in legacy_drafts
                           if d.get("campaign_id") == campaign_id and d.get("status") == "approved"]
        if legacy_approved:
            for ld in legacy_approved:
                _sync_draft_to_outbound(ld, session_token, owner_id=owner_id)
            approved = [outbound_draft_store.get(ld["id"]) for ld in legacy_approved]
            approved = [d for d in approved if d and d.status.value in ("approved", "auto_approved")]
    if not approved:
        log.info("[campaign_launch] No approved drafts found for campaign %s", campaign_id)
        return {"ok": False,
                "error": "No approved drafts to send — approve drafts before launching",
                "total": 0, "sent": 0, "failed": 0, "results": []}

    real_provider_id = _find_outbound_gmail_provider_id()
    if not real_provider_id:
        log.warning("[campaign_launch] No Gmail outbound provider registered")
        total = len(approved)
        campaign["total_sends"] = total
        campaign["sent_count"] = 0
        campaign["failed_count"] = total
        await _update_campaign_launch_progress(owner_id, session_token, campaign_id, 0, total, total)
        return {"ok": False, "error": "No Gmail outbound provider registered",
                "total": total, "sent": 0, "failed": total, "results": []}

    log.info("[campaign_launch] Dispatching %d approved drafts via provider %s", len(approved), real_provider_id)
    results = []
    sent_count = 0
    failed_count = 0
    for draft in approved:
        try:
            recipient_email = (draft.recipient.email if draft.recipient else "") or ""
            if not str(recipient_email).strip():
                failed_count += 1
                results.append({"draft_id": draft.id, "ok": False, "error": "This lead has no email address"})
                publish(session_token, WMEventType.DRAFT_FAILED, {
                    "draft_id": draft.id,
                    "campaign_id": campaign_id,
                    "error": "This lead has no email address",
                }, actor="system")
                await _update_campaign_launch_progress(
                    owner_id, session_token, campaign_id, sent_count, failed_count, len(approved))
                continue
            r = outbound_executor.execute("send_reply", {
                "provider_id": real_provider_id,
                "draft_id": draft.id,
                "conversation_id": draft.conversation_id,
                "thread_id": draft.thread_id,
                "workflow_id": draft.workflow_id,
                "subject": draft.subject,
                "body": draft.body,
                "recipient": {"email": draft.recipient.email, "name": draft.recipient.name},
                "sender": {"email": draft.sender.email, "name": draft.sender.name},
            })
            if r.get("ok"):
                sent_count += 1
                outbound_draft_store.mark_sent(draft.id)
                try:
                    from services.workspace_state import persist_draft_update_awaited
                    await persist_draft_update_awaited(owner_id, draft.id, {"status": "sent"})
                except Exception as e:
                    log.error(
                        "persistence_write_failed category=draft_status status=sent draft_id=%s campaign_id=%s error_type=%s",
                        draft.id[:12], campaign_id[:12], type(e).__name__,
                    )
                send_data = r.get("send_result", {})
                publish(session_token, WMEventType.DRAFT_SENT, {
                    "draft_id": draft.id,
                    "thread_id": send_data.get("thread_id", ""),
                    "external_message_id": send_data.get("external_message_id", ""),
                    "provider_id": real_provider_id,
                    "campaign_id": campaign_id,
                    "recipient_email": draft.recipient.email,
                }, actor="system")
                try:
                    from services.conversations.integration import create_conversation_from_send
                    conversation = create_conversation_from_send(
                        provider_id=real_provider_id,
                        provider_type="gmail",
                        external_thread_id=send_data.get("thread_id", ""),
                        external_message_id=send_data.get("external_message_id", ""),
                        subject=draft.subject,
                        from_email=draft.sender.email,
                        from_name=draft.sender.name,
                        to_email=draft.recipient.email,
                        to_name=draft.recipient.name,
                        body=draft.body,
                        campaign_id=campaign_id,
                        workflow_id=draft.workflow_id or campaign_id,
                        owner_id=owner_id,
                    )
                    simulate_reply({
                        "conversation_id": conversation.conversation_id,
                        "external_thread_id": send_data.get("thread_id", ""),
                        "subject": draft.subject,
                        "from_email": draft.sender.email,
                        "from_name": draft.sender.name,
                        "to_email": draft.recipient.email,
                        "to_name": draft.recipient.name,
                        "body": draft.body,
                        "campaign_id": campaign_id,
                        "workflow_id": draft.workflow_id or campaign_id,
                        "lead": draft.metadata.get("lead", {}) if draft.metadata else {},
                        "objective": campaign.get("objective", "") if campaign else "",
                    })
                except Exception as conv_err:
                    log.error(
                        "persistence_write_failed category=conversation operation=create_from_send "
                        "draft_id=%s campaign_id=%s provider_id=%s error_type=%s",
                        draft.id[:12], campaign_id[:12], real_provider_id[:12], type(conv_err).__name__,
                    )
            else:
                failed_count += 1
                publish(session_token, WMEventType.DRAFT_FAILED, {
                    "draft_id": draft.id,
                    "campaign_id": campaign_id,
                    "error": r.get("error", "Send failed"),
                }, actor="system")
            results.append({"draft_id": draft.id, "ok": r.get("ok", False), "error": r.get("error")})
        except Exception as e:
            failed_count += 1
            results.append({"draft_id": draft.id, "ok": False, "error": str(e)})
            publish(session_token, WMEventType.DRAFT_FAILED, {
                "draft_id": draft.id,
                "campaign_id": campaign_id,
                "error": str(e),
            }, actor="system")
        await _update_campaign_launch_progress(
            owner_id, session_token, campaign_id, sent_count, failed_count, len(approved))
    total = len(approved)
    campaign["total_sends"] = total
    campaign["sent_count"] = sent_count
    campaign["failed_count"] = failed_count
    log.info("[campaign_launch] Complete: %d/%d sent, %d failed", sent_count, total, failed_count)
    return {"ok": True, "total": total, "sent": sent_count, "failed": failed_count, "results": results}


async def _update_campaign_launch_progress(owner_id: str, session_token: str, campaign_id: str,
                                           sent_count: int, failed_count: int, total_count: int) -> None:
    """Persist launch progress onto the durable campaign row for polling.

    The in-memory campaign store is never populated by the web flow, so
    progress must live on the campaign's settings for /launch-progress to read.
    """
    from services.workspace_state import persist_campaign_update_awaited
    if total_count <= 0:
        status = "idle"
    elif failed_count == 0:
        status = "launched" if sent_count >= total_count else "sending"
    elif sent_count == 0:
        status = "failed"
    else:
        status = "partial"
    await persist_campaign_update_awaited(owner_id, campaign_id, {"launch": {
        "total": total_count,
        "sent": sent_count,
        "failed": failed_count,
        "status": status,
    }})


@app.delete("/api/web/session/{session_token}/campaigns/{campaign_id}")
async def delete_campaign(session_token: str, campaign_id: str, request: Request):
    session_token = _session_token_from_request(request)
    """Soft-delete a campaign: status='deleted' + deleted_at.

    The row is kept for audit/restore but hidden from all normal reads.
    """
    owner_id = await _workspace_owner(request, session_token)
    ws_id = await _resolved_workspace_id_or_default(request, owner_id)
    campaigns = _workspace_campaigns(owner_id, session_token, workspace_id=ws_id)
    target = next((c for c in campaigns if c.get("id") == campaign_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Campaign not found")
    target["status"] = "deleted"
    target["updated_at"] = datetime.now(timezone.utc).isoformat()
    from services.workspace_state import persist_campaign_update_awaited
    if not await persist_campaign_update_awaited(owner_id, campaign_id, {"status": "deleted"}, workspace_id=ws_id):
        raise HTTPException(status_code=503, detail="Campaign delete could not be persisted")
    publish(session_token, WMEventType.CAMPAIGN_DELETED, {
        "campaign_id": campaign_id,
        "name": target.get("name", ""),
    }, actor="user")
    return {"ok": True, "campaign": target}


@app.post("/api/web/session/{session_token}/campaigns/{campaign_id}/duplicate")
async def duplicate_campaign(session_token: str, campaign_id: str, request: Request):
    session_token = _session_token_from_request(request)
    """Deep-copy a campaign: campaign row + current strategy + lead links.

    Drafts, inbox threads, sent mail, analytics and runtime state are never
    duplicated. The copy starts fresh in planning so the pipeline can rerun.
    """
    owner_id = await _workspace_owner(request, session_token)
    ws_id = await _resolved_workspace_id_or_default(request, owner_id)
    from services.workspace_state import duplicate_campaign as _duplicate_campaign
    copy = await _duplicate_campaign(owner_id, campaign_id, workspace_id=ws_id)
    if copy is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    publish(session_token, WMEventType.CAMPAIGN_DUPLICATED, {
        "campaign_id": campaign_id,
        "copy_id": copy.get("id"),
        "name": copy.get("name"),
    }, actor="user")
    return {"ok": True, "campaign": copy}


@app.post("/api/web/session/{session_token}/campaigns/{campaign_id}/attach-discovery")
async def attach_discovery_to_campaign(session_token: str, campaign_id: str, payload: AttachDiscoveryRequest, request: Request):
    session_token = _session_token_from_request(request)
    """Attach every lead surfaced by an existing Discovery to the campaign."""
    owner_id = await _workspace_owner(request, session_token)
    campaigns = _workspace_campaigns(owner_id, session_token)
    target = next((c for c in campaigns if c.get("id") == campaign_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Campaign not found")
    from services.discovery import get_discovery
    discovery = await asyncio.to_thread(get_discovery, payload.discovery_id)
    if not discovery:
        raise HTTPException(status_code=404, detail="Discovery not found")
    from services.workspace_state import ensure_workspace
    workspace_id = await asyncio.to_thread(ensure_workspace, owner_id)
    if not workspace_id or discovery.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=404, detail="Discovery not found")

    from services.workspace_state import persist_campaign_lead_awaited, persist_campaign_update_awaited
    added = 0
    for link in discovery.get("discovery_leads") or []:
        ws_lead = link.get("workspace_lead") if isinstance(link, dict) else None
        if not isinstance(ws_lead, dict) or not ws_lead.get("email"):
            continue
        lead = {
            "id": ws_lead.get("id"),
            "email": ws_lead.get("email"),
            "first_name": ws_lead.get("first_name", ""),
            "last_name": ws_lead.get("last_name", ""),
            "title": ws_lead.get("title", ""),
            "company": (ws_lead.get("company") or {}).get("name", "")
            if isinstance(ws_lead.get("company"), dict) else "",
            "source": "discovery",
        }
        if await persist_campaign_lead_awaited(owner_id, campaign_id, lead):
            added += 1
    if added:
        target["updated_at"] = datetime.now(timezone.utc).isoformat()
        if str(target.get("discovery_id") or "") != payload.discovery_id:
            target["discovery_id"] = payload.discovery_id
            await persist_campaign_update_awaited(owner_id, campaign_id, {"discovery_id": payload.discovery_id})
        await _maybe_auto_strategy(
            session_token,
            owner_id,
            campaign_id,
            str(target.get("objective") or "").strip(),
            target,
        )
        publish(session_token, WMEventType.CAMPAIGN_UPDATED, {
            "campaign_id": campaign_id,
            "lead_count": (target.get("lead_count") or 0) + added,
            "source_discovery_id": payload.discovery_id,
        }, actor="user")
    return {"ok": True, "campaign": target, "added": added}


@app.get("/api/web/session/{session_token}/campaigns/{campaign_id}/drafts")
async def list_campaign_drafts(session_token: str, campaign_id: str, request: Request):
    session_token = _session_token_from_request(request)
    owner_id = await _workspace_owner(request, session_token)
    all_drafts = _workspace_drafts(owner_id, session_token)
    filtered = [d for d in all_drafts if d.get("campaign_id") == campaign_id]
    return {"ok": True, "drafts": filtered}


@app.post("/api/web/session/{session_token}/campaigns/{campaign_id}/generate-drafts", status_code=202)
async def generate_campaign_drafts(session_token: str, campaign_id: str, request: Request):
    session_token = _session_token_from_request(request)
    owner_id = await _workspace_owner(request, session_token)
    from services.workspace_state import load_campaign_state
    target = await asyncio.to_thread(load_campaign_state, owner_id, campaign_id)
    if not target:
        raise HTTPException(status_code=404, detail="Campaign not found")

    active_job = next(
        (j for j in batch_jobs.values()
         if j.get("campaign_id") == campaign_id and j.get("status") == "processing"),
        None,
    )
    if active_job:
        return {"ok": True, "batch_id": active_job.get("batch_id"), "total": active_job.get("total", 0)}
    generation = target.get("generation")
    generation = generation if isinstance(generation, dict) else {}
    if generation.get("status") == "processing":
        target = _reconcile_campaign_generation(owner_id, target)
        generation = target.get("generation") or {}
    if generation.get("status") == "completed" and generation.get("batch_id"):
        return {"ok": True, "batch_id": generation.get("batch_id"), "total": generation.get("total", 0)}

    leads = target.get("leads") or []
    strategy = target.get("strategy") or {}
    strategy_campaigns = strategy.get("campaigns") if isinstance(strategy, dict) else []

    if not leads:
        for sc in strategy_campaigns if isinstance(strategy_campaigns, list) else []:
            sc_leads = sc.get("leads") if isinstance(sc, dict) else []
            if isinstance(sc_leads, list):
                leads.extend(sc_leads)

    if not leads:
        raise HTTPException(status_code=400, detail="No leads found in campaign")

    batch_id = str(uuid.uuid4())
    total = len(leads)
    _create_batch_job(batch_id, campaign_id, total)
    target["updated_at"] = datetime.now(timezone.utc).isoformat()
    from services.workspace_state import persist_campaign_update_awaited
    if not await persist_campaign_update_awaited(owner_id, campaign_id, {
        "generation": {
            "batch_id": batch_id,
            "total": total,
            "completed": 0,
            "status": "processing",
            "started_at": target["updated_at"],
        },
    }):
        batch_jobs.pop(batch_id, None)
        raise HTTPException(status_code=503, detail="Draft generation could not be started")
    publish(session_token, WMEventType.CAMPAIGN_UPDATED, {
        "campaign_id": campaign_id,
        "generation": {"batch_id": batch_id, "total": total, "status": "processing"},
        "lead_count": total,
    }, actor="user")
    _launch_batch_task(session_token, batch_id, leads, owner_id)
    return {"ok": True, "batch_id": batch_id, "total": total}


@app.get("/api/web/session/{session_token}/campaigns/{campaign_id}/generation-status")
async def campaign_generation_status(session_token: str, campaign_id: str, request: Request):
    session_token = _session_token_from_request(request)
    active_jobs = [
        job for job in batch_jobs.values()
        if job.get("campaign_id") == campaign_id and job.get("status") == "processing"
    ]
    if active_jobs:
        latest = max(active_jobs, key=lambda j: j.get("current_index", -1))
        return {
            "ok": True,
            "active": True,
            "status": "processing",
            "total": latest.get("total", 0),
            "completed": latest.get("completed", 0),
            "batch_id": latest.get("batch_id"),
        }

    owner_id = await _workspace_owner(request, session_token)
    campaigns = _workspace_campaigns(owner_id, session_token)
    target = next((c for c in campaigns if c.get("id") == campaign_id), None)
    if not target:
        return {"ok": True, "active": False, "status": "unknown", "jobs": []}

    generation = target.get("generation")
    generation = generation if isinstance(generation, dict) else {}
    if generation.get("status") == "processing":
        target = _reconcile_campaign_generation(owner_id, target)
        generation = target.get("generation") or {}

    return {
        "ok": True,
        "active": False,
        "status": generation.get("status", "unknown"),
        "total": generation.get("total", 0),
        "completed": generation.get("completed", 0),
        "batch_id": generation.get("batch_id"),
    }


async def _launch_initial_research(
    user_id: str,
    wizard: dict[str, object],
    session_token: str,
) -> None:
    """Start first research immediately after onboarding finalization.

    The durable onboarding user owns the job. The optional web session is used
    only as the event stream consumed by Mission Control.
    """
    if wizard.get("initial_research_launched"):
        return

    offering = str(wizard.get("companyDescription") or wizard.get("description") or "").strip()
    icp = str(wizard.get("idealCustomer") or wizard.get("target_market") or "").strip()
    if not offering and not icp:
        raise ValueError("Onboarding did not contain research inputs")
    query = f"{offering} for {icp}".strip() if offering and icp else (offering or icp)
    if session_token:
        record_memory(session_token, "company_description", offering)
        record_memory(session_token, "ideal_customer", icp)

    def publish_job_update(update: dict[str, object]) -> None:
        if not session_token:
            return
        status = update.get("status")
        event_type = (
            WMEventType.RESEARCH_COMPLETED if status == "completed"
            else WMEventType.WORKFLOW_FAILED if status == "failed"
            else WMEventType.WORKFLOW_PROGRESS
        )
        publish(session_token, event_type, {
            "workflow_type": "research",
            "query": query,
            **update,
        }, actor="loqi")

    # Persist the launch marker before scheduling to make completion retries
    # idempotent. If scheduling fails, reset it so a retry can start work.
    await _onboarding_svc.save_wizard_data(user_id, {"initial_research_launched": True})
    result = await job_manager.create_search_job(
        user_id=user_id,
        query=query,
        on_update=publish_job_update,
    )
    if not result:
        await _onboarding_svc.save_wizard_data(user_id, {"initial_research_launched": False})
        if session_token:
            publish(session_token, WMEventType.WORKFLOW_FAILED, {
                "workflow_type": "research", "query": query,
                "error": "Unable to create the initial research job",
            }, actor="loqi")
        return

    job_id = str(result.get("job_id", ""))
    await _onboarding_svc.save_wizard_data(user_id, {
        "initial_research_job_id": job_id,
        "initial_research_session_token": session_token,
    })
    if session_token:
        record_search_started(session_token, query)
        publish(session_token, WMEventType.WORKFLOW_STARTED, {
            "workflow_type": "research", "job_id": job_id,
            "query": query, "status": "queued",
        }, actor="loqi")


set_onboarding_completion_handler(_launch_initial_research)


def _mc_phase(name: str, t: list[float]) -> None:
    now = time.monotonic()
    print(f"[MC-DIAG] {name}: {(now - t[0]) * 1000:.0f}ms", flush=True)
    t[0] = now


@app.get("/api/web/session/{session_token}/mission-control")
async def mission_control_summary(session_token: str, request: Request, onboarding_user_id: str = ""):
    session_token = _session_token_from_request(request)
    _mc_t = [time.monotonic()]
    owner_id, summary = await _workspace_owner_and_summary(request, session_token)
    _mc_phase("auth/owner", _mc_t)
    from services.mission_control.payload import compute_shared_payload
    payload = await compute_shared_payload(
        owner_id, session_token, summary.get("user_id") if summary else None,
    )
    campaigns = payload["campaigns"]
    drafts = payload["drafts"]
    snapshot = payload["snapshot"]
    analysis = payload["analysis"]
    recommendations = payload["recommendations"]
    brief = payload["brief"]
    _mc_phase("shared payload", _mc_t)
    now = datetime.now(timezone.utc)

    total_leads = sum(c.get("lead_count", 0) or 0 for c in campaigns)

    db_user_id = summary.get("user_id") if summary else None
    _mc_phase("session summary", _mc_t)

    # ── Phase 4: compute delta from World Model ──
    wm_store = get_wm_store()
    last_seq = wm_store.get_last_sequence(session_token)
    delta = payload["delta"]
    _mc_phase("wm delta", _mc_t)
    log.info(
        f"[phase4] delta: first_visit={delta.first_visit}, "
        f"events={delta.event_count}, range={delta.event_range}, "
        f"new_campaigns={len(delta.new_campaigns)}, "
        f"changed_campaigns={len(delta.changed_campaigns)}, "
        f"new_drafts={len(delta.new_drafts)}, "
        f"new_leads={len(delta.new_leads)}"
    )

    snapshot = payload["snapshot"]

    # Embed delta into snapshot for Executive Brief (no interface change)
    _embed_delta_into_snapshot(snapshot, delta)

    _mc_phase("snapshot+analysis", _mc_t)
    _mc_phase("recommendations", _mc_t)
    _mc_phase("brief", _mc_t)

    # Record acknowledgement after generating the brief
    ack_ts, ack_seq = wm_store.record_acknowledgement(session_token)
    log.info(f"[phase4] acknowledgement recorded at seq={ack_seq}")
    _mc_phase("ack", _mc_t)

    # Phase 3: use snapshot-derived values (which come from World Model when available)
    campaign_list = snapshot.get("campaigns", [])
    draft_counts = snapshot.get("drafts", {"total": 0, "pending": 0, "approved": 0})
    pending_drafts = draft_counts.get("pending", 0)
    approved_drafts = draft_counts.get("approved", 0)
    total_drafts = draft_counts.get("total", 0)
    snapshot_total_leads = snapshot.get("total_leads", total_leads)
    reply_rate_heuristic = round((approved_drafts / total_drafts * 100) if total_drafts else 0)

    try:
        # SaaS-2.4: never trust the client-supplied onboarding_user_id query
        # param as a target identity. Jobs/wizard data are always read for the
        # authenticated caller (db_user_id) only.
        if db_user_id:
            current_jobs = job_manager.list_active_jobs(db_user_id)
        else:
            current_jobs = []
    except Exception:
        current_jobs = []

    initial_research = None
    initial_research_result_count = None
    if db_user_id:
        try:
            wizard = await _onboarding_svc.get_wizard_data(db_user_id)
            job_id = str(wizard.get("initial_research_job_id") or "")
            if not job_id:
                recent_searches = [
                    job for job in job_manager.list_recent_jobs(db_user_id)
                    if job.get("type") == "search"
                ]
                if recent_searches:
                    job_id = str(recent_searches[0].get("id") or "")
            if job_id:
                initial_research = job_manager.get_job(job_id)
                if initial_research and initial_research.get("status") == "completed":
                    result = job_manager.get_job_results(job_id)
                    if result and result.get("ok"):
                        initial_research_result_count = len(result.get("leads") or [])
        except Exception:
            initial_research = None

    attention_items = analysis.get("attention_items", [])[:4]
    needs_attention = [
        {
            "type": a.get("action", "").lower().replace(" ", "_"),
            "campaign_id": a.get("campaign_id"),
            "campaign_name": a.get("campaign_name"),
            "label": a.get("title", ""),
            "action": a.get("action", "review"),
        }
        for a in attention_items
    ]

    from services.workspace_timeline import get_grouped_events
    grouped_activity = get_grouped_events(session_token, limit=10)
    _mc_phase("timeline", _mc_t)
    print(f"[MC-DIAG] mission_control_summary TOTAL: {(time.monotonic() - _mc_t[0]) * 1000:.0f}ms", flush=True)

    return {
        "ok": True,
        "campaigns": campaign_list[:4],
        "draft_counts": draft_counts,
        "needs_attention": needs_attention,
        "live_activity": grouped_activity,
        "campaign_count": len(campaign_list),
        "active_jobs": current_jobs,
        "initial_research": initial_research,
        "initial_research_result_count": initial_research_result_count,
        "recommendations": recommendations[:3],
        "kpis": {
            "estimated_reply_rate": reply_rate_heuristic,
            "pending_reviews": pending_drafts,
            "campaigns_ready": analysis.get("workspace_health", {}).get("campaigns_ready", 0),
        },
        "total_leads": snapshot_total_leads,
        "brief": brief,
        "workspace_memory": snapshot.get("memory", {}),
        "delta": snapshot.get("_delta", {}),
        "workspace_analysis": {
            "current_focus": analysis.get("current_focus"),
            "recommended_next_action": analysis.get("recommended_next_action"),
            "campaign_priorities": analysis.get("campaign_priorities", [])[:8],
            "workspace_health": analysis.get("workspace_health"),
            "cross_campaign_insights": analysis.get("cross_campaign_insights", []),
            "workflow_continuation": analysis.get("workflow_continuation"),
        },
    }


@app.get("/api/web/session/{session_token}/briefing")
async def briefing_endpoint(session_token: str, request: Request, onboarding_user_id: str = ""):
    session_token = _session_token_from_request(request)
    from services.mission_control.api import handle_get_briefing

    _mc_t = [time.monotonic()]
    owner_id, summary = await _workspace_owner_and_summary(request, session_token)
    _mc_phase("auth/owner", _mc_t)
    from services.mission_control.payload import compute_shared_payload
    payload = await compute_shared_payload(
        owner_id, session_token, summary.get("user_id") if summary else None,
    )
    _mc_phase("shared payload", _mc_t)

    db_user_id = summary.get("user_id") if summary else None
    _mc_phase("session summary", _mc_t)

    result = await handle_get_briefing(
        session_token=session_token,
        campaigns=payload["campaigns"],
        drafts=payload["drafts"],
        total_leads=payload["total_leads"],
        db_user_id=db_user_id,
        prebuilt=payload,
    )
    _mc_phase("handler total", _mc_t)
    print(f"[MC-DIAG] briefing_endpoint TOTAL: {(time.monotonic() - _mc_t[0]) * 1000:.0f}ms", flush=True)
    return result


@app.get("/api/web/session/{session_token}/export-csv")
async def export_csv(session_token: str, request: Request = None):
    session_token = _session_token_from_request(request)
    leads: list[dict] = []
    for d in draft_store.get(session_token, []):
        lead = d.get("lead")
        if lead:
            leads.append(lead)

    if not leads:
        from services.conversation_engine import ConversationEngine, _message
        local_engine = ConversationEngine()
        summary = await asyncio.to_thread(local_engine.get_web_session_summary, session_token)
        if summary:
            for msg in (summary.get("messages") or []):
                data = msg.get("data") or {}
                msg_leads = data.get("leads") or []
                leads.extend(msg_leads)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Name", "Title", "Company", "Email", "LinkedIn URL", "Industry", "Phone"])
    for lead in leads:
        writer.writerow([
            lead.get("name") or f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip(),
            lead.get("title", ""),
            lead.get("company", ""),
            lead.get("email", ""),
            lead.get("linkedin_url", ""),
            lead.get("company_industry", ""),
            "",
        ])

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=loqi-leads-{session_token[:8]}.csv"},
    )


@app.post("/api/web/session/{session_token}/select-lead")
async def select_lead_endpoint(session_token: str, payload: SelectLeadRequest, request: Request = None):
    session_token = _session_token_from_request(request)
    from services.supabase import get_pending_leads, get_user

    user = get_web_session_internal(session_token)
    if user is None:
        raise HTTPException(status_code=404, detail="Session not found")

    engine = ConversationEngine()
    workflow_session_id = ensure_workflow_session_internal(user["id"], session_token)
    result = engine.select_lead_and_draft(
        user_id=user["id"],
        lead_index=payload.index,
        workflow_session_id=workflow_session_id,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("messages", [{}])[0].get("text", "Selection failed"))

    for message in result.get("messages", []):
        if message.get("role") == "assistant":
            text = (message.get("text") or "").strip()
            if text:
                log_conversation_internal(user["id"], "assistant", text)

    publish(session_token, WMEventType.LEAD_SELECTED, {
        "lead_index": payload.index,
        "lead_name": result.get("messages", [{}])[0].get("lead_name", ""),
    }, actor="user")
    return {"ok": True, "messages": result.get("messages", [])}


class PreviewLeadRequest(BaseModel):
    index: int


@app.post("/api/web/session/{session_token}/preview-lead")
async def preview_lead_endpoint(session_token: str, payload: PreviewLeadRequest, request: Request = None):
    session_token = _session_token_from_request(request)
    user = get_web_session_internal(session_token)
    if user is None:
        raise HTTPException(status_code=404, detail="Session not found")

    engine = ConversationEngine()
    result = engine.preview_lead_intelligence(
        user_id=user["id"],
        lead_index=payload.index,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Preview failed"))

    return {"ok": True, "lead_intelligence": result.get("lead_intelligence")}


def get_web_session_internal(session_token: str) -> dict | None:
    from services.conversation_store import get_web_session

    return get_web_session(session_token)


def ensure_workflow_session_internal(user_id: str, session_token: str) -> str:
    from services.conversation_store import ensure_workflow_session

    return ensure_workflow_session(
        user_id=user_id,
        channel="web",
        session_key=session_token,
    )


def log_conversation_internal(user_id: str, role: str, text: str) -> None:
    from services.supabase import log_conversation

    log_conversation(user_id, role, text)


@app.get("/api/web/session/{session_token}/gmail")
async def get_web_gmail_status(session_token: str, request: Request = None):
    session_token = _session_token_from_request(request)
    # PR-2B: only user_id + gmail_connected are used — cached identity.
    summary = await _cached_session_identity(session_token)
    if summary is None:
        raise HTTPException(status_code=404, detail="Session not found")

    auth_url = engine.get_gmail_connect_url(
        channel="web",
        external_user_id=session_token,
    )
    return {
        "ok": True,
        "gmail_connected": summary.get("gmail_connected", False),
        "connect_url": auth_url,
    }


@app.get("/google/callback")
async def google_callback(code: str, state: str):
    """Legacy Telegram Gmail-connect callback.

    Harden (SaaS-1.5): the ``state`` must be a server-issued, single-use,
    expiring token bound to the initiating user/context (issued by
    ``conversation_engine.get_gmail_connect_url``). The callback never trusts a
    client-constructed ``user_id``; a state that was not server-issued, was
    already consumed, or has expired is rejected with 401.
    """
    from services.oauth_state import consume_state
    user_id, context = await consume_state(state)
    if not user_id or user_id == "gmail_user":
        raise HTTPException(status_code=401, detail="Invalid or expired OAuth state")
    context = context or {}
    channel = context.get("channel", "telegram")
    transport_id = str(context.get("transport_id", "") or "")

    try:
        tokens = exchange_code_for_tokens(code)
        saved_user = save_google_tokens(
            user_id,
            email=tokens.get("email", ""),
            telegram_chat_id=int(transport_id) if channel == "telegram" else None,
            access_token=tokens.get("access_token", ""),
            refresh_token=tokens.get("refresh_token", ""),
            token_expiry=tokens.get("token_expiry"),
        )
        if saved_user is None:
            raise HTTPException(status_code=500, detail="Failed to save Google tokens")

        session_id = f"{channel}:{user_id}"
        publish(session_id, WMEventType.PROVIDER_CONNECTED, {
            "provider_type": "gmail",
            "email": tokens.get("email", ""),
            "channel": channel,
        }, actor="user")

        if channel == "telegram":
            send_message(
                chat_id=int(transport_id),
                text="Gmail connected successfully. You can send emails now.",
            )
            return PlainTextResponse("Gmail connected. You can go back to Telegram.")

        return HTMLResponse(
            f"""
            <html>
              <body style="background:#0b1020;color:#f3f4f6;font-family:system-ui;padding:32px;">
                <h1 style="margin:0 0 12px;">Gmail connected</h1>
                <p style="opacity:.8;">You can close this window and return to Loqi.</p>
                <script>
                  window.opener && window.opener.postMessage({{ type: 'loqi:gmail-connected' }}, {json.dumps(_frontend_postmessage_origin() or '*')});
                </script>
              </body>
            </html>
            """
        )
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


# ── Job Engine API ──

class StartSearchRequest(BaseModel):
    query: str


async def _resolve_web_user_id(request: Request) -> tuple[str, str]:
    """Resolve (user_id, session_token) for web job/discovery endpoints.

    PR10.8.3.3: the user is derived ONLY from ``Authorization: Bearer``
    (identity or web-session token). The legacy ``x-session-token`` header has
    been removed — it is no longer a supported authentication channel. A
    client-supplied user_id query parameter is never trusted.
    """
    return await _resolve_session_context(request)


async def _create_search_run(user_id: str, query: str, session_token: str = "") -> dict:
    """Create a first-class discovery entity AND the search job that fills it.

    The discovery row is created FIRST; the transient job is then enqueued
    with ``discovery_id`` baked in (the relationship lives on the job side:
    ``jobs.discovery_id``, Discovery → many Jobs). There is no window where
    the two can drift apart. ``on_complete`` finalizes the discovery in the
    runner's event loop; failed/cancelled jobs move the discovery to the same
    state. If the discovery row cannot be created the job still runs, exactly
    like the legacy /api/jobs/search behavior.
    """
    from services.discovery import (
        create_discovery,
        finalize_discovery,
        get_discovery_by_job_id,
        get_discovery_id_for_job,
        mark_discovery_status,
        update_discovery_progress,
    )

    async def _emit_job_event(payload: dict) -> None:
        # PR-3A: real-time fan-out via Redis pub/sub (best-effort).
        try:
            from services.events_bus import event_bus
            await event_bus.publish_user_event(
                user_id,
                "job.progress",
                {"stage": payload.get("stage", "")},
                job_id=payload.get("job_id", ""),
                status=str(payload.get("status") or ""),
                progress=int(payload.get("progress") or 0),
            )
        except Exception:
            pass

    def on_update(payload: dict) -> None:
        status = payload.get("status")
        job_id = payload.get("job_id", "")
        import asyncio as _asyncio
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                loop.create_task(_emit_job_event(payload))
            else:
                _asyncio.run(_emit_job_event(payload))
        except RuntimeError:
            pass
        if status in ("failed", "cancelled"):
            discovery = get_discovery_by_job_id(job_id)
            if discovery:
                mark_discovery_status(
                    str(discovery["id"]),
                    status,
                    payload.get("error", ""),
                )
            return
        stage = payload.get("stage")
        if status == "running" and stage:
            discovery_id = get_discovery_id_for_job(job_id)
            if discovery_id:
                update_discovery_progress(
                    discovery_id,
                    str(stage),
                    int(payload.get("progress") or 0),
                )

    async def on_complete(job):
        await finalize_discovery(job)

    from services.workspace_state import ensure_workspace
    workspace_id = await asyncio.to_thread(ensure_workspace, user_id)
    log.info("[kickoff] _create_search_run: user=%s query=%r workspace_id=%s",
             user_id, query, workspace_id or "(none)")

    discovery_id = ""
    if workspace_id:
        discovery = await asyncio.to_thread(create_discovery, workspace_id, user_id, query)
        if discovery:
            discovery_id = str(discovery.get("id") or "")
    log.info("[kickoff] _create_search_run: discovery_id=%s (empty => row not created)",
             discovery_id or "(none)")

    result = await job_manager.create_search_job(
        user_id=user_id,
        query=query,
        discovery_id=discovery_id,
        on_update=on_update,
        on_complete=on_complete,
    )
    log.info("[kickoff] _create_search_run: create_search_job returned=%s", bool(result))
    if not result:
        if discovery_id:
            await asyncio.to_thread(
                mark_discovery_status, discovery_id, "failed", "Failed to create job"
            )
        raise HTTPException(status_code=500, detail="Failed to create job")

    if session_token:
        try:
            publish(session_token, WMEventType.LEAD_DISCOVERED, {
                "job_id": result.get("job_id", ""),
                "discovery_id": discovery_id,
                "query": query,
                "status": "searching",
            }, actor="user")
        except Exception as e:
            log.warning("[kickoff] publish(LEAD_DISCOVERED) failed (non-fatal): %s", e)

    result["discovery_id"] = discovery_id
    return result


@app.post("/api/jobs/search")
async def start_search(payload: StartSearchRequest, request: Request):
    user_id, session_token = await _resolve_web_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Valid session required")
    return await _create_search_run(user_id, payload.query, session_token)


# ── Discovery API (first-class entities) ──

class CreateDiscoveryRequest(BaseModel):
    query: str


@app.post("/api/discoveries")
async def create_discovery_endpoint(payload: CreateDiscoveryRequest, request: Request):
    """Create a new research run as a first-class discovery entity.

    A new query ALWAYS creates a new discovery — it never overwrites an
    existing one. Returns the discovery + job ids so clients can navigate
    straight to the new entity.
    """
    user_id, session_token = await _resolve_web_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Valid session required")
    log.info("[kickoff] POST /api/discoveries: user=%s query=%r", user_id, payload.query)
    result = await _create_search_run(user_id, payload.query, session_token)
    log.info("[kickoff] POST /api/discoveries: ok discovery_id=%s job_id=%s",
             result.get("discovery_id", ""), result.get("job_id", ""))
    return {"ok": True, **result}


@app.get("/api/discoveries")
async def list_discoveries_endpoint(request: Request):
    """Recent discoveries for the workspace, newest first."""
    from services.discovery import list_discoveries
    user_id, _ = await _resolve_web_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Valid session required")
    from services.workspace_state import ensure_workspace
    workspace_id = await asyncio.to_thread(ensure_workspace, user_id)
    if not workspace_id:
        return {"ok": True, "discoveries": []}
    discoveries = await asyncio.to_thread(list_discoveries, workspace_id)
    return {"ok": True, "discoveries": discoveries}


@app.get("/api/discoveries/{discovery_id}")
async def get_discovery_endpoint(discovery_id: str, request: Request):
    """One discovery with its surfaced companies and leads."""
    from services.discovery import get_discovery
    user_id, _ = await _resolve_web_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Valid session required")
    log.info("[kickoff] GET /api/discoveries/%s: user=%s", discovery_id, user_id)
    workspace_id = await _resolved_workspace_id_or_default(request, user_id)
    # SaaS-2.5: constrain the lookup to the caller's workspace so a foreign
    # discovery id cannot return another tenant's PII even before the check.
    discovery = await asyncio.to_thread(get_discovery, discovery_id, workspace_id)
    if not discovery:
        raise HTTPException(status_code=404, detail="Discovery not found")
    return {"ok": True, "discovery": discovery}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str, request: Request):
    user_id, _ = await _resolve_web_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Valid session required")
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    # PR10.8.3.2: jobs are tenant-scoped — a user may only read their own job.
    if str(job.get("user_id") or "") != str(user_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/api/jobs/{job_id}/results")
async def get_job_results(job_id: str, request: Request):
    user_id, _ = await _resolve_web_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Valid session required")
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if str(job.get("user_id") or "") != str(user_id):
        raise HTTPException(status_code=404, detail="Job not found")
    result = job_manager.get_job_results(job_id)
    if not result:
        raise HTTPException(status_code=404, detail="Job not found")
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Job not ready"))
    return result


@app.get("/api/jobs")
async def list_jobs(request: Request):
    # PR10.8.3.2: the user is derived ONLY from the credential — never from a
    # client-supplied user_id query parameter (parameter-substitution IDOR).
    user_id, _ = await _resolve_web_user_id(request)
    if not user_id:
        return {"jobs": []}
    jobs = job_manager.list_recent_jobs(user_id)
    return {"jobs": jobs}


@app.post("/api/web/session/{session_token}/plan")
async def plan_workflow_endpoint(session_token: str, payload: PlanningInput, request: Request = None):
    session_token = _session_token_from_request(request)
    campaigns = campaign_store.get(session_token, [])
    drafts = draft_store.get(session_token, [])
    total_leads = sum(c.get("lead_count", 0) or 0 for c in campaigns)
    # PR-2B: only the owning user id is consumed here — cached identity.
    _summary = await _cached_session_identity(session_token)
    _db_user_id = _summary.get("user_id") if _summary else None
    snapshot = await asyncio.to_thread(
        build_snapshot, session_token, campaigns, drafts, total_leads, user_id=_db_user_id,
    )
    result = plan_workflow(
        objective=payload.objective,
        snapshot=snapshot,
        current_page=payload.current_page,
    )
    return {
        "ok": True,
        "plan": result.primary_plan.model_dump(),
        "alternative_plan": result.alternative_plan.model_dump(),
        "recommendation": result.recommendation,
        "confidence": result.confidence,
    }


class ExecuteWorkflowRequest(BaseModel):
    plan_id: str
    goal: str
    reasoning: str = ""
    estimated_duration: str = ""
    risk_level: str = "low"
    requires_approval: bool = False
    steps: list[dict]


@app.post("/api/web/session/{session_token}/workflows/execute")
async def execute_workflow_endpoint(session_token: str, payload: ExecuteWorkflowRequest, request: Request = None):
    session_token = _session_token_from_request(request)
    plan = WorkflowPlan(
        id=payload.plan_id,
        goal=payload.goal,
        reasoning=payload.reasoning,
        estimated_duration=payload.estimated_duration,
        risk_level=payload.risk_level,
        requires_approval=payload.requires_approval,
        steps=payload.steps,
    )
    runtime = execute_workflow(plan, session_token)
    progress = calculate_progress(runtime)
    publish(session_token, WMEventType.WORKFLOW_STARTED, {
        "workflow_id": runtime.workflow_id,
        "goal": payload.goal,
        "step_count": len(payload.steps),
        "risk_level": payload.risk_level,
        "requires_approval": payload.requires_approval,
    }, actor="user")
    return {
        "ok": True,
        "workflow_id": runtime.workflow_id,
        "status": runtime.status.value,
        "progress": progress,
        "runtime": runtime.summary(),
    }


@app.get("/api/web/session/{session_token}/workflows/{workflow_id}")
def _require_workflow_owned(workflow_id: str, request: Request, session_token: str = ""):
    """Return the workflow runtime only when it belongs to the caller's session.

    Fail-closed (PR10.8.3.2): workflows are session-scoped (RuntimeEntry holds
    the creating session_token). A user may only read/mutate their own workflow.
    """
    from services.workflow_runtime import get_runtime
    runtime = get_runtime(workflow_id)
    if runtime is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    caller_token = _session_token_from_request(request) if request is not None else session_token
    if not caller_token or runtime.session_token != caller_token:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return runtime


async def get_workflow_status(session_token: str, workflow_id: str, request: Request = None):
    runtime = _require_workflow_owned(workflow_id, request, session_token)
    progress = calculate_progress(runtime)
    return {
        "ok": True,
        "runtime": runtime.to_dict(),
        "progress": progress,
    }


@app.get("/api/web/session/{session_token}/workflows/{workflow_id}/events")
async def get_workflow_events_endpoint(session_token: str, workflow_id: str, request: Request = None):
    _require_workflow_owned(workflow_id, request, session_token)
    return {
        "ok": True,
        "events": get_workflow_events(workflow_id),
    }


@app.post("/api/web/session/{session_token}/workflows/{workflow_id}/approve")
async def approve_workflow_step(session_token: str, workflow_id: str, request: Request = None):
    session_token = _session_token_from_request(request)
    _require_workflow_owned(workflow_id, request, session_token)
    try:
        runtime = approve_workflow(workflow_id)
        progress = calculate_progress(runtime)
        publish(session_token, WMEventType.WORKFLOW_APPROVED, {
            "workflow_id": workflow_id,
            "status": runtime.status.value,
        }, actor="user")
        return {
            "ok": True,
            "workflow_id": runtime.workflow_id,
            "status": runtime.status.value,
            "progress": progress,
            "runtime": runtime.summary(),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/web/session/{session_token}/workflows")
async def list_workflows(session_token: str, request: Request = None):
    session_token = _session_token_from_request(request)
    workflows = get_all_runtimes(session_token)
    return {
        "ok": True,
        "workflows": [wf.summary() for wf in workflows],
        "active": [calculate_progress(wf) for wf in get_active_runtimes(session_token)],
    }


@app.get("/api/web/session/{session_token}/workflows/history")
async def workflow_history(session_token: str, status: str | None = None, limit: int = 50, request: Request = None):
    session_token = _session_token_from_request(request)
    return {
        "ok": True,
        "history": get_workflow_history(session_token, status_filter=status, limit=limit),
    }


@app.get("/api/web/session/{session_token}/workflows/{workflow_id}/events/stream")
async def workflow_events_after(session_token: str, workflow_id: str, after: int = 0, request: Request = None):
    _require_workflow_owned(workflow_id, request, session_token)
    return {
        "ok": True,
        "events": get_workflow_events(workflow_id, after_sequence=after),
        "latest_sequence": get_latest_sequence(workflow_id),
    }


@app.post("/api/web/session/{session_token}/workflows/{workflow_id}/pause")
async def pause_workflow_endpoint(session_token: str, workflow_id: str, request: Request = None):
    session_token = _session_token_from_request(request)
    _require_workflow_owned(workflow_id, request, session_token)
    try:
        runtime = pause_workflow(workflow_id)
        progress = calculate_progress(runtime)
        publish(session_token, WMEventType.WORKFLOW_PAUSED, {
            "workflow_id": workflow_id,
            "status": runtime.status.value,
        }, actor="user")
        return {
            "ok": True,
            "workflow_id": runtime.workflow_id,
            "status": runtime.status.value,
            "progress": progress,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/web/session/{session_token}/workflows/{workflow_id}/resume")
async def resume_workflow_endpoint(session_token: str, workflow_id: str, request: Request = None):
    session_token = _session_token_from_request(request)
    _require_workflow_owned(workflow_id, request, session_token)
    try:
        runtime = resume_workflow(workflow_id)
        progress = calculate_progress(runtime)
        publish(session_token, WMEventType.WORKFLOW_RESUMED, {
            "workflow_id": workflow_id,
            "status": runtime.status.value,
        }, actor="user")
        return {
            "ok": True,
            "workflow_id": runtime.workflow_id,
            "status": runtime.status.value,
            "progress": progress,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/web/session/{session_token}/workflows/{workflow_id}/cancel")
async def cancel_workflow_endpoint(session_token: str, workflow_id: str, request: Request = None):
    session_token = _session_token_from_request(request)
    _require_workflow_owned(workflow_id, request, session_token)
    try:
        runtime = cancel_workflow(workflow_id)
        publish(session_token, WMEventType.WORKFLOW_CANCELLED, {
            "workflow_id": workflow_id,
            "status": runtime.status.value,
        }, actor="user")
        return {
            "ok": True,
            "workflow_id": runtime.workflow_id,
            "status": runtime.status.value,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Conversation Routes ──

@app.get("/api/web/session/{session_token}/conversations")
async def list_conversations_route(session_token: str, request: Request = None):
    from services.conversations.conversation_store import conversation_store
    owner_id = await _resolve_session_context(request) if request is not None else ("", "")
    owner_id = owner_id[0]
    conversations = conversation_store.list_conversations(limit=1000)
    # Fail-closed: only conversations that provably belong to the owner are
    # returned; unattributable conversations are hidden.
    owned = [c for c in conversations if _conversation_owned_by(c, owner_id)]
    return {
        "ok": True,
        "conversations": [c.to_dict() for c in owned],
    }


@app.get("/api/web/session/{session_token}/conversations/{conversation_id}")
async def get_conversation_route(session_token: str, conversation_id: str, request: Request = None):
    owner_id = (await _resolve_session_context(request))[0] if request is not None else ""
    from services.conversations.conversation_store import conversation_store
    convo = conversation_store.get_conversation(conversation_id)
    if not convo or not _conversation_owned_by(convo, owner_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {
        "ok": True,
        "conversation": convo.to_dict(),
    }


@app.get("/api/web/session/{session_token}/conversations/{conversation_id}/timeline")
async def get_conversation_timeline_route(session_token: str, conversation_id: str, request: Request = None):
    owner_id = (await _resolve_session_context(request))[0] if request is not None else ""
    from services.conversations.conversation_store import conversation_store
    convo = conversation_store.get_conversation(conversation_id)
    if not convo or not _conversation_owned_by(convo, owner_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    events = conversation_store.get_timeline(conversation_id)
    return {
        "ok": True,
        "events": [e.to_dict() for e in events],
    }


@app.get("/api/web/session/{session_token}/conversations/{conversation_id}/messages")
async def get_conversation_messages_route(session_token: str, conversation_id: str, request: Request = None):
    owner_id = (await _resolve_session_context(request))[0] if request is not None else ""
    from services.conversations.conversation_store import conversation_store
    convo = conversation_store.get_conversation(conversation_id)
    if not convo or not _conversation_owned_by(convo, owner_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = conversation_store.get_messages_for_conversation(conversation_id)
    return {
        "ok": True,
        "messages": [m.to_dict() for m in messages],
    }


@app.get("/api/web/session/{session_token}/conversations/{conversation_id}/reasoning")
async def get_conversation_reasoning_route(session_token: str, conversation_id: str, request: Request = None):
    owner_id = (await _resolve_session_context(request))[0] if request is not None else ""
    from services.conversations.conversation_store import conversation_store
    from services.conversation_intelligence.intelligence_pipeline import IntelligencePipeline
    from services.reasoning.reasoning_pipeline import get_pipeline as get_reasoning_pipeline

    convo = conversation_store.get_conversation(conversation_id)
    if not convo or not _conversation_owned_by(convo, owner_id):
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = conversation_store.get_messages_for_conversation(conversation_id)
    if not messages:
        return {"ok": True, "reasoning": None}

    # Build intelligence from latest message
    latest = messages[-1]
    msg_body = latest.body or latest.body_preview or ""
    msg_subject = latest.subject or ""

    intel_pipeline = IntelligencePipeline()
    intelligence = intel_pipeline.analyze_message(
        message_body=msg_body,
        lead_id=conversation_id,
        subject=msg_subject,
    )

    # Run reasoning pipeline
    reasoning_pipeline = get_reasoning_pipeline()
    result = reasoning_pipeline.reason(intelligence)

    return {
        "ok": True,
        "reasoning": result.to_dict(),
    }


@app.post("/api/web/session/{session_token}/conversations/{conversation_id}/plan")
async def get_conversation_plan_route(session_token: str, conversation_id: str, request: Request = None):
    owner_id = (await _resolve_session_context(request))[0] if request is not None else ""
    from services.conversations.conversation_store import conversation_store
    from services.conversation_intelligence.intelligence_pipeline import IntelligencePipeline
    from services.reasoning.reasoning_pipeline import get_pipeline as get_reasoning_pipeline

    convo = conversation_store.get_conversation(conversation_id)
    if not convo or not _conversation_owned_by(convo, owner_id):
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = conversation_store.get_messages_for_conversation(conversation_id)
    if not messages:
        return {"ok": True, "plan": None, "validation": None}

    latest = messages[-1]
    msg_body = latest.body or latest.body_preview or ""
    msg_subject = latest.subject or ""

    intel_pipeline = IntelligencePipeline()
    intelligence = intel_pipeline.analyze_message(
        message_body=msg_body,
        lead_id=conversation_id,
        subject=msg_subject,
    )

    reasoning_pipeline = get_reasoning_pipeline()
    reasoning_result = reasoning_pipeline.reason(intelligence)

    planning_pipeline = get_planning_pipeline()
    try:
        plan, validation = planning_pipeline.plan(reasoning_result)
    except PlanningValidationError as e:
        return {
            "ok": False,
            "error": e.message,
            "error_type": "PlanningValidationError",
            "validation": {
                "valid": False,
                "issues": e.context.get("issues", []),
                "warnings": [],
            },
        }

    graph_edges = plan.get_all_dependency_pairs()
    graph_nodes = [
        {
            "id": t.id,
            "type": t.type.value,
            "status": t.status.value,
            "label": t.label,
            "dependencies": t.dependencies,
            "approval": t.approval.value,
        }
        for t in plan.tasks
    ]

    validation_dict = None
    if validation:
        validation_dict = {
            "valid": validation.valid,
            "issues": [
                {"severity": i.severity, "code": i.code, "message": i.message, "task_id": i.task_id, "suggested_fix": i.suggested_fix}
                for i in validation.issues
            ],
            "warnings": [
                {"severity": w.severity, "code": w.code, "message": w.message, "task_id": w.task_id, "suggested_fix": w.suggested_fix}
                for w in validation.warnings
            ],
        }

    explainability = _build_plan_explainability(plan)

    return {
        "ok": True,
        "plan": plan.to_dict(),
        "graph": {
            "nodes": graph_nodes,
            "edges": [{"source": s, "target": t} for s, t in graph_edges],
        },
        "explainability": explainability,
        "validation": validation_dict,
    }


def _build_plan_explainability(plan):
    from services.planner.planning_models import PlanGoal
    goal = plan.goal or PlanGoal()
    return {
        "goal": {
            "outcome": goal.outcome,
            "target_action": goal.target_action,
            "priority": goal.priority,
        },
        "strategy": plan.strategy,
        "task_chain": [
            {
                "id": t.id,
                "label": t.label,
                "type": t.type.value,
                "reason": t.reasoning_trace,
                "goal": t.reasoning_goal,
                "approval": t.approval.value,
            }
            for t in plan.tasks
        ],
        "total_tasks": len(plan.tasks),
        "strategy_version": plan.version,
    }


@app.post("/api/web/session/{session_token}/conversations/{conversation_id}/generate-reply")
async def generate_reply_route(
    session_token: str,
    conversation_id: str,
    body: dict = None,
    request: Request = None,
):
    session_token = _session_token_from_request(request)
    owner_id = (await _resolve_session_context(request))[0]
    from services.conversations.conversation_store import conversation_store
    from services.conversation_intelligence.intelligence_pipeline import IntelligencePipeline
    from services.reasoning.reasoning_pipeline import get_pipeline as get_reasoning_pipeline
    from services.reply_generation.generation_pipeline import GenerationPipeline
    from services.reply_generation.generation_models import GenerationStyle

    convo = conversation_store.get_conversation(conversation_id)
    if not convo or not _conversation_owned_by(convo, owner_id):
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = conversation_store.get_messages_for_conversation(conversation_id)
    if not messages:
        return {"ok": True, "generation": None}

    payload = body or {}
    style_names = payload.get("styles", ["professional"])
    styles = []
    for name in style_names:
        try:
            styles.append(GenerationStyle(name))
        except ValueError:
            pass
    if not styles:
        styles = [GenerationStyle.PROFESSIONAL]
    instruction = str(payload.get("instruction") or "").strip()
    follow_up = bool(payload.get("follow_up"))

    latest = messages[-1]
    msg_body = latest.body or latest.body_preview or ""
    msg_subject = latest.subject or ""

    # The session/request owner is the only source of Knowledge scope. Direct
    # callers without an authenticated session retain the existing generation
    # behavior and simply receive no Knowledge context.
    owner_id = ""
    if request is not None:
        try:
            owner_id = await _workspace_owner(request, session_token)
        except HTTPException:
            owner_id = ""

    knowledge_context = {}
    if owner_id:
        from services.knowledge.context_adapter import retrieve_knowledge_context
        knowledge_query = " ".join(
            part for part in (
                "follow-up" if follow_up else "reply",
                msg_subject,
                msg_body[:500],
            ) if part
        )
        retrieved = await retrieve_knowledge_context(
            owner_id,
            query=knowledge_query,
            categories=["company", "messaging", "sales_offer"],
            limit=8,
        )
        knowledge_context = retrieved.to_dict()

    intel_pipeline = IntelligencePipeline()
    intelligence = intel_pipeline.analyze_message(
        message_body=msg_body,
        lead_id=conversation_id,
        subject=msg_subject,
    )

    reasoning_pipeline = get_reasoning_pipeline()
    reasoning = reasoning_pipeline.reason(intelligence)

    latest_texts = []
    if follow_up:
        # Follow-up context: only the outbound messages (the original
        # outreach) — there is no inbound reply to respond to.
        outbound = [m for m in messages if m.direction == "outbound"]
        for m in outbound[-3:]:
            preview = m.body_preview or (m.body or "")[:200]
            if preview:
                latest_texts.append(f"[You]: {preview}")
    else:
        for m in messages[-3:]:
            preview = m.body_preview or (m.body or "")[:200]
            direction = "Prospect" if m.direction == "inbound" else "You"
            if preview:
                latest_texts.append(f"[{direction}]: {preview}")

    gen_pipeline = GenerationPipeline()
    # PR-P1.2: GenerationPipeline.generate performs synchronous OpenAI HTTP
    # calls with an internal time.sleep retry loop (worst case ~95s). Offload
    # the whole generation to a worker thread so the event loop stays free.
    result = await asyncio.to_thread(
        gen_pipeline.generate,
        intelligence=intelligence,
        reasoning=reasoning,
        styles=styles,
        variant_count=payload.get("variant_count", 1),
        latest_messages=latest_texts,
        instruction=instruction or None,
        follow_up=follow_up,
        knowledge_context=knowledge_context,
    )

    return {
        "ok": True,
        "generation": result.to_dict(),
        "reasoning": reasoning.to_dict(),
    }


class SendConversationReplyRequest(BaseModel):
    body: str
    thread_id: str = ""
    reply_to_message_id: str = ""
    from_email: str = ""
    to_email: str = ""
    test_recipient: str = ""
    test_recipient_name: str = ""


@app.post("/api/web/session/{session_token}/conversations/{conversation_id}/reply")
async def send_conversation_reply_route(
    session_token: str,
    conversation_id: str,
    body: SendConversationReplyRequest = None,
    request: Request = None,
):
    session_token = _session_token_from_request(request)
    """Send an outbound reply from a conversation via the connected Gmail provider.

    Resolves the provider from the conversation's thread/draft first, then the
    owner's connected provider (same rules as outbound sends). Replies are
    sent on the original Gmail thread (threadId in payload). A conversation can
    only be replied to once per inbound turn: if the conversation is already in
    an awaiting-response state (SENT / DELIVERED / OPENED / FOLLOW_UP_PENDING /
    FOLLOW_UP_READY / FOLLOW_UP_SENT), the request is rejected as a duplicate.
    On success the reply is recorded in the conversation (message + EMAIL_SENT
    timeline event + status transition to SENT).
    """
    from services.conversations.conversation_models import ConversationMessage, ConversationStatus
    from services.conversations.conversation_store import conversation_store
    from services.conversations.state_machine import transition as state_transition
    from services.conversations.timeline import TimelineEventType, build_timeline_event
    from services.outbound.outbound_executor import OutboundActionType

    payload = body or SendConversationReplyRequest(body="")
    reply_body = (payload.body or "").strip()
    if not reply_body:
        raise HTTPException(status_code=400, detail="Reply body is required")

    test_recipient = (payload.test_recipient or "").strip()
    if test_recipient and not _test_recipient_override_enabled():
        raise HTTPException(status_code=403, detail="Test recipient override is disabled")

    convo = conversation_store.get_conversation(conversation_id)
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # PR10.8.3.1: fail-closed ownership — the authenticated owner must be
    # resolvable and the conversation must belong to that owner.
    if request is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    owner_id = await _workspace_owner(request, session_token)
    if not _conversation_owned_by(convo, owner_id):
        # Safe not-found: foreign-but-existing conversation is indistinguishable
        # from nonexistent (no existence leak).
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Duplicate-send guard: after a reply the conversation must return to an
    # awaiting-response state before another reply is allowed.
    if convo.status in {
        ConversationStatus.SENT,
        ConversationStatus.DELIVERED,
        ConversationStatus.OPENED,
        ConversationStatus.FOLLOW_UP_PENDING,
        ConversationStatus.FOLLOW_UP_READY,
        ConversationStatus.FOLLOW_UP_SENT,
    }:
        raise HTTPException(
            status_code=409,
            detail="Conversation is already awaiting a response — reply already sent",
        )

    threads = conversation_store.get_threads_for_conversation(conversation_id)
    thread = threads[-1] if threads else None
    external_thread_id = payload.thread_id or getattr(thread, "external_thread_id", "") or ""

    provider_id = _resolve_provider_for_conversation(convo)
    if not provider_id:
        raise HTTPException(status_code=503, detail="No connected Gmail provider available to send the reply")

    # Recipient/sender resolution from conversation participants.
    contact = next((p for p in convo.participants if p.role == "contact"), None)
    sender = next((p for p in convo.participants if p.role == "sender"), None)
    contact_email = payload.to_email or (contact.email if contact else "") or ""
    contact_name = (contact.name if contact else "") or ""
    if not contact_email:
        inbound = [m for m in conversation_store.get_messages_for_conversation(conversation_id)
                   if m.direction == "inbound"]
        latest_inbound = inbound[-1] if inbound else None
        if latest_inbound:
            contact_email = latest_inbound.from_email
            contact_name = latest_inbound.from_name
    if not contact_email:
        raise HTTPException(status_code=400, detail="No recipient email available for this conversation")
    sender_email = payload.from_email or (sender.email if sender else "") or ""

    reply_to_msg = None
    if external_thread_id:
        for m in conversation_store.get_messages_for_conversation(conversation_id):
            if m.external_message_id and m.thread_id == (thread.thread_id if thread else ""):
                reply_to_msg = m
                break
    reply_to_message_id = payload.reply_to_message_id or (
        getattr(reply_to_msg, "external_message_id", "") if reply_to_msg else ""
    )

    # Test-only recipient override (LOQI_ENABLE_TEST_RECIPIENT_OVERRIDE=true):
    # changes ONLY the outbound envelope recipient. The conversation's contact
    # identity, thread, provider and persisted message stay the real lead.
    envelope_email = contact_email
    envelope_name = contact_name
    if test_recipient:
        envelope_email = test_recipient
        envelope_name = (payload.test_recipient_name or "Test Recipient").strip()
        log.info("[TEST RECIPIENT] original_recipient=%s effective_recipient=%s", contact_email, test_recipient)

    result = outbound_executor.execute(
        OutboundActionType.SEND_REPLY,
        {
            "provider_id": provider_id,
            "body": reply_body,
            "conversation_id": conversation_id,
            "subject": "Re: " + ((thread.subject if thread else convo.subject) or ""),
            "thread_id": external_thread_id,
            "reply_to_message_id": reply_to_message_id,
            "recipient": {"email": envelope_email, "name": envelope_name},
            "sender": {"email": sender_email, "name": ""},
        },
    )
    if not result or not result.get("ok"):
        raise HTTPException(status_code=502, detail=(result or {}).get("error") or "Failed to send reply")

    send_result = (result.get("send_result") or {})
    external_message_id = str(send_result.get("external_message_id") or send_result.get("id") or "")

    sent_message = ConversationMessage(
        conversation_id=conversation_id,
        thread_id=thread.thread_id if thread else "",
        provider_id=provider_id,
        external_message_id=external_message_id,
        direction="outbound",
        from_email=sender_email,
        from_name="You",
        to_email=contact_email,
        to_name=contact_name,
        subject="Re: " + ((thread.subject if thread else convo.subject) or ""),
        body=reply_body,
    )
    conversation_store.add_message(sent_message)
    conversation_store.add_timeline_event(build_timeline_event(
        conversation_id=conversation_id,
        event_type=TimelineEventType.EMAIL_SENT,
        title="Reply sent",
        description=f"To: {contact_name or contact_email} | Provider: {provider_id[:8]}…",
        metadata={
            "conversation_id": conversation_id,
            "direction": "outbound",
            "external_thread_id": external_thread_id,
            "reply_to_message_id": reply_to_message_id,
            "provider_id": provider_id,
        },
    ))
    try:
        convo.status = state_transition(convo.status, ConversationStatus.SENT)
        conversation_store.update_conversation(convo)
    except ValueError:
        raise HTTPException(status_code=409, detail="Conversation status no longer allows a reply send")

    return {
        "ok": True,
        "conversation_id": conversation_id,
        "status": convo.status.value,
        "message_id": sent_message.message_id,
        "external_message_id": external_message_id,
    }


@app.post("/api/web/session/{session_token}/conversations/{conversation_id}/follow-up")
async def send_conversation_followup_route(
    session_token: str,
    conversation_id: str,
    body: SendConversationReplyRequest = None,
    request: Request = None,
):
    session_token = _session_token_from_request(request)
    """Send a follow-up email on the conversation's existing thread.

    Distinct from /reply: a follow-up continues the original outbound
    outreach when there is NO inbound reply to respond to. The conversation
    must be in a follow-up-waiting state (FOLLOW_UP_PENDING / FOLLOW_UP_READY);
    any other state — including FOLLOW_UP_SENT — is rejected as a duplicate
    follow-up, and reply-mode conversations cannot send follow-ups.

    Sends through the same outbound executor path as replies (SEND_REPLY on
    the original thread), records the outbound message + FOLLOW_UP_SENT
    timeline event, and transitions the conversation to FOLLOW_UP_SENT
    (awaiting a response).
    """
    from services.conversations.conversation_models import ConversationMessage, ConversationStatus
    from services.conversations.conversation_store import conversation_store
    from services.conversations.state_machine import transition as state_transition
    from services.conversations.timeline import TimelineEventType, build_timeline_event
    from services.outbound.outbound_executor import OutboundActionType

    payload = body or SendConversationReplyRequest(body="")
    follow_up_body = (payload.body or "").strip()
    if not follow_up_body:
        raise HTTPException(status_code=400, detail="Follow-up body is required")

    test_recipient = (payload.test_recipient or "").strip()
    if test_recipient and not _test_recipient_override_enabled():
        raise HTTPException(status_code=403, detail="Test recipient override is disabled")

    convo = conversation_store.get_conversation(conversation_id)
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # PR10.8.3.1: fail-closed ownership — the authenticated owner must be
    # resolvable and the conversation must belong to that owner.
    if request is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    owner_id = await _workspace_owner(request, session_token)
    if not _conversation_owned_by(convo, owner_id):
        # Safe not-found: foreign-but-existing conversation is indistinguishable
        # from nonexistent (no existence leak).
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Duplicate follow-up guard: only a conversation currently waiting for a
    # follow-up may send one. FOLLOW_UP_SENT (already sent) is rejected.
    if convo.status not in {
        ConversationStatus.FOLLOW_UP_PENDING,
        ConversationStatus.FOLLOW_UP_READY,
    }:
        raise HTTPException(
            status_code=409,
            detail="Conversation is not waiting for a follow-up — follow-up already sent or not due",
        )

    threads = conversation_store.get_threads_for_conversation(conversation_id)
    thread = threads[-1] if threads else None
    external_thread_id = payload.thread_id or getattr(thread, "external_thread_id", "") or ""

    provider_id = _resolve_provider_for_conversation(convo)
    if not provider_id:
        raise HTTPException(status_code=503, detail="No connected Gmail provider available to send the follow-up")

    contact = next((p for p in convo.participants if p.role == "contact"), None)
    sender = next((p for p in convo.participants if p.role == "sender"), None)
    contact_email = payload.to_email or (contact.email if contact else "") or ""
    contact_name = (contact.name if contact else "") or ""
    if not contact_email:
        raise HTTPException(status_code=400, detail="No recipient email available for this conversation")
    sender_email = payload.from_email or (sender.email if sender else "") or ""

    envelope_email = contact_email
    envelope_name = contact_name
    if test_recipient:
        envelope_email = test_recipient
        envelope_name = (payload.test_recipient_name or "Test Recipient").strip()
        log.info("[TEST RECIPIENT] original_recipient=%s effective_recipient=%s", contact_email, test_recipient)

    result = outbound_executor.execute(
        OutboundActionType.SEND_REPLY,
        {
            "provider_id": provider_id,
            "body": follow_up_body,
            "conversation_id": conversation_id,
            "subject": "Re: " + ((thread.subject if thread else convo.subject) or ""),
            "thread_id": external_thread_id,
            "recipient": {"email": envelope_email, "name": envelope_name},
            "sender": {"email": sender_email, "name": ""},
        },
    )
    if not result or not result.get("ok"):
        raise HTTPException(status_code=502, detail=(result or {}).get("error") or "Failed to send follow-up")

    send_result = (result.get("send_result") or {})
    external_message_id = str(send_result.get("external_message_id") or send_result.get("id") or "")

    sent_message = ConversationMessage(
        conversation_id=conversation_id,
        thread_id=thread.thread_id if thread else "",
        provider_id=provider_id,
        external_message_id=external_message_id,
        direction="outbound",
        from_email=sender_email,
        from_name="You",
        to_email=contact_email,
        to_name=contact_name,
        subject="Re: " + ((thread.subject if thread else convo.subject) or ""),
        body=follow_up_body,
    )
    conversation_store.add_message(sent_message)
    conversation_store.add_timeline_event(build_timeline_event(
        conversation_id=conversation_id,
        event_type=TimelineEventType.FOLLOW_UP_SENT,
        title="Follow-up sent",
        description=f"To: {contact_name or contact_email} | Provider: {provider_id[:8]}…",
        metadata={
            "conversation_id": conversation_id,
            "direction": "outbound",
            "external_thread_id": external_thread_id,
            "provider_id": provider_id,
        },
    ))
    try:
        convo.status = state_transition(convo.status, ConversationStatus.FOLLOW_UP_SENT)
        conversation_store.update_conversation(convo)
    except ValueError:
        raise HTTPException(status_code=409, detail="Conversation status no longer allows a follow-up send")

    return {
        "ok": True,
        "conversation_id": conversation_id,
        "status": convo.status.value,
        "message_id": sent_message.message_id,
        "external_message_id": external_message_id,
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "10000"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
