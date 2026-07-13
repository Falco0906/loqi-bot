import asyncio
import csv
import io
import logging
import os
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from pydantic import BaseModel
from services.agent import process_message
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
from services.executive_brief import generate_brief
from services.draft_intelligence import analyze_draft as analyze_draft_intelligence
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

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("loqi")

request_id_var: ContextVar[str] = ContextVar("request_id")

app = FastAPI()
engine = ConversationEngine()
_start_time = time.time()

# ── In-memory batch / draft / campaign stores ──
batch_jobs: dict[str, dict[str, Any]] = {}
draft_store: dict[str, list[dict[str, Any]]] = {}
campaign_store: dict[str, list[dict[str, Any]]] = {}


def _build_copilot_workspace_context(session_token: str, current_page: str | None = None, page_context: dict | None = None) -> dict:
    campaigns = campaign_store.get(session_token, [])
    drafts = draft_store.get(session_token, [])
    total_leads = sum(c.get("lead_count", 0) or 0 for c in campaigns)
    from services.workspace_snapshot import build_snapshot
    snapshot = build_snapshot(session_token, campaigns, drafts, total_leads)
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

    return result


def _parse_draft_body(message: str) -> str | None:
    if "Draft ready:" not in message or "---" not in message:
        return None
    parts = message.split("---")
    return parts[1].strip() if len(parts) >= 3 else None


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

            job["drafts"].append(draft_entry)
            job["completed"] = i + 1

            if session_token not in draft_store:
                draft_store[session_token] = []
            draft_store[session_token].append(draft_entry)

        except Exception as e:
            print(f"[batch] Draft failed for lead {i} ({name}): {e}")
            job["completed"] = i + 1

    job["status"] = "completed"

    campaign_id = job.get("campaign_id")
    campaign_name = None
    if campaign_id:
        campaigns = campaign_store.get(session_token, [])
        for c in campaigns:
            if c.get("id") == campaign_id:
                c["status"] = "draft_review"
                c["updated_at"] = datetime.now(timezone.utc).isoformat()
                campaign_name = c.get("name")
                break
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
    return response


# ── CORS Configuration ──

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
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


@app.on_event("startup")
def startup_event():
    required_vars = ["OPENAI_API_KEY"]
    missing = [v for v in required_vars if not os.getenv(v)]
    if missing:
        log.warning("Missing required environment variables: %s", ", ".join(missing))
    log.info("SUPABASE_URL=%s", "set" if os.getenv("SUPABASE_URL") else "not set")
    log.info("SUPABASE_KEY=%s", "set" if os.getenv("SUPABASE_KEY") else "not set")
    try:
        test_supabase_connection()
    except Exception as e:
        log.warning("Supabase connection test failed: %s", e)
    register_workflows()
    try:
        from services.migration import apply_migrations
        apply_migrations()
    except Exception as e:
        log.warning("Migration check failed: %s", e)
    log.info("Job engine initialized")
    try:
        recovered = recover_all()
        if recovered["total_recovered"] > 0:
            log.info("Workflow recovery: %s", recovered)
    except Exception as e:
        log.warning("Workflow recovery failed: %s", e)


@app.get("/", response_class=PlainTextResponse)
def read_root():
    return "Loqi backend running"


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
            process_message(chat_id, telegram_id, text, username=username)

        return {"status": "ok"}
    except Exception as error:
        print(f"Error processing webhook: {error}")
        return {"status": "error", "message": str(error)}


@app.post("/api/web/session")
async def create_web_session(payload: CreateWebSessionRequest):
    try:
        return engine.create_web_session(display_name=payload.display_name)
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
async def post_web_session_message(session_token: str, payload: SendWebMessageRequest):
    import time; _t0 = time.time()
    print(f"[TRACE] 1 | ENTERED ENDPOINT | post_web_session_message | +0ms")
    summary = engine.get_web_session_summary(session_token)

    if summary is None:
        created = engine.create_web_session(display_name="web-user")
        if created is None:
            raise HTTPException(status_code=500, detail="Unable to create session")
        summary = engine.get_web_session_summary(created["session_token"])
        if summary is None:
            raise HTTPException(status_code=500, detail="Session creation failed")
        return engine.handle_message(
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

    _result = engine.handle_message(
        channel="web",
        external_user_id=session_token,
        text=payload.text,
        username=summary.get("display_name"),
    )
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
    search_query: str = ""
    lead_count: int = 0
    leads: list[dict] | None = None
    strategy: dict | None = None
    status: str = "planning"


class UpdateCampaignRequest(BaseModel):
    name: str | None = None
    status: str | None = None


class GenerateDraftsRequest(BaseModel):
    campaign_id: str


class SelectLeadRequest(BaseModel):
    index: int


@app.post("/api/web/session/{session_token}/batch-draft")
async def batch_draft(session_token: str, payload: BatchDraftRequest):
    if not payload.leads:
        raise HTTPException(status_code=400, detail="No leads provided")
    batch_id = str(uuid.uuid4())
    total = len(payload.leads)
    batch_jobs[batch_id] = {
        "status": "processing",
        "total": total,
        "completed": 0,
        "current_index": -1,
        "current_name": None,
        "drafts": [],
        "error": None,
        "campaign_id": payload.campaign_id,
    }
    asyncio.create_task(_process_batch_drafts(session_token, batch_id, payload.leads))
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
async def list_drafts(session_token: str):
    drafts = draft_store.get(session_token, [])
    return {"ok": True, "drafts": drafts}


@app.put("/api/web/session/{session_token}/drafts/{draft_id}")
async def update_draft(session_token: str, draft_id: str, payload: UpdateDraftRequest):
    drafts = draft_store.get(session_token, [])
    for d in drafts:
        if d.get("id") == draft_id:
            d["text"] = payload.text
            return {"ok": True, "draft": d}
    raise HTTPException(status_code=404, detail="Draft not found")


@app.post("/api/web/session/{session_token}/drafts/{draft_id}/refine")
async def refine_draft(session_token: str, draft_id: str, payload: RefineDraftRequest):
    drafts = draft_store.get(session_token, [])
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

            push_rewrite_history(
                session_token, draft_id,
                previous_text=previous_text,
                reason=payload.edit_request or "AI rewrite",
                strategy="custom",
                change_summary=["✓ Draft rewritten"],
            )

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


@app.post("/api/web/session/{session_token}/drafts/{draft_id}/approve")
async def approve_draft(session_token: str, draft_id: str):
    drafts = draft_store.get(session_token, [])
    toggled = None
    campaign_id = None
    for d in drafts:
        if d.get("id") == draft_id:
            d["status"] = "approved" if d.get("status") != "approved" else "pending"
            toggled = d
            campaign_id = d.get("campaign_id")
            break
    if not toggled:
        raise HTTPException(status_code=404, detail="Draft not found")

    campaign_status = None
    if campaign_id:
        cdrafts = [d for d in drafts if d.get("campaign_id") == campaign_id]
        all_approved = all(d.get("status") == "approved" for d in cdrafts)
        campaigns = campaign_store.get(session_token, [])
        for c in campaigns:
            if c.get("id") == campaign_id:
                c["status"] = "ready_to_send" if all_approved else "draft_review"
                c["updated_at"] = datetime.now(timezone.utc).isoformat()
                campaign_status = c["status"]
                break

    pending_drafts = sum(1 for d in draft_store.get(session_token, []) if d.get("campaign_id") == campaign_id and d.get("status") == "pending") if campaign_id else 0
    if toggled and toggled.get("status") == "approved":
        lead_name = toggled.get("lead", {}).get("name", "Unknown")
        campaign_name = None
        if campaign_id:
            for c in campaign_store.get(session_token, []):
                if c.get("id") == campaign_id:
                    campaign_name = c.get("name")
                    break
        record_draft_approved(session_token, lead_name, campaign_name)
        if campaign_status == "ready_to_send" and campaign_name:
            record_campaign_ready(session_token, campaign_name)
    return {
        "ok": True,
        "draft": toggled,
        "campaign_status": campaign_status,
        "pending_drafts": pending_drafts,
    }


@app.post("/api/web/session/{session_token}/drafts/{draft_id}/undo")
async def undo_draft(session_token: str, draft_id: str):
    drafts = draft_store.get(session_token, [])
    target = next((d for d in drafts if d.get("id") == draft_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Draft not found")

    entry = undo_rewrite_history(session_token, draft_id)
    if entry is None:
        raise HTTPException(status_code=400, detail="No history to undo")

    target["text"] = entry.previous_text
    target["status"] = "pending"
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


@app.post("/api/web/session/{session_token}/campaigns")
async def save_campaign(session_token: str, payload: SaveCampaignRequest):
    if session_token not in campaign_store:
        campaign_store[session_token] = []
    now = datetime.now(timezone.utc).isoformat()
    leads = payload.leads or []
    campaign = {
        "id": str(uuid.uuid4()),
        "name": payload.name,
        "search_query": payload.search_query,
        "lead_count": payload.lead_count or len(leads),
        "leads": leads,
        "status": payload.status,
        "strategy": payload.strategy,
        "created_at": now,
        "updated_at": now,
    }
    campaign_store[session_token].append(campaign)
    record_campaign_created(session_token, payload.name)
    return {"ok": True, "campaign": campaign}


@app.get("/api/web/session/{session_token}/campaigns")
async def list_campaigns(session_token: str):
    from services.workspace_snapshot import enrich_campaigns
    campaigns = campaign_store.get(session_token, [])
    drafts = draft_store.get(session_token, [])
    return {"ok": True, "campaigns": enrich_campaigns(campaigns, drafts)}


@app.get("/api/web/session/{session_token}/campaigns/summary")
async def campaign_summary(session_token: str):
    from services.workspace_snapshot import enrich_campaigns
    campaigns = campaign_store.get(session_token, [])
    drafts = draft_store.get(session_token, [])
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
async def get_campaign(session_token: str, campaign_id: str):
    from services.workspace_snapshot import enrich_campaigns
    campaigns = campaign_store.get(session_token, [])
    drafts = draft_store.get(session_token, [])
    enriched = enrich_campaigns(campaigns, drafts)
    target = next((c for c in enriched if c.get("id") == campaign_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Campaign not found")
    record_campaign_open(session_token, campaign_id, target.get("name", ""))
    return {"ok": True, "campaign": target}


@app.put("/api/web/session/{session_token}/campaigns/{campaign_id}")
async def update_campaign(session_token: str, campaign_id: str, payload: UpdateCampaignRequest):
    campaigns = campaign_store.get(session_token, [])
    target = next((c for c in campaigns if c.get("id") == campaign_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if payload.name is not None:
        target["name"] = payload.name
    if payload.status is not None:
        old_status = target.get("status", "")
        target["status"] = payload.status
        if payload.status == "completed" and old_status != "completed":
            record_campaign_launched(session_token, target.get("name", ""))
        elif payload.status in ("ready", "ready_to_send"):
            record_campaign_ready(session_token, target.get("name", ""))
    target["updated_at"] = datetime.now(timezone.utc).isoformat()
    return {"ok": True, "campaign": target}


@app.delete("/api/web/session/{session_token}/campaigns/{campaign_id}")
async def delete_campaign(session_token: str, campaign_id: str):
    campaigns = campaign_store.get(session_token, [])
    target = next((c for c in campaigns if c.get("id") == campaign_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Campaign not found")
    target["status"] = "archived"
    target["updated_at"] = datetime.now(timezone.utc).isoformat()
    return {"ok": True, "campaign": target}


@app.get("/api/web/session/{session_token}/campaigns/{campaign_id}/drafts")
async def list_campaign_drafts(session_token: str, campaign_id: str):
    all_drafts = draft_store.get(session_token, [])
    filtered = [d for d in all_drafts if d.get("campaign_id") == campaign_id]
    return {"ok": True, "drafts": filtered}


@app.post("/api/web/session/{session_token}/campaigns/{campaign_id}/generate-drafts")
async def generate_campaign_drafts(session_token: str, campaign_id: str):
    campaigns = campaign_store.get(session_token, [])
    target = next((c for c in campaigns if c.get("id") == campaign_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Campaign not found")

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
    batch_jobs[batch_id] = {
        "status": "processing",
        "total": total,
        "completed": 0,
        "current_index": -1,
        "current_name": None,
        "drafts": [],
        "error": None,
        "campaign_id": campaign_id,
    }
    target["status"] = "generating"
    target["updated_at"] = datetime.now(timezone.utc).isoformat()
    asyncio.create_task(_process_batch_drafts(session_token, batch_id, leads))
    return {"ok": True, "batch_id": batch_id, "total": total}


@app.get("/api/web/session/{session_token}/campaigns/{campaign_id}/generation-status")
async def campaign_generation_status(session_token: str, campaign_id: str):
    active_jobs = [
        {"batch_id": bid, **job}
        for bid, job in batch_jobs.items()
        if job.get("campaign_id") == campaign_id
    ]
    if not active_jobs:
        return {"ok": True, "active": False, "jobs": []}
    latest = max(active_jobs, key=lambda j: j.get("current_index", -1))
    return {
        "ok": True,
        "active": latest.get("status") == "processing",
        "status": latest.get("status"),
        "total": latest.get("total", 0),
        "completed": latest.get("completed", 0),
        "batch_id": latest.get("batch_id"),
    }


@app.get("/api/web/session/{session_token}/mission-control")
async def mission_control_summary(session_token: str):
    campaigns = campaign_store.get(session_token, [])
    drafts = draft_store.get(session_token, [])
    now = datetime.now(timezone.utc)

    total_leads = sum(c.get("lead_count", 0) or 0 for c in campaigns)
    pending_drafts = sum(1 for d in drafts if d.get("status") == "pending")
    approved_drafts = sum(1 for d in drafts if d.get("status") == "approved")
    reply_rate_heuristic = round((approved_drafts / len(drafts) * 100) if drafts else 0)

    snapshot = build_snapshot(session_token, campaigns, drafts, total_leads)
    analysis = snapshot.get("analysis", {})
    recommendations = generate_recommendations(snapshot)
    brief = generate_brief(snapshot, recommendations)

    campaign_list = snapshot.get("campaigns", [])
    user_id = f"web:{session_token}"
    try:
        current_jobs = job_manager.list_active_jobs(user_id)
    except Exception:
        current_jobs = []

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
        "draft_counts": {"pending": pending_drafts, "approved": approved_drafts, "total": len(drafts)},
        "needs_attention": needs_attention,
        "live_activity": grouped_activity,
        "campaign_count": len(campaign_list),
        "active_jobs": current_jobs,
        "recommendations": recommendations[:3],
        "kpis": {
            "estimated_reply_rate": reply_rate_heuristic,
            "pending_reviews": pending_drafts,
            "campaigns_ready": analysis.get("workspace_health", {}).get("campaigns_ready", 0),
        },
        "total_leads": total_leads,
        "brief": brief,
        "workspace_memory": snapshot.get("memory", {}),
        "workspace_analysis": {
            "current_focus": analysis.get("current_focus"),
            "recommended_next_action": analysis.get("recommended_next_action"),
            "campaign_priorities": analysis.get("campaign_priorities", [])[:8],
            "workspace_health": analysis.get("workspace_health"),
            "cross_campaign_insights": analysis.get("cross_campaign_insights", []),
            "workflow_continuation": analysis.get("workflow_continuation"),
        },
    }


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
def list_jobs(request: Request):
    session_token = request.headers.get("x-session-token", "")
    summary = engine.get_web_session_summary(session_token) if session_token else None
    user_id = summary.get("user_id") if summary else None
    if not user_id:
        return {"jobs": []}
    jobs = job_manager.list_active_jobs(user_id)
    return {"jobs": jobs}


@app.post("/api/web/session/{session_token}/plan")
async def plan_workflow_endpoint(session_token: str, payload: PlanningInput):
    campaigns = campaign_store.get(session_token, [])
    drafts = draft_store.get(session_token, [])
    total_leads = sum(c.get("lead_count", 0) or 0 for c in campaigns)
    snapshot = build_snapshot(session_token, campaigns, drafts, total_leads)
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
