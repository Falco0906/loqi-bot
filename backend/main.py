import asyncio
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
from services.workflows.api import router as workflows_router
import services.outbound.service as outbound_service
from services.conversations.api import engine, router as conversations_router
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
from services.operations.diagnostics import get_build_metadata
from app import lifespan as app_lifespan
from services.learning.behavior_tracker import get_tracker as _get_behavior_tracker
from services.learning.feedback_interpreter import FeedbackInterpreter as _FeedbackInterpreter
from services.draft_intelligence import analyze_draft as analyze_draft_intelligence
from services.strategic_intelligence_api import router as strategic_intelligence_router
from services.rewrite_engine import execute_rewrite
from services.draft_comparison import compare_versions
from services.communication import provider_startup
from services.communication.reply_simulator import maybe_schedule as simulate_reply
from services.events_bus import publish_draft_event
from services.conversation_intelligence.legacy_models import FollowupAction, BuyingSignal, SignalStrength
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
from services.platform.logging_setup import configure_logging
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

    from services.platform.lifecycle import set_ready

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
app.include_router(workflows_router)

# ── Wire Organization Platform services ──
_org_deps = _build_org_deps()
register_org_deps(_org_deps)

# ── Wire Organization Service into Onboarding ──
from services.identity.api import get_auth_user_service
from services.onboarding.api import set_onboarding_service
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
    from services.platform.rate_limit import classify_rate_limit, rate_limiter, resolve_rate_limit_identity

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


@app.get("/", response_class=PlainTextResponse)
def read_root():
    return "Loqi backend running"

class LeadDecisionRequest(BaseModel):
    lead: dict
    approved: bool


class GenerateDraftsRequest(BaseModel):
    campaign_id: str


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "10000"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
