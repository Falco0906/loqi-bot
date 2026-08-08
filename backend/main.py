import asyncio
import csv
import io
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from pydantic import BaseModel
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
    SessionRevokedException,
)
from services.identity.metrics import get_metrics
from services.identity.schemas import ErrorResponse
from starlette.responses import JSONResponse
from services.conversation_engine import ConversationEngine, _message
from services.google_auth import exchange_code_for_tokens
from services.supabase import save_google_tokens, test_supabase_connection
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
    record_campaign_ready,
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
log = logging.getLogger("loqi")

request_id_var: ContextVar[str] = ContextVar("request_id")

@asynccontextmanager
async def lifespan(app: FastAPI):
    set_startup_time()
    log_config_warnings()
    startup_diagnostics(app)
    register_workflows()
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

    try:
        from services.memory.consolidation import consolidate_memories
        from services.memory.memory_store import get_memory_provider
        result = asyncio.create_task(consolidate_memories(get_memory_provider()))
        log.info("Memory consolidation startup task created")
    except Exception as e:
        log.warning("Memory consolidation startup failed: %s", e)

    _start_outbound_scheduler()
    try:
        recovered = _reconcile_stale_generating_campaigns()
        if recovered:
            log.info("Reconciled %d interrupted draft generation(s) after restart", recovered)
    except Exception as e:
        log.warning("Draft generation recovery sweep failed: %s", e)

    # Backfill canonical launch tables from the event log (idempotent).
    try:
        from services.persistence.launch import backfill_all
        asyncio.create_task(asyncio.to_thread(backfill_all))
    except Exception as e:
        log.warning("Canonical backfill startup task failed: %s", e)

    yield

app = FastAPI(lifespan=lifespan)
app.add_middleware(RequestLoggingMiddleware)
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
            message=str(exc),
            request_id=req_id,
        ).model_dump(),
    )


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
    """Resolve a campaign left in 'generating' against the durable draft stream.

    Callers must verify no live batch task exists for this campaign. Moves the
    campaign to draft_review when drafts were persisted for the current batch,
    otherwise back to lead_selection so generation can be retried. Uses only
    the durable workflow event stream; never touches authentication.
    """
    if campaign.get("status") != "generating":
        return campaign

    generation = campaign.get("generation")
    generation = generation if isinstance(generation, dict) else {}
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
        campaign["status"] = "draft_review"
        updates = {
            "status": "draft_review",
            "generation": {
                **generation,
                "status": "completed",
                "total": generation.get("total", len(batch_drafts)),
                "completed": len(batch_drafts),
                "finished_at": now,
            },
        }
    else:
        campaign["status"] = "lead_selection"
        updates = {
            "status": "lead_selection",
            "generation": {
                **generation,
                "status": "failed",
                "error": "Draft generation was interrupted before any draft was persisted",
                "finished_at": now,
            },
        }

    if persist_campaign_update(owner_id, campaign.get("id", ""), updates):
        campaign["updated_at"] = now
    return campaign


def _reconcile_stale_generating_campaigns() -> int:
    """One-shot startup recovery for draft batches interrupted by a restart.

    After a restart no batch tasks exist, so any campaign still in 'generating'
    reflects an interrupted batch. Reconcile every one from the durable
    workflow event stream. Returns the number of campaigns reconciled.
    """
    from services.supabase import get_supabase_client
    from services.workspace_state import load_workspace_state

    client = get_supabase_client()
    if client is None:
        return 0
    try:
        sessions = (
            client.table("workflow_sessions")
            .select("user_id")
            .eq("channel", "workspace")
            .execute()
        )
    except Exception as error:
        log.warning("[recovery] workflow session scan failed: %s", error)
        return 0
    user_ids = {
        row.get("user_id")
        for row in getattr(sessions, "data", None) or []
        if row.get("user_id")
    }

    recovered = 0
    for user_id in user_ids:
        try:
            state = load_workspace_state(user_id)
            for campaign in state["campaigns"]:
                if campaign.get("status") == "generating":
                    _reconcile_campaign_generation(user_id, campaign)
                    recovered += 1
        except Exception as error:
            log.warning("[recovery] reconcile failed for user %s: %s", user_id, error)
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

    providers = communication_store.list_providers()
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

    if conversation_id:
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
    )
    outbound_register_instance(comm_provider_id, outbound)
    log.info("[outbound] Registered GmailOutboundProvider instance for %s", comm_provider_id)


def _save_provider_credentials(provider_id: str, session_token: str) -> None:
    """Persist provider credentials to Supabase for startup recovery."""
    from services.supabase import save_provider_credentials
    comm_instance = get_provider(provider_id)
    if not comm_instance:
        log.warning("[startup] No comm instance found for %s", provider_id)
        return
    access_token = getattr(comm_instance, '_access_token', '')
    refresh_token = getattr(comm_instance, '_refresh_token', '')
    client_id = getattr(comm_instance, '_client_id', '')
    client_secret = getattr(comm_instance, '_client_secret', '')
    token_expiry = getattr(comm_instance, '_token_expiry', 0.0)
    email = getattr(comm_instance, '_mailbox_email', '')
    if not access_token and not refresh_token:
        log.warning("[startup] No tokens to persist for provider %s", provider_id)
        return
    import time
    expiry_iso = datetime.fromtimestamp(token_expiry, tz=timezone.utc).isoformat() if token_expiry else ""
    save_provider_credentials(
        session_token, provider_id,
        access_token=access_token,
        refresh_token=refresh_token,
        token_expiry=expiry_iso,
        email=email,
        client_id=client_id,
        client_secret=client_secret,
    )


def _restore_providers_on_startup() -> None:
    """On startup, load saved provider credentials from Supabase and restore instances.
    Refreshes tokens if expired.
    """
    log.info("[startup] Attempting provider restoration from Supabase")
    from services.supabase import load_all_provider_credentials
    from services.outbound.gmail_outbound import GmailOutboundProvider
    from services.communication.gmail_provider import GmailProvider
    from services.google_auth import refresh_access_token
    records = load_all_provider_credentials()
    if not records:
        log.info("[startup] No saved provider credentials found")
        return
    restored = 0
    for row in records:
        try:
            user_id = row.get("id", "")
            provider_id = row.get("google_provider_id", "") or str(uuid.uuid4())
            refresh_token = row.get("google_refresh_token", "")
            access_token = row.get("google_access_token", "")
            email = row.get("email", "")
            client_id = row.get("google_client_id", "") or os.getenv("GOOGLE_CLIENT_ID", "")
            client_secret = row.get("google_client_secret", "") or os.getenv("GOOGLE_CLIENT_SECRET", "")
            token_expiry_str = row.get("token_expiry", "")
            token_expiry = 0.0
            if token_expiry_str:
                try:
                    token_expiry = datetime.fromisoformat(token_expiry_str.replace("Z", "+00:00")).timestamp()
                except Exception:
                    token_expiry = 0.0
            if not refresh_token:
                log.warning("[startup] No refresh_token for provider %s, skipping", provider_id[:12])
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
                except Exception as e:
                    log.warning("[startup] Token refresh failed for provider %s: %s", provider_id[:12], e)
                    continue
            comm_provider = GmailProvider()
            from services.communication.provider_models import ProviderType
            comm_record = comm_provider.connect(
                auth_token=access_token,
                user_id=user_id,
                email=email,
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
            )
            outbound_register_instance(comm_record.id, outbound)
            log.info("[startup] Restored provider %s (%s)", comm_record.id[:12], email)
            restored += 1
        except Exception as e:
            log.warning("[startup] Failed to restore provider: %s", e)
    log.info("[startup] Provider restoration complete: %d restored", restored)


def _get_outbound_provider_for_draft(outbound_draft) -> str:
    """Get a working outbound provider ID for a draft.
    Falls back to the first registered Gmail provider if the draft's provider_id is not found.
    """
    if outbound_draft and outbound_draft.provider_id and get_outbound_provider(outbound_draft.provider_id):
        return outbound_draft.provider_id
    found = _find_outbound_gmail_provider_id()
    if found:
        if outbound_draft:
            outbound_draft.provider_id = found
            from services.outbound.draft_store import draft_store as outbound_draft_store
            outbound_draft_store.update(outbound_draft)
        return found
    return outbound_draft.provider_id if outbound_draft else ""


def _sync_draft_to_outbound(legacy_draft: dict, session_token: str) -> None:
    """Sync a legacy campaign draft into the outbound DraftStore.
    
    Uses workflow_id to store campaign_id for later lookup.
    Stores lead metadata in the DraftMessage metadata field.
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
    real_provider_id = _find_outbound_gmail_provider_id()
    outbound_draft = DraftMessage(
        id=legacy_draft.get("id", ""),
        provider_id=real_provider_id or "campaign",
        workflow_id=legacy_draft.get("campaign_id", ""),
        subject=legacy_draft.get("subject", ""),
        body=legacy_draft.get("text", ""),
        recipient=Recipient(email=lead_email, name=lead_name),
        sender=Recipient(email="", name=""),
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


async def _process_batch_drafts(
    session_token: str,
    batch_id: str,
    leads: list[dict],
    owner_id: str,
) -> None:
    job = batch_jobs[batch_id]
    loop = asyncio.get_event_loop()

    for i, lead in enumerate(leads):
        job["current_index"] = i
        name = (
            lead.get("name")
            or f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
            or "Unknown"
        )
        job["current_name"] = name

        try:
            workflow_result = await loop.run_in_executor(
                None,
                run_workflow,
                {"type": "draft_message", "lead": lead},
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
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

            from services.workspace_state import persist_draft
            if not persist_draft(owner_id, draft_entry):
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

            _sync_draft_to_outbound(draft_entry, session_token)

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
            persist_campaign_update(owner_id, campaign_id, {
                "status": "lead_selection",
                "generation": generation,
            })
            job["status"] = "failed"
            job["error"] = "No drafts were generated"
            return
        if not persist_campaign_update(owner_id, campaign_id, {
            "status": "draft_review",
            "generation": generation,
        }):
            job["status"] = "failed"
            job["error"] = "Campaign status could not be persisted"
            return
        campaigns = _workspace_campaigns(owner_id, session_token)
        for c in campaigns:
            if c.get("id") == campaign_id:
                c["status"] = "draft_review"
                c["updated_at"] = datetime.now(timezone.utc).isoformat()
                campaign_name = c.get("name")
                break
        publish(session_token, WMEventType.CAMPAIGN_STATUS_CHANGED, {
            "campaign_id": campaign_id,
            "status": "draft_review",
            "previous_status": "researching",
        }, actor="system")
    if campaign_name:
        record_drafts_generated(session_token, campaign_name, job.get("completed", 0))

# ── Logging Middleware ──

@app.middleware("http")
async def log_requests(request: Request, call_next):
    req_id = str(uuid.uuid4())[:8]
    request_id_var.set(req_id)
    start = time.time()
    response = await call_next(request)
    duration = (time.time() - start) * 1000
    log.info(
        "%s %s %s %.0fms %s",
        req_id, request.method, request.url.path, duration, response.status_code,
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


def _start_outbound_scheduler() -> None:
    global _scheduler_task
    try:
        from services.outbound.outbound_scheduler import outbound_scheduler
        _scheduler_task = asyncio.create_task(outbound_scheduler.run())
        log.info("Outbound scheduler started")
    except Exception as e:
        log.warning("Failed to start outbound scheduler: %s", e)
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


@app.get("/", response_class=PlainTextResponse)
def read_root():
    return "Loqi backend running"


# ── Gmail OAuth Endpoints ──


@app.get("/api/auth/gmail/url")
async def gmail_auth_url(request: Request, session_token: str = ""):
    from services.google_auth import get_google_auth_url
    try:
        user_id = ""
        if request.headers.get("authorization", ""):
            from services.identity.api import get_authenticated_user_id
            user_id = await get_authenticated_user_id(request)
        state_subject = user_id or session_token
        state = f"dev_providers:{state_subject}" if state_subject else "dev_providers"
        url = get_google_auth_url(state=state)
        return {"ok": True, "url": url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class GmailCallbackResponse(BaseModel):
    ok: bool
    provider_id: str = ""
    email: str = ""
    error: str = ""


@app.get("/api/auth/gmail/callback")
def gmail_auth_callback(code: str = "", state: str = "", error: str = ""):
    import json
    from services.google_auth import exchange_code_for_tokens, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
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
        tokens = exchange_code_for_tokens(code)
        access_token = tokens.get("access_token", "")
        refresh_token = tokens.get("refresh_token", "")
        email_val = tokens.get("email", "")
        from services.communication.gmail_provider import GmailProvider
        provider = GmailProvider()
        _user_id = "gmail_user"
        if state and ":" in state:
            _parts = state.split(":", 1)
            if len(_parts) == 2 and _parts[1]:
                _user_id = _parts[1]
        provider_record = provider.connect(
            auth_token=access_token,
            user_id=_user_id,
            email=email_val,
            scope=",".join(["https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.send"]),
            refresh_token=refresh_token,
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
        )
        register_instance(provider_record.id, provider)
        _register_outbound_gmail_instance(provider_record.id)
        _save_provider_credentials(provider_record.id, _user_id)
        _register_credential_instance(access_token, refresh_token, email_val)
        ok = True
        provider_id = provider_record.id
    except Exception as e:
        error_msg = str(e)
    payload = json.dumps({"ok": ok, "provider_id": provider_id, "email": email_val, "error": error_msg})
    status_text = "✓ Gmail Connected" if ok else "✗ Gmail Connection Failed"
    html = f"""<!DOCTYPE html>
<html><body style="font-family:sans-serif;background:#0f172a;color:#e2e8f0;padding:40px;text-align:center">
<h2>{status_text}</h2>
<p style="color:#94a3b8">{email_val or error_msg}</p>
<p style="color:#6b7280;font-size:13px">You can close this window.</p>
<script>
if (window.opener) {{
    window.opener.postMessage({{ type: 'gmail-oauth', payload: {payload} }}, '*');
    setTimeout(function() {{ window.close(); }}, 500);
}}
</script>
</body></html>"""
    return HTMLResponse(content=html)


@app.get("/health")
def health():
    db_status = "connected" if test_supabase_connection() else "disconnected"
    return {
        "status": "healthy",
        "version": "v2",
        "uptime": int(time.time() - _start_time),
        "database": db_status,
        "providers": "ready",
    }


@app.post("/webhook")
async def telegram_webhook(request: Request):
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
        if request.headers.get("authorization", ""):
            from services.identity.api import get_authenticated_user_id
            try:
                user_id = await get_authenticated_user_id(request)
            except HTTPException:
                # Failed authentication falls back to an anonymous web
                # session rather than failing the whole bootstrap request.
                user_id = None
        result = await asyncio.to_thread(
            engine.create_web_session,
            display_name=payload.display_name,
            user_id=user_id,
        )
        if user_id:
            from services.workspace_state import ensure_workspace
            await asyncio.to_thread(ensure_workspace, user_id)
        return result
    except ValueError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@app.get("/api/web/session/{session_token}")
async def get_web_session(session_token: str):
    data = engine.get_web_session_summary(session_token)
    if data is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return data


@app.get("/api/web/session/{session_token}/messages")
async def get_web_session_messages(session_token: str):
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
    import time; _t0 = time.time()
    print(f"[TRACE] 1 | ENTERED ENDPOINT | post_web_session_message | +0ms")
    summary = engine.get_web_session_summary(session_token)

    if summary is None:
        user_id = None
        if request.headers.get("authorization", ""):
            from services.identity.api import get_authenticated_user_id
            try:
                user_id = await get_authenticated_user_id(request)
            except HTTPException:
                user_id = None
        created = engine.create_web_session(
            display_name="web-user",
            user_id=user_id,
        )
        if created is None:
            raise HTTPException(status_code=500, detail="Unable to create session")
        summary = engine.get_web_session_summary(created["session_token"])
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
        response_text = generate_copilot_response(
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


class SaveCampaignRequest(BaseModel):
    name: str
    objective: str = ""
    search_query: str = ""
    lead_count: int = 0
    leads: list[dict] | None = None
    strategy: dict | None = None
    status: str = "planning"


class UpdateCampaignRequest(BaseModel):
    name: str | None = None
    objective: str | None = None
    strategy: dict | None = None
    status: str | None = None


class AddCampaignLeadRequest(BaseModel):
    lead: dict


class LeadDecisionRequest(BaseModel):
    lead: dict
    approved: bool


class GenerateDraftsRequest(BaseModel):
    campaign_id: str


class SelectLeadRequest(BaseModel):
    index: int


@app.post("/api/web/session/{session_token}/batch-draft")
async def batch_draft(session_token: str, payload: BatchDraftRequest, request: Request):
    if not payload.leads:
        raise HTTPException(status_code=400, detail="No leads provided")
    batch_id = str(uuid.uuid4())
    total = len(payload.leads)
    _create_batch_job(batch_id, payload.campaign_id, total)
    owner_id = await _workspace_owner(request, session_token)
    _launch_batch_task(session_token, batch_id, payload.leads, owner_id)
    return {"ok": True, "batch_id": batch_id, "total": total}


@app.get("/api/web/session/{session_token}/batch-status/{batch_id}")
async def batch_status(session_token: str, batch_id: str):
    job = batch_jobs.get(batch_id)
    if not job:
        raise HTTPException(status_code=404, detail="Batch not found")
    return {"ok": True, **job}


@app.post("/api/web/session/{session_token}/analyze-campaigns")
async def analyze_campaigns_endpoint(session_token: str, payload: BatchDraftRequest):
    result = analyze_campaigns(payload.leads)
    return result

@app.get("/api/web/session/{session_token}/drafts")
async def list_drafts(session_token: str, request: Request):
    owner_id = await _workspace_owner(request, session_token)
    return {"ok": True, "drafts": _workspace_drafts(owner_id, session_token)}


@app.put("/api/web/session/{session_token}/drafts/{draft_id}")
async def update_draft(session_token: str, draft_id: str, payload: UpdateDraftRequest, request: Request):
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
    owner_id = await _workspace_owner(request, session_token)
    durable_drafts = _workspace_drafts(owner_id, session_token)
    durable_target = next((d for d in durable_drafts if d.get("id") == draft_id), None)
    if durable_target:
        new_status = "approved" if durable_target.get("status") != "approved" else "pending"
        from services.workspace_state import persist_draft_update_awaited
        if not await persist_draft_update_awaited(owner_id, draft_id, {"status": new_status}):
            raise HTTPException(status_code=503, detail="Draft approval could not be persisted")
        durable_target["status"] = new_status
        campaign_id = durable_target.get("campaign_id")
        current_step = None
        if campaign_id:
            campaign_drafts = [d for d in durable_drafts if d.get("campaign_id") == campaign_id]
            all_approved = bool(campaign_drafts) and all(d.get("status") == "approved" for d in campaign_drafts)
            current_step = "sending" if all_approved else "review"
        publish(session_token, WMEventType.DRAFT_APPROVED if new_status == "approved" else WMEventType.DRAFT_UPDATED, {
            "draft_id": draft_id, "campaign_id": campaign_id, "status": new_status,
        }, actor="user")
        return {"ok": True, "draft": durable_target, "current_step": current_step,
                "pending_drafts": sum(1 for d in durable_drafts if d.get("status") == "pending")}

    raise HTTPException(status_code=404, detail="Draft not found in the durable workspace")


@app.post("/api/web/session/{session_token}/drafts/{draft_id}/undo")
async def undo_draft(session_token: str, draft_id: str, request: Request):
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
async def draft_rewrite_history(session_token: str, draft_id: str):
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
async def communication_memory_update(session_token: str, payload: AnalyzeMessageRequest):
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
async def communication_timeline(session_token: str, conversation_id: str):
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
async def dev_workspace_context(session_token: str, conversation_id: str = ""):
    """Returns workspace context with provider info for the dev providers page."""
    ctx = _build_copilot_workspace_context(
        session_token,
        current_page="Mission Control",
        conversation_id=conversation_id or None,
    )
    return ctx


# ── Provider Endpoints ──


class ProviderConnectRequest(BaseModel):
    provider_type: str  # "gmail", "outlook", etc.
    auth_token: str
    email: str = ""
    scope: str = ""


@app.post("/api/web/session/{session_token}/providers/connect")
async def provider_connect(session_token: str, payload: ProviderConnectRequest):
    try:
        ptype = ProviderType(payload.provider_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown provider type: {payload.provider_type}")

    instance = instantiate_provider(ptype)
    if not instance:
        raise HTTPException(status_code=400, detail=f"Provider not registered: {payload.provider_type}")

    provider = instance.connect(
        auth_token=payload.auth_token,
        user_id=session_token,
        email=payload.email,
        scope=payload.scope,
    )
    register_instance(provider.id, instance)
    if ptype == ProviderType.GMAIL:
        _register_outbound_gmail_instance(provider.id)
    publish(session_token, WMEventType.PROVIDER_CONNECTED, {
        "provider_id": provider.id,
        "provider_type": payload.provider_type,
        "email": payload.email,
    }, actor="user")
    return {"ok": True, "provider": provider.model_dump()}


@app.post("/api/web/session/{session_token}/providers/{provider_id}/disconnect")
async def provider_disconnect(session_token: str, provider_id: str):
    success = registry_disconnect(provider_id)
    if not success:
        raise HTTPException(status_code=404, detail="Provider not found or already disconnected")
    publish(session_token, WMEventType.PROVIDER_DISCONNECTED, {
        "provider_id": provider_id,
    }, actor="user")
    return {"ok": True}


@app.get("/api/web/session/{session_token}/providers")
async def provider_list(session_token: str):
    providers = communication_store.get_user_providers(session_token)
    result = []
    for p in providers:
        instance = get_provider(p.id)
        health_val = instance.health().value if instance else p.status.value
        result.append({
            "id": p.id,
            "provider_type": p.provider_type.value,
            "status": health_val,
            "email": p.metadata.get("email", ""),
            "last_sync": p.last_sync,
            "sync_cursor": p.sync_cursor,
            "created_at": p.created_at,
        })
    return {"ok": True, "providers": result}


@app.get("/api/web/session/{session_token}/providers/{provider_id}/health")
async def provider_health(session_token: str, provider_id: str):
    instance = get_provider(provider_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Provider not found")
    status = instance.health()
    provider = communication_store.get_provider(provider_id)
    return {
        "ok": True,
        "provider_id": provider_id,
        "status": status.value,
        "last_sync": provider.last_sync if provider else "",
    }


@app.post("/api/web/session/{session_token}/providers/{provider_id}/sync")
async def provider_sync(session_token: str, provider_id: str, cursor: str = ""):
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
async def provider_status(session_token: str, provider_id: str):
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
async def provider_threads(session_token: str, provider_id: str):
    """List all tracked thread mappings for a provider."""
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
async def provider_messages(session_token: str, provider_id: str):
    """Get message count, mailbox info, and recent activity for a provider."""
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
async def provider_events_endpoint(session_token: str, provider_id: str = "", after: int = 0):
    events = get_provider_events(provider_id=provider_id, after_sequence=after)
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
async def outbound_delete_draft(session_token: str, draft_id: str, provider_id: str = ""):
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


@app.post("/api/web/session/{session_token}/drafts/{draft_id}/send")
async def send_draft(session_token: str, draft_id: str):
    from services.outbound.draft_store import draft_store as outbound_draft_store
    outbound_draft = outbound_draft_store.get(draft_id)
    if not outbound_draft:
        legacy_drafts = draft_store.get(session_token, [])
        legacy = next((d for d in legacy_drafts if d.get("id") == draft_id), None)
        if not legacy:
            raise HTTPException(status_code=404, detail="Draft not found in any store")
        _sync_draft_to_outbound(legacy, session_token)
        outbound_draft = outbound_draft_store.get(draft_id)
        if not outbound_draft:
            raise HTTPException(status_code=500, detail="Failed to sync draft to outbound store")
    real_provider_id = _get_outbound_provider_for_draft(outbound_draft)
    if not real_provider_id:
        return {"ok": False, "error": "No Gmail outbound provider registered"}
    log.info("[send_draft] Sending draft %s via provider %s", draft_id, real_provider_id)
    result = outbound_executor.execute("send_reply", {
        "provider_id": real_provider_id,
        "draft_id": outbound_draft.id,
        "conversation_id": outbound_draft.conversation_id,
        "thread_id": outbound_draft.thread_id,
        "workflow_id": outbound_draft.workflow_id,
        "subject": outbound_draft.subject,
        "body": outbound_draft.body,
        "recipient": {"email": outbound_draft.recipient.email, "name": outbound_draft.recipient.name},
        "sender": {"email": outbound_draft.sender.email, "name": outbound_draft.sender.name},
    })
    if result.get("ok"):
        outbound_draft_store.mark_sent(draft_id)
        legacy_drafts = draft_store.get(session_token, [])
        for d in legacy_drafts:
            if d.get("id") == draft_id:
                d["status"] = "sent"
                break
        send_data = result.get("send_result", {})
        try:
            from services.conversations.integration import create_conversation_from_send
            create_conversation_from_send(
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
            )
        except Exception as e:
            log.warning("[send_draft] Failed to create conversation: %s", e)
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
async def schedule_draft(session_token: str, draft_id: str, payload: ScheduleDraftRequest):
    from services.outbound.draft_store import draft_store as outbound_draft_store
    from services.outbound.outbound_scheduler import outbound_scheduler
    outbound_draft = outbound_draft_store.get(draft_id)
    if not outbound_draft:
        legacy_drafts = draft_store.get(session_token, [])
        legacy = next((d for d in legacy_drafts if d.get("id") == draft_id), None)
        if not legacy:
            raise HTTPException(status_code=404, detail="Draft not found in any store")
        _sync_draft_to_outbound(legacy, session_token)
        outbound_draft = outbound_draft_store.get(draft_id)
        if not outbound_draft:
            raise HTTPException(status_code=500, detail="Failed to sync draft to outbound store")
    real_provider_id = _get_outbound_provider_for_draft(outbound_draft)
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
async def cancel_schedule_draft(session_token: str, draft_id: str):
    from services.outbound.draft_store import draft_store as outbound_draft_store
    from services.outbound.outbound_scheduler import outbound_scheduler
    outbound_draft = outbound_draft_store.get(draft_id)
    if not outbound_draft:
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
async def outbound_cancel_schedule(session_token: str, schedule_id: str, provider_id: str = ""):
    from services.outbound.outbound_scheduler import outbound_scheduler
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
async def outbound_get_draft(session_token: str, draft_id: str):
    draft = outbound_draft_store.get(draft_id)
    if not draft:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Draft not found")
    return {"ok": True, "draft": draft.model_dump()}


@app.post("/api/web/session/{session_token}/outbound/drafts/{draft_id}/approve")
async def outbound_approve_draft(session_token: str, draft_id: str, auto: bool = False):
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
async def outbound_reject_draft(session_token: str, draft_id: str):
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
async def outbound_approve_all(session_token: str, payload: ApproveAllRequest):
    all_drafts = outbound_draft_store.list_all()
    pending = [d for d in all_drafts.drafts if d.status.value in ("draft", "pending_approval")]
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
async def outbound_history(session_token: str, provider_id: str = ""):
    history = outbound_persistence.get_history(provider_id=provider_id)
    return {"ok": True, "history": [h.model_dump() for h in history]}


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


# ── Campaign Endpoints ──


async def _workspace_owner(request: Request, session_token: str) -> str:
    """Resolve the durable workspace owner, never the temporary web token."""
    authorization = request.headers.get("authorization", "")
    if authorization:
        from services.identity.api import get_authenticated_user_id
        return await get_authenticated_user_id(request)
    summary = engine.get_web_session_summary(session_token)
    if not summary:
        raise HTTPException(status_code=404, detail="Session not found")
    return str(summary.get("user_id") or "")


def _workspace_campaigns(user_id: str, session_token: str = "") -> list[dict[str, Any]]:
    from services.workspace_state import load_workspace_state
    return load_workspace_state(user_id)["campaigns"]


def _workspace_drafts(user_id: str, session_token: str = "") -> list[dict[str, Any]]:
    from services.workspace_state import load_workspace_state
    return load_workspace_state(user_id)["drafts"]


@app.post("/api/web/session/{session_token}/campaigns")
async def save_campaign(session_token: str, payload: SaveCampaignRequest, request: Request):
    owner_id = await _workspace_owner(request, session_token)
    now = datetime.now(timezone.utc).isoformat()
    leads = payload.leads or []
    campaign = {
        "id": str(uuid.uuid4()),
        "name": payload.name,
        "objective": payload.objective,
        "search_query": payload.search_query,
        "lead_count": payload.lead_count or len(leads),
        "leads": leads,
        "status": payload.status,
        "strategy": payload.strategy,
        "created_at": now,
        "updated_at": now,
    }
    from services.workspace_state import persist_campaign
    if not persist_campaign(owner_id, campaign):
        raise HTTPException(status_code=503, detail="Campaign could not be persisted")
    record_campaign_created(session_token, payload.name)
    publish(session_token, WMEventType.CAMPAIGN_CREATED, {
        "id": campaign["id"],
        "name": campaign["name"],
        "status": campaign["status"],
        "lead_count": campaign["lead_count"],
        "search_query": campaign["search_query"],
    }, actor="user")
    _get_feedback().on_campaign_created(session_token, campaign["id"])
    return {"ok": True, "campaign": campaign}


@app.get("/api/web/session/{session_token}/campaigns")
async def list_campaigns(session_token: str, request: Request):
    from services.workspace_snapshot import enrich_campaigns
    owner_id = await _workspace_owner(request, session_token)
    campaigns = _workspace_campaigns(owner_id, session_token)
    drafts = _workspace_drafts(owner_id, session_token)
    return {"ok": True, "campaigns": enrich_campaigns(campaigns, drafts)}


@app.get("/api/web/session/{session_token}/campaigns/summary")
async def campaign_summary(session_token: str, request: Request):
    from services.workspace_snapshot import enrich_campaigns
    owner_id = await _workspace_owner(request, session_token)
    campaigns = _workspace_campaigns(owner_id, session_token)
    drafts = _workspace_drafts(owner_id, session_token)
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
    from services.workspace_snapshot import enrich_campaigns
    owner_id = await _workspace_owner(request, session_token)
    campaigns = _workspace_campaigns(owner_id, session_token)
    drafts = _workspace_drafts(owner_id, session_token)
    enriched = enrich_campaigns(campaigns, drafts)
    target = next((c for c in enriched if c.get("id") == campaign_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Campaign not found")
    record_campaign_open(session_token, campaign_id, target.get("name", ""))
    return {"ok": True, "campaign": target}


@app.get("/api/web/session/{session_token}/campaigns/{campaign_id}/launch-progress")
async def campaign_launch_progress(session_token: str, campaign_id: str, request: Request):
    owner_id = await _workspace_owner(request, session_token)
    campaigns = _workspace_campaigns(owner_id, session_token)
    target = next((c for c in campaigns if c.get("id") == campaign_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return {
        "ok": True,
        "launch_sent": target.get("launch_sent", 0),
        "launch_total": target.get("launch_total", 0),
        "launch_complete": target.get("launch_sent", 0) >= target.get("launch_total", 0) if target.get("launch_total", 0) > 0 else False,
    }


@app.put("/api/web/session/{session_token}/campaigns/{campaign_id}")
async def update_campaign(session_token: str, campaign_id: str, payload: UpdateCampaignRequest, request: Request):
    owner_id = await _workspace_owner(request, session_token)
    campaigns = _workspace_campaigns(owner_id, session_token)
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
        old_status = target.get("status", "")
        target["status"] = payload.status
        updates["status"] = payload.status
        publish(session_token, WMEventType.CAMPAIGN_STATUS_CHANGED, {
            "campaign_id": campaign_id,
            "status": payload.status,
            "previous_status": old_status,
        }, actor="user")
        if payload.status == "completed" and old_status != "completed":
            durable_drafts = _workspace_drafts(owner_id, session_token)
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
        elif payload.status in ("ready", "ready_to_send"):
            record_campaign_ready(session_token, target.get("name", ""))
    elif payload.name is not None:
        publish(session_token, WMEventType.CAMPAIGN_UPDATED, {
            "campaign_id": campaign_id,
            "name": payload.name,
        }, actor="user")
    target["updated_at"] = datetime.now(timezone.utc).isoformat()
    from services.workspace_state import persist_campaign_update_awaited
    if updates and not await persist_campaign_update_awaited(owner_id, campaign_id, updates):
        raise HTTPException(status_code=503, detail="Campaign update could not be persisted")
    return {"ok": True, "campaign": target}


@app.post("/api/web/session/{session_token}/campaigns/{campaign_id}/generate-strategy")
async def generate_campaign_strategy(session_token: str, campaign_id: str, request: Request):
    owner_id = await _workspace_owner(request, session_token)
    """Create and persist the first strategy artifact for a campaign."""
    campaigns = _workspace_campaigns(owner_id, session_token)
    target = next((c for c in campaigns if c.get("id") == campaign_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Campaign not found")
    objective = str(target.get("objective") or "").strip()
    if not objective:
        raise HTTPException(status_code=400, detail="Campaign objective is required")

    strategy = {
        "objective": objective,
        "audience": "Prospects matching the research profile",
        "channel": "email",
        "messaging_angle": f"Lead with a relevant outcome tied to: {objective}",
        "sequence": ["Personalized introduction", "Value-led follow-up", "Final check-in"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    target["strategy"] = strategy
    old_status = target.get("status", "planning")
    target["status"] = "strategy_review"
    target["updated_at"] = datetime.now(timezone.utc).isoformat()
    from services.workspace_state import persist_campaign_update
    if not persist_campaign_update(owner_id, campaign_id, {
        "strategy": strategy,
        "status": "strategy_review",
    }):
        raise HTTPException(status_code=503, detail="Strategy could not be persisted")
    publish(session_token, WMEventType.CAMPAIGN_UPDATED, {
        "campaign_id": campaign_id,
        "objective": objective,
        "strategy": strategy,
    }, actor="loqi")
    publish(session_token, WMEventType.CAMPAIGN_STATUS_CHANGED, {
        "campaign_id": campaign_id,
        "status": "strategy_review",
        "previous_status": old_status,
    }, actor="loqi")
    return {"ok": True, "campaign": target}


@app.post("/api/web/session/{session_token}/campaigns/{campaign_id}/leads")
async def add_campaign_lead(session_token: str, campaign_id: str, payload: AddCampaignLeadRequest, request: Request):
    owner_id = await _workspace_owner(request, session_token)
    campaigns = _workspace_campaigns(owner_id, session_token)
    target = next((c for c in campaigns if c.get("id") == campaign_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Campaign not found")
    lead = dict(payload.lead)
    lead_id = str(lead.get("id") or lead.get("linkedin_url") or lead.get("email") or uuid.uuid4())
    lead["id"] = lead_id
    leads = target.setdefault("leads", [])
    if any(str(existing.get("id")) == lead_id for existing in leads if isinstance(existing, dict)):
        return {"ok": True, "campaign": target, "added": False}
    leads.append(lead)
    target["lead_count"] = len(leads)
    target["updated_at"] = datetime.now(timezone.utc).isoformat()
    from services.workspace_state import persist_campaign_lead
    if not persist_campaign_lead(owner_id, campaign_id, lead):
        raise HTTPException(status_code=503, detail="Lead could not be persisted to the campaign")
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
            _sync_draft_to_outbound(d, session_token)

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
                _sync_draft_to_outbound(ld, session_token)
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
                    log.warning("[campaign_launch] Durable sent-mark failed: %s", e)
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
                    create_conversation_from_send(
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
                    )
                except Exception as conv_err:
                    log.warning("[campaign_launch] Failed to create conversation: %s", conv_err)
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
    owner_id = await _workspace_owner(request, session_token)
    campaigns = _workspace_campaigns(owner_id, session_token)
    target = next((c for c in campaigns if c.get("id") == campaign_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Campaign not found")
    target["status"] = "archived"
    target["updated_at"] = datetime.now(timezone.utc).isoformat()
    from services.workspace_state import persist_campaign_update
    if not persist_campaign_update(owner_id, campaign_id, {"status": "archived"}):
        raise HTTPException(status_code=503, detail="Campaign archive could not be persisted")
    publish(session_token, WMEventType.CAMPAIGN_ARCHIVED, {
        "campaign_id": campaign_id,
        "name": target.get("name", ""),
    }, actor="user")
    return {"ok": True, "campaign": target}


@app.get("/api/web/session/{session_token}/campaigns/{campaign_id}/drafts")
async def list_campaign_drafts(session_token: str, campaign_id: str, request: Request):
    owner_id = await _workspace_owner(request, session_token)
    all_drafts = _workspace_drafts(owner_id, session_token)
    filtered = [d for d in all_drafts if d.get("campaign_id") == campaign_id]
    return {"ok": True, "drafts": filtered}


@app.post("/api/web/session/{session_token}/campaigns/{campaign_id}/generate-drafts")
async def generate_campaign_drafts(session_token: str, campaign_id: str, request: Request):
    owner_id = await _workspace_owner(request, session_token)
    campaigns = _workspace_campaigns(owner_id, session_token)
    target = next((c for c in campaigns if c.get("id") == campaign_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Campaign not found")

    active_job = next(
        (j for j in batch_jobs.values()
         if j.get("campaign_id") == campaign_id and j.get("status") == "processing"),
        None,
    )
    if active_job:
        return {"ok": True, "batch_id": active_job.get("batch_id"), "total": active_job.get("total", 0)}
    if target.get("status") == "generating":
        target = _reconcile_campaign_generation(owner_id, target)

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
    target["status"] = "generating"
    target["updated_at"] = datetime.now(timezone.utc).isoformat()
    from services.workspace_state import persist_campaign_update
    if not persist_campaign_update(owner_id, campaign_id, {
        "status": "generating",
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
    publish(session_token, WMEventType.CAMPAIGN_STATUS_CHANGED, {
        "campaign_id": campaign_id,
        "status": "generating",
        "previous_status": "planning",
        "lead_count": total,
    }, actor="user")
    _launch_batch_task(session_token, batch_id, leads, owner_id)
    return {"ok": True, "batch_id": batch_id, "total": total}


@app.get("/api/web/session/{session_token}/campaigns/{campaign_id}/generation-status")
async def campaign_generation_status(session_token: str, campaign_id: str, request: Request):
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

    if target.get("status") == "generating":
        target = _reconcile_campaign_generation(owner_id, target)

    generation = target.get("generation")
    generation = generation if isinstance(generation, dict) else {}
    return {
        "ok": True,
        "active": False,
        "status": target.get("status", "unknown"),
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


@app.get("/api/web/session/{session_token}/mission-control")
async def mission_control_summary(session_token: str, request: Request, onboarding_user_id: str = ""):
    owner_id = await _workspace_owner(request, session_token)
    campaigns = _workspace_campaigns(owner_id, session_token)
    drafts = _workspace_drafts(owner_id, session_token)
    now = datetime.now(timezone.utc)

    total_leads = sum(c.get("lead_count", 0) or 0 for c in campaigns)

    from services.conversation_engine import ConversationEngine
    _engine = ConversationEngine()
    summary = _engine.get_web_session_summary(session_token)
    db_user_id = summary.get("user_id") if summary else None

    # ── Phase 4: compute delta from World Model ──
    wm_store = get_wm_store()
    last_seq = wm_store.get_last_sequence(session_token)
    delta = wm_store.compute_delta(session_token)
    log.info(
        f"[phase4] delta: first_visit={delta.first_visit}, "
        f"events={delta.event_count}, range={delta.event_range}, "
        f"new_campaigns={len(delta.new_campaigns)}, "
        f"changed_campaigns={len(delta.changed_campaigns)}, "
        f"new_drafts={len(delta.new_drafts)}, "
        f"new_leads={len(delta.new_leads)}"
    )

    snapshot = build_snapshot(session_token, campaigns, drafts, total_leads, user_id=db_user_id)

    # Embed delta into snapshot for Executive Brief (no interface change)
    _embed_delta_into_snapshot(snapshot, delta)

    analysis = snapshot.get("analysis", {})
    recommendations = generate_recommendations(snapshot)
    brief = generate_brief(snapshot, recommendations)

    # Record acknowledgement after generating the brief
    ack_ts, ack_seq = wm_store.record_acknowledgement(session_token)
    log.info(f"[phase4] acknowledgement recorded at seq={ack_seq}")

    # Phase 3: use snapshot-derived values (which come from World Model when available)
    campaign_list = snapshot.get("campaigns", [])
    draft_counts = snapshot.get("drafts", {"total": 0, "pending": 0, "approved": 0})
    pending_drafts = draft_counts.get("pending", 0)
    approved_drafts = draft_counts.get("approved", 0)
    total_drafts = draft_counts.get("total", 0)
    snapshot_total_leads = snapshot.get("total_leads", total_leads)
    reply_rate_heuristic = round((approved_drafts / total_drafts * 100) if total_drafts else 0)

    try:
        if onboarding_user_id:
            current_jobs = job_manager.list_active_jobs(onboarding_user_id)
        elif db_user_id:
            current_jobs = job_manager.list_active_jobs(db_user_id)
        else:
            current_jobs = []
    except Exception:
        current_jobs = []

    initial_research = None
    initial_research_result_count = None
    if onboarding_user_id:
        try:
            wizard = await _onboarding_svc.get_wizard_data(onboarding_user_id)
            job_id = str(wizard.get("initial_research_job_id") or "")
            if not job_id:
                recent_searches = [
                    job for job in job_manager.list_recent_jobs(onboarding_user_id)
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
    from services.mission_control.api import handle_get_briefing

    owner_id = await _workspace_owner(request, session_token)
    campaigns = _workspace_campaigns(owner_id, session_token)
    drafts = _workspace_drafts(owner_id, session_token)

    total_leads = sum(c.get("lead_count", 0) or 0 for c in campaigns)

    from services.conversation_engine import ConversationEngine
    _engine = ConversationEngine()
    summary = _engine.get_web_session_summary(session_token)
    db_user_id = summary.get("user_id") if summary else None

    return await handle_get_briefing(
        session_token=session_token,
        campaigns=campaigns,
        drafts=drafts,
        total_leads=total_leads,
        db_user_id=onboarding_user_id or db_user_id,
    )


@app.get("/api/web/session/{session_token}/export-csv")
async def export_csv(session_token: str):
    leads: list[dict] = []
    for d in draft_store.get(session_token, []):
        lead = d.get("lead")
        if lead:
            leads.append(lead)

    if not leads:
        from services.conversation_engine import ConversationEngine, _message
        local_engine = ConversationEngine()
        summary = local_engine.get_web_session_summary(session_token)
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
async def select_lead_endpoint(session_token: str, payload: SelectLeadRequest):
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
async def preview_lead_endpoint(session_token: str, payload: PreviewLeadRequest):
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
async def get_web_gmail_status(session_token: str):
    summary = engine.get_web_session_summary(session_token)
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
    state_parts = state.split(":")

    if len(state_parts) == 2:
        channel = "telegram"
        user_id, transport_id = state_parts
    elif len(state_parts) == 3:
        channel, user_id, transport_id = state_parts
    else:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

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
            """
            <html>
              <body style="background:#0b1020;color:#f3f4f6;font-family:system-ui;padding:32px;">
                <h1 style="margin:0 0 12px;">Gmail connected</h1>
                <p style="opacity:.8;">You can close this window and return to Loqi.</p>
                <script>
                  window.opener && window.opener.postMessage({ type: 'loqi:gmail-connected' }, '*');
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


@app.post("/api/jobs/search")
async def start_search(payload: StartSearchRequest, request: Request):
    session_token = request.headers.get("x-session-token", "")
    if session_token:
        summary = await asyncio.to_thread(engine.get_web_session_summary, session_token)
    else:
        summary = None
    user_id = summary.get("user_id") if summary else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Valid session required")

    result = await job_manager.create_search_job(user_id=user_id, query=payload.query)
    if not result:
        raise HTTPException(status_code=500, detail="Failed to create job")
    if session_token:
        publish(session_token, WMEventType.LEAD_DISCOVERED, {
            "job_id": result.get("id", ""),
            "query": payload.query,
            "status": "searching",
        }, actor="user")
    return result


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/api/jobs/{job_id}/results")
def get_job_results(job_id: str):
    result = job_manager.get_job_results(job_id)
    if not result:
        raise HTTPException(status_code=404, detail="Job not found")
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Job not ready"))
    return result


@app.get("/api/jobs")
async def list_jobs(request: Request):
    session_token = request.headers.get("x-session-token", "")
    summary = engine.get_web_session_summary(session_token) if session_token else None
    # Onboarding research is owned by the authenticated identity, while the
    # legacy web session has its own adapter user. Accept the explicit
    # onboarding identity so Discovery can retrieve that same job.
    requested_user_id = request.query_params.get("user_id", "")
    authorization = request.headers.get("authorization", "")
    authenticated_user_id = ""
    if authorization:
        from services.identity.api import get_authenticated_user_id
        authenticated_user_id = await get_authenticated_user_id(request)
        if requested_user_id and requested_user_id != authenticated_user_id:
            raise HTTPException(status_code=403, detail="User identity mismatch")
    user_id = authenticated_user_id or requested_user_id or (summary.get("user_id") if summary else None)
    if not user_id:
        return {"jobs": []}
    jobs = job_manager.list_recent_jobs(user_id)
    return {"jobs": jobs}


@app.post("/api/web/session/{session_token}/plan")
async def plan_workflow_endpoint(session_token: str, payload: PlanningInput):
    campaigns = campaign_store.get(session_token, [])
    drafts = draft_store.get(session_token, [])
    total_leads = sum(c.get("lead_count", 0) or 0 for c in campaigns)
    from services.conversation_engine import ConversationEngine
    _summary = ConversationEngine().get_web_session_summary(session_token)
    _db_user_id = _summary.get("user_id") if _summary else None
    snapshot = build_snapshot(session_token, campaigns, drafts, total_leads, user_id=_db_user_id)
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
async def execute_workflow_endpoint(session_token: str, payload: ExecuteWorkflowRequest):
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
async def get_workflow_status(session_token: str, workflow_id: str):
    runtime = get_runtime(workflow_id)
    if not runtime:
        raise HTTPException(status_code=404, detail="Workflow not found")
    progress = calculate_progress(runtime)
    return {
        "ok": True,
        "runtime": runtime.to_dict(),
        "progress": progress,
    }


@app.get("/api/web/session/{session_token}/workflows/{workflow_id}/events")
async def get_workflow_events_endpoint(session_token: str, workflow_id: str):
    runtime = get_runtime(workflow_id)
    if not runtime:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return {
        "ok": True,
        "events": get_workflow_events(workflow_id),
    }


@app.post("/api/web/session/{session_token}/workflows/{workflow_id}/approve")
async def approve_workflow_step(session_token: str, workflow_id: str):
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
async def list_workflows(session_token: str):
    workflows = get_all_runtimes(session_token)
    return {
        "ok": True,
        "workflows": [wf.summary() for wf in workflows],
        "active": [calculate_progress(wf) for wf in get_active_runtimes(session_token)],
    }


@app.get("/api/web/session/{session_token}/workflows/history")
async def workflow_history(session_token: str, status: str | None = None, limit: int = 50):
    return {
        "ok": True,
        "history": get_workflow_history(session_token, status_filter=status, limit=limit),
    }


@app.get("/api/web/session/{session_token}/workflows/{workflow_id}/events/stream")
async def workflow_events_after(session_token: str, workflow_id: str, after: int = 0):
    runtime = get_runtime(workflow_id)
    if not runtime:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return {
        "ok": True,
        "events": get_workflow_events(workflow_id, after_sequence=after),
        "latest_sequence": get_latest_sequence(workflow_id),
    }


@app.post("/api/web/session/{session_token}/workflows/{workflow_id}/pause")
async def pause_workflow_endpoint(session_token: str, workflow_id: str):
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
async def resume_workflow_endpoint(session_token: str, workflow_id: str):
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
async def cancel_workflow_endpoint(session_token: str, workflow_id: str):
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
async def list_conversations_route(session_token: str):
    from services.conversations.conversation_store import conversation_store
    conversations = conversation_store.list_conversations(limit=100)
    return {
        "ok": True,
        "conversations": [c.to_dict() for c in conversations],
    }


@app.get("/api/web/session/{session_token}/conversations/{conversation_id}")
async def get_conversation_route(session_token: str, conversation_id: str):
    from services.conversations.conversation_store import conversation_store
    convo = conversation_store.get_conversation(conversation_id)
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {
        "ok": True,
        "conversation": convo.to_dict(),
    }


@app.get("/api/web/session/{session_token}/conversations/{conversation_id}/timeline")
async def get_conversation_timeline_route(session_token: str, conversation_id: str):
    from services.conversations.conversation_store import conversation_store
    convo = conversation_store.get_conversation(conversation_id)
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found")
    events = conversation_store.get_timeline(conversation_id)
    return {
        "ok": True,
        "events": [e.to_dict() for e in events],
    }


@app.get("/api/web/session/{session_token}/conversations/{conversation_id}/messages")
async def get_conversation_messages_route(session_token: str, conversation_id: str):
    from services.conversations.conversation_store import conversation_store
    convo = conversation_store.get_conversation(conversation_id)
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = conversation_store.get_messages_for_conversation(conversation_id)
    return {
        "ok": True,
        "messages": [m.to_dict() for m in messages],
    }


@app.get("/api/web/session/{session_token}/conversations/{conversation_id}/reasoning")
async def get_conversation_reasoning_route(session_token: str, conversation_id: str):
    from services.conversations.conversation_store import conversation_store
    from services.conversation_intelligence.intelligence_pipeline import IntelligencePipeline
    from services.reasoning.reasoning_pipeline import get_pipeline as get_reasoning_pipeline

    convo = conversation_store.get_conversation(conversation_id)
    if not convo:
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
async def get_conversation_plan_route(session_token: str, conversation_id: str):
    from services.conversations.conversation_store import conversation_store
    from services.conversation_intelligence.intelligence_pipeline import IntelligencePipeline
    from services.reasoning.reasoning_pipeline import get_pipeline as get_reasoning_pipeline

    convo = conversation_store.get_conversation(conversation_id)
    if not convo:
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
):
    from services.conversations.conversation_store import conversation_store
    from services.conversation_intelligence.intelligence_pipeline import IntelligencePipeline
    from services.reasoning.reasoning_pipeline import get_pipeline as get_reasoning_pipeline
    from services.reply_generation.generation_pipeline import GenerationPipeline
    from services.reply_generation.generation_models import GenerationStyle

    convo = conversation_store.get_conversation(conversation_id)
    if not convo:
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
    reasoning = reasoning_pipeline.reason(intelligence)

    latest_texts = []
    for m in messages[-3:]:
        preview = m.body_preview or (m.body or "")[:200]
        direction = "Prospect" if m.direction == "inbound" else "You"
        if preview:
            latest_texts.append(f"[{direction}]: {preview}")

    gen_pipeline = GenerationPipeline()
    result = gen_pipeline.generate(
        intelligence=intelligence,
        reasoning=reasoning,
        styles=styles,
        variant_count=payload.get("variant_count", 1),
        latest_messages=latest_texts,
    )

    return {
        "ok": True,
        "generation": result.to_dict(),
        "reasoning": reasoning.to_dict(),
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "10000"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
