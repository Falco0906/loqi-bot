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
from services.conversation_engine import ConversationEngine
from services.google_auth import exchange_code_for_tokens
from services.supabase import save_google_tokens, test_supabase_connection
from services.telegram import send_message
from services.campaign_planner import analyze_campaigns
from workflows import run_workflow

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


def _parse_draft_body(message: str) -> str | None:
    if "Draft ready:" not in message or "---" not in message:
        return None
    parts = message.split("---")
    return parts[1].strip() if len(parts) >= 3 else None


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
    if campaign_id:
        campaigns = campaign_store.get(session_token, [])
        for c in campaigns:
            if c.get("id") == campaign_id:
                c["status"] = "draft_review"
                c["updated_at"] = datetime.now(timezone.utc).isoformat()
                break

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
        from services.conversational_response_generator import generate_copilot_response
        response_text = generate_copilot_response(
            user_message=payload.text,
            copilot_context=payload.copilot.model_dump(),
            context={
                "user_id": summary.get("user_id"),
                "service": "",
                "target": "",
            },
        )
        msg = _message(role="assistant", message_type="text", text=response_text)
        return {"ok": True, "messages": [msg], "events": []}

    return engine.handle_message(
        channel="web",
        external_user_id=session_token,
        text=payload.text,
        username=summary.get("display_name"),
    )


class BatchDraftRequest(BaseModel):
    leads: list[dict]
    campaign_id: str | None = None


class RefineDraftRequest(BaseModel):
    edit_request: str
    previous_message: str
    lead: dict


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

    loop = asyncio.get_event_loop()
    try:
        workflow_result = await loop.run_in_executor(
            None,
            run_workflow,
            {
                "type": "draft_message",
                "lead": payload.lead,
                "edit_request": payload.edit_request,
                "previous_message": payload.previous_message,
            },
        )
        new_body = _parse_draft_body(workflow_result.get("message", ""))
        if new_body:
            target["text"] = new_body
            target["status"] = "pending"
        return {"ok": True, "draft": target}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/web/session/{session_token}/drafts/{draft_id}/approve")
async def approve_draft(session_token: str, draft_id: str):
    drafts = draft_store.get(session_token, [])
    for d in drafts:
        if d.get("id") == draft_id:
            d["status"] = "approved" if d.get("status") != "approved" else "pending"
            return {"ok": True, "draft": d}
    raise HTTPException(status_code=404, detail="Draft not found")


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
    return {"ok": True, "campaign": campaign}


@app.get("/api/web/session/{session_token}/campaigns")
async def list_campaigns(session_token: str):
    campaigns = campaign_store.get(session_token, [])

    def _enrich(c: dict) -> dict:
        cid = c.get("id", "")
        drafts = [d for d in draft_store.get(session_token, []) if d.get("campaign_id") == cid]
        pending = sum(1 for d in drafts if d.get("status") == "pending")
        approved = sum(1 for d in drafts if d.get("status") == "approved")
        return {**c, "pending_drafts": pending, "approved_drafts": approved}

    return {"ok": True, "campaigns": [_enrich(c) for c in campaigns]}


@app.get("/api/web/session/{session_token}/campaigns/summary")
async def campaign_summary(session_token: str):
    campaigns = campaign_store.get(session_token, [])
    items = []
    for c in campaigns:
        cid = c.get("id", "")
        drafts = [d for d in draft_store.get(session_token, []) if d.get("campaign_id") == cid]
        pending = sum(1 for d in drafts if d.get("status") == "pending")
        items.append({
            "id": cid,
            "name": c.get("name", ""),
            "status": c.get("status", "planning"),
            "lead_count": c.get("lead_count", 0),
            "pending_drafts": pending,
            "updated_at": c.get("updated_at", ""),
        })
    return {"ok": True, "campaigns": items}


@app.get("/api/web/session/{session_token}/campaigns/{campaign_id}")
async def get_campaign(session_token: str, campaign_id: str):
    campaigns = campaign_store.get(session_token, [])
    target = next((c for c in campaigns if c.get("id") == campaign_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Campaign not found")
    drafts = [d for d in draft_store.get(session_token, []) if d.get("campaign_id") == campaign_id]
    pending = sum(1 for d in drafts if d.get("status") == "pending")
    approved = sum(1 for d in drafts if d.get("status") == "approved")
    return {"ok": True, "campaign": {**target, "pending_drafts": pending, "approved_drafts": approved}}


@app.put("/api/web/session/{session_token}/campaigns/{campaign_id}")
async def update_campaign(session_token: str, campaign_id: str, payload: UpdateCampaignRequest):
    campaigns = campaign_store.get(session_token, [])
    target = next((c for c in campaigns if c.get("id") == campaign_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if payload.name is not None:
        target["name"] = payload.name
    if payload.status is not None:
        target["status"] = payload.status
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


@app.get("/api/web/session/{session_token}/export-csv")
async def export_csv(session_token: str):
    leads: list[dict] = []
    for d in draft_store.get(session_token, []):
        lead = d.get("lead")
        if lead:
            leads.append(lead)

    if not leads:
        from services.conversation_engine import ConversationEngine
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


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "10000"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
