import asyncio
import hashlib
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
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field
import services.identity.dependencies as identity_dependencies
import services.workspace.access as workspace_access
from services.workspace import context as workspace_context_service
from services.identity.api import router as auth_router
from services.onboarding.api import router as onboarding_router
from services.organizations.api import router as organizations_router, _build_org_deps, register_deps as register_org_deps
from services.billing.api import router as billing_router, _build_billing_deps, register_deps as register_billing_deps, create_billing_provider
from services.billing.config import BillingConfig
from services.billing.api import register_provider_and_config as _register_billing_provider_config
from services.capabilities.api import router as capabilities_router, register_deps as register_capability_deps, CapabilityDeps
from services.knowledge.api import router as knowledge_router
from services.mission_control.api import router as mission_control_router
from services.strategic.api import router as strategic_router
from services.discovery.api import router as discovery_router
from services.campaigns.api import router as campaigns_router
from services.drafts.api import router as drafts_router
from services.outbound.api import router as outbound_router
from services.communication.api import router as communication_router
from services.events.api import router as events_router
from services.export.api import router as export_router
from services.workspace.api import router as workspace_router
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
from services.workflows.planner import plan_workflow
from services.workflows.models import PlanningInput
from services.workflows.executor import execute as execute_workflow, approve as approve_workflow, pause as pause_workflow, resume as resume_workflow, cancel as cancel_workflow
from services.workflows.runtime import get_runtime, get_active_runtimes, get_all_runtimes, get_history as get_workflow_history
from services.workflows.progress import calculate_progress
from services.workflows.events import get_events as get_workflow_events, get_latest_sequence
from services.workflows.models import WorkflowPlan
from services.conversation_models import ConversationMessage
from services.communication import provider_startup
from services.communication.reply_simulator import maybe_schedule as simulate_reply
from services.events_bus import publish_draft_event
from services.reply_intelligence import analyze_message
from services.conversation_memory import memory_store, create_or_update_memory
from services.followup_reasoner import recommend_followup
from services.reply_summary import generate_summary
from services.conversation_timeline import get_events as get_conversation_events
from services.conversation_models import FollowupAction, BuyingSignal, SignalStrength, ConversationStage
from services.buying_signal import detect_signals
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
    provider_startup.initialize_gmail_runtime()

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
app.include_router(strategic_router)
app.include_router(mission_control_router)
app.include_router(discovery_router)
app.include_router(campaigns_router)
app.include_router(drafts_router)
app.include_router(outbound_router)
app.include_router(communication_router)
app.include_router(events_router)
app.include_router(export_router)
app.include_router(workspace_router)
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
            from services.workspace.state import ensure_workspace
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
        from services.copilot.memory import CopilotMemoryService, merge_turn_history
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
            workspace_context_service.build_workspace_context,
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
        from services.copilot.tools import execute_copilot_tool, select_copilot_tool
        from services.copilot_orchestrator import execute_copilot_plan, has_multi_step_plan

        async def execute_at_copilot_boundary(
            requested_tool_name: str,
            requested_decision: dict[str, Any],
        ) -> dict[str, Any]:
            """Run tools through the authenticated, durable Phase 6 boundary."""
            from services.copilot.tools import COPILOT_TOOLS

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
            from services.copilot.executions import CopilotExecutionService
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
            from services.copilot.tools import (
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
            from services.copilot.tools import (
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


class LeadDecisionRequest(BaseModel):
    lead: dict
    approved: bool


class AnalyzeCampaignsRequest(BaseModel):
    leads: list[dict]
    campaign_id: str | None = None


class GenerateDraftsRequest(BaseModel):
    campaign_id: str


class SelectLeadRequest(BaseModel):
    index: int


@app.post("/api/web/session/{session_token}/analyze-campaigns")
async def analyze_campaigns_endpoint(session_token: str, payload: AnalyzeCampaignsRequest):
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


@app.get("/api/web/session/{session_token}/workspace-context")
async def dev_workspace_context(session_token: str, conversation_id: str = "", request: Request = None):
    session_token = identity_dependencies.web_session_token(request)
    """Returns workspace context with provider info for the dev providers page."""
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    selected_workspace = await workspace_access.resolve_selected_workspace_context(request, owner_id)
    ctx = await asyncio.to_thread(
        workspace_context_service.build_workspace_context,
        session_token,
        current_page="Mission Control",
        conversation_id=conversation_id or None,
        user_id=owner_id,
        workspace_id=selected_workspace.workspace_id,
    )
    return ctx


# ── Provider Endpoints ──


def _copilot_tool_failure_reason(tool_name: str) -> str:
    """Return a stable user-facing failure without leaking driver details."""
    return f"{tool_name} could not be completed. Please try again."


def _workspace_drafts(user_id: str, session_token: str = "", workspace_id: str = "") -> list[dict[str, Any]]:
    from services.workspace.state import load_drafts_only
    return load_drafts_only(user_id, workspace_id=workspace_id)


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


@app.post("/api/web/session/{session_token}/select-lead")
async def select_lead_endpoint(session_token: str, payload: SelectLeadRequest, request: Request = None):
    session_token = identity_dependencies.web_session_token(request)
    from services.conversations.compatibility import ensure_workflow_session, get_web_session

    user = get_web_session(session_token)
    if user is None:
        raise HTTPException(status_code=404, detail="Session not found")

    workflow_session_id = ensure_workflow_session(
        user_id=user["id"],
        channel="web",
        session_key=session_token,
    )
    result = conversation_service.select_legacy_workflow_lead_and_draft(
        user_id=user["id"],
        lead_index=payload.index,
        workflow_session_id=workflow_session_id,
        session_token=session_token,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("messages", [{}])[0].get("text", "Selection failed"))

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

    result = conversation_service.preview_legacy_workflow_lead_intelligence(
        user_id=user["id"],
        lead_index=payload.index,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Preview failed"))

    return {"ok": True, "lead_intelligence": result.get("lead_intelligence")}


@app.post("/api/web/session/{session_token}/plan")
async def plan_workflow_endpoint(session_token: str, payload: PlanningInput, request: Request = None):
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    selected_workspace = await workspace_access.resolve_selected_workspace_context(request, owner_id)
    workspace_id = selected_workspace.workspace_id
    from services.workspace.state import load_drafts_only
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


def _require_workflow_owned(workflow_id: str, request: Request, session_token: str = ""):
    """Return the workflow runtime only when it belongs to the caller's session.

    Fail-closed (PR10.8.3.2): workflows are session-scoped (RuntimeEntry holds
    the creating session_token). A user may only read/mutate their own workflow.
    """
    from services.workflows.runtime import get_runtime
    runtime = get_runtime(workflow_id)
    if runtime is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    caller_token = identity_dependencies.web_session_token(request) if request is not None else session_token
    if not caller_token or runtime.session_token != caller_token:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return runtime


@app.get("/api/web/session/{session_token}/workflows/{workflow_id}")
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
