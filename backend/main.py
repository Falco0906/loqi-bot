import asyncio
import csv
import hashlib
import io
import json
import logging
import os
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
import services.identity.dependencies as identity_dependencies
import services.workspace_context as workspace_access
from services.identity.api import router as auth_router
from services.onboarding.api import router as onboarding_router
from services.organizations.api import router as organizations_router, _build_org_deps, register_deps as register_org_deps
from services.billing.api import router as billing_router, _build_billing_deps, register_deps as register_billing_deps, create_billing_provider
from services.billing.config import BillingConfig
from services.billing.api import register_provider_and_config as _register_billing_provider_config
from services.capabilities.api import router as capabilities_router, register_deps as register_capability_deps, CapabilityDeps
from services.knowledge.api import router as knowledge_router
from services.mission_control.api import router as mission_control_router
from services.discovery.api import router as discovery_router
from services.campaigns.api import router as campaigns_router
from services.drafts.api import router as drafts_router
import services.drafts.service as draft_service
import services.campaigns.service as campaign_service
import services.outbound.service as outbound_service
import services.conversations.service as conversation_service
import services.copilot.runners as copilot_runners
from services.campaigns.service import load_campaigns
from services.conversations.api import router as conversations_router
from services.conversations.conversation_store import conversation_in_workspace, conversation_owned_by
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
from services.operations.diagnostics import get_build_metadata
from services.campaign_planner import analyze_campaigns
from app import lifespan as app_lifespan
from services.workspace_memory import record as record_memory, record_draft_review, record_search
from services.workspace_timeline import (
    add_event as add_timeline_event,
    record_search_started,
    record_search_completed,
    record_campaign_created,
    record_draft_approved,
    record_campaign_launched,
)
from services.workspace_snapshot import build_snapshot
from services.learning.behavior_tracker import get_tracker as _get_behavior_tracker
from services.learning.feedback_interpreter import FeedbackInterpreter as _FeedbackInterpreter
from services.draft_intelligence import analyze_draft as analyze_draft_intelligence
from services.strategic_intelligence_api import router as strategic_intelligence_router
from services.rewrite_engine import execute_rewrite
from services.draft_comparison import compare_versions
from services.workflow_planner import plan_workflow
from services.workflows.models import PlanningInput
from services.workflow_executor import execute as execute_workflow, approve as approve_workflow, pause as pause_workflow, resume as resume_workflow, cancel as cancel_workflow
from services.workflow_runtime import get_runtime, get_active_runtimes, get_all_runtimes, get_history as get_workflow_history
from services.workflow_progress import calculate_progress
from services.workflow_events import get_events as get_workflow_events, get_latest_sequence
from services.workflows.models import WorkflowPlan
from services.conversation_models import ConversationMessage
from services.communication.provider_registry import (
    get_provider, list_providers,
    instantiate_provider, register_instance, remove_instance,
    disconnect_provider as registry_disconnect, health_check,
    list_registered_types,
)
from services.outbound.outbound_registry import (
    list_providers as outbound_list_providers,
    remove_instance as outbound_remove_instance,
)
from services.communication import provider_startup
from services.communication.provider_models import (
    ProviderType, ProviderStatus, CommunicationProvider,
)
from services.communication.communication_store import store as communication_store
from services.communication.provider_events import get_events as get_provider_events, latest_sequence
from services.communication.gmail_provider import GmailProvider
from services.communication.reply_simulator import maybe_schedule as simulate_reply
from services.events_bus import publish_draft_event
from services.reply_intelligence import analyze_message
from services.conversation_memory import memory_store, create_or_update_memory
from services.followup_reasoner import recommend_followup
from services.reply_summary import generate_summary
from services.conversation_timeline import get_events as get_conversation_events
from services.conversation_models import FollowupAction, BuyingSignal, SignalStrength, ConversationStage
from services.buying_signal import detect_signals
from services.adapters.credential_registry import CredentialRegistry
from services.adapters.credentials import CredentialInstance
from services.execution import AdapterRegistry as ExecutionAdapterRegistry
from services.operations import (
    RequestLoggingMiddleware,
    log_config_warnings,
    operations_router,
    set_startup_time,
    startup_diagnostics,
    redact_session_path,
    request_id_var,
)
from services.world_model import EventType as WMEventType, publish

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

@asynccontextmanager
async def lifespan(app: FastAPI):
    startup_started = app_lifespan.begin_startup(app)

    # Validate before any background worker, provider restore, or sync engine.
    app_lifespan.validate_startup_configuration()

    app_lifespan.initialize_runtime_services(_execution_adapter_registry)

    app_lifespan.register_execution_observability()

    background_tasks: list[asyncio.Task] = []
    app_lifespan.start_memory_consolidation(background_tasks)

    app_lifespan.rehydrate_conversation_store()

    app_lifespan.rehydrate_communication_store()

    # Restore workflow and provider runtime state before any worker consumes it.
    app_lifespan.recover_persisted_workflows()
    provider_startup.initialize_gmail_runtime(_credential_registry)

    inbox_sync_engine, simulator_task = await app_lifespan.start_communication_background_services()
    app_lifespan.start_generation_recovery(background_tasks)

    await app_lifespan.recover_search_and_start_due_jobs(background_tasks)

    app_lifespan.start_launch_backfill(background_tasks)

    app_lifespan.start_abandoned_registration_cleanup(background_tasks)

    from services.lifecycle import set_ready

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

    await app_lifespan.shutdown_runtime(background_tasks, inbox_sync_engine, simulator_task)

_production_env = (os.getenv("ENVIRONMENT") or os.getenv("APP_ENV") or "development").strip().lower() == "production"

app = FastAPI(
    lifespan=lifespan,
    # PR10.8.3.3: do not expose the OpenAPI surface in production.
    docs_url=None if _production_env else "/docs",
    openapi_url=None if _production_env else "/openapi.json",
    redoc_url=None if _production_env else "/redoc",
)
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
        await identity_dependencies.resolve_web_session(request)  # raises 401 when unauthenticated
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return await call_next(request)


app.include_router(operations_router)
app.include_router(auth_router)
app.include_router(onboarding_router)
app.include_router(organizations_router, prefix="/api/v1")
app.include_router(billing_router)
app.include_router(capabilities_router)
app.include_router(knowledge_router)
app.include_router(strategic_intelligence_router)
app.include_router(mission_control_router)
app.include_router(discovery_router)
app.include_router(campaigns_router)
app.include_router(drafts_router)
app.include_router(conversations_router)

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

# R5/R8 compatibility projection only. Credential values and connected-account
# ownership are durable in Supabase; this process-local registry only exposes
# descriptors to the legacy execution bridge. Do not add durable authority here.
_credential_registry = CredentialRegistry()
# R5/R8 compatibility projection only. The execution adapter implementation is
# owned by services.execution; this startup registry is process-local wiring,
# not a durable source of provider or workflow state.
_execution_adapter_registry = ExecutionAdapterRegistry()

# Strategy generation returns 202 immediately; clients poll
# `strategy-jobs/{job_id}`. Runtime task handles are in-memory, while the
# lifecycle authority is persisted in campaign settings so a restart resolves
# interrupted work to an explicit terminal state.
# R5/R8 compatibility projection only. Campaign strategy-job metadata is
# persisted on the canonical campaign record; this map retains live task state
# for legacy polling until that route family moves to the durable jobs boundary.


def _build_copilot_workspace_context(
    session_token: str,
    current_page: str | None = None,
    page_context: dict | None = None,
    conversation_id: str | None = None,
    user_id: str = "",
    workspace_id: str = "",
) -> dict:
    # Copilot is a read/analyze surface. Its workspace context must come from
    # the canonical workspace projection so a reload, another tab, or a
    # previous session cannot leave the assistant reasoning over stale
    # session-local campaign/draft state.
    if not user_id or not workspace_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    campaigns = []
    drafts = []
    try:
        from services.workspace_state import load_workspace_state
        state = load_workspace_state(
            user_id,
            include_details=False,
            workspace_id=workspace_id,
            canonical_only=True,
        )
        campaigns = state.get("campaigns") or []
        drafts = state.get("drafts") or []
    except Exception as error:
        log.warning("Copilot canonical workspace context unavailable: %s", error)
    # Scope the prompt-facing operational set to the active resource. The
    # canonical loaders remain authoritative; this only prevents unrelated
    # campaigns/drafts from becoming retrieval context for the turn.
    page_context = page_context or {}
    active_campaign_id = str(
        page_context.get("campaign_id") or page_context.get("active_campaign_id") or ""
    ).strip()
    active_draft_id = str(
        page_context.get("draft_id") or page_context.get("active_draft_id") or ""
    ).strip()
    if active_campaign_id:
        campaigns = [c for c in campaigns if str(c.get("id") or "") == active_campaign_id]
        drafts = [d for d in drafts if str(d.get("campaign_id") or "") == active_campaign_id]
    if active_draft_id:
        drafts = [d for d in drafts if str(d.get("id") or "") == active_draft_id]
    campaigns = campaigns[:20]
    drafts = drafts[:50]
    # Keep turn context deliberately narrow and workspace-scoped. The legacy
    # snapshot helper also hydrates session memory/timeline and user-wide jobs;
    # those are not authoritative for an explicitly selected workspace. Live
    # questions use their canonical read tool after intent selection.
    from services.workspace_snapshot import enrich_campaigns
    from services.workspace_reasoner import WorkspaceReasoner

    enriched_campaigns = enrich_campaigns(campaigns, drafts)
    total_leads = sum(int(c.get("lead_count") or 0) for c in enriched_campaigns)
    pending_drafts = sum(1 for draft in drafts if str(draft.get("status") or "") == "pending")
    approved_drafts = sum(1 for draft in drafts if str(draft.get("status") or "") == "approved")
    prompt_campaigns = [
        {
            "id": str(campaign.get("id") or ""),
            "name": str(campaign.get("name") or ""),
            "status": str(campaign.get("status") or "planning"),
            "current_step": str(campaign.get("current_step") or ""),
            "lead_count": int(campaign.get("lead_count") or 0),
            "pending_drafts": int(campaign.get("pending_drafts") or 0),
            "approved_drafts": int(campaign.get("approved_drafts") or 0),
            "created_at": campaign.get("created_at") or "",
            "updated_at": campaign.get("updated_at") or "",
        }
        for campaign in enriched_campaigns
    ]
    snapshot = {
        "campaigns": prompt_campaigns,
        "campaign_count": len(prompt_campaigns),
        "campaigns_ready": sum(1 for campaign in prompt_campaigns if campaign["current_step"] == "sending"),
        "campaigns_draft_review": sum(1 for campaign in prompt_campaigns if campaign["current_step"] == "review"),
        "drafts": {"total": len(drafts), "pending": pending_drafts, "approved": approved_drafts},
        "total_leads": total_leads,
        "jobs": {"running": [], "recently_completed": []},
        "memory": {},
        "timeline": [],
    }
    analysis = WorkspaceReasoner(snapshot).analyze().to_dict()

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
            "active_workflows": [],
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
        if (
            convo is not None
            and conversation_owned_by(convo, user_id)
            and conversation_in_workspace(convo, str(workspace_id or ""))
        ):
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


# ── Logging Middleware ──

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
    from services.rate_limit import classify_rate_limit, rate_limiter, resolve_rate_limit_identity

    category = classify_rate_limit(request.url.path)
    if category == "health":
        return await call_next(request)

    limit = rate_limiter.limits.get(category, 300)
    if limit <= 0:
        return await call_next(request)

    session_token = identity_dependencies.web_session_token(request)
    identity = f"ip:{request.client.host if request.client else 'unknown'}"
    if session_token:
        # Compatibility seam: main supplies the legacy session lookup so rate_limit stays independent of ConversationEngine.
        user_id = await resolve_rate_limit_identity(session_token, engine.get_web_session_user_id)
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
# Keep correlation and API-version headers around every response, including
# early rate-limit and session-auth rejections from the middleware below it.
app.add_middleware(RequestLoggingMiddleware)


class CreateWebSessionRequest(BaseModel):
    display_name: str | None = None


class CopilotContextModel(BaseModel):
    current_page: str | None = None
    page_context: dict | None = None
    available_actions: list[str] | None = None
    message_history: list[dict] | None = None
    conversation_id: str | None = None
    # A browser-generated turn identifier. It is an idempotency correlation
    # key only, never user/workspace authority.
    request_id: str | None = None
    active_search: dict | None = None


class SendWebMessageRequest(BaseModel):
    text: str
    copilot: CopilotContextModel | None = None


def _copilot_read_message(result: dict) -> str:
    status = str(result.get("status") or "")
    if status != "completed":
        return f"That Discovery is currently {status or 'not ready'}; I don't have completed results yet."
    leads = int(result.get("lead_count") or 0)
    companies = int(result.get("company_count") or 0)
    return (
        f"The Discovery found {leads} lead{'s' if leads != 1 else ''}"
        f" across {companies} compan{'ies' if companies != 1 else 'y'}."
    )


async def _copilot_grounded_response_text(
    user_message: str,
    decision: dict,
    workspace_context: dict,
    tool_name: str,
    result: dict,
) -> str:
    """Explain an authoritative read result without inventing workspace facts."""
    from services.conversational_response_generator import generate_copilot_response

    return await asyncio.to_thread(
        generate_copilot_response,
        user_message=user_message,
        copilot_context={
            "intent": decision.get("intent"),
            "current_page": decision.get("current_page", ""),
            "page_context": decision.get("page_context") or {},
            "message_history": decision.get("message_history") or [],
            "workspace_context": workspace_context,
            "authoritative_tool": tool_name,
            "authoritative_result": result,
            "mvp_read_only": True,
        },
        context={"user_id": "", "service": "", "target": ""},
    )


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
                summary = await identity_dependencies.cached_web_session_identity(session_token)
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
    if await asyncio.to_thread(get_user, user_id):
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
        provider_startup.register_outbound_gmail_instance(provider_record.id)

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
        tokens = await asyncio.to_thread(exchange_code_for_tokens, code)
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
        if user_id:
            await identity_dependencies.ensure_legacy_user_bridge(user_id)
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
    session_token = identity_dependencies.web_session_token(request)
    data = await asyncio.to_thread(engine.get_web_session_summary, session_token)
    if data is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return data


@app.get("/api/web/session/{session_token}/messages")
async def get_web_session_messages(session_token: str, request: Request = None):
    session_token = identity_dependencies.web_session_token(request)
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
    session_token = identity_dependencies.web_session_token(request)
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
        if user_id:
            await identity_dependencies.ensure_legacy_user_bridge(user_id)
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
        session_token = created["session_token"]
        # A Copilot bootstrap must continue through the Copilot owner below.
        # Only legacy web messages use ConversationEngine.handle_message.
        if payload.copilot is None:
            return await asyncio.to_thread(
                engine.handle_message,
                channel="web",
                external_user_id=session_token,
                text=payload.text,
                username=summary.get("display_name"),
            )

    if payload.copilot is not None:
        # Copilot conversation state is supplied explicitly by the Copilot
        # surface. Do not hydrate it from legacy conversations/user_messages;
        # those fields belong exclusively to ConversationEngine callers.
        # The authenticated request is the only identity authority for
        # Copilot. A web-session summary is useful conversation metadata but
        # must never select the user or workspace used for reads/tools.
        user_id, _canonical_session_id = await identity_dependencies.resolve_web_session(request)
        selected_workspace = await workspace_access.resolve_selected_workspace_context(request, user_id)
        workspace_id = str(selected_workspace.workspace_id or "")
        if not workspace_id:
            raise HTTPException(status_code=404, detail="No accessible workspace")
        from services.copilot_memory import CopilotMemoryService, merge_turn_history
        conversation_key = str(payload.copilot.conversation_id or "").strip()[:128]
        if not conversation_key:
            # Older clients do not send a chat id. Keep their memory isolated
            # without persisting a bearer/session token itself.
            conversation_key = "legacy-" + hashlib.sha256(session_token.encode()).hexdigest()[:32]
        copilot_memory = CopilotMemoryService()
        remembered_context = await copilot_memory.retrieve(
            user_id=user_id,
            workspace_id=workspace_id,
            conversation_key=conversation_key,
        )
        try:
            from services.supabase import get_user_preferences
            user_preferences = await asyncio.to_thread(get_user_preferences, user_id)
        except Exception:
            user_preferences = None
        if isinstance(user_preferences, dict):
            remembered_context["user_preferences"] = user_preferences
        bounded_history = merge_turn_history(
            remembered_context,
            payload.copilot.message_history,
        )
        log.info(
            "COPILOT_REQUEST path=post_web_session_message workspace=%s page=%s text_chars=%s",
            workspace_id,
            payload.copilot.current_page or "(unset)",
            len(payload.text or ""),
        )
        workspace_context = await asyncio.to_thread(
            _build_copilot_workspace_context,
            session_token,
            current_page=payload.copilot.current_page,
            page_context=payload.copilot.page_context,
            user_id=user_id,
            workspace_id=workspace_id,
        )
        # This is derived conversational context, never a replacement for the
        # canonical workspace projection above or tool reads below.
        workspace_context["copilot_memory"] = remembered_context
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
        from services.conversational_response_generator import (
            classify_copilot_read_question,
            decide_copilot_intent,
        )
        decision = classify_copilot_read_question(
            payload.text,
            page_context=payload.copilot.page_context,
            active_search=payload.copilot.active_search,
            message_history=bounded_history,
        )
        if decision is None:
            decision = await asyncio.to_thread(
                decide_copilot_intent,
                payload.text,
                workspace_context=workspace_context,
                message_history=bounded_history,
                active_search=payload.copilot.active_search,
            )
        decision = {
            **decision,
            "user_message": payload.text,
            "message_history": bounded_history,
            "active_search": payload.copilot.active_search or {},
            "page_context": payload.copilot.page_context or {},
            "current_page": payload.copilot.current_page or "",
        }
        await copilot_memory.record_turn(
            user_id=user_id,
            workspace_id=workspace_id,
            conversation_key=conversation_key,
            user_text=payload.text,
            intent=str(decision.get("intent") or ""),
            tool=str(decision.get("action") or ""),
        )
        from services.copilot_tools import execute_copilot_tool, select_copilot_tool
        from services.copilot_orchestrator import execute_copilot_plan, has_multi_step_plan

        async def execute_at_copilot_boundary(
            requested_tool_name: str,
            requested_decision: dict[str, Any],
        ) -> dict[str, Any]:
            """Run tools through the authenticated, durable Phase 6 boundary."""
            from services.copilot_tools import COPILOT_TOOLS

            registered_tool = COPILOT_TOOLS.get(requested_tool_name)
            if registered_tool is None:
                return {"ok": False, "status": "unsupported", "tool": requested_tool_name}

            async def invoke() -> dict[str, Any]:
                return await execute_copilot_tool(
                    requested_tool_name,
                    user_id=user_id,
                    workspace_id=workspace_id,
                    session_token=session_token,
                    decision=requested_decision,
                    discovery_runner=copilot_runners.run_discovery,
                    campaign_runner=copilot_runners.run_campaign,
                    outreach_runner=copilot_runners.run_outreach,
                    inbox_runner=lambda *args: copilot_runners.run_inbox(*args, request=request),
                    knowledge_runner=copilot_runners.run_knowledge,
                    analytics_runner=copilot_runners.run_analytics,
                )

            if registered_tool.read_only:
                return await invoke()

            # The selected workspace was resolved from the authenticated
            # request before this closure was constructed. Model/page ids do
            # not participate in selecting either authority value.
            from services.copilot_execution_ledger import CopilotExecutionService
            return await CopilotExecutionService().execute(
                tool_name=requested_tool_name,
                user_id=user_id,
                workspace_id=workspace_id,
                request_id=payload.copilot.request_id,
                conversation_key=conversation_key,
                decision=requested_decision,
                operation=invoke,
            )

        async def execute_planned_tool(planned_tool_name: str, planned_decision: dict[str, Any]) -> dict[str, Any]:
            """Run one planned step through the same Phase 2 guard as a turn.

            The planner has no authority to confirm a mutation.  Each planned
            mutation is evaluated against this user message before the
            existing tool executor receives it.
            """
            from services.copilot_tools import (
                COPILOT_TOOLS,
                PHASE2_MUTATION_TOOLS,
                mutation_confirmation_state,
            )

            tool = COPILOT_TOOLS.get(planned_tool_name)
            if tool is None:
                return {"ok": False, "status": "unavailable", "tool": planned_tool_name,
                        "reason": "That planned capability is not available."}
            guarded_decision = dict(planned_decision)
            if not tool.read_only and planned_tool_name not in {"discovery.search", "discovery.refine"}:
                if planned_tool_name not in PHASE2_MUTATION_TOOLS:
                    return {"ok": False, "status": "unavailable", "tool": planned_tool_name,
                            "reason": "That operation is not available in Copilot yet because its safe execution path has not been verified."}
                confirmation = mutation_confirmation_state(planned_tool_name, payload.text)
                if confirmation == "declined":
                    return {"ok": False, "status": "declined", "tool": planned_tool_name,
                            "reason": "Understood — no changes were made."}
                if confirmation != "confirmed":
                    return {"ok": False, "status": "confirmation_required", "tool": planned_tool_name,
                            "reason": f"I have not made any changes. Explicitly confirm this by using the requested action, for example: ‘Confirm {planned_tool_name.replace('.', ' ')}.’"}
                guarded_decision["confirmed"] = True
            return await execute_at_copilot_boundary(planned_tool_name, guarded_decision)

        if has_multi_step_plan(decision):
            orchestration = await execute_copilot_plan(decision, execute_planned_tool)
            await copilot_memory.record_outcome(
                user_id=user_id,
                workspace_id=workspace_id,
                conversation_key=conversation_key,
                tool="copilot.orchestration",
                status=str(orchestration.get("status") or ""),
                operation=orchestration.get("operation"),
            )
            if orchestration.get("status") == "accepted":
                started = orchestration.get("operation") or {}
                search_context = decision.get("search_context") or {}
                active_context = {
                    **search_context,
                    "discovery_id": started.get("discovery_id"),
                    "job_id": started.get("job_id"),
                }
                return {
                    "ok": bool(orchestration.get("ok")),
                    "intent": decision.get("intent"),
                    "messages": [_message(
                        role="assistant", message_type="tool",
                        text="I’m starting a Discovery search and will report back when the results are persisted.",
                        data={"operation": "search_discovery", "tool": "copilot.orchestration", "search_context": active_context, **started},
                    )],
                    "events": [{"type": "tool.started", "tool": "copilot.orchestration", "operation": "search_discovery", **started}],
                    "operation": {"kind": "search_discovery", "tool": "copilot.orchestration", "search_context": active_context, **started},
                }
            if not orchestration.get("ok"):
                return {
                    "ok": False,
                    "intent": decision.get("intent"),
                    "messages": [_message(
                        role="assistant", message_type="tool",
                        text=str(orchestration.get("reason") or "Copilot could not complete the planned steps."),
                        data={"tool": "copilot.orchestration", "status": orchestration.get("status"), "steps": orchestration.get("steps") or []},
                    )],
                    "events": [{"type": "tool.failed", "tool": "copilot.orchestration", "status": orchestration.get("status")}],
                    "operation": {"kind": "copilot.orchestration", "status": orchestration.get("status"), "error": orchestration.get("reason")},
                }
            steps = orchestration.get("steps") or []
            completed_tools = [str(step.get("tool") or "") for step in steps if step.get("ok")]
            verified = any(str(step.get("source") or "").startswith("verify:") for step in steps)
            text = "Retrieved the requested current workspace data."
            if completed_tools:
                prefix = "Completed and verified" if verified else "Retrieved"
                text = f"{prefix}: {', '.join(completed_tools)}."
            return {
                "ok": True,
                "intent": decision.get("intent"),
                "messages": [_message(
                    role="assistant", message_type="text", text=text,
                    data={"tool": "copilot.orchestration", "result": orchestration.get("result") or {}, "steps": steps, "verified": verified},
                )],
                "events": [{"type": "tool.completed", "tool": "copilot.orchestration", "steps": steps}],
            }

        tool_name = select_copilot_tool(decision)
        # Retrieval follows classification: operational records were loaded
        # structurally above. Semantic Knowledge is only retrieved for a
        # deliberately knowledge-grounded non-tool response; read tools fetch
        # their own canonical records, so a broad second snapshot is avoided.
        if (
            tool_name is None
            and decision.get("intent") in {"read", "clarification"}
            and (
                decision.get("knowledge_categories")
                or str(decision.get("knowledge_query") or "").strip()
            )
        ):
            try:
                from services.knowledge.context_adapter import retrieve_knowledge_context
                knowledge = await retrieve_knowledge_context(
                    user_id,
                    query=str(decision.get("knowledge_query") or payload.text),
                    categories=decision.get("knowledge_categories") or None,
                    workspace_id=workspace_id,
                )
                workspace_context["knowledge_context"] = knowledge.to_dict()
            except Exception as error:
                log.warning("Copilot semantic Knowledge retrieval unavailable: %s", error)
        if tool_name:
            from services.copilot_tools import (
                COPILOT_TOOLS,
                PHASE2_MUTATION_TOOLS,
                mutation_confirmation_state,
            )
            tool = COPILOT_TOOLS[tool_name]
            if not tool.read_only and tool_name not in {"discovery.search", "discovery.refine"}:
                if tool_name not in PHASE2_MUTATION_TOOLS:
                    return {
                        "ok": False,
                        "intent": decision.get("intent"),
                        "messages": [_message(
                            role="assistant", message_type="text",
                            text="That operation is not available in Copilot yet because its safe execution path has not been verified.",
                            data={"tool": tool_name, "status": "unavailable"},
                        )],
                        "events": [{"type": "tool.unavailable", "tool": tool_name}],
                        "operation": {"kind": tool_name, "status": "unavailable"},
                    }
                confirmation = mutation_confirmation_state(tool_name, payload.text)
                if confirmation == "declined":
                    return {
                        "ok": False,
                        "intent": decision.get("intent"),
                        "messages": [_message(
                            role="assistant", message_type="text",
                            text="Understood — no changes were made.",
                            data={"tool": tool_name, "status": "declined"},
                        )],
                        "events": [{"type": "tool.declined", "tool": tool_name}],
                        "operation": {"kind": tool_name, "status": "declined"},
                    }
                if confirmation != "confirmed":
                    return {
                        "ok": False,
                        "intent": decision.get("intent"),
                        "messages": [_message(
                            role="assistant", message_type="text",
                            text=f"I have not made any changes. Explicitly confirm this by using the requested action, for example: ‘Confirm {tool_name.replace('.', ' ')}.’",
                            data={"tool": tool_name, "status": "confirmation_required"},
                        )],
                        "events": [{"type": "tool.confirmation_required", "tool": tool_name}],
                        "operation": {"kind": tool_name, "status": "confirmation_required"},
                    }
                # The user's own message, not a model-emitted JSON flag, is
                # the confirmation authority passed to legacy adapters.
                decision["confirmed"] = True
            log.info(
                "COPILOT_DECISION workspace=%s intent=%s tool=%s mode=%s",
                workspace_id, decision.get("intent"), tool_name, decision.get("mode"),
            )
            try:
                tool_result = await execute_at_copilot_boundary(tool_name, decision)
            except Exception as error:
                log.exception("Copilot tool failed tool=%s", tool_name)
                tool_result = {
                    "ok": False,
                    "status": "failed",
                    "tool": tool_name,
                    # Keep database/provider details in server logs only. Raw
                    # driver errors are not a safe Copilot-facing contract.
                    "reason": _copilot_tool_failure_reason(tool_name),
                }
            await copilot_memory.record_outcome(
                user_id=user_id,
                workspace_id=workspace_id,
                conversation_key=conversation_key,
                tool=tool_name,
                status=str(tool_result.get("status") or ""),
                operation=tool_result.get("operation"),
            )
            if tool_name.startswith("campaign."):
                if tool_result.get("ok"):
                    result = tool_result.get("result") or {}
                    campaigns = result.get("campaigns") or []
                    campaign = result.get("campaign") or {}
                    drafts = result.get("drafts") or []
                    if tool_name == "campaign.list":
                        text = await _copilot_grounded_response_text(
                            payload.text, decision, workspace_context, tool_name, result,
                        )
                    elif tool_name == "campaign.drafts":
                        text = await _copilot_grounded_response_text(
                            payload.text, decision, workspace_context, tool_name, result,
                        )
                    elif campaign:
                        text = f"Campaign “{campaign.get('name') or 'Untitled campaign'}” was updated and verified in your workspace."
                    else:
                        text = f"{tool_name.replace('.', ' ').capitalize()} completed."
                    response: dict[str, Any] = {
                        "ok": True,
                        "intent": decision.get("intent"),
                        "messages": [_message(
                            role="assistant", message_type="text", text=text,
                            data={"tool": tool_name, "result": result, "operation": tool_result.get("operation")},
                        )],
                        "events": [{"type": "tool.completed", "tool": tool_name, "result": result}],
                    }
                    if tool_result.get("operation"):
                        response["operation"] = tool_result["operation"]
                    return response
                return {
                    "ok": False,
                    "intent": decision.get("intent"),
                    "messages": [_message(
                        role="assistant", message_type="text",
                        text=str(tool_result.get("reason") or "Campaign operation failed."),
                        data={"tool": tool_name, "status": tool_result.get("status", "failed")},
                    )],
                    "events": [{"type": "tool.failed", "tool": tool_name}],
                    "operation": {"kind": tool_name, "status": tool_result.get("status", "failed"), "error": tool_result.get("reason")},
                }

            if tool_name.startswith("outreach."):
                if tool_result.get("ok"):
                    result = tool_result.get("result") or {}
                    drafts = result.get("drafts") or ([] if not result.get("draft") else [result.get("draft")])
                    if tool_name == "outreach.drafts.read":
                        text = await _copilot_grounded_response_text(
                            payload.text, decision, workspace_context, tool_name, result,
                        )
                    elif tool_name == "outreach.draft.generate":
                        text = "Draft generation has started for this campaign."
                    elif tool_name == "outreach.draft.refine":
                        text = "The draft was updated and verified in your workspace."
                    elif tool_name == "outreach.draft.approve":
                        text = "The draft was approved and verified in your workspace."
                    else:
                        text = f"{tool_name.replace('.', ' ').capitalize()} completed."
                    response = {
                        "ok": True,
                        "intent": decision.get("intent"),
                        "messages": [_message(
                            role="assistant", message_type="text", text=text,
                            data={"tool": tool_name, "result": result, "operation": result.get("operation")},
                        )],
                        "events": [{"type": "tool.completed", "tool": tool_name, "result": result}],
                    }
                    if result.get("operation"):
                        response["operation"] = result["operation"]
                    return response
                return {
                    "ok": False,
                    "intent": decision.get("intent"),
                    "messages": [_message(
                        role="assistant", message_type="tool",
                        text=str(tool_result.get("reason") or "Outreach operation failed."),
                        data={"tool": tool_name, "status": tool_result.get("status", "failed")},
                    )],
                    "events": [{"type": "tool.failed", "tool": tool_name}],
                    "operation": {"kind": tool_name, "status": tool_result.get("status", "failed"), "error": tool_result.get("reason")},
                }

            if tool_name.startswith("inbox."):
                if tool_result.get("ok"):
                    result = tool_result.get("result") or {}
                    if tool_name != "inbox.reply.send":
                        text = await _copilot_grounded_response_text(
                            payload.text, decision, workspace_context, tool_name, result,
                        )
                    elif tool_name == "inbox.reply.send":
                        conversation = result.get("conversation") or {}
                        text = f"The reply was sent and the conversation is now {conversation.get('status') or result.get('status') or 'updated'}."
                    else:
                        text = f"{tool_name.replace('.', ' ').capitalize()} completed."
                    return {
                        "ok": True,
                        "intent": decision.get("intent"),
                        "messages": [_message(
                            role="assistant", message_type="text", text=text,
                            data={"tool": tool_name, "result": result},
                        )],
                        "events": [{"type": "tool.completed", "tool": tool_name, "result": result}],
                    }
                return {
                    "ok": False,
                    "intent": decision.get("intent"),
                    "messages": [_message(
                        role="assistant", message_type="tool",
                        text=str(tool_result.get("reason") or "Inbox operation failed."),
                        data={"tool": tool_name, "status": tool_result.get("status", "failed")},
                    )],
                    "events": [{"type": "tool.failed", "tool": tool_name}],
                    "operation": {"kind": tool_name, "status": tool_result.get("status", "failed"), "error": tool_result.get("reason")},
                }

            if tool_name.startswith("knowledge."):
                if tool_result.get("ok"):
                    result = tool_result.get("result") or {}
                    found = len(result.get("items") or []) + len(result.get("sources") or [])
                    if found:
                        text = await _copilot_grounded_response_text(
                            payload.text, decision, workspace_context, tool_name, result,
                        )
                    else:
                        text = "I couldn't find matching Knowledge in your workspace, so I won't infer an answer."
                    return {
                        "ok": True,
                        "intent": decision.get("intent"),
                        "messages": [_message(
                            role="assistant", message_type="text", text=text,
                            data={"tool": tool_name, "result": result, "grounded": bool(found)},
                        )],
                        "events": [{"type": "tool.completed", "tool": tool_name, "result": result}],
                    }
                return {
                    "ok": False,
                    "intent": decision.get("intent"),
                    "messages": [_message(
                        role="assistant", message_type="tool",
                        text=str(tool_result.get("reason") or "Knowledge retrieval failed."),
                        data={"tool": tool_name, "status": tool_result.get("status", "failed")},
                    )],
                    "events": [{"type": "tool.failed", "tool": tool_name}],
                    "operation": {"kind": tool_name, "status": tool_result.get("status", "failed"), "error": tool_result.get("reason")},
                }

            if tool_name.startswith("analytics."):
                if tool_result.get("ok"):
                    result = tool_result.get("result") or {}
                    metrics = result.get("metrics") or {}
                    text = await _copilot_grounded_response_text(
                        payload.text, decision, workspace_context, tool_name, result,
                    ) if metrics else "The analytics result contains no metric fields for this context."
                    return {
                        "ok": True,
                        "intent": decision.get("intent"),
                        "messages": [_message(
                            role="assistant", message_type="text", text=text,
                            data={"tool": tool_name, "result": result, "authoritative": True},
                        )],
                        "events": [{"type": "tool.completed", "tool": tool_name, "result": result}],
                    }
                return {
                    "ok": False,
                    "intent": decision.get("intent"),
                    "messages": [_message(
                        role="assistant", message_type="tool",
                        text=str(tool_result.get("reason") or "Analytics are unavailable for this context."),
                        data={"tool": tool_name, "status": tool_result.get("status", "failed")},
                    )],
                    "events": [{"type": "tool.failed", "tool": tool_name}],
                    "operation": {"kind": tool_name, "status": tool_result.get("status", "failed"), "error": tool_result.get("reason")},
                }

            if tool_name == "discovery.read" or tool_name.startswith("lead."):
                if tool_result.get("ok"):
                    result = tool_result.get("result") or {}
                    if tool_name == "discovery.read":
                        text = await _copilot_grounded_response_text(
                            payload.text, decision, workspace_context, tool_name, result,
                        )
                    elif tool_name in {"lead.read", "lead.filter", "lead.rank"}:
                        text = await _copilot_grounded_response_text(
                            payload.text, decision, workspace_context, tool_name, result,
                        )
                    else:
                        text = f"{tool_name.replace('.', ' ').capitalize()} was completed and verified for {len(result.get('leads') or [])} lead(s)."
                    return {
                        "ok": True,
                        "intent": decision.get("intent"),
                        "messages": [_message(
                            role="assistant",
                            message_type="text",
                            text=text,
                            data={"tool": tool_name, "result": result},
                        )],
                        "events": [{"type": "tool.completed", "tool": tool_name, "result": result}],
                        "read_result": result if tool_name == "discovery.read" or tool_name.startswith("lead.") else None,
                    }
                return {
                    "ok": False,
                    "intent": decision.get("intent"),
                    "messages": [_message(
                        role="assistant", message_type="tool",
                        text=str(tool_result.get("reason") or "I couldn't retrieve that Discovery."),
                        data={"tool": tool_name, "status": tool_result.get("status", "failed")},
                    )],
                    "events": [{"type": "tool.failed", "tool": tool_name}],
                    "operation": {"kind": tool_name, "status": "failed", "error": tool_result.get("reason")},
                }

            if not tool_result.get("ok"):
                reason = str(tool_result.get("reason") or "Discovery operation failed.")
                return {
                    "ok": False,
                    "intent": decision.get("intent"),
                    "messages": [_message(
                        role="assistant", message_type="tool", text=reason,
                        data={"tool": tool_name, "status": "failed"},
                    )],
                    "events": [{"type": "tool.failed", "tool": tool_name}],
                    "operation": {"kind": tool_name, "status": "failed", "error": reason},
                }

            started = tool_result.get("operation") or {}
            search_context = tool_result.get("search_context") or {}
            active_context = {
                **search_context,
                "discovery_id": started.get("discovery_id"),
                "job_id": started.get("job_id"),
            }
            operation_message = _message(
                role="assistant",
                message_type="tool",
                text="I’m starting a Discovery search and will report back when the results are persisted.",
                data={"operation": "search_discovery", "tool": tool_name, "search_context": active_context, **started},
            )
            return {
                "ok": True,
                "intent": decision.get("intent"),
                "messages": [operation_message],
                "events": [{"type": "tool.started", "tool": tool_name, "operation": "search_discovery", **started}],
                "operation": {"kind": "search_discovery", "tool": tool_name, "search_context": active_context, **started},
            }

        if decision.get("intent") == "action":
            requested_action = str(decision.get("action") or "")
            message = "That action is understood, but the corresponding Loqi capability is not available yet."
            return {
                "ok": False,
                "intent": decision.get("intent"),
                "messages": [_message(
                    role="assistant", message_type="tool", text=message,
                    data={"status": "unsupported", "action": requested_action},
                )],
                "events": [{"type": "tool.unsupported", "action": requested_action}],
                "operation": {"kind": "action", "status": "unsupported", "action": requested_action},
            }
        from services.conversational_response_generator import generate_copilot_response
        # PR-P1.2: generate_copilot_response performs a synchronous OpenAI
        # HTTP call (20s timeout). Offload to a worker thread so a slow LLM
        # response cannot freeze the event loop for unrelated requests.
        response_text = await asyncio.to_thread(
            generate_copilot_response,
            user_message=payload.text,
            copilot_context={
                **(payload.copilot.model_dump()),
                "intent": decision.get("intent"),
                "message_history": bounded_history,
                "workspace_context": workspace_context,
                "mvp_read_only": True,
            },
            context={
                "user_id": summary.get("user_id"),
                "service": "",
                "target": "",
            },
        )
        print(f"[COPILOT_TRACE] page={payload.copilot.current_page or '(unset)'} message={payload.text[:60]} history_len={len(payload.copilot.message_history or [])}")
        msg = _message(role="assistant", message_type="text", text=response_text)
        return {"ok": True, "intent": decision.get("intent"), "messages": [msg], "events": []}

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
    session_token = identity_dependencies.web_session_token(request)
    if not payload.leads:
        raise HTTPException(status_code=400, detail="No leads provided")
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    workspace_id = await workspace_access.resolve_legacy_workspace_id(request, owner_id)
    batch = await draft_service.enqueue_draft_batch(
        session_token,
        owner_id,
        workspace_id,
        payload.leads,
        payload.campaign_id or "",
    )
    return {"ok": True, "batch_id": batch["batch_id"], "total": batch["total"]}


@app.get("/api/web/session/{session_token}/batch-status/{batch_id}")
async def batch_status(session_token: str, batch_id: str, request: Request = None):
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    workspace_id = await workspace_access.resolve_legacy_workspace_id(request, owner_id)
    job = await draft_service.draft_batch_status(owner_id, workspace_id, batch_id)
    if not job:
        raise HTTPException(status_code=404, detail="Batch not found")
    return {"ok": True, **job}


@app.post("/api/web/session/{session_token}/analyze-campaigns")
async def analyze_campaigns_endpoint(session_token: str, payload: BatchDraftRequest):
    result = analyze_campaigns(payload.leads)
    return result

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
    session_token = identity_dependencies.web_session_token(request)
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
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    from services.conversations.conversation_store import conversation_store
    convo = conversation_store.get_conversation(conversation_id)
    if convo is None or not conversation_owned_by(convo, owner_id):
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
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    from services.workspace_context import workspaces_for_user
    ws = await asyncio.to_thread(workspaces_for_user, None, owner_id)
    return {"ok": True, "workspaces": ws}


@app.post("/api/web/session/{session_token}/workspaces/select")
async def select_workspace(session_token: str, request: Request):
    """Validate + return the context for an explicitly selected workspace."""
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    ctx = await workspace_access.resolve_selected_workspace_context(request, owner_id)
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
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
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
    session_token = identity_dependencies.web_session_token(request)
    """Returns workspace context with provider info for the dev providers page."""
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    selected_workspace = await workspace_access.resolve_selected_workspace_context(request, owner_id)
    ctx = await asyncio.to_thread(
        _build_copilot_workspace_context,
        session_token,
        current_page="Mission Control",
        conversation_id=conversation_id or None,
        user_id=owner_id,
        workspace_id=selected_workspace.workspace_id,
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
    session_token = identity_dependencies.web_session_token(request)
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
            provider_startup.register_outbound_gmail_instance(provider.id)
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
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    if not outbound_service.provider_record_owned_by(provider_id, owner_id):
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
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)

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
                status_val = (await asyncio.to_thread(runtime_instance.health)).value
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
            "status": (await asyncio.to_thread(instance.health)).value if instance else p.status.value,
            "email": p.metadata.get("email", ""),
            "last_sync": p.last_sync,
            "sync_cursor": p.sync_cursor,
            "created_at": p.created_at,
        })

    return {"ok": True, "providers": result}


@app.get("/api/web/session/{session_token}/providers/{provider_id}/health")
async def provider_health(session_token: str, provider_id: str, request: Request):
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    if not outbound_service.provider_record_owned_by(provider_id, owner_id):
        raise HTTPException(status_code=404, detail="Provider not found")
    instance = get_provider(provider_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Provider not found")
    status = await asyncio.to_thread(instance.health)
    provider = communication_store.get_provider(provider_id)
    # Persisted auth_failed wins over a still-valid runtime access token.
    if provider is not None and provider.provider_type == ProviderType.GMAIL:
        try:
            from services.supabase import is_connected_account_reauth_required
            if await asyncio.to_thread(is_connected_account_reauth_required, provider.user_id, "google"):
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
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    if not outbound_service.provider_record_owned_by(provider_id, owner_id):
        raise HTTPException(status_code=404, detail="Provider not found")
    from services.communication.inbox_sync_engine import inbox_sync_engine
    result = await inbox_sync_engine.sync_provider_now(provider_id, cursor=cursor)
    if result is None:
        raise HTTPException(status_code=404, detail="Provider not found")
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
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    if not outbound_service.provider_record_owned_by(provider_id, owner_id):
        raise HTTPException(status_code=404, detail="Provider not found")
    provider = communication_store.get_provider(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    instance = get_provider(provider_id)
    health_val = (await asyncio.to_thread(instance.health)).value if instance else provider.status.value
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
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token) if request is not None else ""
    if not outbound_service.provider_record_owned_by(provider_id, owner_id):
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
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token) if request is not None else ""
    if not outbound_service.provider_record_owned_by(provider_id, owner_id):
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
        owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
        from services.workspace_state import ensure_workspace
        ws = await workspace_access.resolve_legacy_workspace_id(request, owner_id)
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
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    if not outbound_service.provider_owned_by(payload.provider_id, owner_id):
        raise HTTPException(status_code=404, detail="Provider not found")
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
    from services.workspace_state import persist_draft_awaited
    canonical = {
        "id": draft.id,
        "campaign_id": draft.workflow_id,
        "provider": payload.provider_id,
        "subject": draft.subject,
        "body": draft.body,
        "status": "draft",
        "lead": {"email": draft.recipient.email, "name": draft.recipient.name},
    }
    if not await persist_draft_awaited(owner_id, canonical):
        raise HTTPException(status_code=503, detail="Draft could not be persisted")

    # Provider projection happens only after the canonical review draft is
    # durable. A projection failure is visible as an explicit failed state;
    # it cannot turn an unpersisted draft into a successful API response.
    from services.outbound.outbound_registry import create_draft as reg_create_draft
    from services.workspace_state import persist_draft_update_awaited
    workspace_id = await workspace_access.resolve_legacy_workspace_id(request, owner_id)
    try:
        result = reg_create_draft(payload.provider_id, draft)
        if not result:
            raise RuntimeError("Provider did not return a draft projection")
        draft = result
        if not await outbound_service.persist_outbound_projection(
            owner_id, workspace_id, draft, change_summary="provider draft created",
        ):
            raise RuntimeError("Provider draft projection could not be persisted")
    except Exception as error:
        await persist_draft_update_awaited(owner_id, draft.id, {"status": "failed"})
        raise HTTPException(status_code=502, detail="Draft was persisted but provider projection failed") from error
    publish(session_token, WMEventType.DRAFT_GENERATED, {
        "id": draft.id,
        "campaign_id": draft.workflow_id,
        "subject": draft.subject,
        "body_preview": draft.body[:200],
        "recipient_email": draft.recipient.email,
        "provider_id": payload.provider_id,
    }, actor="user")
    return {"ok": True, "draft": draft.model_dump()}


@app.patch("/api/web/session/{session_token}/outbound/drafts/{draft_id}")
async def outbound_update_draft(session_token: str, draft_id: str, payload: OutboundUpdateDraftRequest, request: Request):
    session_token = identity_dependencies.web_session_token(request)
    owner_id, workspace_id, _canonical, existing = await outbound_service.require_canonical_outbound_draft(
        request, session_token, draft_id, provider_id=payload.provider_id,
    )
    update_data = {}
    if payload.subject:
        update_data["subject"] = payload.subject
    if payload.body:
        update_data["body"] = payload.body
    if payload.recipient_email:
        update_data["recipient"] = Recipient(email=payload.recipient_email, name=payload.recipient_name)
    canonical_updates = {
        key: value for key, value in update_data.items()
        if key in {"subject", "body"}
    }
    if canonical_updates:
        from services.workspace_state import persist_draft_update_awaited
        if not await persist_draft_update_awaited(
            owner_id, draft_id, canonical_updates, workspace_id=workspace_id,
        ):
            raise HTTPException(status_code=503, detail="Draft update could not be persisted")
    updated = existing.model_copy(update=update_data)
    if payload.external_draft_id:
        from services.outbound.outbound_registry import update_draft as reg_update_draft
        reg_result = reg_update_draft(payload.provider_id, updated)
        if not reg_result:
            raise HTTPException(status_code=502, detail="Provider draft update failed")
        updated = reg_result
    if not await outbound_service.persist_outbound_projection(
        owner_id, workspace_id, updated, change_summary="provider draft updated",
    ):
        raise HTTPException(status_code=503, detail="Draft projection could not be persisted")
    publish(session_token, WMEventType.DRAFT_UPDATED, {
        "draft_id": draft_id,
        "provider_id": payload.provider_id,
        "subject": payload.subject or existing.subject,
    }, actor="user")
    return {"ok": True, "draft": updated.model_dump()}


@app.delete("/api/web/session/{session_token}/outbound/drafts/{draft_id}")
async def outbound_delete_draft(session_token: str, draft_id: str, provider_id: str = "", request: Request = None):
    session_token = identity_dependencies.web_session_token(request)
    if request is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    owner_id, workspace_id, _canonical, draft = await outbound_service.require_canonical_outbound_draft(
        request, session_token, draft_id, provider_id=provider_id,
    )
    if draft and draft.external_draft_id and provider_id:
        from services.outbound.outbound_registry import delete_draft as reg_delete_draft
        reg_delete_draft(provider_id, draft.external_draft_id)
    from services.workspace_state import persist_draft_update_awaited
    if not await persist_draft_update_awaited(
        owner_id, draft_id, {"status": "rejected"}, workspace_id=workspace_id,
    ):
        raise HTTPException(status_code=503, detail="Draft deletion could not be persisted")
    from services.outbound.outbound_models import DraftStatus
    draft.status = DraftStatus.REJECTED
    if not await outbound_service.persist_outbound_projection(
        owner_id, workspace_id, draft, change_summary="provider draft deleted",
    ):
        raise HTTPException(status_code=503, detail="Draft deletion projection could not be persisted")
    publish(session_token, WMEventType.DRAFT_REJECTED, {
        "draft_id": draft_id,
        "provider_id": provider_id,
    }, actor="user")
    _get_feedback().on_draft_rejected(session_token, draft_id)
    return {"ok": True}


class SendDraftRequest(BaseModel):
    """Optional test-only recipient override. Ignored unless
    LOQI_ENABLE_TEST_RECIPIENT_OVERRIDE=true."""
    test_recipient: str = ""
    test_recipient_name: str = ""


def _test_recipient_override_enabled() -> bool:
    return os.getenv("LOQI_ENABLE_TEST_RECIPIENT_OVERRIDE", "").strip().lower() in {"1", "true", "yes"}


@app.post("/api/web/session/{session_token}/drafts/{draft_id}/send")
async def send_draft(session_token: str, draft_id: str, request: Request, payload: SendDraftRequest = None):
    session_token = identity_dependencies.web_session_token(request)
    payload = payload or SendDraftRequest()
    test_recipient = payload.test_recipient or ""
    if test_recipient and not _test_recipient_override_enabled():
        raise HTTPException(status_code=403, detail="Test recipient override is disabled")

    owner_id, ws_id, canonical_draft, outbound_draft = await outbound_service.require_canonical_outbound_draft(
        request, session_token, draft_id,
    )
    if canonical_draft.get("status") == "sent":
        return {"ok": False, "error": "Draft already sent"}
    from services.outbound.outbound_models import DraftStatus
    if outbound_draft.status in (DraftStatus.SENT, DraftStatus.SENDING):
        return {"ok": False, "error": "Draft already sent"}
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
    real_provider_id = outbound_service.resolve_provider_for_draft(outbound_draft, owner_id)
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
    result = await asyncio.to_thread(
        outbound_executor.send_hydrated_draft,
        outbound_draft,
        provider_id=real_provider_id,
        recipient_override=Recipient(**send_recipient),
    )
    if result.get("ok"):
        from services.workspace_state import persist_draft_update_awaited
        if not await persist_draft_update_awaited(
            owner_id, draft_id, {"status": "sent"}, workspace_id=ws_id,
        ):
            raise HTTPException(status_code=503, detail="Email was sent but the canonical Draft could not be updated")
        outbound_draft.status = DraftStatus.SENT
        if not await outbound_service.persist_outbound_projection(owner_id, ws_id, outbound_draft, change_summary="sent"):
            raise HTTPException(status_code=503, detail="Email was sent but the outbound projection could not be updated")
        await publish_draft_event(
            owner_id, "draft.sent", draft_id=draft_id,
            campaign_id=outbound_draft.workflow_id or "",
            lead_name=outbound_draft.recipient.name if outbound_draft.recipient else "",
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
                workspace_id=ws_id,
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
    session_token = identity_dependencies.web_session_token(request)
    owner_id, ws_id, canonical_draft, outbound_draft = await outbound_service.require_canonical_outbound_draft(
        request, session_token, draft_id,
    )
    recipient_email = (outbound_draft.recipient.email if outbound_draft.recipient else "") or ""
    if not str(recipient_email).strip():
        return {"ok": False, "error": "This lead has no email address"}
    real_provider_id = outbound_service.resolve_provider_for_draft(outbound_draft, owner_id)
    if not real_provider_id:
        return {"ok": False, "error": "No Gmail outbound provider registered"}
    log.info("[schedule_draft] Scheduling draft %s at %s via provider %s", draft_id, payload.send_at, real_provider_id)
    result = await outbound_service.enqueue_scheduled_outbound_send(
        owner_id, ws_id, canonical_draft, outbound_draft, payload.send_at,
    )
    if result.get("ok"):
        await publish_draft_event(owner_id, "draft.scheduled", draft_id=draft_id)
        publish(session_token, WMEventType.DRAFT_SCHEDULED, {
            "draft_id": draft_id,
            "send_at": payload.send_at,
            "provider_id": real_provider_id,
            "campaign_id": outbound_draft.workflow_id if outbound_draft else "",
        }, actor="user")
    if result.get("error") == "Draft was scheduled but canonical persistence failed":
        raise HTTPException(status_code=503, detail=result["error"])
    if result.get("error") == "Draft schedule projection persistence failed":
        raise HTTPException(status_code=503, detail=result["error"])
    result.pop("job_id", None)
    return result


@app.post("/api/web/session/{session_token}/drafts/{draft_id}/cancel-schedule")
async def cancel_schedule_draft(session_token: str, draft_id: str, request: Request):
    session_token = identity_dependencies.web_session_token(request)
    owner_id, ws_id, canonical_draft, outbound_draft = await outbound_service.require_canonical_outbound_draft(
        request, session_token, draft_id,
    )
    result = await outbound_service.cancel_scheduled_outbound_send(
        owner_id, ws_id, canonical_draft, outbound_draft,
    )
    if result.get("ok"):
        await publish_draft_event(owner_id, "draft.updated", draft_id=draft_id)
        publish(session_token, WMEventType.DRAFT_UPDATED, {
            "draft_id": draft_id,
            "status": "pending",
            "previous_status": "scheduled",
        }, actor="user")
    if result.get("error") == "Schedule was cancelled but canonical Draft persistence failed":
        raise HTTPException(status_code=503, detail=result["error"])
    if result.get("error") == "Draft schedule projection persistence failed":
        raise HTTPException(status_code=503, detail=result["error"])
    return result


@app.post("/api/web/session/{session_token}/outbound/send")
async def outbound_send(session_token: str, payload: OutboundSendRequest, request: Request):
    """Compatibility alias for canonical Draft send; payload is not authority."""
    if not payload.draft_id:
        raise HTTPException(status_code=400, detail="Draft id is required")
    return await send_draft(session_token, payload.draft_id, request, SendDraftRequest())


@app.post("/api/web/session/{session_token}/outbound/schedule")
async def outbound_schedule(session_token: str, payload: OutboundScheduleRequest, request: Request):
    return await schedule_draft(
        session_token, payload.draft_id, ScheduleDraftRequest(send_at=payload.send_at), request,
    )


@app.delete("/api/web/session/{session_token}/outbound/schedule/{schedule_id}")
async def outbound_cancel_schedule(session_token: str, schedule_id: str, provider_id: str = "", request: Request = None):
    if request is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    session_token = identity_dependencies.web_session_token(request)
    owner_id, ws_id, canonical_draft, draft = await outbound_service.require_canonical_outbound_draft(
        request, session_token, schedule_id, provider_id,
    )
    result = await outbound_service.cancel_scheduled_outbound_send(
        owner_id, ws_id, canonical_draft, draft,
    )
    if result.get("ok"):
        await publish_draft_event(owner_id, "draft.updated", draft_id=schedule_id)
    if result.get("error") == "Schedule was cancelled but canonical Draft persistence failed":
        raise HTTPException(status_code=503, detail=result["error"])
    if result.get("error") == "Draft schedule projection persistence failed":
        raise HTTPException(status_code=503, detail=result["error"])
    return result


@app.get("/api/web/session/{session_token}/outbound/drafts")
async def outbound_list_drafts(session_token: str, request: Request, provider_id: str = ""):
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    if provider_id and not outbound_service.provider_owned_by(provider_id, owner_id):
        raise HTTPException(status_code=404, detail="Provider not found")
    workspace_id = await workspace_access.resolve_legacy_workspace_id(request, owner_id)
    from services.workspace_state import load_drafts_only

    drafts = [
        outbound_service.hydrate_outbound_draft(draft, session_token, owner_id=owner_id)
        for draft in load_drafts_only(owner_id, workspace_id=workspace_id)
        if (draft.get("provider") or (draft.get("metadata") or {}).get("outbound_projection"))
        and (not provider_id or str(draft.get("provider") or (draft.get("metadata") or {}).get("outbound_projection", {}).get("provider_id") or "") == provider_id)
    ]
    return {"ok": True, "drafts": [d.model_dump() for d in drafts], "total": len(drafts)}


@app.get("/api/web/session/{session_token}/outbound/drafts/{draft_id}")
async def outbound_get_draft(session_token: str, draft_id: str, request: Request):
    session_token = identity_dependencies.web_session_token(request)
    _owner_id, _ws_id, canonical, _draft = await outbound_service.require_canonical_outbound_draft(
        request, session_token, draft_id,
    )
    return {"ok": True, "draft": canonical}


@app.post("/api/web/session/{session_token}/outbound/drafts/{draft_id}/approve")
async def outbound_approve_draft(session_token: str, draft_id: str, auto: bool = False, request: Request = None):
    if request is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    session_token = identity_dependencies.web_session_token(request)
    owner_id, ws_id, _canonical, draft = await outbound_service.require_canonical_outbound_draft(request, session_token, draft_id)
    from services.outbound.outbound_models import ApprovalState, DraftStatus
    draft.approval_state = ApprovalState.AUTO_APPROVED if auto else ApprovalState.APPROVED
    draft.status = DraftStatus.AUTO_APPROVED if auto else DraftStatus.APPROVED
    result = draft
    try:
        from services.outbound.outbound_registry import create_draft as reg_create_draft
        provider_result = reg_create_draft(result.provider_id, result)
        if not provider_result:
            err = "No provider registered for " + result.provider_id
            raise HTTPException(status_code=502, detail=err)
        if not provider_result.external_draft_id:
            err = "Provider created draft but returned no external_draft_id"
            raise HTTPException(status_code=502, detail=err)
        updated = provider_result
        updated.status = result.status
        updated.approval_state = result.approval_state
        from services.workspace_state import persist_draft_update_awaited
        if not await persist_draft_update_awaited(
            owner_id, draft_id, {"status": "approved"}, workspace_id=ws_id,
        ):
            raise HTTPException(status_code=503, detail="Provider draft was created but canonical Draft persistence failed")
        if not await outbound_service.persist_outbound_projection(owner_id, ws_id, updated or result, change_summary="provider draft created"):
            raise HTTPException(status_code=503, detail="Provider draft projection persistence failed")
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
        publish(session_token, WMEventType.DRAFT_FAILED, {
            "draft_id": draft_id,
            "error": str(e),
        }, actor="system")
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/web/session/{session_token}/outbound/drafts/{draft_id}/reject")
async def outbound_reject_draft(session_token: str, draft_id: str, request: Request = None):
    if request is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    session_token = identity_dependencies.web_session_token(request)
    owner_id, ws_id, _canonical, draft = await outbound_service.require_canonical_outbound_draft(request, session_token, draft_id)
    from services.outbound.outbound_models import ApprovalState, DraftStatus
    draft.approval_state = ApprovalState.REJECTED
    draft.status = DraftStatus.REJECTED
    result = draft
    from services.workspace_state import persist_draft_update_awaited
    if not await persist_draft_update_awaited(owner_id, draft_id, {"status": "rejected"}, workspace_id=ws_id):
        raise HTTPException(status_code=503, detail="Canonical Draft persistence failed")
    if not await outbound_service.persist_outbound_projection(
        owner_id, ws_id, result, change_summary="rejected",
    ):
        raise HTTPException(status_code=503, detail="Draft rejection projection persistence failed")
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
    if request is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    ws_id = await workspace_access.resolve_legacy_workspace_id(request, owner_id)
    pending = [
        draft for draft in _workspace_drafts(owner_id, session_token, workspace_id=ws_id)
        if str(draft.get("status") or "") in ("draft", "pending_approval")
    ]
    if not pending:
        return {"ok": True, "total": 0, "created": 0, "failed": 0, "results": []}
    from services.outbound.outbound_registry import create_draft as reg_create_draft
    results = []
    for canonical in pending:
        draft_id = str(canonical.get("id") or "")
        try:
            _owner, _workspace, _canonical, draft = await outbound_service.require_canonical_outbound_draft(
                request, session_token, draft_id,
            )
            from services.outbound.outbound_models import ApprovalState, DraftStatus
            draft.approval_state = ApprovalState.AUTO_APPROVED if payload.auto else ApprovalState.APPROVED
            draft.status = DraftStatus.AUTO_APPROVED if payload.auto else DraftStatus.APPROVED
            provider_result = reg_create_draft(draft.provider_id, draft)
            if not provider_result or not provider_result.external_draft_id:
                results.append({"draft_id": draft.id, "ok": False, "error": "No provider or no external_draft_id"})
            else:
                updated = provider_result
                updated.status = draft.status
                updated.approval_state = draft.approval_state
                from services.workspace_state import persist_draft_update_awaited
                if not await persist_draft_update_awaited(
                    owner_id, draft.id, {"status": "approved"}, workspace_id=ws_id,
                ):
                    raise RuntimeError("canonical Draft persistence failed")
                if not await outbound_service.persist_outbound_projection(owner_id, ws_id, updated or draft, change_summary="provider draft created"):
                    raise RuntimeError("Provider draft projection persistence failed")
                results.append({"draft_id": draft.id, "ok": True})
        except Exception as e:
            results.append({"draft_id": draft_id, "ok": False, "error": str(e)})
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
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    ws = await workspace_access.resolve_legacy_workspace_id(request, owner_id)
    if provider_id and not outbound_service.provider_record_owned_by(provider_id, owner_id):
        raise HTTPException(status_code=404, detail="Provider not found")
    from services.persistence.launch.communication_persistence import list_outbound_history
    durable = await asyncio.to_thread(list_outbound_history, ws, provider_id, 100)

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

    return {"ok": True, "history": [_hist_dict(h) for h in durable]}


@app.get("/api/web/session/{session_token}/outbound/events")
async def outbound_events_endpoint(session_token: str, request: Request, provider_id: str = "", after: int = 0):
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    if provider_id and not outbound_service.provider_owned_by(provider_id, owner_id):
        raise HTTPException(status_code=404, detail="Provider not found")
    events = [
        event for event in get_outbound_events(provider_id=provider_id, after_sequence=after)
        if outbound_service.provider_owned_by(event.provider_id, owner_id)
    ]
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
async def outbound_draft_versions(session_token: str, draft_id: str, request: Request):
    session_token = identity_dependencies.web_session_token(request)
    _owner_id, _workspace_id, canonical, _draft = await outbound_service.require_canonical_outbound_draft(
        request, session_token, draft_id,
    )
    versions = list((canonical.get("metadata") or {}).get("outbound_versions") or [])
    return {"ok": True, "versions": [
        {"draft_id": draft_id, **version} for version in versions
    ]}


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
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
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
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    return await _strategic_service().refresh(owner_id)


@app.get("/api/web/session/{session_token}/strategic-updates/{update_id}/actions")
async def list_strategic_actions(session_token: str, update_id: str, request: Request):
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    actions = await _strategic_action_service().list_actions(owner_id, update_id)
    return {"ok": True, "actions": actions}


@app.post("/api/web/session/{session_token}/strategic-updates/{update_id}/actions")
async def propose_strategic_action(
    session_token: str, update_id: str, request: Request, payload: dict = None,
):
    session_token = identity_dependencies.web_session_token(request)
    from services.strategic.actions import StrategicActionError
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    action_type = str((payload or {}).get("action_type") or "").strip()
    try:
        action = await _strategic_action_service().propose(owner_id, update_id, action_type)
    except StrategicActionError as error:
        raise _strategic_action_http_error(error)
    return {"ok": True, "action": action}


@app.get("/api/web/session/{session_token}/strategic-updates/{update_id}")
async def get_strategic_update(session_token: str, update_id: str, request: Request):
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
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
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    return {"ok": True, "action": await _action_route_call("approve", owner_id, action_id)}


@app.post("/api/web/session/{session_token}/strategic-actions/{action_id}/dismiss")
async def dismiss_strategic_action(session_token: str, action_id: str, request: Request):
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    return {"ok": True, "action": await _action_route_call("dismiss", owner_id, action_id)}


@app.post("/api/web/session/{session_token}/strategic-actions/{action_id}/refine")
async def refine_strategic_action(
    session_token: str, action_id: str, request: Request, payload: dict = None,
):
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    changes = (payload or {}).get("changes") if isinstance(payload, dict) else {}
    return {"ok": True, "action": await _action_route_call("refine", owner_id, action_id, changes or {})}


@app.post("/api/web/session/{session_token}/strategic-actions/{action_id}/execute")
async def execute_strategic_action(session_token: str, action_id: str, request: Request):
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    return {"ok": True, "action": await _action_route_call("execute", owner_id, action_id)}


@app.delete("/api/web/session/{session_token}/strategic-updates/{update_id}")
async def archive_strategic_update(session_token: str, update_id: str, request: Request):
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    update = await _strategic_service().archive_update(owner_id, update_id)
    if update is None:
        raise HTTPException(status_code=404, detail="Strategic Update not found")
    return {"ok": True, "update": update}


# ── Campaign Endpoints ──


def _copilot_tool_failure_reason(tool_name: str) -> str:
    """Return a stable user-facing failure without leaking driver details."""
    return f"{tool_name} could not be completed. Please try again."


def _workspace_drafts(user_id: str, session_token: str = "", workspace_id: str = "") -> list[dict[str, Any]]:
    from services.workspace_state import load_drafts_only
    return load_drafts_only(user_id, workspace_id=workspace_id)


@app.post("/api/web/session/{session_token}/campaigns/{campaign_id}/generate-strategy", status_code=202)
async def generate_campaign_strategy(session_token: str, campaign_id: str, payload: RegenerateStrategyRequest | None, request: Request):
    session_token = identity_dependencies.web_session_token(request)
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
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    workspace_id = await workspace_access.resolve_legacy_workspace_id(request, owner_id)
    campaigns = load_campaigns(owner_id, workspace_id=workspace_id)
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

    job_id, status = await campaign_service.enqueue_strategy_job(session_token, owner_id, campaign_id, objective, target, workspace_id=workspace_id)
    return {"ok": True, "job_id": job_id, "status": status}



@app.get("/api/web/session/{session_token}/campaigns/{campaign_id}/strategy-jobs/{job_id}")
async def strategy_job_status(session_token: str, campaign_id: str, job_id: str, request: Request):
    """Poll endpoint for a background strategy generation job.

    PR-3F: when the in-memory record is gone (process restart) the durable
    ``settings.strategy_job`` record is reconciled lazily — a stale
    queued/running entry becomes an explicit FAILED with an actionable
    message instead of leaving the client polling forever."""
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    workspace_id = await workspace_access.resolve_legacy_workspace_id(request, owner_id)
    from services.job_engine import job_manager
    job = await asyncio.to_thread(job_manager.get_job, job_id)
    if not job or job.get("type") != "strategy" or job.get("campaign_id") != campaign_id or job.get("workspace_id") != workspace_id or job.get("user_id") != owner_id:
        raise HTTPException(status_code=404, detail="Strategy job not found")
    return {
        "job_id": job_id,
        "status": job.get("status"),
        "strategy": (job.get("result") or {}).get("strategy"),
        "error": job.get("error_message"),
    }


@app.get("/api/web/session/{session_token}/campaigns/{campaign_id}/drafts")
async def list_campaign_drafts(session_token: str, campaign_id: str, request: Request):
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    workspace_id = await workspace_access.resolve_legacy_workspace_id(request, owner_id)
    all_drafts = _workspace_drafts(owner_id, session_token, workspace_id=workspace_id)
    filtered = [d for d in all_drafts if d.get("campaign_id") == campaign_id]
    return {"ok": True, "drafts": filtered}


@app.post("/api/web/session/{session_token}/campaigns/{campaign_id}/generate-drafts", status_code=202)
async def generate_campaign_drafts(session_token: str, campaign_id: str, request: Request):
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    workspace_id = await workspace_access.resolve_legacy_workspace_id(request, owner_id)
    from services.workspace_state import load_campaign_state
    target = await asyncio.to_thread(load_campaign_state, owner_id, campaign_id, workspace_id=workspace_id)
    if not target:
        raise HTTPException(status_code=404, detail="Campaign not found")

    active_job = await draft_service.active_draft_batch(owner_id, workspace_id, campaign_id)
    if active_job:
        return {"ok": True, "batch_id": active_job["batch_id"], "total": active_job["total"]}
    generation = target.get("generation")
    generation = generation if isinstance(generation, dict) else {}
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

    batch = await draft_service.schedule_campaign_draft_batch(
        session_token, owner_id, workspace_id, leads, campaign_id,
    )
    batch_id, total = batch["batch_id"], batch["total"]
    target["updated_at"] = datetime.now(timezone.utc).isoformat()
    publish(session_token, WMEventType.CAMPAIGN_UPDATED, {
        "campaign_id": campaign_id,
        "generation": {"batch_id": batch_id, "total": total, "status": "processing"},
        "lead_count": total,
    }, actor="user")
    return {"ok": True, "batch_id": batch_id, "total": total}


@app.get("/api/web/session/{session_token}/campaigns/{campaign_id}/generation-status")
async def campaign_generation_status(session_token: str, campaign_id: str, request: Request):
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    workspace_id = await workspace_access.resolve_legacy_workspace_id(request, owner_id)
    active_job = await draft_service.active_draft_batch(owner_id, workspace_id, campaign_id)
    if active_job:
        status = await draft_service.draft_batch_status(owner_id, workspace_id, active_job["batch_id"])
        if status:
            return {
                "ok": True,
                "active": True,
                "status": "processing",
                "total": status["total"],
                "completed": status["completed"],
                "batch_id": status["batch_id"],
            }

    campaigns = load_campaigns(owner_id, workspace_id=workspace_id)
    target = next((c for c in campaigns if c.get("id") == campaign_id), None)
    if not target:
        return {
            "ok": True, "active": False, "status": "unknown", "jobs": [],
        }

    generation = target.get("generation")
    generation = generation if isinstance(generation, dict) else {}

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
    from services.discovery.service import DiscoveryJobLifecycleError, create_search_run

    try:
        result = await create_search_run(
            user_id,
            query,
            on_update=publish_job_update,
        )
    except DiscoveryJobLifecycleError:
        result = None
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


@app.get("/api/web/session/{session_token}/export-csv")
async def export_csv(session_token: str, request: Request = None):
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    selected_workspace = await workspace_access.resolve_selected_workspace_context(request, owner_id)
    from services.workspace_state import load_drafts_only
    drafts = await asyncio.to_thread(
        load_drafts_only,
        owner_id,
        workspace_id=selected_workspace.workspace_id,
    )
    leads: list[dict] = []
    for d in drafts:
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
    session_token = identity_dependencies.web_session_token(request)
    from services.conversations.compatibility import ensure_workflow_session, get_web_session
    from services.supabase import log_conversation

    user = get_web_session(session_token)
    if user is None:
        raise HTTPException(status_code=404, detail="Session not found")

    engine = ConversationEngine()
    workflow_session_id = ensure_workflow_session(
        user_id=user["id"],
        channel="web",
        session_key=session_token,
    )
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
                log_conversation(user["id"], "assistant", text)

    publish(session_token, WMEventType.LEAD_SELECTED, {
        "lead_index": payload.index,
        "lead_name": result.get("messages", [{}])[0].get("lead_name", ""),
    }, actor="user")
    return {"ok": True, "messages": result.get("messages", [])}


class PreviewLeadRequest(BaseModel):
    index: int


@app.post("/api/web/session/{session_token}/preview-lead")
async def preview_lead_endpoint(session_token: str, payload: PreviewLeadRequest, request: Request = None):
    session_token = identity_dependencies.web_session_token(request)
    from services.conversations.compatibility import get_web_session

    user = get_web_session(session_token)
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


@app.get("/api/web/session/{session_token}/gmail")
async def get_web_gmail_status(session_token: str, request: Request = None):
    session_token = identity_dependencies.web_session_token(request)
    # PR-2B: only user_id + gmail_connected are used — cached identity.
    summary = await identity_dependencies.cached_web_session_identity(session_token)
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
    """Gmail-connect callback for the web application.

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
    channel = "web"

    try:
        tokens = await asyncio.to_thread(exchange_code_for_tokens, code)
        saved_user = await asyncio.to_thread(
            save_google_tokens,
            user_id,
            email=tokens.get("email", ""),
            telegram_chat_id=None,
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


@app.post("/api/web/session/{session_token}/plan")
async def plan_workflow_endpoint(session_token: str, payload: PlanningInput, request: Request = None):
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    selected_workspace = await workspace_access.resolve_selected_workspace_context(request, owner_id)
    workspace_id = selected_workspace.workspace_id
    from services.workspace_state import load_drafts_only
    campaigns, drafts = await asyncio.gather(
        asyncio.to_thread(load_campaigns, owner_id, workspace_id=workspace_id),
        asyncio.to_thread(load_drafts_only, owner_id, workspace_id=workspace_id),
    )
    total_leads = sum(c.get("lead_count", 0) or 0 for c in campaigns)
    snapshot = await asyncio.to_thread(
        build_snapshot, session_token, campaigns, drafts, total_leads, user_id=owner_id,
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
    session_token = identity_dependencies.web_session_token(request)
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
    caller_token = identity_dependencies.web_session_token(request) if request is not None else session_token
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
    session_token = identity_dependencies.web_session_token(request)
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
    session_token = identity_dependencies.web_session_token(request)
    workflows = get_all_runtimes(session_token)
    return {
        "ok": True,
        "workflows": [wf.summary() for wf in workflows],
        "active": [calculate_progress(wf) for wf in get_active_runtimes(session_token)],
    }


@app.get("/api/web/session/{session_token}/workflows/history")
async def workflow_history(session_token: str, status: str | None = None, limit: int = 50, request: Request = None):
    session_token = identity_dependencies.web_session_token(request)
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
    session_token = identity_dependencies.web_session_token(request)
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
    session_token = identity_dependencies.web_session_token(request)
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
    session_token = identity_dependencies.web_session_token(request)
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


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "10000"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


# ── PR-3D: SSE event gateway ─────────────────────────────────────────────

_SSE_HEARTBEAT_SECONDS = 15.0
_SSE_REVOCATION_CHECK_SECONDS = 30.0


@app.get("/api/events/stream")
async def events_stream(request: Request):
    """User-scoped Server-Sent Events gateway (PR-3D).

    Security:
      - identity resolved server-side from the Authorization header via the
        SAME resolver every session endpoint uses; the subscription target is
        ALWAYS the resolved owner — a client can never subscribe to another
        user's channel.
      - the stream self-terminates if the bearer stops resolving (revoked /
        expired), so revoked sessions cannot receive events indefinitely.

    Degraded mode:
      - Redis unavailable ⇒ stream stays alive with heartbeats only
        (REST + client cache remain fully functional).
    """
    from services.events_bus import event_bus

    try:
        owner_id, token = await identity_dependencies.resolve_web_session(request)
    except HTTPException:
        raise
    if not owner_id or not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    pubsub = await event_bus.subscribe_user(owner_id)

    async def generator():
        nonlocal pubsub
        import json as _json
        import time as _time

        log.info("[sse] stream opened user=%s subscribed=%s", owner_id[:8], pubsub is not None)
        yield "retry: 5000\n\n"
        yield f"data: {_json.dumps({'type': 'hello', 'user': owner_id[:8]})}\n\n"

        last_heartbeat = _time.monotonic()
        last_revocation_check = _time.monotonic()
        still_valid = True
        try:
            while True:
                now = _time.monotonic()
                got_event = False
                if pubsub is not None:
                    try:
                        message = await asyncio.wait_for(pubsub.get_message(ignore_subscribe_messages=True), timeout=0.5)
                        if message is not None and message.get("type") == "message":
                            got_event = True
                            raw = message.get("data", "")
                            # Payload was scrubbed at the producer; forward verbatim.
                            yield f"data: {raw}\n\n"
                    except asyncio.TimeoutError:
                        pass
                    except Exception as error:
                        log.warning("[sse] pubsub read failed error_type=%s", type(error).__name__)
                        # Pub/sub broke (e.g. Redis died) — drop the
                        # subscription but keep heartbeats; client keeps
                        # working over REST.
                        try:
                            await pubsub.aclose()
                        except Exception:
                            pass
                        pubsub = None

                now = _time.monotonic()
                if not got_event and now - last_heartbeat >= _SSE_HEARTBEAT_SECONDS:
                    last_heartbeat = now
                    yield ": heartbeat\n\n"

                if now - last_revocation_check >= _SSE_REVOCATION_CHECK_SECONDS:
                    last_revocation_check = now
                    identity = await identity_dependencies.cached_web_session_identity(token)
                    if identity is None or identity.get("user_id") != owner_id:
                        log.info("[sse] stream closing: identity no longer valid user=%s", owner_id[:8])
                        still_valid = False
                        break

                # With Redis unavailable there is no event source to poll.
                # Wake at the same cadence as the pub/sub wait instead of
                # spinning 20 times per second for every degraded stream.
                await asyncio.sleep(0.5 if pubsub is None else 0.05)
        except asyncio.CancelledError:
            pass
        finally:
            if pubsub is not None:
                try:
                    await pubsub.aclose()
                except Exception:
                    pass
            log.info("[sse] stream closed user=%s reason=%s",
                     owner_id[:8], "auth" if not still_valid else "client")

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
