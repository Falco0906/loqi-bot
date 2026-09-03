"""Canonical durable Draft review and lifecycle use cases."""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from services.draft_comparison import compare_versions
from services.draft_intelligence import analyze_draft as analyze_draft_intelligence
from services.events_bus import publish_draft_event
from services.outbound import service as outbound_service
from services.rewrite_engine import execute_rewrite
from services.world_model import EventType as WMEventType, publish
from services.workspace_timeline import record_drafts_generated
from workflows import run_workflow

log = logging.getLogger("loqi")

# Temporary compatibility state for legacy batch routes. R5-B-6b will move
# batch execution and recovery to the durable job engine.
batch_jobs: dict[str, dict[str, Any]] = {}
_draft_batch_tasks: dict[str, asyncio.Task] = {}


_SYNONYM_STRATEGY_TABLE = [
    (["shorter", "concise", "brief", "trim", "cut down"], "shorten"),
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
_CONTEXT_FIELDS = (
    "campaign_id", "campaign_name", "company", "contact", "role", "industry",
    "messaging_angle", "business_summary",
)


def _parse_draft_body(message: str) -> str | None:
    if "Draft ready:" not in message or "---" not in message:
        return None
    parts = message.split("---")
    return parts[1].strip() if len(parts) >= 3 else None


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


def register_draft_batch_workflow() -> None:
    """Register the durable draft-batch worker before enqueue or recovery."""
    from services.job_engine.registry import WorkflowRegistration, get_registry

    registry = get_registry()
    if not registry.has("draft_batch"):
        registry.register(WorkflowRegistration(
            type="draft_batch",
            description="Campaign draft generation",
            runner_fn=run_draft_batch_job,
        ))


def _batch_item_key(lead: dict[str, Any], position: int) -> str:
    identity = str(lead.get("id") or lead.get("email") or lead.get("linkedin_url") or position)
    return f"{position}:{identity}"


async def enqueue_draft_batch(
    session_token: str,
    owner_id: str,
    workspace_id: str,
    leads: list[dict[str, Any]],
    campaign_id: str = "",
) -> dict[str, Any]:
    """Durably create one draft batch and its item snapshots before queueing it."""
    from services.job_engine import Job, job_manager
    from services.job_engine.models import BatchItem

    register_draft_batch_workflow()
    job = Job(
        user_id=owner_id,
        type="draft_batch",
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        payload={"session_token": session_token, "total": len(leads)},
    )
    items = [
        BatchItem(
            job_id=job.id,
            workspace_id=workspace_id,
            campaign_id=campaign_id,
            position=position,
            lead_snapshot=dict(lead),
            idempotency_key=_batch_item_key(lead, position),
        )
        for position, lead in enumerate(leads)
    ]
    created = await job_manager.create_batch_job(job, items)
    if not created:
        raise HTTPException(status_code=503, detail="Draft generation could not be scheduled")
    return {"batch_id": job.id, "total": len(items), "status": "queued"}


async def run_draft_batch_job(job, on_progress) -> dict[str, Any]:
    """Generate drafts from durable batch items, resuming incomplete items only."""
    from services.job_engine import job_manager
    from services.workspace_state import load_campaign_state, persist_draft_awaited

    storage = job_manager._storage
    items = await asyncio.to_thread(storage.list_batch_resume_items, job.id, job.workspace_id)
    session_token = str((job.payload or {}).get("session_token") or "")
    campaign = await asyncio.to_thread(
        load_campaign_state, job.user_id, job.campaign_id, workspace_id=job.workspace_id,
    ) if job.campaign_id else {}
    strategy = dict((campaign or {}).get("strategy") or {})
    completed = 0
    loop = asyncio.get_running_loop()

    for item in items:
        if not await asyncio.to_thread(storage.mark_batch_item_generating, item.id):
            continue
        lead = item.lead_snapshot
        name = str(lead.get("name") or lead.get("company") or "Unknown")
        progress = int((item.position / max(len(items), 1)) * 100)
        on_progress(job.id, f"Generating draft for {name}", progress)
        try:
            result = await _run_draft_with_retry(loop, {"type": "draft_message", "campaign_strategy": strategy, "lead": lead})
            draft = {
                "id": str(uuid.uuid4()), "campaign_id": job.campaign_id,
                "batch_id": job.id, "lead": lead, "subject": result.get("subject", ""),
                "text": _parse_draft_body(result.get("message", "")) or result.get("message", ""),
                "status": "pending", "created_at": datetime.now(timezone.utc).isoformat(),
            }
            if not await persist_draft_awaited(job.user_id, draft):
                raise RuntimeError("Draft could not be persisted")
            if not await asyncio.to_thread(storage.mark_batch_item_completed, job.id, item.idempotency_key, draft["id"]):
                raise RuntimeError("Draft completion could not be persisted")
            completed += 1
            publish(session_token, WMEventType.DRAFT_GENERATED, {"id": draft["id"], "campaign_id": job.campaign_id, "lead_name": name, "subject": draft["subject"], "body_preview": draft["text"][:200]}, actor="system")
        except Exception as error:
            await asyncio.to_thread(storage.mark_batch_item_failed, item.id, str(error))
    return {"ok": True, "result": {"total": len(items), "completed": completed}}


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

            await publish_draft_event(
                owner_id, "draft.created",
                draft_id=draft_entry["id"],
                campaign_id=str(draft_entry["campaign_id"] or ""),
                lead_name=name,
            )
            outbound_service.sync_draft_to_outbound(draft_entry, session_token, owner_id=owner_id)

        except Exception as e:
            print(f"[batch] Draft failed for lead {i} ({name}): {e}")
            publish(session_token, WMEventType.DRAFT_FAILED, {
                "lead_index": i,
                "lead_index": i,
                "lead_name": name,
                "error": str(e),
                "campaign_id": job.get("campaign_id"),
            }, actor="system")
            job["completed"] = i + 1
            await publish_draft_event(
                owner_id, "draft.generation_failed",
                campaign_id=str(job.get("campaign_id") or ""),
                lead_name=name,
                extra={"lead_index": i},
            )

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
    final_status = "draft.generation_completed" if job["status"] != "failed" else "draft.generation_failed"
    await publish_draft_event(
        owner_id, final_status,
        campaign_id=str(campaign_id or ""),
        extra={"completed": job.get("completed", 0), "total": job.get("total", 0)},
    )
    if campaign_name:
        record_drafts_generated(session_token, campaign_name, job.get("completed", 0))


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
    from services.workspace_state import load_drafts_only, persist_campaign_update
    drafts = load_drafts_only(owner_id)
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


# Product decision for R5-B: draft text is durable, but rewrite undo/version
# history is intentionally unavailable after this migration. We do not retain a
# process-local copy that would silently disappear on restart or session change.


def load_drafts(owner_id: str, *, workspace_id: str = "") -> list[dict[str, Any]]:
    """Load canonical workspace drafts without legacy session projections."""
    from services.workspace_state import load_drafts_only

    return load_drafts_only(owner_id, workspace_id=workspace_id)


def _context(payload: dict[str, Any]) -> dict[str, Any]:
    return {field: payload[field] for field in _CONTEXT_FIELDS if payload.get(field)}


def _rewrite_strategy(instruction: str) -> str:
    lower = instruction.lower()
    best_match, best_count = None, 0
    for keywords, strategy in _SYNONYM_STRATEGY_TABLE:
        count = sum(keyword in lower for keyword in keywords)
        if count > best_count:
            best_match, best_count = strategy, count
    return best_match or "custom"


def _draft_body(message: str) -> str | None:
    if "Draft ready:" not in message or "---" not in message:
        return None
    parts = message.split("---")
    return parts[1].strip() if len(parts) >= 3 else None


async def list_drafts(owner_id: str, workspace_id: str) -> dict[str, Any]:
    return {"ok": True, "drafts": await asyncio.to_thread(load_drafts, owner_id, workspace_id=workspace_id)}


async def update_draft(session_token: str, owner_id: str, draft_id: str, text: str) -> dict[str, Any]:
    from services.workspace_state import persist_draft_update

    drafts = load_drafts(owner_id)
    for draft in drafts:
        if draft.get("id") != draft_id:
            continue
        if not persist_draft_update(owner_id, draft_id, {"text": text, "status": "pending"}):
            raise HTTPException(status_code=503, detail="Draft could not be persisted")
        draft["text"] = text
        draft["status"] = "pending"
        publish(session_token, WMEventType.DRAFT_UPDATED, {
            "draft_id": draft_id, "campaign_id": draft.get("campaign_id", ""),
            "lead_name": draft.get("lead", {}).get("name", ""),
        }, actor="user")
        return {"ok": True, "draft": draft}
    raise HTTPException(status_code=404, detail="Draft not found")


async def refine_draft(
    session_token: str, owner_id: str, draft_id: str, payload: dict[str, Any],
) -> dict[str, Any]:
    from services.workspace_state import persist_draft_update

    target = next((draft for draft in load_drafts(owner_id) if draft.get("id") == draft_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Draft not found")
    context = _context(payload)
    try:
        if payload.get("edit_request") and payload.get("previous_message"):
            strategy = _rewrite_strategy(payload["edit_request"])
            rewrite_result = await asyncio.to_thread(
                execute_rewrite, payload["previous_message"], strategy, context or None,
                payload["edit_request"] if strategy == "custom" else None,
            )
            previous_text = target["text"]
            target.update({"text": rewrite_result.text, "status": "pending"})
            if not persist_draft_update(owner_id, draft_id, {"text": target["text"], "status": "pending"}):
                raise RuntimeError("Draft rewrite could not be persisted")
            comparison = await asyncio.to_thread(
                compare_versions, previous_text, rewrite_result.text, rewrite_result.change_summary,
            )
            try:
                intelligence = await asyncio.to_thread(
                    analyze_draft_intelligence, rewrite_result.text, context or None,
                )
            except Exception:
                intelligence = None
            publish(session_token, WMEventType.DRAFT_UPDATED, {
                "draft_id": draft_id, "campaign_id": target.get("campaign_id", ""),
                "strategy": strategy, "change_summary": rewrite_result.change_summary or [],
            }, actor="user")
            return {
                "ok": True, "draft": target, "rewritten_text": rewrite_result.text,
                "change_summary": rewrite_result.change_summary,
                "draft_intelligence": intelligence.to_dict() if intelligence else None,
                "version": 1, "confidence": rewrite_result.confidence,
                "comparison": comparison.to_dict(),
            }
        workflow_input = {
            "type": "draft_message", "lead": payload.get("lead"),
            "edit_request": payload.get("edit_request"),
            "previous_message": payload.get("previous_message"),
        }
        if context:
            workflow_input["context"] = context
        workflow_result = await asyncio.to_thread(run_workflow, workflow_input)
        new_body = _draft_body(workflow_result.get("message", ""))
        rewritten_text = new_body or target["text"]
        if new_body:
            previous_text = target["text"]
            target.update({"text": new_body, "status": "pending"})
            if not persist_draft_update(owner_id, draft_id, {"text": target["text"], "status": "pending"}):
                raise RuntimeError("Draft rewrite could not be persisted")
        publish(session_token, WMEventType.DRAFT_UPDATED, {
            "draft_id": draft_id, "campaign_id": target.get("campaign_id", ""),
            "method": "workflow_rewrite",
        }, actor="user")
        return {"ok": True, "draft": target, "rewritten_text": rewritten_text}
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


async def analyze_draft(payload: dict[str, Any]) -> dict[str, Any]:
    context = _context(payload)
    try:
        workflow_result = await asyncio.to_thread(
            run_workflow,
            {"type": "draft_analysis", "draft_text": payload["draft_text"], "context": context},
        )
        try:
            intelligence = await asyncio.to_thread(
                analyze_draft_intelligence, payload["draft_text"], context or None,
            )
        except Exception:
            intelligence = None
        return {
            "ok": workflow_result.get("ok", False), "analysis": workflow_result.get("analysis"),
            "draft_intelligence": intelligence.to_dict() if intelligence else None,
            "error": workflow_result.get("error"),
        }
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


async def ask_draft_question(payload: dict[str, Any]) -> dict[str, Any]:
    context = _context(payload)
    try:
        workflow_result = await asyncio.to_thread(
            run_workflow,
            {"type": "draft_question", "question": payload["question"],
             "draft_text": payload["draft_text"], "context": context},
        )
        return {
            "ok": workflow_result.get("ok", False), "answer": workflow_result.get("answer"),
            "error": workflow_result.get("error"),
        }
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


async def approve_draft(
    session_token: str, owner_id: str, workspace_id: str, draft_id: str,
) -> dict[str, Any]:
    from services.workspace_snapshot import enrich_campaigns
    from services.workspace_state import load_workspace_state, persist_draft_update_awaited

    state = await asyncio.to_thread(
        load_workspace_state, owner_id, include_details=False, workspace_id=workspace_id,
    )
    target = next((draft for draft in state["drafts"] if draft.get("id") == draft_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Draft not found in the durable workspace")
    if target.get("status") in ("sent", "sending"):
        raise HTTPException(status_code=409, detail="Draft already sent")
    new_status = "approved" if target.get("status") != "approved" else "pending"
    if not await persist_draft_update_awaited(
        owner_id, draft_id, {"status": new_status}, workspace_id=workspace_id,
    ):
        raise HTTPException(status_code=503, detail="Draft approval could not be persisted")
    target["status"] = new_status
    campaign_id = target.get("campaign_id")
    if new_status == "approved":
        outbound_service.sync_draft_to_outbound(target, session_token, owner_id=owner_id)
        outbound_service.create_provider_draft_after_approval(draft_id)
        await publish_draft_event(
            owner_id, "draft.approved", draft_id=draft_id,
            campaign_id=str(campaign_id or ""),
            lead_name=(target.get("lead") or {}).get("name", ""),
        )
    current_step, pending_in_campaign = None, 0
    if campaign_id:
        enriched = next(
            (campaign for campaign in enrich_campaigns(state["campaigns"], state["drafts"])
             if campaign.get("id") == campaign_id),
            None,
        )
        if enriched:
            current_step = enriched.get("current_step")
            pending_in_campaign = int(enriched.get("pending_drafts", 0) or 0)
    publish(session_token, WMEventType.DRAFT_APPROVED if new_status == "approved" else WMEventType.DRAFT_UPDATED, {
        "draft_id": draft_id, "campaign_id": campaign_id, "status": new_status,
    }, actor="user")
    return {"ok": True, "draft": target, "current_step": current_step,
            "pending_drafts": pending_in_campaign}


async def undo_draft(session_token: str, owner_id: str, draft_id: str) -> dict[str, Any]:
    from services.workspace_state import persist_draft_update

    target = next((draft for draft in load_drafts(owner_id) if draft.get("id") == draft_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Draft not found")
    raise HTTPException(status_code=400, detail="No history to undo")


async def draft_history(session_token: str, owner_id: str, draft_id: str) -> dict[str, Any]:
    from services.outbound.draft_store import draft_store

    draft = draft_store.get(draft_id) if hasattr(draft_store, "get") else None
    if not outbound_service.outbound_draft_owned_by(draft, owner_id):
        raise HTTPException(status_code=404, detail="Draft not found")
    return {"ok": True, "history": [], "current_version": 1}


async def compare_draft_versions(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        comparison = compare_versions(
            payload["old_text"], payload["new_text"], payload.get("change_summary"),
        )
        return {"ok": True, "comparison": comparison.to_dict()}
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))
