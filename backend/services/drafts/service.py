"""Canonical durable Draft review and lifecycle use cases."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import HTTPException

from services.draft_comparison import compare_versions
from services.draft_intelligence import analyze_draft as analyze_draft_intelligence
from services.events_bus import publish_draft_event
from services.outbound import service as outbound_service
from services.rewrite_engine import execute_rewrite
from services.rewrite_history import (
    get_current_version,
    get_history,
    push,
    undo,
)
from services.world_model import EventType as WMEventType, publish
from workflows import run_workflow


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
            version = push(
                session_token, draft_id, previous_text=previous_text,
                reason=payload["edit_request"], strategy=strategy,
                change_summary=rewrite_result.change_summary,
            )
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
                "version": version, "confidence": rewrite_result.confidence,
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
            push(
                session_token, draft_id, previous_text=previous_text,
                reason=payload.get("edit_request") or "AI rewrite", strategy="custom",
                change_summary=["✓ Draft rewritten"],
            )
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
    entry = undo(session_token, draft_id)
    if entry is None:
        raise HTTPException(status_code=400, detail="No history to undo")
    target.update({"text": entry.previous_text, "status": "pending"})
    if not persist_draft_update(owner_id, draft_id, {"text": target["text"], "status": "pending"}):
        raise HTTPException(status_code=503, detail="Draft undo could not be persisted")
    return {"ok": True, "draft": target, "undo": entry.to_dict()}


async def draft_history(session_token: str, owner_id: str, draft_id: str) -> dict[str, Any]:
    from services.outbound.draft_store import draft_store

    draft = draft_store.get(draft_id) if hasattr(draft_store, "get") else None
    if not outbound_service.outbound_draft_owned_by(draft, owner_id):
        raise HTTPException(status_code=404, detail="Draft not found")
    return {"ok": True, "history": get_history(session_token, draft_id),
            "current_version": get_current_version(session_token, draft_id)}


async def compare_draft_versions(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        comparison = compare_versions(
            payload["old_text"], payload["new_text"], payload.get("change_summary"),
        )
        return {"ok": True, "comparison": comparison.to_dict()}
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))
