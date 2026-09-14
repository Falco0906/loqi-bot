import asyncio
import concurrent.futures
import os
import time

from services.workflows.runtime import RuntimeEntry, get_runtime
from services.campaigns.service import load_campaigns
from services.workspace.state import load_drafts_only
from services.workspace_snapshot import build_snapshot
from services.workflows.executor import (
    approve as approve_runtime,
    cancel as cancel_runtime,
    execute as execute_runtime,
    pause as pause_runtime,
    resume as resume_runtime,
)
from services.workflows.models import WorkflowPlan
from services.workflows.planner import plan_workflow
from services.workflows.progress import calculate_progress
from services.world_model import EventType as WMEventType, publish

# TEMPORARY: shared executor for bridging sync→async.
# Remove once handle_message() and the workflow execution path
# become async-native and can directly await GmailAdapter.
# See backlog in AGENTS.md.
#
# PR-3F hardening:
#   - workers raised 4 → 16 (env-tunable) so one user's slow blocking op
#     cannot exhaust the shared pool and stall unrelated requests;
#   - every bridge call carries a bounded timeout (env-tunable). On timeout a
#     TimeoutError surfaces to the CALLER immediately — the underlying worker
#     thread keeps draining until the coroutine finishes naturally (Python
#     threads are not cancellable), but it no longer blocks other work items
#     beyond that single slot. Active-worker gauge is logged per call.
_ASYNC_BRIDGE_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=int(os.getenv("ASYNC_BRIDGE_WORKERS", "16")),
    thread_name_prefix="async_bridge",
)
_ASYNC_BRIDGE_TIMEOUT_SECONDS = float(os.getenv("ASYNC_BRIDGE_TIMEOUT_SECONDS", "120"))


def owned_runtime(workflow_id: str, session_token: str) -> RuntimeEntry | None:
    """Return a legacy workflow runtime only for its creating web session."""
    runtime = get_runtime(workflow_id)
    if runtime is None or not session_token or runtime.session_token != session_token:
        return None
    return runtime


class WorkflowNotFoundError(Exception):
    """Raised when a legacy session does not own the requested runtime."""


def _owned_runtime_or_raise(workflow_id: str, session_token: str) -> RuntimeEntry:
    runtime = owned_runtime(workflow_id, session_token)
    if runtime is None:
        raise WorkflowNotFoundError(workflow_id)
    return runtime


def start_workflow(
    *,
    session_token: str,
    plan_id: str,
    goal: str,
    reasoning: str = "",
    estimated_duration: str = "",
    risk_level: str = "low",
    requires_approval: bool = False,
    steps: list[dict],
) -> dict:
    """Start one legacy runtime and publish its established world-model event."""
    plan = WorkflowPlan(
        id=plan_id,
        goal=goal,
        reasoning=reasoning,
        estimated_duration=estimated_duration,
        risk_level=risk_level,
        requires_approval=requires_approval,
        steps=steps,
    )
    runtime = execute_runtime(plan, session_token)
    progress = calculate_progress(runtime)
    publish(session_token, WMEventType.WORKFLOW_STARTED, {
        "workflow_id": runtime.workflow_id,
        "goal": goal,
        "step_count": len(steps),
        "risk_level": risk_level,
        "requires_approval": requires_approval,
    }, actor="user")
    return {
        "ok": True,
        "workflow_id": runtime.workflow_id,
        "status": runtime.status.value,
        "progress": progress,
        "runtime": runtime.summary(),
    }


def approve_workflow_for_session(workflow_id: str, session_token: str) -> dict:
    """Approve one owned workflow step and publish the established event."""
    _owned_runtime_or_raise(workflow_id, session_token)
    runtime = approve_runtime(workflow_id)
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


def pause_workflow_for_session(workflow_id: str, session_token: str) -> dict:
    """Pause one owned workflow and publish the established event."""
    _owned_runtime_or_raise(workflow_id, session_token)
    runtime = pause_runtime(workflow_id)
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


def resume_workflow_for_session(workflow_id: str, session_token: str) -> dict:
    """Resume one owned workflow and publish the established event."""
    _owned_runtime_or_raise(workflow_id, session_token)
    runtime = resume_runtime(workflow_id)
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


def cancel_workflow_for_session(workflow_id: str, session_token: str) -> dict:
    """Cancel one owned workflow and publish the established event."""
    _owned_runtime_or_raise(workflow_id, session_token)
    runtime = cancel_runtime(workflow_id)
    publish(session_token, WMEventType.WORKFLOW_CANCELLED, {
        "workflow_id": workflow_id,
        "status": runtime.status.value,
    }, actor="user")
    return {
        "ok": True,
        "workflow_id": runtime.workflow_id,
        "status": runtime.status.value,
    }


async def plan_workspace_workflow(
    *,
    user_id: str,
    workspace_id: str,
    session_token: str,
    objective: str,
    current_page: str = "unknown",
) -> dict:
    """Build one authorized workspace snapshot and return workflow alternatives."""
    campaigns, drafts = await asyncio.gather(
        asyncio.to_thread(load_campaigns, user_id, workspace_id=workspace_id),
        asyncio.to_thread(load_drafts_only, user_id, workspace_id=workspace_id),
    )
    total_leads = sum(campaign.get("lead_count", 0) or 0 for campaign in campaigns)
    snapshot = await asyncio.to_thread(
        build_snapshot,
        session_token,
        campaigns,
        drafts,
        total_leads,
        user_id=user_id,
    )
    result = plan_workflow(
        objective=objective,
        snapshot=snapshot,
        current_page=current_page,
    )
    return {
        "ok": True,
        "plan": result.primary_plan.model_dump(),
        "alternative_plan": result.alternative_plan.model_dump(),
        "recommendation": result.recommendation,
        "confidence": result.confidence,
    }


def _bridge_active_workers() -> int:
    return len([t for t in _ASYNC_BRIDGE_EXECUTOR._threads if t.is_alive()]) \
        if getattr(_ASYNC_BRIDGE_EXECUTOR, "_threads", None) else -1


def _run_async(coro):
    """TEMPORARY — run a coroutine from a synchronous context.

    Python 3.12+ blocks all forms of nested loop execution within the
    same thread (even ``asyncio.run``, ``Runner.run``, or raw
    ``loop.run_until_complete`` on a fresh loop).  The only
    cross-version way to call async code from a sync function that may
    execute on the event-loop thread is to offload to a worker thread.

    This bridge exists only because handle_message() and the workflow
    dispatch path are still synchronous.  Once they become async-native
    (see backlog), callers should ``await adapter.execute(ctx)``
    directly and this function should be removed.
    """
    started = time.monotonic()
    future = _ASYNC_BRIDGE_EXECUTOR.submit(asyncio.run, coro)
    try:
        result = future.result(timeout=_ASYNC_BRIDGE_TIMEOUT_SECONDS)
        import logging as _log_mod
        _log_mod.getLogger(__name__).info(
            "[perf] bridge done active=%d duration_ms=%d",
            _bridge_active_workers(), int((time.monotonic() - started) * 1000),
        )
        return result
    except concurrent.futures.TimeoutError:
        import logging as _log_mod
        _log_mod.getLogger(__name__).error(
            "[perf] bridge TIMEOUT after %ss active=%d — caller receives an error; "
            "worker continues draining",
            _ASYNC_BRIDGE_TIMEOUT_SECONDS, _bridge_active_workers(),
        )
        raise TimeoutError(
            f"Bridge operation exceeded {_ASYNC_BRIDGE_TIMEOUT_SECONDS}s"
        ) from None

from services.communication.google_auth import refresh_access_token
from services.discovery.providers import format_leads_message
from services.intelligence.ai import generate_outreach_email, rewrite_message, OpenAIError
from services.discovery.providers import get_leads, search_with_expansion
from services.platform.supabase import get_user, get_google_credentials, is_token_expired, store_leads, update_google_access_token
from services.conversations.compatibility import record_workflow_event
from services.enrichment.enrichment_factory import get_enricher
from services.intelligence.lead_intelligence import generate_lead_intelligence
from services.adapters.google.gmail import GmailAdapter


VALID_TONES = {"casual", "formal", "aggressive", "friendly"}
VALID_LENGTHS = {"short", "medium", "long"}


def _is_relevant_lead(title: str, target: str) -> bool:
    normalized_title = (title or "").lower()
    keywords = (target or "").lower().split()
    return any(keyword in normalized_title for keyword in keywords)


def _infer_tone(input: dict) -> str:
    explicit_tone = (input.get("tone") or "").strip().lower()
    if explicit_tone in VALID_TONES:
        return explicit_tone

    text_parts = [
        input.get("edit_request") or "",
        * (input.get("conversation_context") or []),
    ]
    combined_text = " ".join(
        part for part in [
            *text_parts,
        ]
        if part
    ).lower()
    word_count = len(combined_text.split())

    if any(word in combined_text for word in ["sir", "madam", "regards", "sincerely", "professional", "formal"]):
        return "formal"
    if word_count and word_count <= 3:
        return "aggressive"
    if "aggressive" in combined_text or "stronger" in combined_text or "hard sell" in combined_text:
        return "aggressive"
    return "casual"


def _infer_length(input: dict) -> str:
    explicit_length = (input.get("length") or "").strip().lower()
    if explicit_length in VALID_LENGTHS:
        return explicit_length

    combined_text = " ".join(
        part for part in [
            input.get("edit_request") or "",
            " ".join(input.get("conversation_context") or []),
        ]
        if part
    ).lower()

    if "shorter" in combined_text or "short" in combined_text:
        return "short"
    if "longer" in combined_text or "long" in combined_text:
        return "long"
    return "medium"


def _normalize_edit_request(edit_request: str) -> str:
    normalized = edit_request.strip()
    lowered = normalized.lower()

    if lowered == "rewrite":
        return "Rewrite the message from scratch using the same goal."
    if "add urgency" in lowered:
        return "Add urgency and make the call to action more time-sensitive."
    return normalized


def _workflow_knowledge_context(
    owner_id: str,
    lead: dict | None = None,
    strategy: dict | None = None,
) -> dict:
    """Synchronously bridge the canonical Knowledge adapter for legacy flows."""
    if not owner_id:
        return {}
    lead = lead or {}
    strategy = strategy or {}
    query = " ".join(
        str(value).strip()
        for value in (
            lead.get("company"),
            lead.get("title"),
            strategy.get("icp"),
            strategy.get("messaging_angle"),
            strategy.get("value_proposition"),
        )
        if str(value).strip()
    )
    try:
        from services.knowledge.context_adapter import retrieve_knowledge_context
        return _run_async(
            retrieve_knowledge_context(
                owner_id,
                query=query,
                categories=["company", "icp", "messaging", "sales_offer"],
                limit=8,
            )
        ).to_dict()
    except Exception as error:
        print(f"[workflows] Knowledge retrieval skipped: {error}")
        return {}


def _clean_lead_title(lead_title: str) -> str:
    return lead_title.replace("|", "").replace("  ", " ").strip()


def _simplify_lead_title(lead_title: str) -> str:
    title = _clean_lead_title(lead_title).lower()

    if "vp" in title or "vice president" in title:
        return "leading hiring"
    if "head" in title:
        return "leading hiring and people operations"
    if "talent" in title or "recruit" in title:
        return "focused on hiring and talent"
    if "account" in title:
        return "working in accounting"
    if "hr" in title or "human resource" in title:
        return "working in HR"

    return "working in your role"


def generate_leads(input: dict) -> dict:
    import time; _t0 = time.time()
    service = input.get("service") or ""
    target = input.get("target") or ""
    user_id = input.get("user_id")
    workflow_session_id = input.get("workflow_session_id")
    print(f"[TRACE] 5b | ENTERED workflows.generate_leads | +0ms")

    discovery_context = {}
    if user_id:
        try:
            from services.discovery.context import retrieve_discovery_context
            discovery_context = _run_async(
                retrieve_discovery_context(user_id, query=f"{service} {target}".strip())
            )
        except Exception as error:
            print(f"[workflows] Discovery context retrieval skipped: {error}")

    result = search_with_expansion(service, target, context=discovery_context)
    print(f"[TRACE] 7 | search_with_expansion DONE | +{int((time.time()-_t0)*1000)}ms | {len(result.get('leads',[]))} leads | ok={result.get('ok')}")
    leads = result.get("leads", [])
    icp = result.get("icp")

    if icp:
        print(f"[workflows] Storing ICP: mode={icp.get('mode')}, offer='{icp.get('offer')}'")
        try:
            if workflow_session_id:
                record_workflow_event(
                    session_id=workflow_session_id,
                    event_type="icp.extracted",
                    payload={"structured_icp": icp},
                )
        except Exception as e:
            print(f"[workflows] Failed to store ICP: {e}")

    filtered = [
        lead for lead in leads
        if _is_relevant_lead(lead.get("title", ""), target)
    ]
    if len(filtered) >= 3:
        leads = filtered

    if not result.get("ok") or not leads:
        error = result.get("error") or "unknown_error"
        friendly_error = (
            "I couldn't find strong matches with that search. "
            "Want me to broaden the search or try a slightly different audience?"
        )
        return {
            "ok": False,
            "type": "generate_leads",
            "source": result.get("source", "lead_provider"),
            "leads": [],
            "stored_leads": [],
            "message": friendly_error,
            "error": error,
        }

    stored_leads = store_leads(user_id, leads) if user_id else []

    return {
        "ok": True,
        "type": "generate_leads",
        "source": result.get("source", "lead_provider"),
        "leads": leads,
        "stored_leads": stored_leads,
        "message": format_leads_message(leads),
        "error": None,
    }


def draft_message(input: dict) -> dict:
    lead = input.get("lead") or {}
    lead_name = ((lead.get("name") or "there").split() or ["there"])[0]
    title = _clean_lead_title(lead.get("title") or "")
    company = (lead.get("company") or "").replace("Unknown Company", "").strip()
    edit_request = _normalize_edit_request((input.get("edit_request") or "").strip())
    tone = _infer_tone(input)
    length = _infer_length(input)
    previous_message = input.get("previous_message") or ""
    context = input.get("context") or {}
    trusted_knowledge = input.get("knowledge_context") if input.get("_knowledge_context_trusted") else None
    knowledge_context = trusted_knowledge or _workflow_knowledge_context(
        str(input.get("user_id") or ""), lead, input.get("campaign_strategy")
    )

    company_intelligence = None
    lead_intelligence = None
    try:
        enricher = get_enricher()
        if enricher.health_check().get("ok"):
            company_intelligence = enricher.enrich_lead(lead)
    except Exception as e:
        print(f"[workflows] Enrichment failed (proceeding without): {e}")

    try:
        lead_intelligence = generate_lead_intelligence(lead, company_intelligence)
    except Exception as e:
        print(f"[workflows] Lead intelligence generation failed (proceeding without): {e}")

    subject = ""
    if edit_request and previous_message:
        try:
            rewrite_context = dict(context)
            if knowledge_context:
                rewrite_context["knowledge_context"] = knowledge_context
            llm_message = rewrite_message(edit_request, previous_message, rewrite_context)
            message = f"Draft ready:\n\n---\n{llm_message}\n---"
        except OpenAIError as e:
            return {
                "ok": False,
                "type": "draft_message",
                "message": f"Couldn't rewrite the draft due to a generation error. Want to try a different instruction or start fresh?",
                "lead": lead,
                "edit_request": edit_request,
                "tone": tone,
                "length": length,
                "error": str(e),
                "company_intelligence": company_intelligence,
                "lead_intelligence": lead_intelligence,
            }
    else:
        try:
            draft = generate_outreach_email(
                lead,
                company_intelligence,
                lead_intelligence,
                strategy=input.get("campaign_strategy"),
                knowledge_context=knowledge_context,
            )
            message = f"Draft ready:\n\n---\n{draft.get('body', '')}\n---"
            subject = draft.get("subject", "")
        except OpenAIError as e:
            return {
                "ok": False,
                "type": "draft_message",
                "message": f"I wasn't able to generate a draft right now. Try again or adjust the targeting.",
                "lead": lead,
                "edit_request": edit_request,
                "tone": tone,
                "length": length,
                "error": str(e),
                "company_intelligence": company_intelligence,
                "lead_intelligence": lead_intelligence,
            }

    return {
        "ok": True,
        "type": "draft_message",
        "message": message,
        "lead": lead,
        "subject": subject,
        "edit_request": edit_request,
        "tone": tone,
        "length": length,
        "company_intelligence": company_intelligence,
        "lead_intelligence": lead_intelligence,
    }


def _resolve_gmail_credentials(user_id: str) -> dict | None:
    """Resolve Gmail OAuth credentials from connected_accounts, refreshing if expired."""
    creds = get_google_credentials(user_id)
    if not creds:
        return None
    access_token = creds.get("access_token") or ""
    if is_token_expired(creds.get("token_expiry")):
        refresh_token = creds.get("refresh_token") or ""
        if not refresh_token:
            return None
        try:
            refreshed = refresh_access_token(refresh_token)
            access_token = refreshed.get("access_token", "")
            update_google_access_token(
                user_id,
                access_token=access_token,
                token_expiry=refreshed.get("token_expiry"),
            )
        except Exception:
            return None
    return {"access_token": access_token}


def send_outreach(input: dict) -> dict:
    lead = input.get("lead") or {}
    user_id = input.get("user_id")

    user = get_user(user_id) if user_id else None
    if user is None:
        return {
            "ok": False,
            "type": "send_outreach",
            "message": "Something went wrong on my end. Mind trying again?",
            "error": "missing_user",
        }

    creds = _resolve_gmail_credentials(user_id)
    if creds is None:
        if not get_google_credentials(user_id):
            return {
                "ok": False,
                "type": "send_outreach",
                "message": "Gmail isn't connected yet. Connect it once and I'll be able to send outreach directly from Loqi.",
                "error": "missing_google_tokens",
            }
        return {
            "ok": False,
            "type": "send_outreach",
            "message": "Your Gmail connection expired. Connect it again with /connect and I'll be ready to send.",
            "error": "token_refresh_failed",
        }

    company_intelligence = None
    lead_intelligence = None
    try:
        enricher = get_enricher()
        if enricher.health_check().get("ok"):
            company_intelligence = enricher.enrich_lead(lead)
    except Exception as e:
        print(f"[workflows] Enrichment failed during send (proceeding without): {e}")

    try:
        lead_intelligence = generate_lead_intelligence(lead, company_intelligence)
    except Exception as e:
        print(f"[workflows] Lead intelligence failed during send (proceeding without): {e}")

    try:
        knowledge_context = _workflow_knowledge_context(
            str(input.get("user_id") or ""), lead, input.get("campaign_strategy")
        )
        draft = generate_outreach_email(
            lead,
            company_intelligence,
            lead_intelligence,
            knowledge_context=knowledge_context,
        )

        # Route through Execution Engine via single-task Plan.
        # The globally registered Gmail BridgeAdapter (with its
        # credentials_factory) resolves per-user credentials from
        # credential_user_id — no per-request adapter construction.
        from services.execution.execution_pipeline import get_pipeline
        from services.execution.adapter_registry_resolver import get_planner_resolver
        from services.planner.planning_models import Plan, PlanStatus, Task, TaskType

        send_task = Task(
            type=TaskType.SEND_EMAIL,
            label="Send outreach email",
            instructions=f"Send outreach email to {lead.get('name', 'Unknown')}",
            params={
                "payload_type": "MessagePayload",
                "channel": "email",
                "template": "",
                "to": [lead.get("email", "")],
                "subject": draft.get("subject", "Sent"),
                "body_plain": draft.get("body", ""),
                "credential_user_id": user_id,
            },
        )
        plan = Plan(tasks=[send_task], status=PlanStatus.VALIDATED, strategy="direct_outreach")
        send_task.plan_id = plan.id

        resolver = get_planner_resolver()
        if resolver is None:
            raise Exception("Planner resolver not available — global registry not initialised")

        session = _run_async(get_pipeline().execute(plan, resolver=resolver))

        etask = session.tasks.get(send_task.id)
        if not etask or not etask.result or not etask.result.success:
            raise Exception(
                (etask and etask.result and etask.result.error) or "Send failed"
            )
    except OpenAIError as e:
        return {
            "ok": False,
            "type": "send_outreach",
            "message": "I couldn't generate the email content. Let me try again — or adjust the draft first.",
            "error": f"openai_error: {e}",
        }
    except Exception:
        return {
            "ok": False,
            "type": "send_outreach",
            "message": "The email didn't go through. Gmail may need reconnecting — try /connect to set it up again.",
            "error": "send_failed",
        }

    company = (lead.get("company") or "").replace("Unknown Company", "").strip()
    company_part = f" @ {company}" if company else ""
    subject = draft.get("subject", "Sent")

    return {
        "ok": True,
        "type": "send_outreach",
        "message": (
            "Looks good — I'll send this from your connected Gmail.\n\n"
            f"To: {lead.get('name', 'Unknown')}{company_part}\n"
            f"Subject: {subject}"
        ),
        "result": draft,
    }


def run_workflow(input: dict) -> dict:
    workflow_type = input.get("type")

    if workflow_type == "generate_leads":
        return generate_leads(input)

    if workflow_type == "draft_message":
        return draft_message(input)

    if workflow_type == "send_outreach":
        return send_outreach(input)

    return {
        "ok": False,
        "type": workflow_type,
        "message": "Unknown workflow.",
        "error": "unknown_workflow",
    }
